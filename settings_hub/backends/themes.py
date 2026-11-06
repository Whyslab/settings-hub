"""Colour themes: wallpaper-theme's theme commands. No GTK. Command-line tools only.

    wallpaper-theme themes --json           every theme with its colours
    wallpaper-theme state --json            the system theme, per-program themes
    wallpaper-theme theme <id> --quiet      the whole system (and its wallpapers)
    wallpaper-theme target <t> <id|system> --quiet
    wallpaper-theme wallpapers on|off       change wallpapers with the theme
    wallpaper-theme random --quiet
    wallpaper-theme custom-save <name> <accent> <bg> <text>   (prints the id)
    wallpaper-theme custom-delete <id>
    wallpaper-theme walls <id> --json       a theme's pictures
    wallpaper-theme walls-set <id> <file> on|off

Nothing is kept in memory: every page refresh asks the command again.

History keys (backend "themes"): "theme.system" (a theme id),
"theme.target.<program>" (an id, or "system" for "as the system"),
"theme.wallpapers" ("on"/"off"). Slow commands run on the "themes" worker.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workers import Dispatch, Workers, glib_dispatch
from .wallpaper import Change

log = logging.getLogger(__name__)

BACKEND = "themes"
WORKER = "themes"
SYSTEM_KEY = "theme.system"
WALLS_KEY = "theme.wallpapers"
AS_SYSTEM = "system"
TARGETS = ("panel", "rofi", "settings", "kitty", "borders", "gtk", "lock")
TIMEOUT_S = 180  # a theme with wallpapers rebuilds the login screen picture too
READ_TIMEOUT_S = 20


def target_key(target: str) -> str:
    return f"theme.target.{target}"


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str
    kind: str  # monochrome, preset, custom, wallpaper
    palette: dict[str, str] | None
    accents: tuple[str, ...]
    wallpapers: int
    active: bool


@dataclass
class State:
    system: str = "monochrome"
    targets: dict[str, str] = field(default_factory=dict)
    wallpapers: bool = True


def default_command() -> str:
    env = os.environ.get("SETTINGS_HUB_WALLPAPER_THEME")
    return env or shutil.which("wallpaper-theme") or str(
        Path.home() / ".local" / "bin" / "wallpaper-theme")


def parse_themes(text: str) -> list[ThemeInfo]:
    out = []
    for item in json.loads(text):
        palette = item.get("palette")
        out.append(ThemeInfo(
            id=str(item["id"]), name=str(item["name"]), kind=str(item.get("kind", "preset")),
            palette=dict(palette) if isinstance(palette, dict) else None,
            accents=tuple(item.get("accents") or ()),
            wallpapers=int(item.get("wallpapers") or 0), active=bool(item.get("active"))))
    return out


def parse_state(text: str) -> State:
    data = json.loads(text)
    targets = data.get("targets") or {}
    return State(system=str(data.get("system") or "monochrome"),
                 targets={t: str(v) for t, v in targets.items() if t in TARGETS},
                 wallpapers=bool(data.get("wallpapers", True)))


class Backend:
    def __init__(self, workers: Workers, command: str | None = None,
                 dispatch: Dispatch | None = None) -> None:
        self.workers = workers
        self.command = command or default_command()
        self._dispatch = dispatch or glib_dispatch
        # Called on the GTK thread after History changed these keys.
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- reading (blocking: call on a worker) ------------------------------

    def available(self) -> bool:
        cmd = self.command
        return bool(shutil.which(cmd)) if os.sep not in cmd else os.access(cmd, os.X_OK)

    def _run(self, *args: str, timeout: float = TIMEOUT_S) -> tuple[bool, str]:
        try:
            run = subprocess.run([self.command, *args], capture_output=True, text=True,
                                 timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if run.returncode != 0:
            lines = (run.stderr or run.stdout).strip().splitlines()
            return False, lines[-1] if lines else f"exit {run.returncode}"
        return True, run.stdout

    def load(self) -> tuple[list[ThemeInfo], State]:
        ok, out = self._run("themes", "--json", timeout=READ_TIMEOUT_S)
        if not ok:
            raise RuntimeError(out)
        themes = parse_themes(out)
        ok, out = self._run("state", "--json", timeout=READ_TIMEOUT_S)
        if not ok:
            raise RuntimeError(out)
        return themes, parse_state(out)

    def state(self) -> State:
        ok, out = self._run("state", "--json", timeout=READ_TIMEOUT_S)
        if not ok:
            raise RuntimeError(out)
        return parse_state(out)

    def read(self, keys) -> dict[str, Any]:
        state = self.state()
        out: dict[str, Any] = {}
        for key in keys:
            if key == SYSTEM_KEY:
                out[key] = state.system
            elif key == WALLS_KEY:
                out[key] = "on" if state.wallpapers else "off"
            elif key.startswith("theme.target.") and key[13:] in TARGETS:
                out[key] = state.targets.get(key[13:], AS_SYSTEM)
            else:
                raise KeyError(key)
        return out

    def walls(self, theme_id: str) -> list[str]:
        ok, out = self._run("walls", theme_id, "--json", timeout=READ_TIMEOUT_S)
        if not ok:
            raise RuntimeError(out)
        return [str(p) for p in json.loads(out)]

    # ---- commands (blocking) -------------------------------------------------

    def _change(self, keys: list[str], *args: str) -> Change:
        before = self.read(keys)
        ok, out = self._run(*args)
        try:
            after = self.read(keys)
        except (RuntimeError, KeyError, ValueError):
            after = dict(before)
        # A warning (one program could not be recoloured) is not a failure of the choice.
        message = "" if ok else out
        return Change(before, after, ok or after != before, message)

    def set_system(self, theme_id: str, keep_wallpapers: bool = False) -> Change:
        extra = ("--keep-wallpapers",) if keep_wallpapers else ()
        return self._change([SYSTEM_KEY], "theme", theme_id, "--quiet", *extra)

    def set_target(self, target: str, theme_id: str) -> Change:
        if target not in TARGETS:
            raise ValueError(target)
        return self._change([target_key(target)], "target", target, theme_id, "--quiet")

    def set_wallpapers(self, enabled: bool, keep_wallpapers: bool = False) -> Change:
        extra = ("--keep-wallpapers",) if keep_wallpapers else ()
        return self._change([WALLS_KEY], "wallpapers", "on" if enabled else "off", *extra)

    def random(self) -> Change:
        return self._change([SYSTEM_KEY], "random", "--quiet")

    def custom_save(self, name: str, accent: str, background: str, text: str) -> str:
        ok, out = self._run("custom-save", name, accent, background, text)
        if not ok:
            raise RuntimeError(out)
        return out.strip()

    def custom_delete(self, theme_id: str) -> None:
        ok, out = self._run("custom-delete", theme_id)
        if not ok:
            raise RuntimeError(out)

    def walls_set(self, theme_id: str, path: str, on: bool) -> None:
        ok, out = self._run("walls-set", theme_id, path, "on" if on else "off",
                            timeout=READ_TIMEOUT_S)
        if not ok:
            raise RuntimeError(out)

    # ---- queueing ---------------------------------------------------------

    def queue(self, fn: Callable[[], Any], on_done, key: Any = None) -> None:
        self.workers.submit(WORKER, fn, on_done, key=key if key is not None else object())

    def notify_external(self, keys: set[str]) -> None:
        def call() -> None:
            for fn in list(self.on_external):
                fn(set(keys))

        self._dispatch(call)


class ThemesApplier:
    """History backend "themes": the system theme, per-program themes, wallpapers."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        for key in values:  # fail now, not on the worker, for a key nobody knows
            if key not in (SYSTEM_KEY, WALLS_KEY) and not (
                    key.startswith("theme.target.") and key[13:] in TARGETS):
                raise KeyError(key)
        if not self.backend.available():
            raise RuntimeError(f"{self.backend.command} not found")
        values = dict(values)

        def job() -> list[str]:
            errors = []
            # Undo brings the colours back and leaves the pictures alone: the old
            # ones are not recorded, and shuffling again would only look random.
            if values.get(WALLS_KEY) in ("on", "off"):
                change = self.backend.set_wallpapers(values[WALLS_KEY] == "on",
                                                     keep_wallpapers=True)
                errors += [change.message] if change.message else []
            if values.get(SYSTEM_KEY):
                change = self.backend.set_system(str(values[SYSTEM_KEY]), keep_wallpapers=True)
                errors += [change.message] if change.message else []
            for target in TARGETS:
                value = values.get(target_key(target))
                if value:
                    change = self.backend.set_target(target, str(value))
                    errors += [change.message] if change.message else []
            return errors

        def done(errors, error) -> None:
            for message in ([str(error)] if error is not None else errors or []):
                log.warning("history themes: %s", message)
            self.backend.notify_external(set(values))

        self.backend.queue(job, done)


def register(history, backend: Backend) -> None:
    history.register(BACKEND, ThemesApplier(backend))
