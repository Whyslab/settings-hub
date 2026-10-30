"""Hyprland dispatches that work under either config format.

A Lua config (Hyprland 0.57+) takes only `hyprctl dispatch 'hl.dsp....'`; a
.conf only the plain `hyprctl dispatch name args`, and rejects the Lua form
with "Invalid dispatcher". So try Lua and fall back only on exactly that reply:
under Lua the plain text would run as Lua code (`hl.dispatch(<text>)`).
"""

from __future__ import annotations


def lua_str(text: str) -> str:
    """A double-quoted Lua string literal.

    Not json.dumps: its \\uXXXX escapes are not Lua (Lua wants \\u{XXXX}), so
    non-ASCII text stays as it is (Lua reads UTF-8 bytes verbatim) and control
    characters become decimal escapes.
    """
    out = []
    for ch in text:
        if ch in '\\"':
            out.append("\\" + ch)
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\{ord(ch):03d}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def dual_dispatch(lua: str, *legacy: str) -> list[str]:
    """A fire-and-forget command: the Lua dispatch, or the plain one if a .conf
    Hyprland rejected it. Arguments travel as positional parameters, never
    inside the script text.
    """
    script = ('case "$(hyprctl dispatch "$1")" in '
              '*"Invalid dispatcher"*) shift; hyprctl dispatch "$@" ;; esac')
    return ["sh", "-c", script, "sh", lua, *legacy]
