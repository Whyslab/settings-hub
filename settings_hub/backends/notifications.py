"""Notifications: HyprPanel shows them, so its settings are what changes here.

* Options live in HyprPanel's config.json, a flat object of dotted keys
  ("notifications.position": "top right"). HyprPanel watches that file and
  takes a change at once. The file is read, the one key changed and the whole
  file written back atomically with its permissions kept; keys this page does
  not know are left alone, and a key at its default is removed rather than
  written (HyprPanel then uses its own default, as before).
* Do Not Disturb is HyprPanel's own state with no way to read it except
  `hyprpanel toggleDnd`, which flips it and answers "Enabled" or "Disabled"
  (GSettings' io.astal.notifd dont-disturb does not follow it: checked
  15.11.2026). Setting needs no read: flip, and if the answer is not the
  wanted state (someone changed it meanwhile), flip once more. Reading flips
  twice and is done only when the page is shown; an answer that does not come
  makes the state unknown (None) rather than guessed.
* Stored notifications are in GSettings (io.astal.notifd notifications):
  counted and their senders listed for the ignore list; `hyprpanel
  clearNotifications` removes them.

No GTK.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BACKEND = "notifications"  # History backend name
WORKER = "notifications"
DND = "dnd"
POSITION = "notifications.position"
TIMEOUT = "notifications.timeout"
ACTIVE_MONITOR = "notifications.active_monitor"
HOVER = "notifications.showActionsOnHover"
IGNORE = "notifications.ignore"

POSITIONS = ("top right", "top", "top left", "right", "left",
             "bottom right", "bottom", "bottom left")
# HyprPanel's defaults (src/configuration/modules/config/notifications).
DEFAULTS: dict[str, Any] = {
    POSITION: "top right",
    TIMEOUT: 7000,
    ACTIVE_MONITOR: True,
    HOVER: False,
    IGNORE: [],
}
TIMEOUT_MIN_MS, TIMEOUT_MAX_MS = 1000, 60000
IGNORE_MAX = 50
NAME_MAX = 100
APPS_MAX = 30

Runner = Callable[[list[str]], tuple[int, str]]


def run(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=5,
                              stdin=subprocess.DEVNULL, check=False, errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("%s: %s", argv[0], exc)
        return 127, ""
    return done.returncode, done.stdout


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hyprpanel" / "config.json"


def clean(key: str, value: Any) -> Any:
    """value as HyprPanel takes it for key, or ValueError."""
    if key == POSITION:
        if value not in POSITIONS:
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == TIMEOUT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key}: {value!r}")
        return max(TIMEOUT_MIN_MS, min(TIMEOUT_MAX_MS, int(value)))
    if key in (ACTIVE_MONITOR, HOVER, DND):
        if not isinstance(value, bool):
            raise ValueError(f"{key}: {value!r}")
        return value
    if key == IGNORE:
        if not isinstance(value, list):
            raise ValueError(f"{key}: {value!r}")
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and 0 < len(item.strip()) <= NAME_MAX \
                    and item.strip() not in out:
                out.append(item.strip())
        return out[:IGNORE_MAX]
    raise KeyError(key)


# GVariant prints a string with ' in it in double quotes: <"Bob's app">
_APP = re.compile(r"""'app-name': <(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")>""")
_ID = re.compile(r"'id': <uint32 \d+>")


def parse_stored(text: str) -> tuple[int, list[str]]:
    """GSettings' printed notifications -> (how many, senders newest-first-ish)."""
    apps: list[str] = []
    for m in _APP.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        name = re.sub(r"""\\(['"\\])""", r"\1", raw).strip()  # only quote escapes
        if name and name not in apps:
            apps.append(name)
    return len(_ID.findall(text)), apps[:APPS_MAX]


@dataclass
class Info:
    panel: bool = False  # HyprPanel answers
    dnd: bool | None = None  # None: unknown, or not read (dnd_read False)
    dnd_read: bool = False
    values: dict[str, Any] = field(default_factory=dict)  # config keys, defaults filled in
    stored: int | None = None
    apps: list[str] = field(default_factory=list)  # senders of stored notifications


