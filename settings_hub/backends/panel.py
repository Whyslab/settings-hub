"""The panel (HyprPanel): where it sits, how it looks, its clock, font and modules.

* Everything is in HyprPanel's config.json (flat dotted keys), written through
  notifications.Backend.update: the whole file under one lock shared with the
  other backends that write it, permissions kept, other keys left alone, a key
  at HyprPanel's default removed rather than written.
* HyprPanel watches the file and takes theme.* and the clock at once. Its
  bar.layouts is bound reactively in this version too, but an older panel read
  it only at start: the page has a "restart the panel" button for that.
* Modules: bar.layouts maps a monitor ("0", "1", ...) or "*" (every monitor) to
  left/middle/right lists. This page edits one entry: "*" if there is one, else
  "0" (HyprPanel's own default has only numbered entries); the others are kept
  as they are and the page names them. A layout this page cannot read is never
  replaced: the module rows are then off.
* The colours are wallpaper-theme's (it changes only hex colour keys) and are
  not touched here.

No GTK.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import hypr
from . import notifications as panel_cfg

log = logging.getLogger(__name__)

BACKEND = "panel"  # History backend name
WORKER = "panel"
READ_WORKER = "panel-read"

LOCATION = "theme.bar.location"
FLOATING = "theme.bar.floating"
OPACITY = "theme.bar.opacity"
AUTOHIDE = "bar.autoHide"
SCALING = "theme.bar.scaling"
CLOCK = "bar.clock.format"
FONT = "theme.font.name"
FONT_SIZE = "theme.font.size"
LAYOUTS = "bar.layouts"

LOCATIONS = ("top", "bottom")
AUTOHIDES = ("never", "fullscreen", "single-window")
SECTIONS = ("left", "middle", "right")
ALL = "*"
OPACITY_MIN, OPACITY_MAX = 0, 100
SCALING_MIN, SCALING_MAX = 50, 200
FONT_PX_MIN, FONT_PX_MAX = 6, 40
CLOCK_MAX = 60
FONT_MAX = 120
MODULES_MAX = 60  # in all three sections together
MODULE = re.compile(r"(?!.*\.\.)[A-Za-z0-9_][A-Za-z0-9_/.-]{0,47}")
MONITOR = re.compile(r"\*|[A-Za-z0-9_-]{1,32}")  # "*", a number or a connector name
FONT_NAME = re.compile(r"[\w .+-]+")  # it goes into HyprPanel's CSS
SIZE = re.compile(r"(\d+(?:\.\d+)?)(px|pt|rem|em)")
REM_PX = 16  # what HyprPanel's rem is (the GTK default 16 px root)

# HyprPanel's own defaults (src/configuration/modules/...; checked 26.11.2026).
DEFAULT_LAYOUTS: dict[str, Any] = {
    "1": {"left": ["dashboard", "workspaces", "windowtitle"], "middle": ["media"],
          "right": ["volume", "clock", "notifications"]},
    "2": {"left": ["dashboard", "workspaces", "windowtitle"], "middle": ["media"],
          "right": ["volume", "clock", "notifications"]},
    "0": {"left": ["dashboard", "workspaces", "windowtitle"], "middle": ["media"],
          "right": ["volume", "network", "bluetooth", "battery", "systray", "clock",
                    "notifications"]},
}
DEFAULTS: dict[str, Any] = {
    LOCATION: "top",
    FLOATING: False,
    OPACITY: 100,
    AUTOHIDE: "never",
    SCALING: 100,
    CLOCK: "%a %b %d  %I:%M:%S %p",
    FONT: "Ubuntu Nerd Font",
    FONT_SIZE: "1.2rem",
    LAYOUTS: DEFAULT_LAYOUTS,
}
KEYS = tuple(DEFAULTS)

# The modules HyprPanel has (src/components/bar/layout/coreWidgets.tsx).
BUILTIN = ("dashboard", "workspaces", "windowtitle", "media", "notifications", "volume",
           "network", "bluetooth", "clock", "systray", "battery", "microphone", "ram", "cpu",
           "cputemp", "storage", "netstat", "kbinput", "updates", "submap", "weather",
           "power", "hyprsunset", "hypridle", "cava", "worldclock", "separator")

RESTART_SCRIPT = (".local", "share", "panel-refresh", "hyprpanel-fresh.sh")  # under HOME
RESTART_WAIT_S = 10.0

Runner = Callable[[list[str]], tuple[int, str]]


def _number(key: str, value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key}: {value!r}")
    return max(lo, min(hi, int(round(value))))


def _text(key: str, value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit \
            or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{key}: {value!r}")
    return value


def clean_layout(value: Any) -> dict[str, Any]:
    """bar.layouts as HyprPanel takes it: monitor -> section -> module names."""
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{LAYOUTS}: {value!r}")
    out: dict[str, Any] = {}
    for monitor, sections in value.items():
        if not isinstance(monitor, str) or not MONITOR.fullmatch(monitor) \
                or not isinstance(sections, dict):
            raise ValueError(f"{LAYOUTS}: {monitor!r}")
        entry: dict[str, list[str]] = {}
        total = 0
        for section in SECTIONS:
            names = sections.get(section, [])
            if not isinstance(names, list):
                raise ValueError(f"{LAYOUTS}: {monitor}.{section}")
            for name in names:
                if not isinstance(name, str) or not MODULE.fullmatch(name):
                    raise ValueError(f"{LAYOUTS}: module {name!r}")
            entry[section] = list(names)
            total += len(names)
        if total > MODULES_MAX:
            raise ValueError(f"{LAYOUTS}: {total} modules")
        out[monitor] = entry
    return out


def clean(key: str, value: Any) -> Any:
    """value as HyprPanel takes it for key, or ValueError (KeyError: not ours)."""
    if key == LOCATION:
        if value not in LOCATIONS:
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == AUTOHIDE:
        if value not in AUTOHIDES:
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == FLOATING:
        if not isinstance(value, bool):
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == OPACITY:
        return _number(key, value, OPACITY_MIN, OPACITY_MAX)
    if key == SCALING:
        return _number(key, value, SCALING_MIN, SCALING_MAX)
    if key == CLOCK:
        return _text(key, value, CLOCK_MAX)
    if key == FONT:
        value = _text(key, value, FONT_MAX)
        if not FONT_NAME.fullmatch(value):
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == FONT_SIZE:
        if not isinstance(value, str) or not SIZE.fullmatch(value):
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == LAYOUTS:
        return clean_layout(value)
    raise KeyError(key)


def size_px(value: str) -> float | None:
    """A CSS size as px ("10px" 10, "1.2rem" 19.2), None if it is not one."""
    m = SIZE.fullmatch(value or "")
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    return {"px": number, "pt": number * 96 / 72, "rem": number * REM_PX,
            "em": number * REM_PX}[unit]


def px_text(px: float) -> str:
    px = max(FONT_PX_MIN, min(FONT_PX_MAX, px))
    return f"{px:g}px"


def edited_entry(layouts: dict[str, Any]) -> str:
    """The entry this page edits: "*", else monitor "0", else the first one."""
    for key in (ALL, "0"):
        if key in layouts:
            return key
    return next(iter(layouts), ALL)


def sections_of(layouts: dict[str, Any]) -> dict[str, list[str]]:
    entry = layouts.get(edited_entry(layouts), {})
    return {s: list(entry.get(s, [])) for s in SECTIONS}


def with_sections(layouts: dict[str, Any], sections: dict[str, list[str]]) -> dict[str, Any]:
    """layouts with the edited entry set to `sections`; every other entry kept."""
    out = dict(layouts)
    out[edited_entry(layouts)] = {s: list(sections.get(s, [])) for s in SECTIONS}
    return out


def custom_modules(path: Path) -> list[str]:
    """The user's own modules (custom/...) from HyprPanel's modules.json."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    return sorted(k for k in raw if isinstance(k, str) and k.startswith("custom/")
                  and MODULE.fullmatch(k))


