"""Read Hyprland's key binds the way Hyprland does. No GTK, read-only.

parse(main) reads hyprland.conf and every `source =` file at the point where it
is sourced (`~`, `$variables` and globs expanded, relative paths against the
sourcing file's directory), and replays the bind lines in order:

    bind[flags] = MODS, KEY, DISPATCHER, ARG     flags: l e m r n d o t i s p c g u
    bindd       = MODS, KEY, DESCRIPTION, DISPATCHER, ARG
    bindm       = MODS, KEY, DISPATCHER          (Hyprland: dispatcher "mouse")
    unbind      = MODS, KEY                      removes every earlier bind of
                                                  that modmask and key spelling
    submap      = NAME | reset

Each Bind keeps its keyword and flags, file, line, the trailing comment, the
comment block right above it, and whether it lies in settings-hub's managed
block (then the comment is its origin, "hyprland.conf:138").

Comments start at a single `#`; `##` is a literal `#`. Lines inside `name { }`
categories are not binds. Modifier names are matched like Hyprland does
(substring, case-insensitive: "SUPERSHIFT" works).

settings-hub.conf (`own`) is read after hyprland.conf if hyprland.conf does not
source it yet (Config.own_sourced tells which), so the page shows what the
config will be once the source line is in place.

reconcile() compares the parsed binds with `hyprctl binds -j` by (modmask, key,
dispatcher, arg, submap).
"""

from __future__ import annotations

import glob
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

BEGIN = "# >>> settings-hub binds"
END = "# <<< settings-hub binds"
ADDED = "settings-hub"  # the origin comment of a bind added in the window
MAX_DEPTH = 16

# Hyprland's stringToModMask: substring tests, in this order of bits.
MOD_BITS = (
    (("SHIFT",), 1),
    (("CAPS",), 2),
    (("CTRL", "CONTROL"), 4),
    (("ALT", "MOD1"), 8),
    (("MOD2",), 16),
    (("MOD3",), 32),
    (("SUPER", "WIN", "LOGO", "MOD4", "META"), 64),
    (("MOD5",), 128),
)
# How a modmask is written back: Super first, like the config does.
MOD_ORDER = (("SUPER", 64), ("CTRL", 4), ("ALT", 8), ("SHIFT", 1), ("CAPS", 2),
             ("MOD2", 16), ("MOD3", 32), ("MOD5", 128))

_BIND_KW = re.compile(r"^bind([a-z]*)$")
_ORIGIN = re.compile(r"^(\S+):(\d+)$")
_CONFIG_LIKE = re.compile(r"^\s*[\w$:.-]+\s*=")


def modmask(text: str) -> int:
    upper = text.upper()
    mask = 0
    for names, bit in MOD_BITS:
        if any(n in upper for n in names):
            mask |= bit
    return mask


def mods_text(mask: int) -> str:
    return " ".join(name for name, bit in MOD_ORDER if mask & bit)


# Keysym -> key code on the first keyboard layout (us). Hyprland resolves a
# keysym bind on the first layout without modifiers, so "SUPER, grave" and
# "SUPER, code:49" fire on the same key press and are one combination.
# Taken from xkb: `xkbcli how-to-type --layout us --keysym NAME` (level 1).
# Page_Up/Page_Down are xkb's other names of Prior/Next.
US_KEYCODES = {
    "escape": 9, "1": 10, "2": 11, "3": 12, "4": 13, "5": 14, "6": 15, "7": 16, "8": 17,
    "9": 18, "0": 19, "minus": 20, "equal": 21, "backspace": 22, "tab": 23, "q": 24, "w": 25,
    "e": 26, "r": 27, "t": 28, "y": 29, "u": 30, "i": 31, "o": 32, "p": 33,
    "bracketleft": 34, "bracketright": 35, "return": 36, "a": 38, "s": 39, "d": 40, "f": 41,
    "g": 42, "h": 43, "j": 44, "k": 45, "l": 46, "semicolon": 47, "apostrophe": 48,
    "grave": 49, "backslash": 51, "z": 52, "x": 53, "c": 54, "v": 55, "b": 56, "n": 57,
    "m": 58, "comma": 59, "period": 60, "slash": 61, "space": 65, "f1": 67, "f2": 68,
    "f3": 69, "f4": 70, "f5": 71, "f6": 72, "f7": 73, "f8": 74, "f9": 75, "f10": 76,
    "scroll_lock": 78, "f11": 95, "f12": 96, "print": 107, "home": 110, "up": 111,
    "prior": 112, "page_up": 112, "left": 113, "right": 114, "end": 115, "down": 116,
    "next": 117, "page_down": 117, "insert": 118, "delete": 119, "xf86audiomute": 121,
    "xf86audiolowervolume": 122, "xf86audioraisevolume": 123, "pause": 127, "menu": 135,
    "xf86audionext": 171, "xf86audioplay": 172, "xf86audioprev": 173, "xf86audiostop": 174,
    "xf86audiomicmute": 198, "xf86monbrightnessdown": 232, "xf86monbrightnessup": 233,
}


