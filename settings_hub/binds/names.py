"""Human names for binds and key combinations. No GTK; texts in strings.py.

A bind's name, first found wins:

    1. "description"  the bindd description
    2. "comment"      the comment at the end of the line ("Fn + F1 (Mute)")
    3. "above"        the comment block right above, shortened to its first
                      clause ("Timer. A second press..." -> "Timer"); not when
                      the bind is one of a run of binds to the same dispatcher
                      (the comment then describes the run)
    4. "dictionary"   by dispatcher and argument, or by the command of an exec
                      (killactive -> "Close window", screenshot.sh area -> ...)
    5. "command"      the command itself

A line in settings-hub's own block carries its origin ("hyprland.conf:138") in
its comment; its name is the name of the line it came from.

Keys: "Super + Shift + N"; code:49 -> "Super + `"; XF86AudioMute -> its name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .. import strings
from .parser import MOD_ORDER, Bind, Config

HUMAN_SOURCES = ("description", "comment", "above", "dictionary")
_COMMANDS = tuple((re.compile(p), n) for p, n in strings.BN_COMMANDS)
_KEY_PREFIX = re.compile(r"^\s*(.+?)\s*(?::\s|\s—\s|\s-\s)\s*(.+)$")
_KEYLIKE = re.compile(r"^(code:\d+|print|esc|escape|tab|f\d{1,2}|xf86\w+)$", re.I)
_CUTS = (". ", ":", ";", " — ", " - ", ",")
_PARENS = re.compile(r"\s*\([^()]*\)")


@dataclass(frozen=True)
class Name:
    text: str
    source: str  # one of HUMAN_SOURCES or "command"

    @property
    def human(self) -> bool:
        return self.source in HUMAN_SOURCES


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _limit(text: str) -> str:
    if len(text) <= strings.BN_NAME_MAX:
        return text
    cut = text[:strings.BN_NAME_MAX].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


def shorten(comment: str) -> str:
    """The first clause of a comment, without key hints in parentheses."""
    text = " ".join(comment.split())
    m = _KEY_PREFIX.match(text)
    if m and ("+" in m.group(1) or _KEYLIKE.match(m.group(1))):
        text = m.group(2)  # "Ctrl + J: Open history" -> the part after the key
    end = len(text)
    for cut in _CUTS:
        i = text.find(cut)
        if 0 < i < end:
            end = i
    text = _PARENS.sub("", text[:end]).strip(" .,;:—-")
    if any(w in text.lower() for w in strings.BN_KEY_WORDS):
        return ""  # it talks about the key, not about what the key does
    return _limit(_capital(text))


def dictionary(bind: Bind) -> str:
    d, arg = bind.dispatcher, bind.arg.strip()
    if d == "mouse":
        return strings.BN_MOUSE.get(arg, "")
    if d == "exec":
        for pattern, name in _COMMANDS:
            if pattern.search(arg):
                return name
        return ""
    if d in strings.BN_DISPATCHERS:
        return strings.BN_DISPATCHERS[d]
    if d == "workspace" and arg in strings.BN_WORKSPACE_STEPS:
        return strings.BN_WORKSPACE_STEPS[arg]
    if d == "layoutmsg" and arg in strings.BN_LAYOUTMSG:
        return strings.BN_LAYOUTMSG[arg]
    if d == "submap" and arg == "reset":
        return strings.BN_SUBMAP_RESET
    if d in strings.BN_WITH_ARG and d != "exec":
        direction = strings.BN_DIRECTIONS.get(arg)
        if "{dir}" in strings.BN_WITH_ARG[d] and direction is None:
            return ""
        return strings.BN_WITH_ARG[d].format(arg=arg, dir=direction or "")
    return ""


def command_text(bind: Bind) -> str:
    """What the bind runs, as one line ("exec" is implied)."""
    if bind.dispatcher == "exec":
        return bind.arg
    if bind.dispatcher == "mouse":
        return bind.arg
    return f"{bind.dispatcher} {bind.arg}".strip()


def bind_name(bind: Bind, cfg: Config | None = None) -> Name:
    if bind.description:
        return Name(_limit(bind.description), "description")
    if bind.managed:
        origin = cfg.def_at(bind.origin) if cfg is not None and bind.origin else None
        if origin is not None:
            return bind_name(origin, cfg)
    elif bind.comment:
        return Name(_limit(_capital(bind.comment.strip())), "comment")
    if bind.above and not bind.series and not bind.managed:
        short = shorten(bind.above)
        if short:
            return Name(short, "above")
    named = dictionary(bind)
    if named:
        return Name(named, "dictionary")
    return Name(_limit(command_text(bind)) or bind.dispatcher, "command")


def entry_name(binds: list[Bind], cfg: Config | None = None) -> Name:
    """A key with several actions: the first human name, else all dictionary names."""
    names = [bind_name(b, cfg) for b in binds]
    for n in names:
        if n.source in ("description", "comment", "above"):
            return n
    if len(names) > 1 and all(n.human for n in names):
        return Name(" + ".join(n.text for n in names), "dictionary")
    return names[0]


# ---- keys -------------------------------------------------------------------


def key_label(key: str) -> str:
    raw = key.strip()
    low = raw.lower()
    if low.startswith("code:"):
        try:
            code = int(low[5:])
        except ValueError:
            return raw
        return strings.BN_KEYCODES.get(code, strings.BN_KEYCODE.format(code=code))
    if low in strings.BN_KEYS:
        return strings.BN_KEYS[low]
    if len(raw) == 1:
        return raw.upper()
    if re.fullmatch(r"f\d{1,2}", low):
        return raw.upper()
    return raw.replace("_", " ")


def mods_label(mask: int) -> list[str]:
    return [strings.BN_MODS[name] for name, bit in MOD_ORDER if mask & bit]


def combo_label(mask: int, key: str) -> str:
    """'Super + Shift + N'."""
    return strings.BN_KEY_JOIN.join([*mods_label(mask), key_label(key)])


def group_of(bind: Bind) -> str:
    """The list group a bind is shown in (strings.BN_GROUPS)."""
    if bind.submap:
        return "submap"
    if bind.dispatcher == "mouse":
        return "mouse"
    if bind.key.lower().startswith("xf86"):
        return "device"
    if bind.dispatcher == "exec":
        return "apps"
    if bind.dispatcher.startswith(("workspace", "movetoworkspace", "togglespecialworkspace")):
        return "workspaces"
    if bind.dispatcher in ("killactive", "forcekillactive", "togglefloating", "fullscreen",
                           "movefocus", "movewindow", "swapwindow", "resizeactive",
                           "cyclenext", "bringactivetotop", "layoutmsg", "pin", "pseudo",
                           "togglesplit", "centerwindow", "togglegroup",
                           "focusurgentorlast"):
        return "windows"
    return "other"
