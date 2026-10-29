"""Animations: rofi-launcher's animations module, loaded live. No GTK.

The module (rofi_hub/sections/animations.py of the installed hub, loaded by
file path as _rofi_live.rofi_hub..., see loader.py) owns the presets, the four
categories with their variants, the speeds and compose(). Applying is what the
module itself does, through its own functions:

    save_tuning(tuning); _set_active(preset id);
    hyprconf.write(compose(preset, tuning)); hyprctl reload

so the window writes exactly the animations.conf/.lua that the rofi grid would
for the same choice. Its language is forced to Russian after import
(strings.LANG for t(), animations.LANG for the preset names), and its notify()
is replaced: messages go to the window's status line instead of notify-send.

The state is three kinds of History keys (backend "animations"):

    "preset"               the active preset id
    "override.<category>"  a variant id, or None for "as in the preset"
    "speed.<category>"     "fast" / "normal" / "slow"

A write reads fresh, changes only the given keys and writes everything once,
on the "animations" worker. Choosing a preset resets the categories, as in the
rofi grid ("a preset is everything at once").

"Look" runs bin/anim-preview.sh with ANIM_PREVIEW_REOPEN=0 on its own worker:
the preview applies settings live with `hyprctl keyword`, writes nothing and
undoes itself with `hyprctl reload`; with 0 it does not reopen the rofi grid.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import loader
from ..workers import Dispatch, Workers, glib_dispatch

log = logging.getLogger(__name__)

BACKEND = "animations"
WORKER = "animations"
PREVIEW_WORKER = "animations-preview"
PRESET_KEY = "preset"
NORMAL = "normal"
RELOAD_TIMEOUT_S = 15
PREVIEW_TIMEOUT_S = 90
LANGUAGE = "ru"


class AnimationsError(Exception):
    """A choice the module refuses (no preset, menu dissolve without windows...)."""


def override_key(category: str) -> str:
    return f"override.{category}"


def speed_key(category: str) -> str:
    return f"speed.{category}"


@dataclass(frozen=True)
class Choice:
    id: str
    name: str
    description: str = ""
    image: Path | None = None


@dataclass
class Change:
    before: dict[str, Any]
    after: dict[str, Any]
    message: str = ""
    path: Path | None = None  # the generated file Hyprland reads
    reload_ok: bool = True
    notes: list[str] = field(default_factory=list)

    def changed(self) -> dict[str, tuple[Any, Any]]:
        return {k: (self.before.get(k), self.after.get(k)) for k in self.after
                if self.before.get(k) != self.after.get(k)}


class Backend:
    def __init__(self, workers: Workers, directory: Path | str | None = None,
                 dispatch: Dispatch | None = None) -> None:
        self.workers = workers
        self.directory = Path(directory) if directory else loader.rofi_dir()
        self._dispatch = dispatch or glib_dispatch
        self._lock = threading.Lock()
        self._module: types.ModuleType | None = None
        self._strings: types.ModuleType | None = None
        self.notes: list[str] = []  # what the module wanted to notify-send
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- the module -------------------------------------------------------

    @property
    def mod(self) -> types.ModuleType:
        with self._lock:
            if self._module is None:
                module = loader.load_rofi_module("rofi_hub.sections.animations", self.directory)
                texts = loader.load_rofi_module("rofi_hub.strings", self.directory)
                texts.LANG = LANGUAGE  # read by t() at call time
                module.LANG = LANGUAGE  # _localized() uses the module's own copy
                module.notify = self.notes.append  # the status line, not notify-send
                self._module, self._strings = module, texts
            return self._module

    def t(self, key: str, **kwargs) -> str:
        self.mod  # noqa: B018 -- loads the module and its strings
        return self._strings.t(key, **kwargs)

    def state(self) -> tuple[str, str]:
        try:
            self.mod  # noqa: B018
        except loader.LoadError as exc:
            return "error", str(exc)
        return "ok", ""

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(self.mod.CATEGORIES)

    @property
    def speeds(self) -> tuple[str, ...]:
        return tuple(self.mod.SPEED_ORDER)

    def keys(self) -> list[str]:
        return [PRESET_KEY, *(override_key(c) for c in self.categories),
                *(speed_key(c) for c in self.categories)]

    def category_title(self, category: str) -> str:
        return self.t(self.mod.CATEGORY_TITLE[category])

    def speed_title(self, speed: str) -> str:
        return self.t(f"anim_speed_{speed}")

    def as_preset_title(self) -> str:
        return self.t("anim_as_preset")

    def _image(self, path: Path) -> Path | None:
        return path if path.is_file() else None

    def presets(self) -> list[Choice]:
        m = self.mod
        return [Choice(p["id"], m._localized(p.get("name")), m._localized(p.get("description")),
                       self._image(m.preview_path(p["id"]))) for p in m.load_all()]

    def variants(self, category: str) -> list[Choice]:
        m = self.mod
        return [Choice(v["id"], m._localized(v.get("name")), m._localized(v.get("description")),
                       self._image(m.variant_preview_path(category, v["id"])))
                for v in m.load_variants(category)]

    def preset_name(self, preset_id: str) -> str:
        preset = self.mod.get(preset_id) if preset_id else None
        return self.mod._localized(preset.get("name")) if preset else ""

    def variant_name(self, category: str, variant_id: str | None) -> str:
        if not variant_id:
            return self.as_preset_title()
        variant = self.mod.get_variant(category, variant_id)
        return self.mod._localized(variant.get("name")) if variant else variant_id

    # ---- reading ----------------------------------------------------------

    def read_all(self) -> dict[str, Any]:
        m = self.mod
        tuning = m.load_tuning()
        out: dict[str, Any] = {PRESET_KEY: m.active_id()}
        for c in m.CATEGORIES:
            out[override_key(c)] = tuning["overrides"].get(c)
            out[speed_key(c)] = tuning["speed"].get(c, NORMAL)
        return out

    def read(self, keys) -> dict[str, Any]:
        state = self.read_all()
        out = {}
        for key in keys:
            if key not in state:
                raise KeyError(key)
            out[key] = state[key]
        return out

    def is_custom(self, state: dict[str, Any]) -> bool:
        return any(state.get(override_key(c)) or state.get(speed_key(c), NORMAL) != NORMAL
                   for c in self.categories)

    # ---- writing ----------------------------------------------------------

    def _tuning(self, values: dict[str, Any]) -> dict:
        """The saved tuning with these keys changed; key order kept where it can be."""
        tuning = self.mod.load_tuning()
        for key, value in values.items():
            kind, _, category = key.partition(".")
            if kind == "override":
                if value:
                    tuning["overrides"][category] = value
                else:
                    tuning["overrides"].pop(category, None)
            elif kind == "speed":
                if value and value != NORMAL:
                    tuning["speed"][category] = value
                else:
                    tuning["speed"].pop(category, None)
        return tuning

    def _check(self, values: dict[str, Any]) -> None:
        state = self.read_all()
        for key, value in values.items():
            if key not in state:
                raise KeyError(key)
            kind, _, category = key.partition(".")
            if kind == "override" and value and self.mod.get_variant(category, value) is None:
                raise AnimationsError(f"{category}/{value}")
            if kind == "speed" and value not in self.mod.SPEEDS:
                raise AnimationsError(f"{category}: {value}")

    def write(self, values: dict[str, Any], guard: bool = False) -> Change:
        """Fresh read -> change these keys -> write once -> reload. On the worker.

        guard: refuse a menu dissolve that cannot work, as the rofi grid does
        (only for a user's choice; History restores what was there).
        """
        m = self.mod
        self._check(values)
        before = self.read_all()
        preset_id = values.get(PRESET_KEY, before[PRESET_KEY])
        preset = m.get(preset_id) if preset_id else None
        if preset is None:
            raise AnimationsError(self.t("anim_no_preset"))
        tuning = self._tuning(values)
        for key, value in values.items():
            kind, _, category = key.partition(".")
            variant = m.get_variant(category, value) if kind == "override" and value else None
            if guard and variant and variant.get("layers_dissolve") \
                    and not m.menu_dissolve_available(tuning):
                raise AnimationsError(self.t("anim_menu_dissolve_needs_windows"))
        composed = m.compose(preset, tuning)  # validates; raises before anything is written
        del self.notes[:]
        m.save_tuning(tuning)
        if PRESET_KEY in values:
            m._set_active(preset["id"])
        path = m.hyprconf.write(composed)
        reload_ok = self.reload()
        return Change(before, self.read_all(), path=path, reload_ok=reload_ok,
                      notes=list(self.notes))

    def reload(self) -> bool:
        try:
            run = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True,
                                 timeout=RELOAD_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("hyprctl reload: %s", exc)
            return False
        return run.returncode == 0

    def preset_values(self, preset_id: str) -> dict[str, Any]:
        """A preset is everything at once: it puts every category back to the preset."""
        values: dict[str, Any] = {PRESET_KEY: preset_id}
        for c in self.categories:
            values[override_key(c)] = None
            values[speed_key(c)] = NORMAL
        return values

    def queue_write(self, values: dict[str, Any], on_done, guard: bool = False) -> None:
        values = dict(values)
        self.workers.submit(WORKER, lambda: self.write(values, guard), on_done, key=object())

    # ---- live preview -----------------------------------------------------

    @property
    def preview_script(self) -> Path:
        return self.directory / "bin" / "anim-preview.sh"

    def preview_argv(self, category: str | None = None, variant: str | None = None,
                     speed: str | None = None, preset: str | None = None) -> list[str]:
        script = str(self.preview_script)
        if category is None:
            return ["bash", script, preset or self.read_all()[PRESET_KEY]]
        if speed is not None:
            return ["bash", script, "cat", category, "speed", speed]
        return ["bash", script, "cat", category, "var", variant or "-"]

    def preview(self, argv: list[str]) -> tuple[bool, str]:
        """Blocking: the demonstration takes seconds. Never reopens the rofi grid."""
        env = dict(os.environ, ANIM_PREVIEW_REOPEN="0")
        try:
            run = subprocess.run(argv, env=env, capture_output=True, text=True,
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


class AnimationsApplier:
    """History backend "animations": the preset and the tuning on top of it."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        self.backend._check(values)  # unknown keys fail now, not on the worker

        def done(_change, error) -> None:
            if error is not None:
                log.warning("history animations: %s", error)
            self.backend.notify_external(set(values))

        self.backend.queue_write(values, done)


def register(history, backend: Backend) -> None:
    history.register(BACKEND, AnimationsApplier(backend))