def key_identity(key: str) -> str:
    """Two spellings that fire on the same key press compare equal:
    "grave" == "code:49", "Page_Down" == "next", "k" == "K"."""
    key = key.strip()
    low = key.lower()
    if low.startswith("code:"):
        return "code:" + low[5:].strip()
    if low.startswith("mouse:"):
        return low
    code = US_KEYCODES.get(key.casefold())  # Hyprland looks keysyms up case-insensitively
    return f"code:{code}" if code else key.casefold()


@dataclass(frozen=True)
class Combo:
    modmask: int
    key: str  # key_identity()

    @classmethod
    def of(cls, mods: str | int, key: str) -> Combo:
        return cls(mods if isinstance(mods, int) else modmask(mods), key_identity(key))

    @classmethod
    def parse(cls, text: str) -> Combo:
        """'SUPER SHIFT, K' (the History key of a combination)."""
        mods, _, key = text.partition(",")
        return cls.of(mods, key)


def combo_text(mask: int, key: str) -> str:
    """The History key of a combination: 'SUPER SHIFT, K' (key as spelled)."""
    return f"{mods_text(mask)}, {key.strip()}"


def keycode_of(key: str) -> int:
    """49 for "code:49", else 0."""
    low = key.strip().lower()
    if low.startswith("code:"):
        try:
            return int(low[5:])
        except ValueError:
            return 0
    return 0


def split_comment(line: str) -> tuple[str, str]:
    """(code as written, with `##` escapes kept; the comment text)."""
    i = 0
    while i < len(line):
        if line[i] == "#":
            if line[i + 1:i + 2] == "#":
                i += 2
                continue
            return line[:i], line[i + 1:].strip()
        i += 1
    return line, ""


@dataclass(frozen=True)
class Bind:
    keyword: str  # "bind", "bindl", "bindel", "bindm", "bindd"...
    mods: str  # as written, variables expanded
    modmask: int
    key: str  # as written: "Tab", "escape", "code:49", "mouse:272"
    dispatcher: str  # as Hyprland reports it: "mouse" for bindm
    arg: str
    description: str  # bindd only
    rest: str  # everything after "MODS, KEY," as written (escapes kept), for rewriting
    comment: str  # trailing comment
    above: str  # the comment block directly above, joined ("" if none)
    file: Path
    line: int
    submap: str = ""
    managed: bool = False  # inside settings-hub's block
    series: bool = False  # the next line binds another key to the same dispatcher

    @property
    def flags(self) -> str:
        return _BIND_KW.match(self.keyword).group(1)

    @property
    def combo(self) -> Combo:
        return Combo.of(self.modmask, self.key)

    @property
    def keycode(self) -> int:
        return keycode_of(self.key)

    @property
    def origin(self) -> str:
        """For a managed line: where it came from ("hyprland.conf:138", or
        "settings-hub" for a bind added in the window)."""
        if not self.managed:
            return ""
        return self.comment if _ORIGIN.match(self.comment) or self.comment == ADDED else ""

    def action(self) -> tuple[str, str, str, str]:
        """What it does, independent of the key: compared when rewriting."""
        return (self.keyword, self.dispatcher, self.arg, self.description)


@dataclass(frozen=True)
class Unbind:
    mods: str
    modmask: int
    key: str
    file: Path
    line: int
    managed: bool
    removed: tuple[Bind, ...]


