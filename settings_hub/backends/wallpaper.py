"""Wallpaper and the wallpaper-driven theme. No GTK. Command-line tools only.

Everything is done by the programs that already do it:

    ~/.config/hypr/scripts/wallpaper.sh set <desktop|lock|sddm|all> <file>
    ~/.config/hypr/scripts/wallpaper.sh random <desktop|lock|sddm> on|off
    ~/.config/hypr/scripts/wallpaper.sh pick          (the rofi grid)
    wallpaper-theme mode off|vivid|tinted
    wallpaper-theme status                            (first line: "<word>: <mode>")

What is on each target is read from the script's own state files,
~/.local/state/hypr-wallpaper/<target>.path, and random.conf ("desktop=on").
Nothing is kept in memory.

`set` turns random wallpapers off on that target, and `random ... on` puts a
random picture up at once, so a change is described by reading every key it may
touch before and after the command (Change.before / Change.after); History
records what really changed.

Thumbnails share the rofi picker's cache (wallpaper-picker.sh): file
<cache>/<sha1("<path>|<mtime>")[:16]>.jpg, 480 px wide, made by magick with the
picker's arguments when missing.

Slow commands run on workers: "wallpaper" (set, random), "theme" (mode and
status), "wallpaper-thumbs" (magick). Keys used in History: backend
"wallpaper": "wallpaper.<target>" (a path) and "random.<target>" ("on"/"off");
backend "theme": "theme.mode".
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workers import Dispatch, Workers, glib_dispatch

log = logging.getLogger(__name__)

BACKEND = "wallpaper"
THEME = "theme"
WORKER = "wallpaper"
THEME_WORKER = "theme"
THUMB_WORKER = "wallpaper-thumbs"

TARGETS = ("desktop", "lock", "sddm")
ALL = "all"
MODES = ("off", "vivid", "tinted")
THEME_KEY = "theme.mode"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
THUMB_WIDTH = 480
TIMEOUT_S = 120
STATUS_TIMEOUT_S = 10


def path_key(target: str) -> str:
    return f"wallpaper.{target}"


def random_key(target: str) -> str:
    return f"random.{target}"


def thumb_key(path: str, mtime: int) -> str:
    """The picker's key: sha1 of "<path>|<mtime in whole seconds>", 16 hex digits."""
    return hashlib.sha1(f"{path}|{mtime}".encode()).hexdigest()[:16]


def parse_mode(status: str) -> str | None:
    """The mode from `wallpaper-theme status`; its first line ends in the mode id."""
    first = status.strip().splitlines()[0] if status.strip() else ""
    word = first.rsplit(":", 1)[-1].strip()
    return word if word in MODES else None


@dataclass(frozen=True)
class Paths:
    script: Path  # wallpaper.sh
    wallpapers: Path  # the library
    state: Path  # hypr-wallpaper state dir
    thumbs: Path  # the picker's thumbnail cache
    theme: str  # the wallpaper-theme command

    @classmethod
    def default(cls) -> Paths:
        home = Path.home()
        env = os.environ.get
        theme = env("SETTINGS_HUB_WALLPAPER_THEME") or shutil.which("wallpaper-theme") or str(
            home / ".local" / "bin" / "wallpaper-theme")
        return cls(
            script=Path(env("SETTINGS_HUB_WALLPAPER_SH")
                        or home / ".config" / "hypr" / "scripts" / "wallpaper.sh"),
            wallpapers=Path(env("SETTINGS_HUB_WALLPAPER_DIR")
                            or home / ".config" / "hypr" / "wallpapers"),
            state=Path(env("SETTINGS_HUB_WALLPAPER_STATE")
                       or home / ".local" / "state" / "hypr-wallpaper"),
            thumbs=Path(env("SETTINGS_HUB_WALLPAPER_THUMBS")
                        or home / ".cache" / "wallpaper-thumbs"),
            theme=theme,
        )


@dataclass(frozen=True)
class Image:
    path: str  # as the picker lists it: <library>/<name>, not resolved
    name: str
    mtime: int
    thumb: Path

    @property
    def real(self) -> str:
        """wallpaper.sh stores realpath(file) in <target>.path."""
        return os.path.realpath(self.path)


