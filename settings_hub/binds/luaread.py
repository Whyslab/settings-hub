"""Binds as hyprland.lua writes them (Hyprland 0.57+). No GTK, read-only.

Under a Lua config `hyprctl binds -j` tells only the kind of dispatcher a bind
calls ("HL.Dispatcher(exec_cmd)", "function: 0x…"); its argument is an internal
number. What the bind runs is in hyprland.lua, often put together from
variables and loops, so the text alone does not say it.

read() runs hyprland.lua in a separate Lua interpreter (lua5.4 or lua) with a
stand-in `hl` that only records hl.bind / hl.unbind / hl.define_submap and
where each call is (file and line). Nothing reaches the running Hyprland, and
the functions a bind would call are never run. The config runs in a sandbox:

* no os.execute, io.popen, require, package, debug; os has getenv/date/time/clock;
* io.open reads only (mode "r"/"rb"), dofile/loadfile/io.open/io.lines only below
  the config's directory and $XDG_STATE_HOME, text chunks only (no bytecode);
* `lua -E` (no LUA_INIT), Lua 5.3/5.4 only, a minimal environment (HOME and
  the XDG variables), stdin empty, cwd the config's directory, memory and CPU
  capped by prlimit when it is there, killed after TIMEOUT_S, output capped.

Roots are real paths (symlinks inside them are followed: reading only). A run
that does not reach the config's end gives None: the page then shows the rows
as before rather than binds the rest of the config would have replaced.

annotate() pairs Hyprland's live list with the records by combination, submap
and dispatcher kind, and gives each paired item as a Bind in .conf terms
(exec, workspace, movefocus…) with the comment on its line and the comment
block above it, so names.py names it like a .conf bind. An item that cannot
be paired gets None: the page shows it as before.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import strings
from .parser import Bind, Combo, mods_text

log = logging.getLogger(__name__)

INTERPRETERS = ("lua5.4", "lua")
TIMEOUT_S = 2
MEMORY_B = 512 * 1024 * 1024
SOURCE_MAX_B = 1024 * 1024  # a Lua file larger than this is not read for comments
ENV_KEYS = ("HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
            "LANG", "LC_ALL")
SEP = "\x1f"  # between the key=value pairs of a table argument

# arg[1]: the config file; arg[2..]: directories it may read below.
# Output: one tab-separated line per call, "end\tok" (or the error) last.
DRIVER = r"""
if _VERSION ~= "Lua 5.4" and _VERSION ~= "Lua 5.3" then  -- older ones ignore loadfile's env
    io.stderr:write("needs Lua 5.3 or 5.4\n")
    os.exit(3)
end
local cfg = arg[1]
local roots = {}
for i = 2, #arg do roots[#roots + 1] = arg[i] end
local s_gsub, s_sub, s_find = string.gsub, string.sub, string.find
local t_concat, t_sort = table.concat, table.sort
local getinfo, write, real_open, real_lines = debug.getinfo, io.write, io.open, io.lines
local real_loadfile, real_load = loadfile, load
local type_, tostring_, pairs_, ipairs_ = type, tostring, pairs, ipairs
local select_, pcall_ = select, pcall
local setmt = setmetatable
local SEP = "\31"

