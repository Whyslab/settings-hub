"""The "Updates" page's data: what pacman would update and what needs tidying.

Read-only. Nothing here runs as root: the list comes from checkupdates (it
syncs a private copy of the package databases), the rest from files and
`pacman -Q`. Upgrading and cleaning the cache need a password, so they run in
a terminal window the person types into (terminal_command()).

No GTK.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

WORKER = "updates"
CHECK_TIMEOUT_S = 90  # checkupdates downloads the databases
AUR_TIMEOUT_S = 30
PACMAN_LOG = Path("/var/log/pacman.log")
CACHE_DIR = Path("/var/cache/pacman/pkg")
MODULES_DIR = Path("/usr/lib/modules")
PACNEW_ROOTS = (Path("/etc"),)
PACNEW_MAX = 50
FULL_UPGRADE = "[PACMAN] starting full system upgrade"

Runner = Callable[[list[str], float], tuple[int, str]]  # argv, timeout -> (rc, stdout)


def run(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, check=False, errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("%s: %s", argv[0], exc)
        return 127, ""
    return done.returncode, done.stdout


@dataclass(frozen=True)
class Package:
    name: str
    old: str
    new: str
    aur: bool = False


@dataclass
class Info:
    packages: list[Package] = field(default_factory=list)
    checked: bool = False  # the list is real (False: no tool or it failed)
    error: str = ""  # why it is not ("" with checked False: no checkupdates)
    running_kernel: str = ""
    reboot_needed: bool = False
    last_upgrade: date | None = None
    cache_bytes: int | None = None
    orphans: list[str] = field(default_factory=list)
    pacnew: list[str] = field(default_factory=list)


_LINE = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)")


def parse_updates(text: str, aur: bool = False) -> list[Package]:
    """`name old -> new` lines (checkupdates, yay -Qua); anything else is skipped."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out.append(Package(m.group(1), m.group(2), m.group(3), aur))
    return out


def last_full_upgrade(log_path: Path = PACMAN_LOG) -> date | None:
    """The day of the last `pacman -Syu` from pacman.log (its end is read only)."""
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4 * 1024 * 1024))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if FULL_UPGRADE in line and line.startswith("["):
            stamp = line[1:line.find("]")]
            try:
                return datetime.fromisoformat(stamp).date()
            except ValueError:
                return None
    return None


def reboot_needed(running: str, modules: Path = MODULES_DIR) -> bool:
    """The running kernel's modules are gone: pacman replaced the kernel."""
    if not running or not modules.is_dir():
        return False
    return not (modules / running).is_dir()


def cache_size(directory: Path = CACHE_DIR) -> int | None:
    try:
        return sum(e.stat(follow_symlinks=False).st_size
                   for e in os.scandir(directory) if e.is_file(follow_symlinks=False))
    except OSError:
        return None


def find_pacnew(roots: tuple[Path, ...] = PACNEW_ROOTS, limit: int = PACNEW_MAX) -> list[str]:
    found: list[str] = []
    for root in roots:
        for path, dirs, files in os.walk(root, onerror=lambda _e: None):
            dirs.sort()
            for name in sorted(files):
                if name.endswith(".pacnew"):
                    found.append(os.path.join(path, name))
                    if len(found) >= limit:
                        return found
    return found


def aur_helper() -> str | None:
    for name in ("yay", "paru"):
        if shutil.which(name):
            return name
    return None


def upgrade_command() -> str:
    """What the Update button runs in the terminal."""
    helper = aur_helper()
    return helper if helper else "sudo pacman -Syu"


def cache_command() -> str:
    return "sudo paccache -rk2"


def terminal_command(command: str, title: str, done_text: str) -> list[str] | None:
    """kitty (or another terminal) running `command`, then waiting for Enter, so
    the person reads what happened before the window closes. None: no terminal."""
    script = f'{command}; echo; printf "%s" "{done_text}"; read -r _'
    if shutil.which("kitty"):
        return ["kitty", "--title", title, "sh", "-c", script]
    for term in ("foot", "alacritty", "wezterm"):
        if shutil.which(term):
            flag = "start" if term == "wezterm" else "-e"
            return [term, flag, "sh", "-c", script]
    return None


def probe(runner: Runner = run, check: bool = True) -> Info:
    """Everything the page shows. check=False skips the network (the lists)."""
    info = Info(running_kernel=os.uname().release)
    info.reboot_needed = reboot_needed(info.running_kernel)
    info.last_upgrade = last_full_upgrade()
    info.cache_bytes = cache_size()
    rc, out = runner(["pacman", "-Qdtq"], 10)
    if rc == 0:
        info.orphans = [line.strip() for line in out.splitlines() if line.strip()]
    info.pacnew = find_pacnew()
    if not check:
        return info
    if not shutil.which("checkupdates"):
        return info
    rc, out = runner(["checkupdates", "--nocolor"], CHECK_TIMEOUT_S)
    if rc == 0:
        info.packages, info.checked = parse_updates(out), True
    elif rc == 2:  # checkupdates: nothing to update
        info.checked = True
    else:
        info.error = f"checkupdates: {rc}"
        return info
    helper = aur_helper()
    if helper:
        rc, out = runner([helper, "-Qua"], AUR_TIMEOUT_S)
        if rc in (0, 1):  # 1: nothing (yay, paru)
            info.packages += parse_updates(out, aur=True)
    return info
