"""Default applications: which program opens links, folders, pictures, … and the terminal.

What decides it is the freedesktop "MIME apps" spec: a [Default Applications]
section in mimeapps.list files, the first file that names a type winning:

    $XDG_CONFIG_HOME/hyprland-mimeapps.list   (the desktop's own, if any)
    $XDG_CONFIG_HOME/mimeapps.list            <- this page writes here
    $XDG_CONFIG_DIRS/…, $XDG_DATA_HOME/applications/…, $XDG_DATA_DIRS/applications/…

A choice sets every type of its kind (Pictures = png, jpeg, gif, …) in
~/.config/mimeapps.list, and also in the desktop's own file when that one
exists and names the type (it would win otherwise). Other lines, sections and
comments stay as they are. One History item per choice: the exact entries the
kind had before (None = no line), so undo puts the file back as it was.

The terminal has no MIME type: programs that need one (a desktop entry with
Terminal=true) run `xdg-terminal-exec`, which reads ~/.config/xdg-terminals.list
(one desktop file id per line, the first that exists wins). The page writes the
choice first in that list; settings-hub installs a small xdg-terminal-exec when
the system has none.

No GTK.
"""

from __future__ import annotations

import configparser
import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BACKEND = WORKER = "default-apps"
DEFAULTS = "Default Applications"
TERMINAL = "terminal"

# kind -> the types it sets; the first one is the one read to show the choice
KINDS: dict[str, tuple[str, ...]] = {
    "browser": ("x-scheme-handler/https", "x-scheme-handler/http", "text/html",
                "application/xhtml+xml"),
    "mail": ("x-scheme-handler/mailto",),
    "files": ("inode/directory",),
    "images": ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
               "image/tiff", "image/avif"),
    "video": ("video/mp4", "video/x-matroska", "video/webm", "video/quicktime",
              "video/x-msvideo", "video/mpeg"),
    "music": ("audio/mpeg", "audio/flac", "audio/ogg", "audio/wav", "audio/x-wav",
              "audio/mp4", "audio/aac", "audio/opus"),
    "text": ("text/plain", "text/markdown"),
    "pdf": ("application/pdf",),
}
ORDER = (*KINDS, TERMINAL)
DESKTOP_ID = re.compile(r"[A-Za-z0-9_.+-]{1,120}\.desktop")
# What a value may hold when it is put back (a hand-written file may have odd ids):
# nothing that could start a line, a group or another key.
LOOSE_ID = re.compile(r"[^\x00-\x20\x7f-\x9f\u2028\u2029/=\[\];#]{1,200}\.desktop")
# A line of xdg-terminals.list as xdg-terminal-exec reads it: an id with an
# optional ":action", or a "/directive:value" line.
TERMINAL_LINE = re.compile(r"[A-Za-z0-9_.+-]{1,120}\.desktop(:[A-Za-z0-9_-]{1,40})?"
                           r"|/[a-z_]{1,40}:[^\x00-\x1f\x7f]*")


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "")
    return Path(value) if value.startswith("/") else default


def _env_dirs(name: str, default: str) -> list[Path]:
    value = os.environ.get(name) or default
    return [Path(p) for p in value.split(":") if p.startswith("/")]


@dataclass(frozen=True)
class App:
    id: str  # desktop file id, "org.gnome.Loupe.desktop"
    name: str
    mime: frozenset[str]
    terminal: bool  # a terminal emulator (Categories has TerminalEmulator)
    hidden: bool  # NoDisplay: not in launchers, still may open files
    exec: str = ""