@dataclass
class Change:
    """What one command did: every key it may touch, read before and after."""

    before: dict[str, Any]
    after: dict[str, Any]
    ok: bool
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def changed(self) -> dict[str, tuple[Any, Any]]:
        return {k: (self.before.get(k), self.after.get(k)) for k in self.after
                if self.before.get(k) != self.after.get(k)}


Runner = Callable[..., subprocess.CompletedProcess]


class Backend:
    def __init__(self, workers: Workers, paths: Paths | None = None,
                 dispatch: Dispatch | None = None) -> None:
        self.workers = workers
        self.paths = paths or Paths.default()
        self._dispatch = dispatch or glib_dispatch
        # Called on the GTK thread after History changed these keys.
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- reading ----------------------------------------------------------

    def state(self) -> tuple[str, str]:
        """("ok", "") or ("missing", script path)."""
        script = self.paths.script
        if script.is_file() and os.access(script, os.X_OK):
            return "ok", ""
        return "missing", str(script)

    def images(self) -> list[Image]:
        """The library, like the picker: top level files with a picture suffix, sorted."""
        folder = self.paths.wallpapers
        out = []
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
        for entry in entries:
            if not entry.name.lower().endswith(EXTENSIONS):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                mtime = int(entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                continue
            path = f"{folder}/{entry.name}"
            out.append(Image(path, entry.name, mtime,
                             self.paths.thumbs / f"{thumb_key(path, mtime)}.jpg"))
        out.sort(key=lambda i: i.path)
        return out

    def current(self) -> dict[str, str]:
        out = {}
        for target in TARGETS:
            try:
                out[target] = (self.paths.state / f"{target}.path").read_text(
                    encoding="utf-8").strip()
            except OSError:
                out[target] = ""
        return out

    def random(self) -> dict[str, bool]:
        try:
            lines = (self.paths.state / "random.conf").read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        return {t: f"{t}=on" in lines for t in TARGETS}

    def read(self, keys) -> dict[str, Any]:
        keys = list(keys)
        out: dict[str, Any] = {}
        current = self.current() if any(k.startswith("wallpaper.") for k in keys) else {}
        random = self.random() if any(k.startswith("random.") for k in keys) else {}
        for key in keys:
            kind, _, target = key.partition(".")
            if kind == "wallpaper" and target in TARGETS:
                out[key] = current[target]
            elif kind == "random" and target in TARGETS:
                out[key] = "on" if random[target] else "off"
            elif key == THEME_KEY:
                out[key] = self.theme_mode()
            else:
                raise KeyError(key)
        return out

    def theme_available(self) -> bool:
        theme = self.paths.theme
        return bool(shutil.which(theme)) if os.sep not in theme else os.access(theme, os.X_OK)

    def theme_mode(self) -> str | None:
        """Blocking (a Python program starts): call it on a worker."""
        if not self.theme_available():
            return None
        ok, out = self._run([self.paths.theme, "status"], STATUS_TIMEOUT_S)
        return parse_mode(out) if ok else None

    # ---- commands ---------------------------------------------------------

    def _run(self, argv: list[str], timeout: float = TIMEOUT_S) -> tuple[bool, str]:
        try:
            run = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                                 timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if run.returncode != 0:
            lines = (run.stderr or run.stdout).strip().splitlines()
            return False, lines[-1] if lines else f"exit {run.returncode}"
        return True, run.stdout

    def set_wallpaper(self, target: str, path: str) -> Change:
        targets = TARGETS if target == ALL else (target,)
        if target != ALL and target not in TARGETS:
            raise ValueError(target)
        keys = [path_key(t) for t in targets] + [random_key(t) for t in targets]
        before = self.read(keys)
        ok, out = self._run([self.paths.script, "set", target, path])
        return Change(before, self.read(keys), ok, "" if ok else out,
                      {"target": target, "path": path})

    def set_random(self, target: str, enabled: bool) -> Change:
        if target not in TARGETS:
            raise ValueError(target)
        keys = [random_key(target), path_key(target)]  # "on" puts a picture up at once
        before = self.read(keys)
        ok, out = self._run([self.paths.script, "random", target, "on" if enabled else "off"])
        return Change(before, self.read(keys), ok, "" if ok else out,
                      {"target": target, "enabled": enabled})

    def set_theme(self, mode: str) -> Change:
        if mode not in MODES:
            raise ValueError(mode)
        before = {THEME_KEY: self.theme_mode()}
        ok, out = self._run([self.paths.theme, "mode", mode])
        return Change(before, {THEME_KEY: self.theme_mode()}, ok, "" if ok else out,
                      {"mode": mode})

    def queue_set(self, target: str, path: str, on_done) -> None:
        self.workers.submit(WORKER, lambda: self.set_wallpaper(target, path), on_done,
                            key=("set", target))

    def queue_random(self, target: str, enabled: bool, on_done) -> None:
        self.workers.submit(WORKER, lambda: self.set_random(target, enabled), on_done,
                            key=("random", target))

    def queue_theme(self, mode: str, on_done) -> None:
        self.workers.submit(THEME_WORKER, lambda: self.set_theme(mode), on_done, key="mode")

    def queue_theme_status(self, on_done: Callable[[str | None], None]) -> None:
        def done(result, error) -> None:
            on_done(None if error is not None else result)

        self.workers.submit(THEME_WORKER, self.theme_mode, done, key="status")

    def picker_argv(self) -> list[str]:
        return [str(self.paths.script), "pick"]

    # ---- thumbnails -------------------------------------------------------

    def make_thumb(self, image: Image) -> bool:
        """The picker's magick command; written next to the target, then renamed."""
        self.paths.thumbs.mkdir(parents=True, exist_ok=True)
        tmp = image.thumb.with_name(f".{image.thumb.stem}.{os.getpid()}.jpg")
        ok, _ = self._run(["magick", image.path, "-auto-orient", "-thumbnail",
                           f"{THUMB_WIDTH}x", "-strip", "-quality", "85", str(tmp)])
        try:
            if ok and tmp.stat().st_size > 0:
                os.replace(tmp, image.thumb)
                return True
        except OSError:
            pass
        tmp.unlink(missing_ok=True)
        return False

    def queue_thumbs(self, images: list[Image], on_one: Callable[[Image, bool], None]) -> int:
        """Make the missing thumbnails on a worker; on_one runs on the GTK thread."""
        missing = [i for i in images if not _nonempty(i.thumb)]

        def job() -> None:
            for image in missing:
                made = self.make_thumb(image)
                self._dispatch(lambda i=image, m=made: on_one(i, m))

        if missing:
            self.workers.submit(THUMB_WORKER, job, None, key="thumbs")
        return len(missing)

    # ---- notifications ----------------------------------------------------

    def notify_external(self, keys: set[str]) -> None:
        def call() -> None:
            for fn in list(self.on_external):
                fn(set(keys))

        self._dispatch(call)


def _nonempty(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


# ---- History appliers ---------------------------------------------------------

class WallpaperApplier:
    """History backend "wallpaper": the picture on each target and random mode."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        for key in values:  # fail now, not on the worker, for a key nobody knows
            kind, _, target = key.partition(".")
            if kind not in ("wallpaper", "random") or target not in TARGETS:
                raise KeyError(key)
        values = dict(values)

        def job() -> list[str]:
            errors = []
            # Pictures first: `set` switches random off, so random comes after.
            for target in TARGETS:
                path = values.get(path_key(target))
                if path:
                    change = self.backend.set_wallpaper(target, path)
                    if not change.ok:
                        errors.append(change.message)
            for target in TARGETS:
                mode = values.get(random_key(target))
                if mode in ("on", "off"):
                    change = self.backend.set_random(target, mode == "on")
                    if not change.ok:
                        errors.append(change.message)
            return errors

        def done(errors, error) -> None:
            for message in ([str(error)] if error is not None else errors or []):
                log.warning("history wallpaper: %s", message)
            self.backend.notify_external(set(values))

        self.backend.workers.submit(WORKER, job, done, key=object())  # never coalesced


class ThemeApplier:
    """History backend "theme": wallpaper-theme's mode."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        mode = values.get(THEME_KEY)
        if mode not in MODES:
            raise ValueError(f"{THEME_KEY}: {mode!r}")
        if not self.backend.theme_available():
            raise RuntimeError(f"{self.backend.paths.theme} not found")

        def done(change, error) -> None:
            if error is not None or not change.ok:
                log.warning("history theme: %s", error or change.message)
            self.backend.notify_external({THEME_KEY})

        self.backend.queue_theme(mode, done)


def register(history, backend: Backend) -> None:
    history.register(BACKEND, WallpaperApplier(backend))
    history.register(THEME, ThemeApplier(backend))
