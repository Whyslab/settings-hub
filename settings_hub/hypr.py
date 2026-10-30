"""Hyprland dispatches that work under either config format.

A Lua config (Hyprland 0.57+) takes only `hyprctl dispatch 'hl.dsp....'`; a
.conf only the plain `hyprctl dispatch name args`, and rejects the Lua form
with "Invalid dispatcher". So try Lua and fall back only on exactly that reply:
under Lua the plain text would run as Lua code (`hl.dispatch(<text>)`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


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


def loads_settings_hub(text: str) -> bool:
    """Whether a hyprland.lua names settings-hub.lua in code, not in a comment
    (block comments `--[[ ]]` and `--` to the end of a line are dropped first)."""
    text = re.sub(r"--\[(=*)\[.*?\]\1\]", "", text, flags=re.S)
    code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
    return "settings-hub.lua" in code


def main(argv: list[str]) -> int:
    """For install.sh: `python3 -m settings_hub.hypr loads-settings-hub FILE`
    exits 0 if FILE loads settings-hub.lua by a line of its own, else 1."""
    if len(argv) != 2 or argv[0] != "loads-settings-hub":
        print("usage: hypr loads-settings-hub FILE", file=sys.stderr)
        return 2
    return 0 if loads_settings_hub(Path(argv[1]).read_text(encoding="utf-8")) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