local out, size, full = {}, 0, false
local LIMIT = 2000000  -- bytes of output; more means something is wrong
local ESC = { ["\\"] = "\\\\", ["\t"] = "\\t", ["\n"] = "\\n", ["\r"] = "\\r" }
local function esc(v) return (s_gsub(tostring_(v), "[\\\t\n\r]", ESC)) end
local function emit(...)
    local parts = {}
    for i = 1, select_("#", ...) do parts[i] = esc((select_(i, ...))) end
    local line = t_concat(parts, "\t")
    size = size + #line + 1
    if size > LIMIT then full = true else out[#out + 1] = line end
end

local function allowed(path)
    if type_(path) ~= "string" or s_find(path, "/..", 1, true) then return false end
    for _, r in ipairs_(roots) do
        if s_sub(path, 1, #r + 1) == r .. "/" then return true end
    end
    return false
end

local function copy(t)
    local c = {}
    for k, v in pairs_(t) do c[k] = v end
    return c
end

local ENV = {}
for _, k in ipairs_({ "assert", "error", "ipairs", "next", "pairs", "pcall", "xpcall", "select",
                      "tonumber", "tostring", "type", "rawequal", "rawget", "rawset", "rawlen",
                      "setmetatable" }) do
    ENV[k] = _G[k]
end
ENV.getmetatable = function(v) if type_(v) == "table" then return getmetatable(v) end end
ENV.print = function() end
ENV.collectgarbage = function() return 0 end
ENV.math, ENV.string, ENV.table = copy(math), copy(string), copy(table)
ENV.utf8, ENV.coroutine = copy(utf8), copy(coroutine)
ENV.string.dump = nil
ENV.os = { getenv = os.getenv, date = os.date, time = os.time, clock = os.clock,
           difftime = os.difftime }
ENV.io = {
    open = function(path, mode)
        mode = mode or "r"
        if mode ~= "r" and mode ~= "rb" then return nil, "read-only" end
        if not allowed(path) then return nil, "not allowed" end
        return real_open(path, mode)
    end,
    lines = function(path, ...)
        if not allowed(path) then error("not allowed: " .. tostring_(path), 2) end
        return real_lines(path, ...)
    end,
}
ENV.loadfile = function(path, _, env)
    if not allowed(path) then return nil, "not allowed: " .. tostring_(path) end
    return real_loadfile(path, "t", env or ENV)
end
ENV.dofile = function(path)
    local f, err = ENV.loadfile(path)
    if not f then error(err, 2) end
    return f()
end
ENV.load = function(chunk, name, _, env) return real_load(chunk, name, "t", env or ENV) end
ENV._G = ENV
ENV._VERSION = _VERSION

-- hl.dsp.window.move{...} -> an action that remembers "window.move" and its argument
local ACTIONS = setmt({}, { __mode = "k" })
local function ns(path)
    return setmt({}, {
        __index = function(_, k)
            return ns(path == "" and tostring_(k) or path .. "." .. tostring_(k))
        end,
        __call = function(_, a) local t = {}; ACTIONS[t] = { path, a }; return t end,
    })
end
local hole
hole = setmt({}, { __index = function() return hole end, __call = function() return nil end })

local function text(v)
    if type_(v) ~= "table" then return v == nil and "" or tostring_(v) end
    local keys = {}
    for k in pairs_(v) do keys[#keys + 1] = tostring_(k) end
    t_sort(keys)
    local parts = {}
    for i, k in ipairs_(keys) do
        local x = v[k]
        if x == nil then x = v[tonumber(k)] end
        parts[i] = s_gsub(k, SEP, " ") .. "=" .. s_gsub(tostring_(x), SEP, " ")
    end
    return t_concat(parts, SEP)
end

local submap, count = "", 0
local hl = setmt({}, { __index = function() return hole end })
hl.dsp = ns("")
for _, k in ipairs_({ "get_devices", "get_layers", "get_loaded_plugins", "get_monitors",
                      "get_windows", "get_workspace_windows", "get_workspaces" }) do
    hl[k] = function() return {} end
end
hl.get_current_submap = function() return submap end
hl.bind = function(keys, act, opts)
    local info = getinfo(2, "Sl")
    count = count + 1
    local id = count
    pcall_(function()
        local src, line = "", 0
        local name = info and s_sub(info.source, 2) or ""
        -- a chunk name is the config's to choose (load(code, "@/dev/zero")): only ours
        if info and s_sub(info.source, 1, 1) == "@" and (name == cfg or allowed(name)) then
            src, line = name, info.currentline
        end
        local kind, a = "?", ""
        if type_(act) == "function" then
            kind = "function"
        elseif ACTIONS[act] then
            kind, a = ACTIONS[act][1], text(ACTIONS[act][2])
        end
        local o = type_(opts) == "table" and opts or {}
        emit("bind", id, keys, kind, a, o.description or "", submap, src, line,
             o.locked and 1 or 0, o.repeating and 1 or 0, o.mouse and 1 or 0)
    end)
    return setmt({}, { __index = function(_, k)  -- an HL.Keybind
        if k == "remove" or k == "unbind" then return function() emit("remove", id) end end
        if k == "is_enabled" then return function() return true end end
        if k == "set_enabled" then return function() end end
    end })
end
hl.unbind = function(keys) emit("unbind", keys) end
hl.define_submap = function(name, a, b)  -- (name, fn) or (name, reset, fn)
    local fn = type_(b) == "function" and b or a
    local prev = submap
    submap = tostring_(name)
    if type_(fn) == "function" then pcall_(fn) end
    submap = prev
end
ENV.hl = hl

local f, err = real_loadfile(cfg, "t", ENV)
local ok, why = false, err
if f then ok, why = pcall_(f) end
for _, line in ipairs_(out) do write(line, "\n") end
if full then ok, why = false, "too much output" end
write("end\t", ok and "ok" or esc(tostring_(why)), "\n")
"""


@dataclass(frozen=True)
class Record:
    keys: str  # as the config wrote it: "SUPER + SHIFT + N"
    kind: str  # "exec_cmd", "window.move", "function", "?" (unknown)
    arg: str  # a string argument as is; a table as "k=v" pairs joined by SEP
    description: str
    submap: str
    file: str  # "" if not known
    line: int
    locked: bool = False
    repeating: bool = False
    mouse: bool = False
    id: int = 0

    @property
    def combo(self) -> Combo:
        mods, key = split_keys(self.keys)
        return Combo.of(mods, key)


def split_keys(keys: str) -> tuple[str, str]:
    """'SUPER + SHIFT + N' -> ('SUPER SHIFT', 'N')."""
    parts = [p.strip() for p in keys.split("+")]
    if len(parts) > 1 and parts[-1] == "" and keys.rstrip().endswith("+"):
        parts = [*parts[:-2], "+"]  # "SUPER + +": the plus key itself
    return " ".join(parts[:-1]), parts[-1]


def interpreter() -> str | None:
    for name in INTERPRETERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def safe_roots(roots: list[Path], spelled: bool = False) -> list[Path]:
    """Real paths of the roots; "/" or a relative one would allow everything.
    spelled: also each root as written (normalized, links kept), for the
    driver's text comparison: a config under a linked ~/.config/hypr (stow)
    names its files by the link."""
    out: list[Path] = []
    for r in roots:
        if not Path(r).is_absolute():  # Path("") is the current directory
            continue
        try:
            forms = [Path(r).resolve()]
        except (OSError, RuntimeError):
            continue
        if spelled:
            forms.append(Path(os.path.abspath(r)))
        for f in forms:
            if f != Path(f.anchor) and f not in out:
                out.append(f)
    return out


def default_roots(lua: Path) -> list[Path]:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return [lua.parent, Path(state)]


def _unescape(text: str) -> str:
    return re.sub(r"\\([\\tnr])", lambda m: {"t": "\t", "n": "\n", "r": "\r"}.get(
        m.group(1), "\\"), text)


def parse_output(out: str) -> list[Record] | None:
    """The driver's lines -> the binds still active at the end (unbinds applied).
    None unless the config ran to its end: a config that stopped early would
    leave binds it later unbinds or replaces, and the page would show those."""
    active: list[Record] = []
    finished = False
    for line in out.split("\n"):  # not splitlines(): \x1c, \x85 … are data
        f = [_unescape(x) for x in line.split("\t")]
        if f[0] == "bind" and len(f) == 12:
            try:
                ident, number = int(f[1]), int(f[8])
            except ValueError:
                continue
            active.append(Record(f[2], f[3], f[4], f[5], f[6], f[7], number,
                                 f[9] == "1", f[10] == "1", f[11] == "1", ident))
        elif f[0] == "remove" and len(f) == 2:
            active = [r for r in active if str(r.id) != f[1]]
        elif f[0] == "unbind" and len(f) == 2:
            try:
                gone = Record(f[1], "", "", "", "", "", 0).combo
            except (IndexError, ValueError):
                continue
            active = [r for r in active if r.combo != gone]
        elif f[0] == "end":
            if len(f) > 1 and f[1] == "ok":
                finished = True
            else:
                log.info("hyprland.lua stopped early in the reader: %s", f[1:])
    return active if finished else None


def read(lua: Path, roots: list[Path] | None = None,
         timeout: float = TIMEOUT_S) -> list[Record] | None:
    """The binds hyprland.lua makes, or None (no interpreter, it hangs, fails)."""
    exe = interpreter()
    if exe is None or not lua.is_file():
        return None
    dirs = safe_roots(roots if roots is not None else default_roots(lua), spelled=True)
    env = {k: os.environ[k] for k in ENV_KEYS if k in os.environ}
    limit = shutil.which("prlimit")  # memory and CPU caps; preexec_fn is unsafe in threads
    cmd = [limit, f"--as={MEMORY_B}", f"--cpu={TIMEOUT_S + 1}", "--"] if limit else []
    try:
        proc = subprocess.run([*cmd, exe, "-E", "-", str(lua), *map(str, dirs)],
                              input=DRIVER, capture_output=True, text=True, timeout=timeout,
                              env=env, cwd=str(lua.parent), errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("reading %s with %s failed: %s", lua, exe, exc)
        return None
    if proc.returncode != 0:
        log.info("reading %s with %s failed: %s", lua, exe, proc.stderr.strip()[:300])
        return None
    return parse_output(proc.stdout)


# ---- in .conf terms -----------------------------------------------------------

DIRECTIONS = {"left": "l", "right": "r", "up": "u", "down": "d"}
SIMPLE = {
    "window.close": "killactive",
    "window.kill": "forcekillactive",
    "window.float": "togglefloating",
    "window.fullscreen": "fullscreen",
    "window.cycle_next": "cyclenext",
    "window.bring_to_top": "bringactivetotop",
    "window.center": "centerwindow",
    "window.pin": "pin",
    "window.pseudo": "pseudo",
    "group.toggle": "togglegroup",
    "exit": "exit",
}


def pairs_of(arg: str) -> dict[str, str]:
    out = {}
    for part in arg.split(SEP) if arg else []:
        k, eq, v = part.partition("=")
        if eq:
            out[k] = v
    return out


def conf_action(r: Record) -> tuple[str, str]:
    """(dispatcher, arg) as a .conf bind would have them."""
    kind, arg = r.kind, r.arg
    p = pairs_of(arg) if SEP in arg or "=" in arg else {}
    if kind == "function":
        return strings.BN_LUA_FUNCTION, ""
    if kind == "exec_cmd":
        return "exec", arg
    if kind in ("window.drag", "window.resize") and r.mouse:
        return "mouse", "movewindow" if kind == "window.drag" else "resizewindow"
    if kind in ("focus", "window.move") and "workspace" in p:
        return ("workspace" if kind == "focus" else "movetoworkspace"), p["workspace"]
    if kind in ("focus", "window.move") and "direction" in p:
        d = p["direction"]
        return ("movefocus" if kind == "focus" else "movewindow"), DIRECTIONS.get(d, d)
    if kind == "window.resize" and {"x", "y"} <= p.keys():
        return "resizeactive", f"{p['x']} {p['y']}"
    if kind == "layout":
        return "layoutmsg", arg
    if kind == "submap":
        return "submap", arg
    if kind == "group.next":
        return "changegroupactive", "f"
    if kind == "group.prev":
        return "changegroupactive", "b"
    if kind in SIMPLE:
        return SIMPLE[kind], ""
    return kind.rsplit(".", 1)[-1], ", ".join(f"{k}={v}" for k, v in p.items()) if p else arg


# ---- comments in the Lua source ---------------------------------------------

_KEY_HINT = re.compile(r"[\w\s]+(\+[\w\s]+)+")  # "Fn+F4": names the key, not the action
_CODE_LIKE = re.compile(r"^\s*(hl\.|local\s|[\w.]+\s*\(|[\w.]+\s*=|end\b|if\s|for\s)")


def trailing_comment(line: str) -> str:
    """The `--` comment at the end of a Lua line ("" if none or unsure)."""
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "[" and line[i + 1:i + 2] in ("[", "="):
            return ""  # a long string: not worth the risk
        elif line.startswith("--", i):
            return line[i:].lstrip("-").strip()
        i += 1
    return ""


def comments(lines: list[str], number: int) -> tuple[str, str]:
    """(comment at the end of line `number`, the comment block right above it)."""
    if not 0 < number <= len(lines):
        return "", ""
    own = trailing_comment(lines[number - 1])
    if own and (_KEY_HINT.fullmatch(own) or own.startswith("[")):
        own = ""
    above: list[str] = []
    i = number - 2
    while i >= 0:
        s = lines[i].strip()
        if not s.startswith("--") or s.startswith("--[["):
            break
        text = s.lstrip("-").strip()
        if text and not _CODE_LIKE.match(text):
            above.append(text)
        i -= 1
    return own, " ".join(reversed(above))


# ---- pairing with Hyprland's live list ---------------------------------------


def live_kind(item: dict) -> str:
    """'HL.Dispatcher(exec_cmd)' -> 'exec_cmd', 'function: 0x…' -> 'function'."""
    d = str(item.get("dispatcher", ""))
    if d.startswith("HL.Dispatcher(") and d.endswith(")"):
        return d[len("HL.Dispatcher("):-1]
    if d.startswith("function:"):
        return "function"
    return ""


def _same_kind(item: dict, r: Record) -> bool:
    k = live_kind(item)
    return bool(k) and (k == r.kind if k == "function" else k == r.kind.rsplit(".", 1)[-1])


def _item_key(item: dict) -> str:
    code = int(item.get("keycode", 0) or 0)
    return f"code:{code}" if code else str(item.get("key", ""))


def annotate(live: list[dict], records: list[Record] | None,
             roots: list[Path] | None = None) -> list[Bind | None]:
    """For each live item: its bind as the config writes it, or None.
    Comments are read only from regular files below `roots` (none without)."""
    if not records:
        return [None] * len(live)
    used = [False] * len(records)
    at: dict[tuple[str, int], list[Record]] = {}
    for r in records:
        at.setdefault((r.file, r.line), []).append(r)
    texts: dict[str, list[str]] = {}

    dirs = safe_roots(roots or [])

    def lines_of(file: str) -> list[str]:
        if file not in texts:
            texts[file] = []
            try:
                real = Path(file).resolve(strict=True)
                if real.is_file() and any(real.is_relative_to(d) for d in dirs):
                    with open(real, "rb") as fh:  # is_file(): no FIFO, no device
                        data = fh.read(SOURCE_MAX_B)
                    texts[file] = data.decode("utf-8", "replace").splitlines()
            except (OSError, RuntimeError):
                pass
        return texts[file]

    out: list[Bind | None] = []
    for item in live:
        mask, key = int(item.get("modmask", 0)), _item_key(item)
        combo, submap = Combo.of(mask, key), str(item.get("submap", ""))
        pick = next((i for i, r in enumerate(records) if not used[i] and r.submap == submap
                     and r.combo == combo and _same_kind(item, r)), None)
        if pick is None:
            out.append(None)
            continue
        used[pick] = True
        r = records[pick]
        dispatcher, arg = conf_action(r)
        own, above = comments(lines_of(r.file), r.line) if r.file else ("", "")
        shared = len(at[(r.file, r.line)]) > 1  # a loop, or a helper that calls hl.bind
        if shared:
            own = ""
        nxt = at.get((r.file, r.line + 1), [])
        series = shared or any(  # like the .conf reader's runs
            conf_action(n)[0] == dispatcher and n.combo != r.combo for n in nxt)
        keyword = "bindm" if r.mouse else "bind" + ("l" if r.locked else "") + (
            "e" if r.repeating else "")
        desc = str(item.get("description", "") or "") or r.description
        out.append(Bind(keyword, mods_text(mask), mask, key, dispatcher, arg, desc, "",
                        own, above, Path(r.file) if r.file else Path("-"), r.line, submap,
                        series=series))
    return out
