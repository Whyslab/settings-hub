"""Game binds: chosen key combinations are off while a game window is focused.

Hyprland does the work itself (0.57+, Lua config), so it also works with the
window closed, after a crash and right after login. This backend only keeps
the list and writes it out:

* games.json in the state dir: {"enabled", "patterns", "combos"} -- what the
  page shows and History stores;
* ~/.config/hypr/settings-hub-games.lua -- settings-hub.lua loads it last.

That Lua file, at every config load and on "window.active" / "window.class":

    a game window got focus  -> hl.unbind() each combination;
    focus left the game      -> `hyprctl reload config-only`, so every bind
                                comes back exactly as the config files say.

Nothing is remembered and re-created: under Lua `hyprctl binds -j` shows a
function number instead of the command (exec_cmd "9"), and binds made from Lua
functions cannot be rebuilt at all; a reload rebuilds all of them. A reload
takes ~10 ms and runs nothing (autostart lives in hl.on("hyprland.start")).

A pattern is matched against the window class and initial class; case does
not matter, `*` is any text and `?` one character: "dota2", "steam_app_*".

No GTK here.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..binds.parser import modmask, mods_text
from ..hypr import loads_settings_hub, lua_str
from ..workers import Workers

log = logging.getLogger(__name__)

BACKEND = "game-binds"  # History backend name
KEY = "games"  # the one History key: the whole state
WORKER = "game-binds"

DEFAULT: dict[str, Any] = {
    "enabled": False,
    "patterns": ["dota2", "steam_app_*"],
    "combos": ["SUPER + V", "SUPER + D"],
}
MAX_ITEMS = 50
MAX_TEXT = 100
MAX_WILDCARDS = 4
OWN_CLASS = "io.github.whyslab.SettingsHub"  # our window is never a game
LUA_FILE = "settings-hub-games.lua"

Runner = Callable[[list[str]], tuple[int, str]]  # hyprctl args -> (returncode, stdout)


def run_hyprctl(args: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(["hyprctl", *args], capture_output=True, text=True,
                              timeout=5, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("hyprctl %s: %s", " ".join(args[:2]), exc)
        return 127, ""
    return done.returncode, done.stdout


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "settings-hub" / "games.json"


def hypr_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hypr"


def lua_path() -> Path:
    return hypr_dir() / LUA_FILE


# ---- combinations and patterns -------------------------------------------------


def combo_of(mask: int, key: str) -> str:
    """Hyprland's Lua spelling: 'SUPER + SHIFT + V'."""
    return " + ".join([*mods_text(mask).split(), key])


def spellings(combo: str) -> list[str]:
    """Every modifier order of a combination.

    hl.unbind matches the text given to hl.bind, ignoring only case and spaces,
    so "SUPER + SHIFT + X" does not remove a bind written "SHIFT + SUPER + X".
    At most 4! = 24 spellings. Aliases (WIN, MOD4) are not covered.
    """
    parts = [p.strip() for p in combo.split("+")]
    mods, key = parts[:-1], parts[-1]
    return [" + ".join([*order, key]) for order in itertools.permutations(mods)]


def parse_combo(text: str) -> tuple[int, str]:
    """'SUPER + SHIFT + V' -> (65, 'V')."""
    parts = [p.strip() for p in text.split("+")]
    return modmask(" ".join(parts[:-1])), parts[-1]


def same_combo(a: str, b: str) -> bool:
    ma, ka = parse_combo(a)
    mb, kb = parse_combo(b)
    return ma == mb and ka.lower() == kb.lower()


def clean_combo(text: Any) -> str | None:
    """A combination written the way Hyprland reads it, or None if it is not one."""
    if not isinstance(text, str) or len(text) > MAX_TEXT or not text.strip():
        return None
    mask, key = parse_combo(text)
    if not key or any(ch in key for ch in '"\\\n') or modmask(key):
        return None
    return combo_of(mask, key)


