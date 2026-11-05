"""The Settings window's own settings: JSON at ~/.config/settings-hub/settings.json.

Every knob the window itself has lives here as a field: the look, the starting
page, the delays, the limits. Only values that differ from their default are
written to the file, so changing a default in a new version reaches everybody
who never touched that field. Values are validated on load and on set: a
hand-edited file with a wrong type or an unknown choice falls back to the
default instead of breaking the window.

The page does not know about widgets: pages/general.py builds them from
fields(). A subscriber is told about every change (the window applies the look
at once); a change made by an undo goes through the same path.

No GTK, no Hyprland here.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

KINDS = ("int", "float", "bool", "choice", "str")
GROUPS = ("appearance", "behavior")


@dataclass(frozen=True)
class Field:
    """One setting: what it accepts and what it defaults to."""

    key: str
    kind: str
    default: Any
    lo: int | float | None = None
    hi: int | float | None = None
    step: int | float | None = None
    choices: tuple[str, ...] = ()
    group: str = "behavior"

    def coerce(self, value: Any) -> Any:
        """value as this field stores it, or ValueError."""
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.key}: not a boolean: {value!r}")
            return value
        if self.kind in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.key}: not a number: {value!r}")
            number = int(round(value)) if self.kind == "int" else float(value)
            if self.lo is not None and number < self.lo:
                raise ValueError(f"{self.key}: {number} < {self.lo}")
            if self.hi is not None and number > self.hi:
                raise ValueError(f"{self.key}: {number} > {self.hi}")
            return number
        if self.kind == "choice":
            if value not in self.choices:
                raise ValueError(f"{self.key}: not one of {self.choices}: {value!r}")
            return value
        if self.kind == "str":
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError(f"{self.key}: not a short string: {value!r}")
            return value
        raise ValueError(f"{self.key}: unknown kind {self.kind!r}")


# Pages are named here as plain strings: importing the registry would create a
# cycle (registry -> strings, search -> registry; settings is used by pages).
START_PAGE_LAST = "last"
START_PAGES = (
    START_PAGE_LAST, "screen-sleep", "wallpaper", "animations", "binds",
    "general", "windows", "input", "system", "sound", "network", "power",
    "modes", "history",
)

FIELDS: tuple[Field, ...] = (
    # ---- appearance -----------------------------------------------------
    Field("appearance.theme", "choice", "system", choices=("system", "light", "dark"),
          group="appearance"),
    Field("appearance.transition", "choice", "none", choices=("none", "fade", "slide"),
          group="appearance"),
    Field("appearance.sidebar_width", "int", 220, lo=160, hi=320, step=4,
          group="appearance"),
    Field("appearance.highlight_ms", "int", 1500, lo=300, hi=5000, step=100,
          group="appearance"),
    Field("appearance.status_ms", "int", 5000, lo=1000, hi=15000, step=500,
          group="appearance"),
    Field("appearance.window_width", "int", 920, lo=600, hi=2400, step=10,
          group="appearance"),
    Field("appearance.window_height", "int", 640, lo=400, hi=1400, step=10,
          group="appearance"),
    Field("appearance.remember_size", "bool", False, group="appearance"),
    # ---- behavior -------------------------------------------------------
    Field("behavior.start_page", "choice", START_PAGE_LAST, choices=START_PAGES),
    Field("behavior.preload_s", "int", 20, lo=0, hi=300, step=5),
    Field("behavior.refresh_s", "int", 5, lo=1, hi=60, step=1),
    Field("behavior.history_keep", "int", 1000, lo=100, hi=10000, step=100),
    Field("behavior.apply_delay_ms", "int", 1500, lo=300, hi=5000, step=100),
    Field("behavior.night_slider_ms", "int", 120, lo=30, hi=600, step=10),
    Field("behavior.series_still_ms", "int", 600, lo=200, hi=2000, step=50),
    Field("behavior.guard_s", "int", 10, lo=2, hi=60, step=1),
    Field("behavior.thumb_width", "int", 480, lo=160, hi=1024, step=16),
    Field("behavior.search_limit", "int", 20, lo=5, hi=50, step=5),
)

BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "settings-hub" / "settings.json"


class Settings:
    """The stored values, their defaults and the subscribers to changes."""

    def __init__(self, path: Path | str | None = None,
                 fields: tuple[Field, ...] = FIELDS) -> None:
        self.path = Path(path) if path is not None else default_path()
        self.fields = {f.key: f for f in fields}
        self._values: dict[str, Any] = {f.key: f.default for f in fields}
        self._subscribers: list[Callable[[str, Any], None]] = []
        self._load()

    # ---- reading --------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def get(self, key: str) -> Any:
        field = self.fields.get(key)
        if field is None:
            raise KeyError(key)
        return self._values[key]

    def default(self, key: str) -> Any:
        return self.fields[key].default

    def field(self, key: str) -> Field:
        return self.fields[key]

    def values(self) -> dict[str, Any]:
        return dict(self._values)

    def changed(self) -> dict[str, Any]:
        """Only the values that differ from their defaults (what the file keeps)."""
        return {k: v for k, v in self._values.items()
                if v != self.fields[k].default}

    def fields_of(self, group: str) -> list[Field]:
        return [f for f in self.fields.values() if f.group == group]

    def groups(self) -> tuple[str, ...]:
        """The groups that have fields, in GROUPS order."""
        return tuple(g for g in GROUPS if any(f.group == g for f in self.fields.values()))

    def __iter__(self) -> Iterator[Field]:
        return iter(self.fields.values())

    # ---- changing -------------------------------------------------------

    def set(self, key: str, value: Any) -> Any:
        """Store value after checking it; returns the previous value.

        A subscriber is called only when the value really changed, so an undo
        that restores what is already there does not trigger anything twice.
        """
        field = self.fields.get(key)
        if field is None:
            raise KeyError(key)
        checked = field.coerce(value)
        before = self._values[key]
        if checked == before:
            return before
        self._values[key] = checked
        self._save()
        for callback in list(self._subscribers):
            try:
                callback(key, checked)
            except Exception:  # a broken subscriber must not lose the value
                log.exception("settings subscriber for %s", key)
        return before

    def reset(self, key: str | None = None) -> list[tuple[str, Any, Any]]:
        """Put one field (or all of them) back to the default.

        Returns (key, before, after) for every value that changed; nothing is
        written when they all are at their defaults already.
        """
        keys = [key] if key is not None else list(self.fields)
        items: list[tuple[str, Any, Any]] = []
        for name in keys:
            before = self._values[name]
            self._values[name] = self.fields[name].default
            if before != self._values[name]:
                items.append((name, before, self._values[name]))
        if items:
            self._save()
            for name, _before, after in items:
                for callback in list(self._subscribers):
                    try:
                        callback(name, after)
                    except Exception:
                        log.exception("settings subscriber for %s", name)
        return items

    # ---- subscribers ----------------------------------------------------

    def subscribe(self, callback: Callable[[str, Any], None]) -> Callable[[], None]:
        """Call callback(key, value) after each change; returns the unsubscribe."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback) \
            if callback in self._subscribers else None

    # ---- the file -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("settings %s: %s", self.path, exc)
            return
        if not isinstance(raw, dict):
            log.warning("settings %s: not an object", self.path)
            return
        for key, value in raw.items():
            field = self.fields.get(key)
            if field is None:
                continue  # a field this version does not have (or a typo)
            try:
                self._values[key] = field.coerce(value)
            except ValueError as exc:
                log.warning("settings %s: %s", self.path, exc)

    def _save(self) -> None:
        """Write only the changed values, atomically, one file per path."""
        data = json.dumps(self.changed(), ensure_ascii=False, indent=1,
                          sort_keys=True) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".settings.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(data)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:  # a read-only config dir must not break the window
            log.warning("settings %s: %s", self.path, exc)


class SettingsApplier:
    """History's view of the settings: one item per key, key is the field name."""

    backend = "settings"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def read(self, keys: list[str]) -> dict[str, Any]:
        return {key: self.settings.get(key) for key in keys if key in self.settings.fields}

    def apply(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            try:
                self.settings.set(key, value)
            except (KeyError, ValueError) as exc:
                log.warning("undo of %s: %s", key, exc)


def register(history, settings: Settings) -> SettingsApplier:
    """Let History undo changes made on the General page."""
    applier = SettingsApplier(settings)
    history.register(SettingsApplier.backend, applier)
    return applier