@dataclass
class Paths:
    home: Path
    config: Path = field(init=False)
    data: Path = field(init=False)
    config_dirs: list[Path] = field(init=False)
    data_dirs: list[Path] = field(init=False)

    def __post_init__(self) -> None:
        self.config = _env_path("XDG_CONFIG_HOME", self.home / ".config")
        self.data = _env_path("XDG_DATA_HOME", self.home / ".local" / "share")
        self.config_dirs = _env_dirs("XDG_CONFIG_DIRS", "/etc/xdg")
        self.data_dirs = _env_dirs("XDG_DATA_DIRS", "/usr/local/share:/usr/share")

    @property
    def mimeapps(self) -> Path:
        return self.config / "mimeapps.list"

    @property
    def terminals(self) -> Path:
        return self.config / "xdg-terminals.list"

    def desktop_names(self) -> list[str]:
        names = [d.lower() for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")]
        return [d for d in names if re.fullmatch(r"[a-z0-9_-]{1,40}", d)]  # part of a file name

    def terminal_lists(self) -> list[Path]:
        """xdg-terminals.list files, strongest first (what xdg-terminal-exec reads)."""
        out = []
        for folder in (self.config, *self.config_dirs):
            out += [folder / f"{d}-xdg-terminals.list" for d in self.desktop_names()]
            out.append(folder / "xdg-terminals.list")
        return out

    def own_terminal_lists(self) -> list[Path]:
        """The ones a choice writes: the plain list, and the desktop's own when it exists."""
        own = [self.config / f"{d}-xdg-terminals.list" for d in self.desktop_names()]
        return [p for p in own if p.exists()] + [self.terminals]

    def writable(self) -> set[str]:
        """Every file this page may write (a History line can touch nothing else)."""
        return {str(self.mimeapps), str(self.terminals),
                *(str(self.config / f"{d}-{n}") for d in self.desktop_names()
                  for n in ("mimeapps.list", "xdg-terminals.list"))}

    def lists(self) -> list[Path]:
        """mimeapps.list files, strongest first (the spec's order)."""
        out = []
        for folder in (self.config, *self.config_dirs, self.data / "applications",
                       *(d / "applications" for d in self.data_dirs)):
            out += [folder / f"{d}-mimeapps.list" for d in self.desktop_names()]
            out.append(folder / "mimeapps.list")
        return out

    def app_dirs(self) -> list[Path]:
        flatpak = [self.data / "flatpak" / "exports" / "share",
                   Path("/var/lib/flatpak/exports/share")]
        return [d / "applications" for d in (self.data, *flatpak, *self.data_dirs)]


# ---- desktop files ---------------------------------------------------------------

def _parser() -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(interpolation=None, strict=False,
                                          delimiters=("=",), comment_prefixes=("#",))
    parser.optionxform = str  # type: ignore[assignment,method-assign]  # keys keep their case
    return parser


def _locales() -> list[str]:
    """Name[...] suffixes in the spec's order: ll_CC@mod, ll_CC, ll@mod, ll."""
    raw = next((os.environ[v] for v in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(v)), "")
    locale, _, modifier = raw.partition("@")
    locale = locale.split(".")[0]
    lang, _, country = locale.partition("_")
    if not lang or lang in ("C", "POSIX"):
        return []
    mod = f"@{modifier.split('.')[0]}" if modifier else ""
    out = [f"{lang}_{country}{mod}", f"{lang}_{country}", f"{lang}{mod}", lang] if country \
        else [f"{lang}{mod}", lang]
    return list(dict.fromkeys(out))


def _localized(entry, key: str) -> str:
    for name in [f"{key}[{suffix}]" for suffix in _locales()] + [key]:
        value = entry.get(name, "").strip()
        if value:
            return value
    return ""


def _on_path(command: str) -> bool:
    return Path(command).is_file() if command.startswith("/") else bool(shutil.which(command))


def read_app(path: Path, desktop_id: str, desktops: list[str] | None = None) -> App | None:
    """The entry, or None when it is not a program that can be offered."""
    parser = _parser()
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    entry = parser["Desktop Entry"]
    if entry.get("Type", "Application") != "Application" or entry.get("Hidden") == "true":
        return None
    try_exec = entry.get("TryExec", "").strip()
    if try_exec and not _on_path(try_exec):
        return None
    if desktops is not None:  # OnlyShowIn / NotShowIn name desktops (GNOME;KDE;)
        only = {d.strip().lower() for d in entry.get("OnlyShowIn", "").split(";") if d.strip()}
        never = {d.strip().lower() for d in entry.get("NotShowIn", "").split(";") if d.strip()}
        if (only and not only & set(desktops)) or never & set(desktops):
            return None
    name = _localized(entry, "Name")
    if not name:
        return None
    mime = frozenset(m.strip() for m in entry.get("MimeType", "").split(";") if m.strip())
    categories = {c.strip() for c in entry.get("Categories", "").split(";")}
    return App(desktop_id, name, mime, "TerminalEmulator" in categories,
               entry.get("NoDisplay") == "true", entry.get("Exec", "").strip())


def installed(paths: Paths) -> dict[str, App]:
    """Every program by desktop id; a user's file hides the system one of the same id."""
    apps: dict[str, App] = {}
    seen: set[str] = set()
    for folder in paths.app_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.desktop")):
            desktop_id = str(path.relative_to(folder)).replace("/", "-")
            if desktop_id in seen:
                continue
            seen.add(desktop_id)  # even a Hidden one hides the ones below it
            app = read_app(path, desktop_id, paths.desktop_names())
            if app is not None:
                apps[desktop_id] = app
    return apps


# ---- mimeapps.list ---------------------------------------------------------------
# Lines are split on "\n" only, the way GLib reads a key file (str.splitlines()
# would also split on \x1c, \x85, … and break a line GLib reads as one). Each
# line keeps its own ending, so CRLF files, blank lines and a missing last newline
# stay as they were.

def _lines(text: str) -> list[str]:
    return re.findall(r"[^\n]*\n|[^\n]+\Z", text)


def _content(line: str) -> str:
    return line.rstrip("\r\n")


def _key(line: str) -> str | None:
    content = _content(line)
    if "=" not in content or content.lstrip().startswith("#"):
        return None
    return content.split("=", 1)[0].strip()


def _header(line: str) -> str | None:
    content = _content(line).strip()
    return content[1:-1] if content.startswith("[") and content.endswith("]") else None


def _sections(lines: list[str], section: str) -> list[tuple[int, int]]:
    """[start, end) line indexes of the body of every group of that name."""
    spans, start = [], None
    for i, line in enumerate(lines):
        name = _header(line)
        if name is None:
            continue
        if start is not None:
            spans.append((start, i))
            start = None
        if name == section:
            start = i + 1
    if start is not None:
        spans.append((start, len(lines)))
    return spans


def read_defaults(text: str) -> dict[str, str]:
    """[Default Applications] of one file: type -> its raw value (ids, ";"-separated).

    Like GLib: groups of the same name are one group, and a later line of a key wins.
    """
    lines = _lines(text)
    out: dict[str, str] = {}
    for start, end in _sections(lines, DEFAULTS):
        for line in lines[start:end]:
            key = _key(line)
            if key is not None:
                out[key] = _content(line).split("=", 1)[1].strip()
    return out


def with_defaults(text: str, values: dict[str, str | None]) -> str:
    """text with these [Default Applications] keys set (None: removed); the rest kept.

    A key keeps the place of its first line in the first such group; its other
    lines (anywhere) go; a new key goes after the group's last line.
    """
    lines = _lines(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    spans = _sections(lines, DEFAULTS)
    if not spans:
        if all(v is None for v in values.values()):
            return text
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += eol
        if lines and _content(lines[-1]).strip():
            lines.append(eol)
        lines.append(f"[{DEFAULTS}]{eol}")
        spans = [(len(lines), len(lines))]
    left = dict(values)
    out: list[str] = []
    first_start, first_end = spans[0]
    inside = {i for start, end in spans for i in range(start, end)}
    # New keys go after the first group's last non-blank line; lines before the
    # group are copied one for one, so its header is out[first_start - 1].
    last_filled = first_start
    for i, line in enumerate(lines):
        key = _key(line) if i in inside else None
        in_first = first_start <= i < first_end
        if key in values:
            if in_first and key in left:
                if left[key] is not None:
                    out.append(f"{key}={left[key]}{line[len(_content(line)):] or eol}")
                    last_filled = len(out)
                del left[key]
            continue  # a later line of the key, here or in another group, goes
        out.append(line)
        if in_first and _content(line).strip():
            last_filled = len(out)
    new = [f"{k}={v}{eol}" for k, v in left.items() if v is not None]
    if new:
        if last_filled and not out[last_filled - 1].endswith("\n"):
            out[last_filled - 1] += eol
        out[last_filled:last_filled] = new
    return "".join(out)


def _first_installed(value: str, apps: dict[str, App]) -> str:
    for desktop_id in value.split(";"):
        desktop_id = desktop_id.strip()
        if desktop_id in apps:
            return desktop_id
    return ""


# ---- the terminal list -------------------------------------------------------------

def read_terminals(text: str) -> list[str]:
    """The ids, in order ("foot.desktop:server" counts as foot.desktop)."""
    out = []
    for line in text.split("\n"):
        line = line.strip().split(":", 1)[0]
        if DESKTOP_ID.fullmatch(line) and line not in out:
            out.append(line)
    return out


def with_terminal(text: str, desktop_id: str) -> str:
    """The list with desktop_id first; the other lines (and comments) after it."""
    keep = [line for line in text.split("\n") if line.strip() != desktop_id]  # actions stay
    return "\n".join([desktop_id, *keep]).rstrip("\n") + "\n"


# ---- what the page shows -----------------------------------------------------------

@dataclass(frozen=True)
class Choice:
    kind: str
    current: str  # desktop id that opens it now, "" if none chosen
    explicit: bool  # some mimeapps.list names it (else it is the system's guess)
    mixed: bool  # some types of the kind open with another program
    options: tuple[App, ...]  # programs that say they can, current first if it does not


@dataclass(frozen=True)
class Info:
    choices: dict[str, Choice]
    shim: bool  # xdg-terminal-exec exists (programs can find the terminal)


class Backend:
    def __init__(self, workers, home: Path | None = None) -> None:
        self.workers = workers
        self.paths = Paths(home or Path.home())
        self._lock = threading.Lock()

    def _texts(self) -> list[tuple[Path, dict[str, str]]]:
        out = []
        for path in self.paths.lists():
            try:
                out.append((path, read_defaults(path.read_text(encoding="utf-8"))))
            except (OSError, UnicodeDecodeError):
                continue
        return out

    def default_for(self, mime: str, apps: dict[str, App],
                    texts: list[tuple[Path, dict[str, str]]]) -> str:
        for _, defaults in texts:
            found = _first_installed(defaults.get(mime, ""), apps)
            if found:
                return found
        return ""

    def probe(self) -> Info:
        apps = installed(self.paths)
        texts = self._texts()
        choices = {}
        for kind, mimes in KINDS.items():
            current = self.default_for(mimes[0], apps, texts)
            others = {self.default_for(m, apps, texts) for m in mimes[1:]}
            mixed = any(o != current for o in others if o)  # also: only http set, not https
            able = [a for a in apps.values() if can_open(a, mimes)]
            choices[kind] = Choice(kind, current, bool(current), mixed,
                                   _options(able, current, apps))
        terminals = [a for a in apps.values() if a.terminal and not a.hidden]
        listed = [t for path in self.paths.terminal_lists()
                  for t in read_terminals(self._read(path))]
        current = next((t for t in listed if t in apps), "")
        choices[TERMINAL] = Choice(TERMINAL, current, bool(current), False,
                                   _options(terminals, current, apps))
        return Info(choices, bool(shutil.which("xdg-terminal-exec")))

    @staticmethod
    def _read(path: Path) -> str:
        """For showing: a file that cannot be read counts as empty."""
        try:
            return _read_text(path)
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _read_strict(path: Path) -> str:
        """For writing: only a missing file is empty; any other error stops the write
        (an unreadable file taken as empty would be replaced by a few lines)."""
        try:
            return _read_text(path)
        except FileNotFoundError:
            return ""

    # ---- writing ---------------------------------------------------------------

    def files_for(self, kind: str) -> list[Path]:
        """The files a choice of kind writes: ~/.config/mimeapps.list, and the
        desktop's own file there when it already names one of the kind's types."""
        if kind == TERMINAL:
            return self.paths.own_terminal_lists()
        out = [self.paths.mimeapps]
        for name in self.paths.desktop_names():
            own = self.paths.config / f"{name}-mimeapps.list"
            if set(read_defaults(self._read_strict(own))) & set(KINDS[kind]):
                out.append(own)
        return out

    def current_values(self, kind: str) -> dict[str, Any]:
        """What History stores for kind: per file, its exact lines for the kind's types."""
        if kind == TERMINAL:
            return {str(p): self._read_strict(p) for p in self.files_for(kind)}
        out: dict[str, Any] = {}
        for path in self.files_for(kind):
            defaults = read_defaults(self._read_strict(path))
            out[str(path)] = {m: defaults.get(m) for m in KINDS[kind]}
        return out

    def choose(self, kind: str, desktop_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Make desktop_id open every type of kind; (before, after) for History."""
        if kind not in ORDER:
            raise ValueError(f"unknown kind {kind!r}")
        if not DESKTOP_ID.fullmatch(desktop_id):
            raise ValueError("not a desktop file id")
        apps = installed(self.paths)
        if desktop_id not in apps:
            raise ValueError(f"{desktop_id} is not installed")
        if kind == TERMINAL and not apps[desktop_id].terminal:
            raise ValueError(f"{desktop_id} is not a terminal")
        with self._lock:
            before = self.current_values(kind)
            if kind == TERMINAL:
                after = {path: with_terminal(text, desktop_id) for path, text in before.items()}
            else:
                after = {path: {m: desktop_id for m in KINDS[kind]} for path in before}
            self._apply({kind: after})
            return before, after

    def apply_values(self, values: dict[str, Any], kind: str) -> None:
        """History: put back what current_values(kind) gave."""
        with self._lock:
            self._apply({kind: values})

    def _apply(self, by_kind: dict[str, dict[str, Any]]) -> None:
        """Check everything, build every new text, and only then write: a bad value
        never leaves one file changed and the other not."""
        terminal_files = {str(p) for p in self.paths.terminal_lists()}
        merged: dict[str, Any] = {}
        for kind, values in by_kind.items():
            if kind not in ORDER or not isinstance(values, dict):
                raise ValueError(f"not a kind of this page: {kind!r}")
            for name, value in values.items():
                if name not in self.paths.writable():  # nothing else, whatever History says
                    raise ValueError(f"not a file of this page: {name}")
                if (kind == TERMINAL) != (name in terminal_files):
                    raise ValueError(f"{name} is not a file of {kind}")
                if kind == TERMINAL:
                    if not isinstance(value, str):
                        raise ValueError("bad terminal list")
                    _check_terminals(value)
                    merged[name] = value
                    continue
                if not isinstance(value, dict) or not all(
                        isinstance(k, str) and (v is None or (isinstance(v, str) and _ids_ok(v)))
                        for k, v in value.items()):
                    raise ValueError("bad default applications")
                if not set(value) <= set(KINDS[kind]):
                    raise ValueError(f"not a type of {kind}")
                merged.setdefault(name, {}).update(value)
        plan = []
        for name, value in merged.items():
            path = Path(name)
            text = self._read_strict(path)
            new = value if isinstance(value, str) else with_defaults(text, value)
            if new != text:
                plan.append((path, new))
        for path, new in plan:
            _write(path, new)


class Applier:
    """History: the key is the kind, the value what Backend.current_values() gives."""

    backend = BACKEND

    def __init__(self, backend: Backend) -> None:
        self.b = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return {k: self.b.current_values(k) for k in keys if k in ORDER}

    def apply(self, values: dict[str, Any]) -> None:
        with self.b._lock:
            self.b._apply(values)  # every kind checked before anything is written


def register(history, backend: Backend) -> Applier:
    applier = Applier(backend)
    history.register(BACKEND, applier)
    return applier


# ---- helpers ---------------------------------------------------------------------

def can_open(app: App, mimes: tuple[str, ...]) -> bool:
    """app says it opens one of mimes, itself or by a "image/*" wildcard."""
    return any(m in app.mime or f"{m.split('/')[0]}/*" in app.mime for m in mimes)


def _options(able: list[App], current: str, apps: dict[str, App]) -> tuple[App, ...]:
    # Hidden entries count: imv or kitty-open are NoDisplay, and still the viewers.
    shown = sorted({a.id: a for a in able}.values(), key=lambda a: a.name.casefold())
    if current and current in apps and all(a.id != current for a in shown):
        shown.insert(0, apps[current])
    return tuple(shown)


def _ids_ok(value: str) -> bool:
    """"a.desktop; b.desktop;" or "" — ids, with only spaces and tabs around them
    (a newline or any other line break must not pass)."""
    return all(LOOSE_ID.fullmatch(p.strip(" \t"))
               for p in value.split(";") if p.strip(" \t"))


def _check_terminals(text: str) -> None:
    for line in text.split("\n"):
        line = line.removesuffix("\r").strip(" \t")
        if line and not line.startswith("#") and not TERMINAL_LINE.fullmatch(line):
            raise ValueError("bad terminal list")


def _read_text(path: Path) -> str:
    """The text as it is: "\r\n" stays (read_text would turn it into "\n")."""
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path: Path, text: str) -> None:
    """Atomic write that keeps the mode and writes through a symlink."""
    path = path.resolve() if path.is_symlink() else path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    log.info("wrote %s", path)