def clean_pattern(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    text = re.sub(r"\*+", "*", text.strip())
    # Printable ASCII only: Lua's string.lower and "." work on bytes, and window
    # classes are ASCII. Few wildcards: Lua matching backtracks, in Hyprland's thread.
    if (not text or len(text) > MAX_TEXT or not all(32 <= ord(ch) < 127 for ch in text)
            or text.count("*") + text.count("?") > MAX_WILDCARDS):
        return None
    return text


def lua_pattern(pattern: str) -> str:
    """A glob ('steam_app_*') as an anchored Lua pattern for the lower-cased class."""
    out = []
    for ch in pattern.lower():
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        elif ch in "^$()%.[]+-":
            out.append("%" + ch)
        else:
            out.append(ch)
    return "^" + "".join(out) + "$"


def matches(pattern: str, window_class: str) -> bool:
    """The same test in Python (the page leaves such windows out of its list)."""
    regex = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
                    for ch in pattern.lower())
    return re.fullmatch(regex, window_class.lower()) is not None


def normalize(raw: Any) -> dict[str, Any]:
    """A valid state from whatever was read (a missing file -> the defaults)."""
    if not isinstance(raw, dict):
        return json.loads(json.dumps(DEFAULT))
    patterns: list[str] = []
    for item in raw.get("patterns", DEFAULT["patterns"]) or []:
        p = clean_pattern(item)
        if p is not None and p.lower() not in (x.lower() for x in patterns):
            patterns.append(p)
    combos: list[str] = []
    for item in raw.get("combos", DEFAULT["combos"]) or []:
        c = clean_combo(item)
        if c is not None and not any(same_combo(c, x) for x in combos):
            combos.append(c)
    return {
        "enabled": raw.get("enabled") is True,
        "patterns": patterns[:MAX_ITEMS],
        "combos": combos[:MAX_ITEMS],
    }


# ---- the Lua file ----------------------------------------------------------------

LUA_HEADER = """\
-- Generated by settings-hub (the "Game binds" page); the window rewrites this file.
-- While a game window is focused these key combinations are off; when focus
-- leaves it, the config is read again and every bind is back as the config has it.
"""

LUA_BODY = """\
local function is_game(w)
    if w == nil then return false end
    for _, name in ipairs({ w.class or "", w.initial_class or "" }) do
        name = string.lower(name)
        if name ~= own then
            for _, p in ipairs(patterns) do
                if string.match(name, p) then return true end
            end
        end
    end
    return false
end

local function turn_off()
    for _, c in ipairs(spellings) do pcall(hl.unbind, c) end
end

-- At load (login and every reload): a game may already be focused.
local off = is_game(hl.get_active_window())
if off then turn_off() end

local function check(w)
    if is_game(w) then
        if not off then
            off = true
            turn_off()
        end
    elseif off then
        off = false
        hl.exec_cmd("hyprctl reload config-only")
    end
end

hl.on("window.active", check)
hl.on("window.class", function() check(hl.get_active_window()) end)
"""


def _lua_list(items: list[str]) -> str:
    return "{ " + ", ".join(lua_str(i) for i in items) + " }" if items else "{}"


def build_lua(state: dict[str, Any]) -> str:
    state = normalize(state)
    if not state["enabled"]:
        return LUA_HEADER + "-- Off.\n"
    if not state["patterns"] or not state["combos"]:
        return LUA_HEADER + "-- On, but the list of games or of combinations is empty.\n"
    return (LUA_HEADER
            + f"local patterns = {_lua_list([lua_pattern(p) for p in state['patterns']])}"
            + "  -- " + ", ".join(p.replace("\n", " ") for p in state["patterns"]) + "\n"
            + f"local combos = {_lua_list(state['combos'])}\n"
            + "-- every modifier order: hl.unbind matches the spelling hl.bind got\n"
            + f"local spellings = {_lua_list([s for c in state['combos'] for s in spellings(c)])}\n"
            + f"local own = {lua_str(OWN_CLASS.lower())}\n\n"
            + LUA_BODY)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- the backend -----------------------------------------------------------------


@dataclass
class Probe:
    """What the page shows next to the list, read from the live session."""

    actions: dict[str, str] = field(default_factory=dict)  # combo -> description ("" = no text)
    classes: list[str] = field(default_factory=list)  # classes of the open windows
    loaded: bool = True  # settings-hub.lua loads our file (an older install does not)