def run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=5,
                              stdin=subprocess.DEVNULL, check=False, errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("%s: %s", argv[0], exc)
        return 127, ""
    return done.returncode, done.stdout


_PID = re.compile(r"^PID=(\d+)$", re.M)


@dataclass
class Info:
    found: bool = False  # config.json exists
    values: dict[str, Any] = field(default_factory=dict)  # every key, defaults filled in
    raw: dict[str, Any] = field(default_factory=dict)  # what the file has for our keys
    custom: list[str] = field(default_factory=list)
    other_monitors: list[str] = field(default_factory=list)  # entries not edited here
    layouts_ok: bool = True  # False: bar.layouts is there but not readable: hands off
    running: bool = False  # the panel answers on D-Bus


class Backend:
    def __init__(self, workers, runner: Runner | None = None, config: Path | None = None,
                 restart_script: Path | None = None) -> None:
        self.workers = workers
        self.run = runner or run
        self.cfg = panel_cfg.Backend(workers, runner=self.run, config=config)
        self.modules_json = self.cfg.config.parent / "modules.json"
        self.restart_script = restart_script or Path.home().joinpath(*RESTART_SCRIPT)

    @property
    def config(self) -> Path:
        return self.cfg.config

    # ---- reading ---------------------------------------------------------------

    def values(self, raw: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self.cfg._load() if raw is None else raw
        out: dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            try:
                out[key] = clean(key, raw.get(key, default))
            except (KeyError, ValueError):
                out[key] = default
        return out

    def probe(self) -> Info:
        info = Info(found=self.config.exists())
        raw = self.cfg._load()
        info.raw = {k: raw[k] for k in KEYS if k in raw}
        info.values = self.values(raw)
        info.custom = custom_modules(self.modules_json)
        if LAYOUTS in raw:
            try:
                clean_layout(raw[LAYOUTS])
            except ValueError:
                info.layouts_ok = False
        layouts = info.values[LAYOUTS]
        edited = edited_entry(layouts)
        info.other_monitors = sorted(k for k in layouts if k != edited)
        info.running = self._panel_pid() is not None
        return info

    # ---- History's Applier -------------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        values = self.values()
        return {k: values[k] for k in keys if k in values}

    def apply(self, values: dict[str, Any]) -> None:
        changes = {k: clean(k, v) for k, v in values.items()}

        def change(raw: dict[str, Any]) -> None:
            if LAYOUTS in changes and LAYOUTS in raw:
                clean_layout(raw[LAYOUTS])  # never overwrite a layout we could not read
            for key, value in changes.items():
                if value == DEFAULTS[key]:
                    raw.pop(key, None)
                else:
                    raw[key] = value

        self.cfg.update(change)

    def set(self, key: str, value: Any) -> None:
        self.apply({key: value})

    def queue_probe(self, on_done) -> None:
        self.workers.submit(READ_WORKER, self.probe, on_done, key="probe")

    # ---- restarting the panel ------------------------------------------------------

    def _panel_pid(self) -> int | None:
        """HyprPanel owns org.freedesktop.Notifications: its PID, if it is HyprPanel."""
        rc, out = self.run(["busctl", "--user", "status", "org.freedesktop.Notifications"])
        m = _PID.search(out) if rc == 0 else None
        if not m:
            return None
        pid = int(m.group(1))
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            return None
        # gjs running the panel's bundle (hyprpanel-fresh.sh extracts it), or hyprpanel
        return pid if b"hyprpanel" in cmdline.lower() else None

    @staticmethod
    def _other_panels(proc: Path = Path("/proc")) -> list[int]:
        """Processes that look like a running HyprPanel (gjs on its bundle)."""
        found = []
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                argv = (entry / "cmdline").read_bytes().lower().split(b"\0")
            except OSError:
                continue
            # gjs itself (not a shell or editor that only names it) on the panel's bundle
            if argv and argv[0].rsplit(b"/", 1)[-1] in (b"gjs", b"gjs-console") \
                    and any(b"hyprpanel" in a for a in argv[1:]):
                found.append(int(entry.name))
        return found

    def restart(self) -> None:
        """Stop the panel, wait until it is gone, start it again through Hyprland
        (a child of this app would die with it), then wait until it is back."""
        if not self.restart_script.is_file():
            raise RuntimeError(f"{self.restart_script}: not found")
        pid = self._panel_pid()
        if pid is None and self._other_panels():
            # a panel runs but does not own the notifications name: starting
            # another would put two bars on the screen
            raise RuntimeError("a panel runs that this window cannot stop")
        if pid is not None:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass  # it is gone already: what was wanted
            end = time.monotonic() + RESTART_WAIT_S
            while Path(f"/proc/{pid}").exists():
                if time.monotonic() > end:
                    raise RuntimeError("the panel did not stop")
                time.sleep(0.1)
        script = str(self.restart_script)
        rc, out = self.run(["hyprctl", "dispatch",
                            f"hl.dsp.exec_cmd({hypr.lua_str(script)})"])
        if "Invalid dispatcher" in out:  # a .conf Hyprland (before 0.57)
            rc, out = self.run(["hyprctl", "dispatch", "exec", script])
        if rc != 0 or out.strip() != "ok":
            raise RuntimeError(out.strip() or f"hyprctl dispatch: {rc}")
        end = time.monotonic() + RESTART_WAIT_S
        # back: owning the notifications name, or at least running
        while self._panel_pid() is None and not self._other_panels():
            if time.monotonic() > end:
                raise RuntimeError("the panel did not come back")
            time.sleep(0.25)


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
