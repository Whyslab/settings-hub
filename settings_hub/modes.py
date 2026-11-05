"""One-click desktop modes: named bundles of settings, applied as one action.

A mode is not a new setting store: it is a list of (backend, key, value) items
that already exist (window variables, power profile and brightness, the night
filter). Applying a mode goes through the same appliers History uses, so undo
takes it back as one group. No GTK here; texts are in strings.MODES and
strings.MODE_ITEMS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Mode:
    id: str
    items: tuple[tuple[str, str, Any], ...]  # (backend, key, value)


# Keys used below: variables/__init__.py options, power's profile/brightness,
# screen-sleep's config paths and the night applier's temperature key.
NIGHT_OVERRIDE = "night.manual_override"
NIGHT_TEMP = "night.current_temp"

MODES: tuple[Mode, ...] = (
    Mode("work", (
        ("hypr", "general:gaps_in", 6),
        ("hypr", "general:gaps_out", 10),
        ("hypr", "decoration:rounding", 12),
        ("hypr", "decoration:blur:enabled", True),
        ("hypr", "decoration:dim_inactive", False),
        ("hypr", "general:snap:enabled", True),
        ("power", "power.profile", "balanced"),
        ("power", "power.brightness", 85),
        ("screen-sleep", NIGHT_OVERRIDE, False),
    )),
    Mode("game", (
        ("hypr", "general:gaps_in", 0),
        ("hypr", "general:gaps_out", 0),
        ("hypr", "general:border_size", 1),
        ("hypr", "decoration:rounding", 0),
        ("hypr", "decoration:blur:enabled", False),
        ("hypr", "decoration:shadow:enabled", False),
        ("hypr", "decoration:dim_inactive", False),
        ("power", "power.profile", "performance"),
        ("power", "power.brightness", 100),
        ("screen-sleep", NIGHT_OVERRIDE, False),
    )),
    Mode("night", (
        ("hypr", "decoration:rounding", 12),
        ("hypr", "decoration:blur:enabled", True),
        ("hypr", "decoration:dim_inactive", True),
        ("power", "power.profile", "balanced"),
        ("power", "power.brightness", 30),
        ("screen-sleep", NIGHT_OVERRIDE, True),
        ("night", NIGHT_TEMP, 3200),
    )),
    Mode("travel", (
        ("hypr", "decoration:blur:enabled", False),
        ("hypr", "decoration:rounding", 8),
        ("hypr", "general:gaps_in", 3),
        ("hypr", "general:gaps_out", 6),
        ("power", "power.profile", "power-saver"),
        ("power", "power.brightness", 45),
        ("screen-sleep", NIGHT_OVERRIDE, False),
    )),
)

BY_ID: dict[str, Mode] = {m.id: m for m in MODES}


def backends(mode: Mode) -> list[str]:
    out: list[str] = []
    for backend, _key, _value in mode.items:
        if backend not in out:
            out.append(backend)
    return out


def values_for(mode: Mode, backend: str) -> dict[str, Any]:
    return {key: value for b, key, value in mode.items if b == backend}


def label_for(backend: str, key: str) -> str:
    from . import strings  # the module with every Cyrillic string

    if backend == "hypr":
        return strings.VARS.get(key, (key,))[0]
    if backend == "power":
        return strings.POWER_LABELS.get(key, key)
    if backend in ("screen-sleep", "night"):
        return strings.MODE_ITEMS.get(key, key)
    return strings.MODE_ITEMS.get(key, key)


def matches(mode: Mode, current: dict[tuple[str, str], Any]) -> bool:
    """Is the desktop already showing this mode (every item equal)?"""
    for backend, key, value in mode.items:
        if (backend, key) not in current:
            return False
        if current[(backend, key)] != value:
            return False
    return True