class Backend:
    def __init__(self, workers: Workers, hyprctl: Runner | None = None,
                 state_file: Path | None = None, lua_file: Path | None = None) -> None:
        self.workers = workers
        self.hyprctl = hyprctl or run_hyprctl
        self.state_file = state_file or state_path()
        self.lua_file = lua_file or lua_path()
        self._seq = 0

    # History's Applier
    def read(self, keys: list[str]) -> dict[str, Any]:
        return {k: self.load() for k in keys if k == KEY}

    def apply(self, values: dict[str, Any]) -> None:
        if KEY in values:
            written, message = self.save(values[KEY])
            if not written:
                raise RuntimeError(message)

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = None
        except (OSError, ValueError) as exc:
            log.warning("reading %s: %s", self.state_file, exc)
            raw = None
        return normalize(raw)

    def save(self, state: dict[str, Any]) -> tuple[bool, str]:
        """Write both files, then reload Hyprland so the new list counts at once.

        (written, warning): written is False only if the files were not written
        (nothing changed); a failed reload is a warning - the list is saved and
        Hyprland takes it at its next reload.
        """
        state = normalize(state)
        try:
            _atomic_write(self.state_file, json.dumps(state, ensure_ascii=False, indent=1) + "\n")
            _atomic_write(self.lua_file, build_lua(state))
        except OSError as exc:
            return False, str(exc)
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return True, ""
        rc, out = self.hyprctl(["reload", "config-only"])
        if rc != 0 or out.strip() != "ok":
            return True, out.strip() or f"hyprctl reload: {rc}"
        return True, ""

    def sync(self) -> bool:
        """At start: a Lua file older than this version's text is written again
        (a reinstall keeps the file, so a fixed body would never arrive).
        True if it was rewritten. Without games.json there is nothing to sync."""
        if not self.state_file.exists():
            return False
        want = build_lua(self.load())
        try:
            if self.lua_file.read_text(encoding="utf-8") == want:
                return False
        except OSError:
            pass
        written, warning = self.save(self.load())
        if warning:
            log.warning("game binds: %s", warning)
        return written

    def queue_save(self, state: dict[str, Any],
                   on_done: Callable[[tuple[bool, str] | None, BaseException | None], None],
                   ) -> None:
        self._seq += 1  # a key of its own: every change runs and reports back
        self.workers.submit(WORKER, lambda: self.save(state), on_done, key=("save", self._seq))

    def probe(self, combos: list[str]) -> Probe:
        out = Probe()
        rc, text = self.hyprctl(["binds", "-j"])
        try:
            live = json.loads(text) if rc == 0 else []
        except ValueError:
            live = []
        for combo in combos:
            mask, key = parse_combo(combo)
            for b in live if isinstance(live, list) else []:
                if (isinstance(b, dict) and not b.get("submap")
                        and b.get("modmask") == mask
                        and str(b.get("key", "")).lower() == key.lower()):
                    action = str(b.get("description") or "") if b.get("has_description") else ""
                    out.actions[combo] = action
                    break
        rc, text = self.hyprctl(["clients", "-j"])
        try:
            clients = json.loads(text) if rc == 0 else []
        except ValueError:
            clients = []
        seen: set[str] = set()
        for c in clients if isinstance(clients, list) else []:
            cls = str(c.get("class") or "") if isinstance(c, dict) else ""
            if cls and cls != OWN_CLASS and cls.lower() not in seen:
                seen.add(cls.lower())
                out.classes.append(cls)
        out.classes.sort(key=str.lower)
        try:
            own_lua = (self.lua_file.parent / "settings-hub.lua").read_text(encoding="utf-8")
            main = (self.lua_file.parent / "hyprland.lua").read_text(encoding="utf-8")
            out.loaded = LUA_FILE in own_lua and loads_settings_hub(main)
        except OSError:
            out.loaded = False  # no Lua config: a .conf Hyprland never reads our file
        return out

    def queue_probe(self, combos: list[str],
                    on_done: Callable[[Probe | None, BaseException | None], None]) -> None:
        self.workers.submit(WORKER, lambda: self.probe(combos), on_done, key="probe")


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