@dataclass
class Config:
    main: Path
    own: Path | None
    binds: list[Bind] = field(default_factory=list)  # effective, in order
    defs: list[Bind] = field(default_factory=list)  # every bind line, also unbound ones
    unbinds: list[Unbind] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)  # read, in order
    missing: list[Path] = field(default_factory=list)  # sourced, but not there
    variables: dict[str, str] = field(default_factory=dict)
    own_sourced: bool = False  # hyprland.conf (or a file it sources) sources `own`
    own_has_block: bool = False

    @property
    def hypr_dir(self) -> Path:
        return self.main.parent

    def where(self, bind: Bind) -> str:
        return location(bind.file, bind.line, self.hypr_dir)

    def def_at(self, origin: str) -> Bind | None:
        for b in self.defs:
            if not b.managed and self.where(b) == origin:
                return b
        return None


def location(path: Path, line: int, hypr_dir: Path) -> str:
    """'hyprland.conf:138' inside the hypr directory, '~/...:3' elsewhere."""
    try:
        rel = str(path.relative_to(hypr_dir))
    except ValueError:
        home = str(Path.home())
        text = str(path)
        rel = "~" + text[len(home):] if text.startswith(home + os.sep) else text
    return f"{rel}:{line}"


def expand(text: str, variables: dict[str, str], escape: bool = False) -> str:
    """Hyprlang's substitution: longest variable names first."""
    for name in sorted(variables, key=len, reverse=True):
        token = "$" + name
        if token in text:
            value = variables[name]
            text = text.replace(token, value.replace("#", "##") if escape else value)
    return text


def expand_path(text: str, base: Path) -> str:
    text = text.strip()
    if text == "~" or text.startswith("~/"):
        text = str(Path.home()) + text[1:]
    if not os.path.isabs(text):
        text = str(base / text)
    return text


def parse_bind_value(keyword: str, value: str) -> tuple[str, str, str, str, str] | None:
    """(mods, key, description, dispatcher, arg) of an unescaped bind value."""
    has_desc = "d" in _BIND_KW.match(keyword).group(1)
    parts = [p.strip() for p in value.split(",", 4 if has_desc else 3)]
    if len(parts) < 3:
        return None
    while len(parts) < (5 if has_desc else 4):
        parts.append("")
    if has_desc:
        mods, key, desc, dispatcher, arg = parts
    else:
        (mods, key, dispatcher, arg), desc = parts, ""
    if "m" in _BIND_KW.match(keyword).group(1):
        dispatcher, arg = "mouse", dispatcher
    return mods, key, desc, dispatcher, arg


class _Reader:
    def __init__(self, main: Path, own: Path | None, overrides: dict[Path, str]) -> None:
        self.cfg = Config(main=main, own=own)
        self.overrides = {Path(p): t for p, t in overrides.items()}
        self.active: list[Bind] = []
        self.submap = ""
        self.stack: list[Path] = []

    def text(self, path: Path) -> str | None:
        if path in self.overrides:
            return self.overrides[path]
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def read(self, path: Path) -> None:
        if path in self.stack or len(self.stack) >= MAX_DEPTH:
            return  # a source loop; Hyprland refuses it as well
        text = self.text(path)
        if text is None:
            self.cfg.missing.append(path)
            return
        self.cfg.files.append(path)
        self.stack.append(path)
        try:
            self._lines(path, text.splitlines())
        finally:
            self.stack.pop()

    def _lines(self, path: Path, lines: list[str]) -> None:
        depth = 0
        above: list[str] = []
        in_block = False
        is_own = self.cfg.own is not None and path == self.cfg.own
        runs = _bind_lines(lines)
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if is_own and stripped == BEGIN:
                in_block = True
                self.cfg.own_has_block = True
                above = []
                continue
            if is_own and stripped == END:
                in_block = False
                above = []
                continue
            code, comment = split_comment(line)
            code = code.strip()
            if not code:
                if stripped.startswith("#"):
                    if not _CONFIG_LIKE.match(comment):  # commented-out config is not prose
                        above.append(comment)
                else:
                    above = []
                continue
            here_above = " ".join(above)
            above = []
            if code.endswith("{"):
                depth += 1
                continue
            if code == "}":
                depth = max(0, depth - 1)
                continue
            if depth or "=" not in code:
                continue
            keyword, _, raw_value = code.partition("=")
            keyword = keyword.strip()
            raw_value = raw_value.strip()
            value = expand(raw_value.replace("##", "#"), self.cfg.variables)
            if keyword.startswith("$"):
                self.cfg.variables[keyword[1:]] = value
            elif keyword == "source":
                self._source(path, value)
            elif keyword == "submap":
                name = value.split(",", 1)[0].strip()
                self.submap = "" if name == "reset" else name
            elif keyword == "unbind":
                self._unbind(path, number, value, in_block)
            elif _BIND_KW.match(keyword):
                raw = expand(raw_value, self.cfg.variables, escape=True)
                mine, nxt = runs.get(number), runs.get(number + 1)
                series = bool(mine and nxt and nxt[1] == mine[1] and nxt[0] != mine[0])
                self._bind(path, number, keyword, value, raw, comment, here_above, in_block,
                           series)

    def _source(self, path: Path, value: str) -> None:
        target = expand_path(value, path.parent)
        targets = sorted(glob.glob(target)) if glob.has_magic(target) else [target]
        for t in targets:
            if self.cfg.own is not None and Path(t) == self.cfg.own:
                self.cfg.own_sourced = True
            self.read(Path(t))

    def _unbind(self, path: Path, number: int, value: str, managed: bool) -> None:
        mods, _, key = value.partition(",")
        mask, key = modmask(mods), key.strip()
        code = keycode_of(key)
        removed = tuple(b for b in self.active if b.modmask == mask and (
            b.keycode == code if code else (not b.keycode and b.key == key)))
        self.active = [b for b in self.active if b not in removed]
        self.cfg.unbinds.append(Unbind(mods.strip(), mask, key, path, number, managed, removed))

    def _bind(self, path: Path, number: int, keyword: str, value: str, raw: str,
              comment: str, above: str, managed: bool, series: bool) -> None:
        parsed = parse_bind_value(keyword, value)
        if parsed is None:
            return
        mods, key, desc, dispatcher, arg = parsed
        rest = raw.split(",", 2)[2].rstrip() if raw.count(",") >= 2 else ""
        bind = Bind(keyword, mods, modmask(mods), key, dispatcher, arg, desc, rest,
                    comment, above, path, number, self.submap, managed, series)
        self.cfg.defs.append(bind)
        self.active.append(bind)


