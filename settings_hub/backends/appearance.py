"""Fonts and icons for programs, the panel and the terminal. No GTK.

    look.font   the interface font, a Pango description ("Adwaita Sans 11")
    look.mono   the monospace font ("Adwaita Mono 11")
    look.scale  the text scale (1.0 = as designed), GTK's text-scaling-factor
    look.icons  the icon theme ("zafiro-dark")
    look.panel_font  HyprPanel's font family (theme.font.name in its config.json)
    look.kitty_font  kitty's font: "Family Size" (font_family + font_size)

GTK programs read GSettings (org.gnome.desktop.interface) on Wayland and the
gtk-3.0 / gtk-4.0 settings.ini files elsewhere: both are written, the other
lines of settings.ini are kept. Qt programs have no tool here (no qt6ct) and
do not follow.

The panel and the terminal are not changed by choosing an interface font: the
page offers "the same there" as its own step (the panel draws its icons from a
Nerd Font, kitty needs a monospace font).

kitty's font goes into its own file, settings-hub-font.conf next to kitty.conf,
which kitty.conf includes on its last line (added once, marked). kitty reloads
its config on SIGUSR1; open windows follow at once.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import notifications as panel_cfg

log = logging.getLogger(__name__)

BACKEND = "appearance"
WORKER = "appearance"
READ_WORKER = "appearance-read"
TIMEOUT_S = 5

FONT, MONO, SCALE, ICONS = "look.font", "look.mono", "look.scale", "look.icons"
PANEL_FONT, KITTY_FONT = "look.panel_font", "look.kitty_font"
KEYS = (FONT, MONO, SCALE, ICONS, PANEL_FONT, KITTY_FONT)

SCHEMA = "org.gnome.desktop.interface"
GSETTINGS = {FONT: "font-name", MONO: "monospace-font-name", SCALE: "text-scaling-factor",
             ICONS: "icon-theme"}
INI_KEYS = {FONT: "gtk-font-name", ICONS: "gtk-icon-theme-name"}
SCALE_MIN, SCALE_MAX = 0.75, 2.0
PANEL_FONT_KEY = "theme.font.name"
PANEL_FONT_DEFAULT = "Ubuntu Nerd Font"  # HyprPanel's own, when its config names none
KITTY_DEFAULT = ("monospace", 11.0)  # kitty's, when kitty.conf names none
KITTY_FILE = "settings-hub-font.conf"
KITTY_MARK = "# settings-hub: fonts chosen in Settings (delete both lines to undo)"
KITTY_INCLUDE = re.compile(r"^\s*include\s+" + re.escape(KITTY_FILE) + r"\s*$", re.M)
NAME_MAX = 120

ICON_DIRS = (Path.home() / ".local" / "share" / "icons", Path.home() / ".icons",
             Path("/usr/local/share/icons"), Path("/usr/share/icons"))

Runner = Callable[[list[str]], tuple[int, str, str]]


def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


# ---- values ------------------------------------------------------------------

_SIZE = re.compile(r"^(.*\S)\s+(\d+(?:\.\d+)?)$")


def split_font(text: str) -> tuple[str, float | None]:
    """"Adwaita Sans 11" -> ("Adwaita Sans", 11.0); a description without a size keeps None."""
    m = _SIZE.match(text.strip())
    if m:
        return m.group(1), float(m.group(2))
    return text.strip(), None


def font_text(family: str, size: float | None) -> str:
    if size is None:
        return family
    return f"{family} {int(size) if float(size).is_integer() else size}"


def clean(key: str, value: Any) -> Any:
    """The value as it is stored, or ValueError (nothing reaches a file unchecked)."""
    if key == SCALE:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key}: {value!r}")
        return round(max(SCALE_MIN, min(SCALE_MAX, float(value))), 2)
    if key in (FONT, MONO, ICONS, PANEL_FONT, KITTY_FONT):
        if not isinstance(value, str) or any(ch < " " or ch == "\x7f" for ch in value):
            raise ValueError(f"{key}: {value!r}")  # control characters: never in a file
        text = " ".join(value.split())
        if not text or len(text) > NAME_MAX or any(ch in text for ch in "\"'\\\n#;"):
            raise ValueError(f"{key}: {value!r}")
        if key == ICONS and "/" in text:
            raise ValueError(f"{key}: {value!r}")
        return text
    raise KeyError(key)


def gvariant_string(text: str) -> str:
    """What gsettings prints for a string ('Adwaita Sans 11') -> the string."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return re.sub(r"\\(.)", r"\1", text[1:-1])
    return text


