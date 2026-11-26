"""What the home screen holds besides its tiles: pinned rows and command tiles. No GTK.

    pins = valid_pins(settings.get("home.pins"))   # [Pin(page, row, title, switch)]
    run_command("kitty -e btop")                   # through Hyprland, fire and forget
    moved(items, index, step)                      # a copy with one item moved

A pin is "page#row", the same address `settings-open` takes. A pin of one of the
window's own on/off settings (a General page field of kind bool) can carry a
switch on its tile; any other pin opens its page at its row.

A command runs the way a keybind's exec does: `hyprctl dispatch hl.dsp.exec_cmd`
(Lua config) or `hyprctl dispatch exec` (.conf). It runs with the user's own
rights, from the user's own settings file, so it can do nothing a terminal
cannot; it is never run by anything but a click on its tile.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import hypr, registry, settings, strings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pin:
    address: str  # "page#row"
    page_id: str
    row_id: str
    page_title: str
    row_title: str
    switch: str = ""  # a bool field of the window's settings this tile can flip


def split(address: str) -> tuple[str, str]:
    page_id, _, row_id = address.partition("#")
    return page_id, row_id


def address(page_id: str, row_id: str) -> str:
    return f"{page_id}#{row_id}"


def pin_of(address_: str) -> Pin | None:
    """The pin, or None when its page or row no longer exists (a renamed row)."""
    page_id, row_id = split(address_)
    if registry.get(page_id) is None:
        return None
    if page_id == "general":
        field = settings.BY_KEY.get(row_id)
        if field is None or field.group in settings.HIDDEN_GROUPS:
            return None
        title = strings.HUB_SETTINGS[row_id][0]
        return Pin(address_, page_id, row_id, registry.title(page_id), title,
                   switch=row_id if field.kind == "bool" else "")
    row = registry.rows(page_id).get(row_id)
    if row is None:
        return None
    return Pin(address_, page_id, row_id, registry.title(page_id), row[0])


def valid_pins(addresses: list[str]) -> list[Pin]:
    return [p for p in (pin_of(a) for a in addresses) if p is not None]


def moved(items: list[Any], index: int, step: int) -> list[Any]:
    """A copy of items with items[index] moved by step; unchanged past an end."""
    out = list(items)
    target = index + step
    if 0 <= index < len(out) and 0 <= target < len(out):
        out[index], out[target] = out[target], out[index]
    return out


def command_argv(cmd: str) -> list[str]:
    """The hyprctl call for cmd; the command travels as an argument, not as shell text."""
    return hypr.dual_dispatch(f"hl.dsp.exec_cmd({hypr.lua_str(cmd)})", "exec", cmd)


def run_command(cmd: str, spawn: Callable[..., Any] = subprocess.Popen) -> None:
    """Start cmd through Hyprland and return at once; OSError if hyprctl cannot start."""
    spawn(command_argv(cmd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, start_new_session=True)
    log.info("command tile started")  # not the text: it may hold a token
