"""Window minimize animation (SUPER+H): the minimize tool's anim module. No GTK.

The minimize tool (~/.local/share/minimize, SETTINGS_HUB_MINIMIZE_DIR in
tests) owns the list of animations and the choice file
~/.config/minimize/animation.json; its anim.py is loaded here by file path,
so the names and the file format live in one place. The tool reads the file
on every minimize, so a write needs no reload.

History keys (backend "minimize_anim"): "style" and "speed".

"Look" runs `minimize preview STYLE SPEED`: the active window (this one)
plays the animation away and back without leaving its workspace.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import threading
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workers import Dispatch, Workers, glib_dispatch

log = logging.getLogger(__name__)

BACKEND = "minimize_anim"
WORKER = "minimize-anim"
PREVIEW_WORKER = "minimize-anim-preview"
KEYS = ("style", "speed")
PREVIEW_TIMEOUT_S = 15
MODULE_NAME = "_settings_hub_minimize_anim"


def minimize_dir() -> Path:
    env = os.environ.get("SETTINGS_HUB_MINIMIZE_DIR")
    return Path(env) if env else Path.home() / ".local" / "share" / "minimize"


class MinimizeAnimError(Exception):
    """The tool is missing or refused a value."""


@dataclass(frozen=True)
class Choice:
    id: str
    name: str
    description: str = ""


class Backend:
    def __init__(self, workers: Workers, directory: Path | str | None = None,
                 dispatch: Dispatch | None = None) -> None:
        self.workers = workers
        self.directory = Path(directory) if directory else minimize_dir()
        self._dispatch = dispatch or glib_dispatch
        self._lock = threading.Lock()
        self._module: types.ModuleType | None = None
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- the module -------------------------------------------------------

    @property
    def mod(self) -> types.ModuleType:
        with self._lock:
            if self._module is None:
                path = self.directory / "anim.py"
                if not path.is_file():
                    raise MinimizeAnimError(f"нет {path}")
                spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
                if spec is None or spec.loader is None:
                    raise MinimizeAnimError(f"не загрузить {path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for name in ("STYLES", "ORDER", "SPEEDS", "SPEED_ORDER", "SPEED_TITLES",
                             "load", "save"):
                    if not hasattr(module, name):
                        raise MinimizeAnimError(f"в {path} нет {name}")
                self._module = module
            return self._module

    def state(self) -> tuple[str, str]:
        try:
            self.mod  # noqa: B018
        except Exception as exc:  # noqa: BLE001 -- чужой файл: любая ошибка — «не работает», а не падение страницы
            return "error", str(exc)
        return "ok", ""

    def styles(self) -> list[Choice]:
        m = self.mod
        return [Choice(s, m.STYLES[s][0], m.STYLES[s][1]) for s in m.ORDER]

    def style_name(self, style: str) -> str:
        entry = self.mod.STYLES.get(style)
        return entry[0] if entry else style

    def style_description(self, style: str) -> str:
        entry = self.mod.STYLES.get(style)
        return entry[1] if entry else ""

    @property
    def speeds(self) -> tuple[str, ...]:
        return tuple(self.mod.SPEED_ORDER)

    def speed_title(self, speed: str) -> str:
        return self.mod.SPEED_TITLES.get(speed, speed)

    # ---- reading and writing ------------------------------------------------

    def read_all(self) -> dict[str, Any]:
        return dict(self.mod.load())

    def read(self, keys) -> dict[str, Any]:
        state = self.read_all()
        out = {}
        for key in keys:
            if key not in KEYS:
                raise KeyError(key)
            out[key] = state[key]
        return out

    def check(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key == "style" and value not in self.mod.STYLES:
                raise MinimizeAnimError(f"неизвестная анимация: {value}")
            if key == "speed" and value not in self.mod.SPEEDS:
                raise MinimizeAnimError(f"неизвестная скорость: {value}")
            if key not in KEYS:
                raise KeyError(key)

    def write(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fresh read -> change these keys -> write once. (before, after)."""
        self.check(values)
        before = self.read_all()
        after = dict(before, **values)
        self.mod.save(after)
        return before, self.read_all()

    def queue_write(self, values: dict[str, Any], on_done) -> None:
        values = dict(values)
        self.workers.submit(WORKER, lambda: self.write(values), on_done, key=object())

    # ---- live preview -----------------------------------------------------

    def preview_argv(self, style: str, speed: str) -> list[str]:
        return [str(self.directory / "minimize"), "preview", style, speed]

    def preview(self, argv: list[str]) -> tuple[bool, str]:
        try:
            run = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=PREVIEW_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if run.returncode != 0:
            lines = run.stderr.strip().splitlines()
            return False, lines[-1] if lines else f"exit {run.returncode}"
        return True, ""

    def queue_preview(self, argv: list[str], on_done) -> None:
        self.workers.submit(PREVIEW_WORKER, lambda: self.preview(argv), on_done, key="preview")

    # ---- notifications ----------------------------------------------------

    def notify_external(self, keys: set[str]) -> None:
        def call() -> None:
            for fn in list(self.on_external):
                fn(set(keys))

        self._dispatch(call)


class MinimizeAnimApplier:
    """History backend "minimize_anim"."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        self.backend.check(values)  # unknown keys fail now, not on the worker

        def done(_result, error) -> None:
            if error is not None:
                log.warning("history minimize_anim: %s", error)
            self.backend.notify_external(set(values))

        self.backend.queue_write(values, done)


def register(history, backend: Backend) -> None:
    history.register(BACKEND, MinimizeAnimApplier(backend))