# ---- icon themes -------------------------------------------------------------

def icon_themes(dirs: Iterable[Path] = ICON_DIRS, keep: str | None = None) -> list[str]:
    """Installed icon themes by name: not cursor-only ones, and not hidden ones
    (hicolor, Adwaita mark themselves so) unless it is `keep`, the one in use."""
    names: dict[str, str] = {}
    for base in dirs:
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            index = entry / "index.theme"
            if entry.name in names or not index.is_file():
                continue
            try:
                text = index.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not re.search(r"^Directories\s*=\s*\S", text, re.M):
                continue  # a cursor theme, or a stub that only inherits
            if entry.name != keep and re.search(r"^Hidden\s*=\s*true", text, re.M | re.I):
                continue
            names[entry.name] = entry.name
    return sorted(names, key=str.lower)


# ---- settings.ini ----------------------------------------------------------------

def set_ini(text: str, values: dict[str, str]) -> str:
    """Set keys in the [Settings] section, keeping every other line."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "[Settings]"), None)
    if start is None:
        lines = (["[Settings]"] + [f"{k}={v}" for k, v in values.items()]
                 + ([""] + lines if lines else []))
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip().startswith("[")), len(lines))
    seen = set()
    for i in range(start + 1, end):
        key = lines[i].split("=", 1)[0].strip()
        if key in values:  # every copy: GTK takes the last one
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1  # new keys go before the blank lines that end the section
    lines[end:end] = [f"{k}={v}" for k, v in values.items() if k not in seen]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, text: str, mode: int | None = None) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- kitty ------------------------------------------------------------------

def kitty_font(conf_dir: Path) -> str:
    """kitty's font as "Family Size", or "" when kitty.conf is missing or names the
    font in a form this page does not write (family="..." and the like): such a
    value could not be put back by undo. Our file wins over kitty.conf (it is
    included last), but only while kitty.conf still includes it."""
    try:
        main = (conf_dir / "kitty.conf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    texts = [main]
    if KITTY_INCLUDE.search(main):
        try:
            texts.append((conf_dir / KITTY_FILE).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    family, size = KITTY_DEFAULT
    for text in texts:
        for line in text.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            if parts[0] == "font_family":
                family = parts[1].strip()
            elif parts[0] == "font_size":
                try:
                    size = float(parts[1])
                except ValueError:
                    pass
    try:
        return clean(KITTY_FONT, font_text(family, size))
    except ValueError:
        return ""


def ensure_kitty_include(conf: Path) -> bool:
    """Add our include as kitty.conf's last line, once. False if kitty.conf is missing."""
    try:
        text = conf.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    if KITTY_INCLUDE.search(text):
        return True  # the include line itself, not the mark: either may be deleted alone
    tail = "" if text.endswith("\n") or not text else "\n"
    write_atomic(conf, f"{text}{tail}\n{KITTY_MARK}\ninclude {KITTY_FILE}\n")
    return True


def _config_dir_of(environ: bytes) -> Path | None:
    """Where a process reads its config: XDG_CONFIG_HOME, else HOME/.config."""
    env = dict(item.split(b"=", 1) for item in environ.split(b"\0") if b"=" in item)
    if env.get(b"XDG_CONFIG_HOME"):
        return Path(os.fsdecode(env[b"XDG_CONFIG_HOME"]))
    if env.get(b"HOME"):
        return Path(os.fsdecode(env[b"HOME"])) / ".config"
    return None


def kitty_pids(config: Path, proc: Path = Path("/proc")) -> list[int]:
    """This user's kitty processes that read kitty.conf from config/kitty (only
    those: a sandboxed window must not make the real terminals reload)."""
    pids = []
    wanted = config.resolve()
    try:
        entries = list(proc.iterdir())
    except OSError:
        return pids
    uid = os.getuid()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != "kitty" or entry.stat().st_uid != uid:
                continue
            where = _config_dir_of((entry / "environ").read_bytes())
            if where is not None and where.resolve() == wanted:
                pids.append(int(entry.name))
        except OSError:
            continue
    return pids


# ---- the backend ---------------------------------------------------------------

@dataclass
class Look:
    values: dict[str, Any] = field(default_factory=dict)  # only what could be read
    icon_themes: list[str] = field(default_factory=list)
    kitty: bool = False  # kitty.conf exists
    panel: bool = False  # HyprPanel's config exists