class Backend:
    def __init__(self, workers, runner: Runner | None = None,
                 config: Path | None = None) -> None:
        self.workers = workers
        self.run = runner or run
        self.config = config or config_path()
        # Reading DND flips it twice: History (main thread) and the page (worker)
        # must not interleave their flips, or both end up believing a wrong state.
        self._dnd_lock = threading.Lock()

    # ---- the config file ---------------------------------------------------

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.config.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(raw, dict):
            raise ValueError(f"{self.config}: not an object")
        return raw

    def values(self) -> dict[str, Any]:
        raw = self._load()
        out = {}
        for key, default in DEFAULTS.items():
            try:
                out[key] = clean(key, raw.get(key, default))
            except (KeyError, ValueError):
                out[key] = default
        return out

    def write(self, changes: dict[str, Any]) -> None:
        """Change these keys in config.json, keeping everything else as it is."""
        raw = self._load()  # a broken file raises: never overwrite what we cannot read
        for key, value in changes.items():
            value = clean(key, value)
            if value == DEFAULTS[key]:
                raw.pop(key, None)
            else:
                raw[key] = value
        path = self.config.resolve()  # a symlinked config stays a symlink
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o600
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(raw, fh, ensure_ascii=False, indent=2)  # HyprPanel's own layout
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---- Do Not Disturb ----------------------------------------------------

    def _toggle(self) -> bool | None:
        rc, out = self.run(["hyprpanel", "toggleDnd"])
        answer = out.strip()
        if rc != 0 or answer not in ("Enabled", "Disabled"):
            return None
        return answer == "Enabled"

    def read_dnd(self) -> bool | None:
        with self._dnd_lock:
            return self._read_dnd()

    def _read_dnd(self) -> bool | None:
        first = self._toggle()
        if first is None:  # it may or may not have flipped: unknown
            return None
        second = self._toggle()
        if second is None or second == first:  # lost, or something else flipped it too
            return None
        return second

    def set_dnd(self, on: bool) -> None:
        with self._dnd_lock:
            self._set_dnd(on)

    def _set_dnd(self, on: bool) -> None:
        for _attempt in range(2):
            answer = self._toggle()
            if answer is None:
                raise RuntimeError("hyprpanel toggleDnd: no answer")
            if answer == on:
                return
        raise RuntimeError("hyprpanel toggleDnd: the state did not change")

    # ---- History's Applier -------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        config_keys = [k for k in keys if k in DEFAULTS]
        if config_keys:
            values = self.values()
            out.update({k: values[k] for k in config_keys})
        if DND in keys:
            dnd = self.read_dnd()
            if dnd is not None:
                out[DND] = dnd
        return out

    def apply(self, values: dict[str, Any]) -> None:
        config = {k: v for k, v in values.items() if k in DEFAULTS}
        if config:
            self.write(config)
        # None: the state was unknown when it was logged; leave it as it is
        if values.get(DND) is not None:
            self.set_dnd(bool(values[DND]))

    # ---- the page ------------------------------------------------------------

    def probe(self, with_dnd: bool = True) -> Info:
        info = Info(values=self.values())
        if shutil.which("hyprpanel"):
            if with_dnd:
                info.dnd, info.dnd_read = self.read_dnd(), True
            if info.dnd is None:  # one lost answer does not mean the panel is gone
                rc, _out = self.run(["hyprpanel", "isInhibiting"])
                info.panel = rc == 0
            else:
                info.panel = True
        rc, out = self.run(["gsettings", "get", "io.astal.notifd", "notifications"])
        if rc == 0:
            info.stored, info.apps = parse_stored(out)
        return info

    def clear(self) -> None:
        rc, out = self.run(["hyprpanel", "clearNotifications"])
        if rc != 0:
            raise RuntimeError(out.strip() or f"hyprpanel clearNotifications: {rc}")

    def test(self, summary: str, body: str, app: str) -> None:
        rc, out = self.run(["notify-send", "-a", app, summary, body])
        if rc != 0:
            raise RuntimeError(out.strip() or f"notify-send: {rc}")


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