def _bind_lines(lines: list[str]) -> dict[int, tuple[str, str]]:
    """Line number -> (mods and key as written, dispatcher) for every bind line."""
    out = {}
    for number, line in enumerate(lines, start=1):
        code = split_comment(line)[0].strip()
        keyword, eq, value = code.partition("=")
        keyword = keyword.strip()
        if eq and _BIND_KW.match(keyword):
            parsed = parse_bind_value(keyword, value.replace("##", "#"))
            if parsed is not None:
                out[number] = (" ".join(parsed[0].split()) + "," + parsed[1], parsed[3])
    return out


def parse(main: Path | str, own: Path | str | None = None,
          overrides: dict[Path, str] | None = None) -> Config:
    """Read the config. overrides: file -> text to use instead of the file."""
    main = Path(main)
    reader = _Reader(main, Path(own) if own else None, overrides or {})
    reader.read(main)
    cfg = reader.cfg
    if cfg.own is not None and not cfg.own_sourced:
        reader.read(cfg.own)  # as if sourced at the end (what the installer adds)
    cfg.binds = list(reader.active)
    return cfg


# ---- the live list ---------------------------------------------------------


def _live_key(modmask_: int, key: str, keycode: int, dispatcher: str, arg: str,
              submap: str) -> tuple:
    k = f"code:{keycode}" if keycode else key_identity(key)
    return (modmask_, k, dispatcher, arg.strip(), submap)


def bind_live_key(b: Bind) -> tuple:
    return _live_key(b.modmask, b.key if not b.keycode else "", b.keycode, b.dispatcher,
                     b.arg, b.submap)


def json_live_key(item: dict) -> tuple:
    return _live_key(int(item.get("modmask", 0)), str(item.get("key", "")),
                     int(item.get("keycode", 0) or 0), str(item.get("dispatcher", "")),
                     str(item.get("arg", "")), str(item.get("submap", "")))


def reconcile(binds: list[Bind], live: list[dict]) -> tuple[list[bool], list[dict]]:
    """Which parsed binds Hyprland really has, and live binds not in the files."""
    pool = Counter(json_live_key(item) for item in live)
    found = []
    for b in binds:
        k = bind_live_key(b)
        if pool[k] > 0:
            pool[k] -= 1
            found.append(True)
        else:
            found.append(False)
    extra = []
    for item in live:
        k = json_live_key(item)
        if pool[k] > 0:
            pool[k] -= 1
            extra.append(item)
    return found, extra
