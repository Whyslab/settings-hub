"""Every desktop variable the window can change: one declarative table. No GTK.

A page builds its rows from this table, so adding a variable is one entry here
plus its text in strings.py (labels live there; this file has none). A Var is
also the contract with the Hyprland backend:

    option  hyprctl's own name, "general:gaps_in"; the same path is used for
            `hyprctl getoption` (reading the live value), and it maps to the
            nested Lua config table used to change it (`hyprctl eval`):
            "input:touchpad:tap-to-click" -> input.touchpad.tap_to_click
    kind    int | float | bool | choice | str; choice values are strings and
            the backend turns them back into the option's own type
    lo/hi/step  the bounds the spin button offers
    page/group  where the row appears (pages/<page>.py, group titles in strings)
    special  not a Hyprland option at all: the cursor theme and size live in
             the environment and are changed by `hyprctl setcursor`

Values that a person changed are kept in the window's own state and written to
~/.config/hypr/settings-hub-vars.lua, which Hyprland loads last: a `hyprctl
reload` or a new login then keeps them. The live value is always read back with
`hyprctl getoption`, so the page shows what Hyprland really uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = ("int", "float", "bool", "choice", "str")
PAGES = ("windows", "input")
GROUPS = {
    "windows": ("gaps", "effects", "layout", "tabs", "behavior"),
    "input": ("keyboard", "mouse", "touchpad", "cursor"),
}


@dataclass(frozen=True)
class Var:
    option: str
    kind: str
    default: Any
    lo: int | float | None = None
    hi: int | float | None = None
    step: int | float | None = None
    choices: tuple[str, ...] = ()
    page: str = ""
    group: str = ""
    unit: str = ""  # a suffix shown after the number: "px", "%"
    special: bool = False  # cursor: not a `hyprctl keyword` option
    numeric_choice: bool = False  # choice values are the option's ints ("0", "1")

    @property
    def lua_path(self) -> tuple[str, ...]:
        """Where the value goes in an hl.config table, e.g. ("general", "gaps_in")."""
        path: list[str] = []
        for part in self.option.split(":"):
            # Lua names use "_" where the old option name has "-" (tap-to-click).
            path.extend(part.replace("-", "_").split("."))
        return tuple(path)

    def stored(self, value: Any) -> Any:
        """The value as it is kept and written: an int for numeric choices."""
        if self.kind == "choice" and self.numeric_choice:
            return int(value)
        return value

    def to_lua(self, value: Any) -> str:
        """The value as a Lua literal for hl.config (strings are always quoted)."""
        return lua_literal(self.stored(value))


def lua_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return repr(round(value, 6))
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def var(option: str, kind: str, default: Any, page: str, group: str, **kw: Any) -> Var:
    return Var(option=option, kind=kind, default=default, page=page, group=group, **kw)


VARS: tuple[Var, ...] = (
    # ---- windows: borders and gaps --------------------------------------
    var("general:gaps_in", "int", 5, "windows", "gaps", lo=0, hi=60, unit="px"),
    var("general:gaps_out", "int", 20, "windows", "gaps", lo=0, hi=120, unit="px"),
    var("general:border_size", "int", 1, "windows", "gaps", lo=0, hi=10, unit="px"),
    var("decoration:rounding", "int", 0, "windows", "gaps", lo=0, hi=40, unit="px"),
    # ---- windows: effects ------------------------------------------------
    var("decoration:active_opacity", "float", 1.0, "windows", "effects",
        lo=0.3, hi=1.0, step=0.01, unit="%"),
    var("decoration:inactive_opacity", "float", 1.0, "windows", "effects",
        lo=0.3, hi=1.0, step=0.01, unit="%"),
    var("decoration:dim_inactive", "bool", False, "windows", "effects"),
    var("decoration:dim_strength", "float", 0.5, "windows", "effects",
        lo=0.0, hi=1.0, step=0.05, unit="%"),
    var("decoration:blur:enabled", "bool", True, "windows", "effects"),
    var("decoration:blur:size", "int", 8, "windows", "effects", lo=1, hi=20, unit="px"),
    var("decoration:blur:passes", "int", 1, "windows", "effects", lo=1, hi=5),
    var("decoration:blur:ignore_opacity", "bool", False, "windows", "effects"),
    var("decoration:blur:xray", "bool", False, "windows", "effects"),
    var("decoration:shadow:enabled", "bool", True, "windows", "effects"),
    var("decoration:shadow:range", "int", 4, "windows", "effects", lo=0, hi=40, unit="px"),
    # ---- windows: layout -------------------------------------------------
    var("general:layout", "choice", "dwindle", "windows", "layout",
        choices=("dwindle", "master", "scrolling")),
    var("dwindle:preserve_split", "bool", False, "windows", "layout"),
    var("dwindle:force_split", "choice", "0", "windows", "layout",
        choices=("0", "1", "2"), numeric_choice=True),
    var("dwindle:smart_split", "bool", False, "windows", "layout"),
    var("scrolling:column_width", "float", 0.5, "windows", "layout",
        lo=0.2, hi=1.0, step=0.005),
    var("scrolling:wrap_focus", "bool", True, "windows", "layout"),
    var("scrolling:wrap_swapcol", "bool", True, "windows", "layout"),
    var("scrolling:fullscreen_on_one_column", "bool", False, "windows", "layout"),
    var("general:snap:enabled", "bool", False, "windows", "layout"),
    var("general:snap:window_gap", "int", 10, "windows", "layout", lo=0, hi=60, unit="px"),
    var("general:snap:monitor_gap", "int", 10, "windows", "layout", lo=0, hi=60, unit="px"),
    # ---- windows: tabs ---------------------------------------------------
    var("group:auto_group", "bool", False, "windows", "tabs"),
    var("group:insert_after_current", "bool", True, "windows", "tabs"),
    var("group:groupbar:render_titles", "bool", True, "windows", "tabs"),
    var("group:groupbar:gradients", "bool", False, "windows", "tabs"),
    var("group:groupbar:stacked", "bool", False, "windows", "tabs"),
    var("group:groupbar:font_size", "int", 10, "windows", "tabs", lo=6, hi=30, unit="px"),
    var("group:groupbar:height", "int", 18, "windows", "tabs", lo=10, hi=60, unit="px"),
    # ---- windows: behavior -----------------------------------------------
    var("misc:focus_on_activate", "bool", False, "windows", "behavior"),
    var("misc:animate_manual_resizes", "bool", False, "windows", "behavior"),
    var("misc:animate_mouse_windowdragging", "bool", False, "windows", "behavior"),
    var("misc:mouse_move_enables_dpms", "bool", False, "windows", "behavior"),
    var("misc:key_press_enables_dpms", "bool", False, "windows", "behavior"),
    var("misc:disable_hyprland_logo", "bool", False, "windows", "behavior"),
    # ---- input: keyboard --------------------------------------------------
    var("input:kb_layout", "str", "us", "input", "keyboard"),
    var("input:kb_options", "str", "", "input", "keyboard"),
    var("input:repeat_delay", "int", 400, "input", "keyboard", lo=100, hi=2000,
        step=10, unit="мс"),
    var("input:repeat_rate", "int", 25, "input", "keyboard", lo=5, hi=100),
    var("input:numlock_by_default", "bool", False, "input", "keyboard"),
    # ---- input: mouse -----------------------------------------------------
    var("input:natural_scroll", "bool", False, "input", "mouse"),
    var("input:sensitivity", "float", 0.0, "input", "mouse", lo=-1.0, hi=1.0, step=0.05),
    var("input:follow_mouse", "choice", "1", "input", "mouse",
        choices=("0", "1", "2", "3"), numeric_choice=True),
    # ---- input: touchpad --------------------------------------------------
    var("input:touchpad:natural_scroll", "bool", False, "input", "touchpad"),
    var("input:touchpad:tap-to-click", "bool", True, "input", "touchpad"),
    var("input:touchpad:disable_while_typing", "bool", True, "input", "touchpad"),
    var("input:touchpad:clickfinger_behavior", "bool", False, "input", "touchpad"),
    var("input:touchpad:scroll_factor", "float", 1.0, "input", "touchpad",
        lo=0.2, hi=3.0, step=0.05),
    # ---- input: cursor (environment, not a keyword) ----------------------
    var("cursor:theme", "choice", "", "input", "cursor", special=True),
    var("cursor:size", "int", 24, "input", "cursor", lo=16, hi=96, step=2,
        unit="px", special=True),
)

BY_OPTION: dict[str, Var] = {v.option: v for v in VARS}


def for_page(page: str) -> tuple[Var, ...]:
    return tuple(v for v in VARS if v.page == page)


def get(option: str) -> Var | None:
    return BY_OPTION.get(option)


def grouped(page: str) -> list[tuple[str, list[Var]]]:
    """[(group id, vars)] for the page, empty groups left out, GROUPS order."""
    out = []
    for group in GROUPS.get(page, ()):
        members = [v for v in VARS if v.page == page and v.group == group]
        if members:
            out.append((group, members))
    return out
