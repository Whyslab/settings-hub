"""
Everything that writes to rofi's stdin protocol.

Protocol: man rofi-script(5). A directive is a line starting with NUL, then the
key, then US, then the value. A row is its text, optionally followed by NUL and
US-separated key/value option pairs.

Both are strictly single-line: a stray newline inside a value silently shifts
every following row by one, which looks like corrupted output rather than an
error. That is what _clean guards against.
"""
from __future__ import annotations

import html
import sys

US = "\x1f"   # separates key/value pairs
NUL = "\0"    # prefixes a directive line, and the options part of a row

MARK_PINNED = "★"
MARK_ACTIVE = "●"
ARROW = "→"
DIM = "#5a5a5a"

# Nerd Font glyphs, written as escapes rather than as the characters themselves.
# They live in Unicode's private use area, where any tool in the chain that is
# not careful about encoding silently turns them into nothing — and an empty
# prompt is not an error anyone notices until they look at the window.
GLYPH_SEARCH = "\uf002"    # the root prompt: a magnifying glass
GLYPH_FOLDER = "\uf07b"    # a folder
GLYPH_BACK = "\uf060"      # the back arrow
GLYPH_SECTION = "\uf013"   # a hub section: a cog

SEPARATOR_WIDTH = 24


def _clean(value):
    """Directives and row options are single-line; a newline would derail rofi."""
    return str(value).replace("\n", " ").replace(NUL, "").replace(US, " ")


def emit_directive(key, value):
    sys.stdout.write(f"{NUL}{_clean(key)}{US}{_clean(value)}\n")


def emit_row(text, **opts):
    line = _clean(text)
    if opts:
        line += NUL + US.join(f"{_clean(k)}{US}{_clean(v)}" for k, v in opts.items())
    sys.stdout.write(line + "\n")


def dim(text):
    return f"<span foreground='{DIM}'>{text}</span>"


def separator(tag=""):
    """A visual rule. Not selectable, and carries no meta so that typing hides it."""
    dashes = "─" * SEPARATOR_WIDTH
    return (f"sep:{tag}", {
        "display": dim(dashes),
        "nonselectable": "true",
        "meta": "",
    })


def back_row(label, meta=""):
    """The row that leaves a section. `permanent` keeps it visible while typing."""
    return ("..", {
        "display": f"{dim(GLYPH_BACK)}  {dim(html.escape(label))}",
        "meta": meta,
        "info": "up",
        "permanent": "true",
    })


def note_row(text):
    """A non-actionable line: 'Empty', 'not installed', an error."""
    return ("!", {"display": dim(html.escape(text)), "nonselectable": "true"})
