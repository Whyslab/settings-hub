"""One-click desktop modes: named bundles of settings, applied as one action.

A mode is not a new setting store: it is a list of (backend, key, value) items
that already exist (window variables, power profile and brightness, the night
filter). Applying a mode goes through the same appliers History uses, so undo
takes it back as one group. No GTK here; texts are in strings.MODES and
strings.MODE_ITEMS.
"""

from __future__ import annotations

import json
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


def groups_that_turned_on(mode: Mode, groups: list, undo_prefix: str) -> list[str]:
    """The History groups that brought this mode about, oldest first ([] if none).

    A mode logs only what it changed, so its groups are found by their items:
    all of this mode, each set to the mode's value. Going back from the newest,
    they are collected until an undo that took one of its items away from the
    mode's value (the mode was turned off) or another mode's group (two items
    or more: a single one is a hand edit that happens to match): undoing
    them all gives the mode's items back as they were before it, even after it
    was switched on twice with hand edits in between.
    """
    wanted = {(b, k): _plain(v) for b, k, v in mode.items}
    found: list[str] = []
    for group in reversed(groups):
        undo = any(e.label.startswith(undo_prefix) for e in group.entries)
        if undo and any((e.backend, e.key) in wanted
                        and wanted[(e.backend, e.key)] != _plain(e.after)
                        for e in group.entries):
            break
        if not undo and _is_group_of(mode, group):
            found.append(group.id)
        elif (not undo and len(group.entries) >= 2  # one item alone is a hand edit
              and any(_is_group_of(other, group) for other in MODES if other is not mode)):
            break
    return found[::-1]


def _is_group_of(mode: Mode, group) -> bool:
    wanted = {(b, k): _plain(v) for b, k, v in mode.items}
    return bool(group.entries) and all(
        wanted.get((e.backend, e.key), _MISSING) == _plain(e.after) for e in group.entries)


_MISSING = object()


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value))


def matches(mode: Mode, current: dict[tuple[str, str], Any]) -> bool:
    """Is the desktop already showing this mode (every item equal)?"""
    for backend, key, value in mode.items:
        if (backend, key) not in current:
            return False
        if current[(backend, key)] != value:
            return False
    return True