class Backend:
    def __init__(self, workers, runner: Runner | None = None, config: Path | None = None,
                 icon_dirs: Iterable[Path] = ICON_DIRS,
                 signal_kitty: Callable[[], int] | None = None) -> None:
        self.workers = workers
        self.run = runner or _run
        self.config = config or config_home()
        self.icon_dirs = tuple(icon_dirs)
        self.signal_kitty = signal_kitty or (lambda: self._signal_kitty(self.config))
        self.panel = panel_cfg.Backend(workers, config=self.config / "hyprpanel" / "config.json")

    # ---- reading -----------------------------------------------------------

    def _gsetting(self, key: str) -> Any:
        code, out, _err = self.run(["gsettings", "get", SCHEMA, GSETTINGS[key]])
        if code != 0:
            return None
        text = out.strip()
        if key == SCALE:
            try:
                return round(float(text), 2)
            except ValueError:
                return None
        return gvariant_string(text) or None

    def read(self, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in keys:
            value: Any = None
            if key in GSETTINGS:
                value = self._gsetting(key)
            elif key == PANEL_FONT:
                try:
                    value = self.panel._load().get(PANEL_FONT_KEY, PANEL_FONT_DEFAULT)
                except (OSError, ValueError):
                    value = None
                if not isinstance(value, str):
                    value = None
            elif key == KITTY_FONT:
                value = kitty_font(self.config / "kitty") or None
            if value is not None:
                out[key] = value
        return out

    def probe(self) -> Look:
        values = self.read(list(KEYS))
        themes = icon_themes(self.icon_dirs, values.get(ICONS))
        if values.get(ICONS) and values[ICONS] not in themes:
            themes.append(values[ICONS])  # in use, though no folder here describes it
        return Look(values=values, icon_themes=themes,
                    kitty=(self.config / "kitty" / "kitty.conf").is_file(),
                    panel=self.panel.config.is_file())

    def queue_probe(self, on_done) -> None:
        self.workers.submit(READ_WORKER, self.probe, on_done, key="probe")

    # ---- changes ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Apply one value; raises with a reason when it cannot."""
        value = clean(key, value)
        if key in GSETTINGS:
            # A GVariant literal; clean() forbids quotes and backslashes in names.
            text = str(value) if key == SCALE else f"'{value}'"
            code, out, err = self.run(["gsettings", "set", SCHEMA, GSETTINGS[key], text])
            if code != 0:
                raise RuntimeError((err or out).strip() or f"gsettings: {code}")
            if key in INI_KEYS:
                # GSettings is what is read back (and undone); settings.ini is for
                # programs that skip it. A file that cannot be written is logged,
                # not a failure: the change has happened and must reach History.
                for version in ("gtk-3.0", "gtk-4.0"):
                    ini = self.config / version / "settings.ini"
                    try:
                        try:
                            old = ini.read_text(encoding="utf-8")
                        except FileNotFoundError:
                            old = ""
                        write_atomic(ini, set_ini(old, {INI_KEYS[key]: value}))
                    except OSError as exc:
                        log.warning("%s: %s", ini, exc)
        elif key == PANEL_FONT:
            self._write_panel({PANEL_FONT_KEY: value})
        elif key == KITTY_FONT:
            self._write_kitty(value)
        else:
            raise KeyError(key)

    def _write_panel(self, changes: dict[str, Any]) -> None:
        # the panel backends share one lock: see notifications.CONFIG_LOCK
        self.panel.update(lambda raw: raw.update(changes))

    def _write_kitty(self, value: str) -> None:
        conf_dir = self.config / "kitty"
        if not ensure_kitty_include(conf_dir / "kitty.conf"):
            raise RuntimeError("kitty.conf not found")
        family, size = split_font(value)
        lines = [KITTY_MARK, f"font_family {family}"]
        if size is not None:
            lines.append(f"font_size {size}")
        write_atomic(conf_dir / KITTY_FILE, "\n".join(lines) + "\n")
        self.signal_kitty()

    @staticmethod
    def _signal_kitty(config: Path) -> int:
        sent = 0
        for pid in kitty_pids(config):
            try:
                os.kill(pid, signal.SIGUSR1)  # kitty: reload kitty.conf
                sent += 1
            except OSError as exc:
                log.info("kitty %s: %s", pid, exc)
        return sent

    def apply(self, values: dict[str, Any]) -> None:
        errors = []
        for key, value in values.items():
            try:
                self.set(key, value)
            except (KeyError, ValueError, OSError, RuntimeError) as exc:
                errors.append(f"{key}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
