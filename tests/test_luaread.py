"""binds/luaread.py: hyprland.lua run with a stand-in `hl` in a sandbox, paired
with Hyprland's live list. Runs a real Lua interpreter on files in tmp_path."""

import os
import shutil
import time
from pathlib import Path

import pytest

from settings_hub.binds import luaread, names
from settings_hub.binds.luaread import Record

needs_lua = pytest.mark.skipif(luaread.interpreter() is None, reason="no Lua interpreter")

CONFIG = r"""
local mainMod = "SUPER"
local home = os.getenv("HOME")
local lr = { locked = true, repeating = true }

hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd("kitty"))
hl.bind(mainMod .. " + SHIFT + R", hl.dsp.exec_cmd("rofi -show drun")) -- запасной плоский список
-- Таймер. Второе нажатие показывает уже идущий.
hl.bind(mainMod .. " + T", hl.dsp.exec_cmd("python3 " .. home .. "/timer.py --daemon"))
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl s 5%+"), lr)  -- Fn+F3

-- Столы: цифра — перейти
for i = 1, 3 do
    hl.bind(mainMod .. " + " .. i, hl.dsp.focus({ workspace = i }))
end
hl.bind(mainMod .. " + left", hl.dsp.focus({ direction = "left" }), { description = "Фокус влево" })
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind("ALT + Tab", function() hl.dispatch(hl.dsp.window.cycle_next()) end)
hl.bind(mainMod .. " + N", hl.dsp.exec_cmd("old"))
hl.define_submap("capture", function()
    hl.bind("SUPER + CTRL + ALT + Escape", hl.dsp.submap("reset"))
end)
dofile(DIR .. "/more.lua")
"""
MORE = """hl.unbind("SUPER + N")
hl.bind("SUPER + N", hl.dsp.exec_cmd("new"))
"""


def write_config(tmp_path, text=CONFIG, more=MORE):
    lua = tmp_path / "hypr" / "hyprland.lua"
    lua.parent.mkdir(parents=True, exist_ok=True)
    lua.write_text(f'local DIR = "{lua.parent}"\n' + text)
    (lua.parent / "more.lua").write_text(more)
    return lua


def live_of(records):
    """Hyprland's live list as 0.57 reports it for these records."""
    out = []
    for r in records:
        mods, key = luaread.split_keys(r.keys)
        kind = "function: 0x1" if r.kind == "function" else \
            f"HL.Dispatcher({r.kind.rsplit('.', 1)[-1]})"
        out.append({"modmask": luaread.Combo.of(mods, key).modmask, "key": key, "keycode": 0,
                    "submap": r.submap, "dispatcher": kind, "arg": "7",
                    "description": r.description})
    return out


@needs_lua
def test_variables_loops_submaps_dofile_and_unbinds(tmp_path):
    lua = write_config(tmp_path)
    recs = luaread.read(lua, roots=[lua.parent])
    assert recs is not None
    by = {(r.keys, r.submap): r for r in recs}
    assert by[("SUPER + Q", "")].kind == "exec_cmd" and by[("SUPER + Q", "")].arg == "kitty"
    assert [by[(f"SUPER + {i}", "")].arg for i in (1, 2, 3)] == \
        ["workspace=1", "workspace=2", "workspace=3"]
    assert by[("SUPER + CTRL + ALT + Escape", "capture")].kind == "submap"
    assert by[("ALT + Tab", "")].kind == "function"
    assert by[("XF86MonBrightnessUp", "")].locked and by[("XF86MonBrightnessUp", "")].repeating
    n = [r for r in recs if r.keys == "SUPER + N"]
    assert [r.arg for r in n] == ["new"]  # the unbind in more.lua removed "old"
    assert n[0].file == str(lua.parent / "more.lua") and n[0].line == 2
    assert by[("SUPER + Q", "")].file == str(lua) and by[("SUPER + Q", "")].line == 7


@needs_lua
def test_names_come_out_like_a_conf_bind(tmp_path):
    lua = write_config(tmp_path)
    recs = luaread.read(lua, roots=[lua.parent])
    live = live_of(recs)
    binds = luaread.annotate(live, recs, [lua.parent])
    assert all(binds)
    named = {names.combo_label(b.modmask, b.key): names.bind_name(b) for b in binds}
    assert named["Super + Q"].text == "Терминал"  # dictionary, by the command
    assert named["Super + Shift + R"].text == "Запасной плоский список"  # its comment
    assert named["Super + T"].text == "Таймер"  # the block above; "--daemon" is no comment
    assert named["Яркость +"].text == "Светлее"  # "Fn+F3" names the key: not used
    assert [named[f"Super + {i}"].text for i in (1, 2, 3)] == ["Стол 1", "Стол 2", "Стол 3"]
    assert named["Super + ←"].text == "Фокус влево"
    assert named["Super + N"].text == "new"
    b = {names.combo_label(x.modmask, x.key): x for x in binds}
    assert (b["Super + Левая кнопка мыши"].dispatcher, b["Super + Левая кнопка мыши"].arg) == \
        ("mouse", "movewindow")
    assert b["Яркость +"].keyword == "bindle"
    assert names.command_text(b["Alt + Tab"]) == names.strings.BN_LUA_FUNCTION


@needs_lua
def test_sandbox_runs_no_commands_and_writes_nothing(tmp_path):
    victim = tmp_path / "victim"
    outside = tmp_path / "outside.lua"
    outside.write_text('return "outside"\n')
    text = f"""
pcall(function() os.execute("touch {victim}-exec") end)
pcall(function() io.popen("touch {victim}-popen") end)
local f = io.open("{victim}-write", "w")
local g = io.open("{victim}-append", "a")
local _, out1 = pcall(dofile, "{outside}")
local _, out2 = pcall(dofile, DIR .. "/../outside.lua")
local loader = loadfile("{outside}")
local escaped = load("return io")()
local probe = table.concat({{
    tostring(os.execute == nil), tostring(io.popen == nil), tostring(require == nil),
    tostring(debug == nil), tostring(package == nil), tostring(f == nil), tostring(g == nil),
    tostring(escaped.popen == nil), tostring(io.open("/etc/hostname") == nil),
    tostring(string.dump == nil), tostring(out1 ~= "outside" and out2 ~= "outside"),
    tostring(loader == nil),
}}, ",")
hl.bind("SUPER + P", hl.dsp.exec_cmd(probe))
"""
    lua = write_config(tmp_path, text)
    recs = luaread.read(lua, roots=[lua.parent])
    assert recs is not None
    assert [r.arg for r in recs] == [",".join(["true"] * 12)]
    assert list(tmp_path.glob("victim*")) == []


@needs_lua
def test_bytecode_is_refused(tmp_path):
    lua = write_config(tmp_path, 'local ok = pcall(load, "\\27Lua")\n'
                       'local f = load("\\27LuaT")\n'
                       'hl.bind("SUPER + B", hl.dsp.exec_cmd(tostring(f == nil)))\n')
    assert [r.arg for r in luaread.read(lua, roots=[lua.parent])] == ["true"]


@needs_lua
def test_a_config_that_hangs_is_given_up(tmp_path):
    lua = write_config(tmp_path, "while true do end\n")
    start = time.monotonic()
    assert luaread.read(lua, roots=[lua.parent], timeout=0.5) is None
    assert time.monotonic() - start < 5


@needs_lua
def test_a_config_that_stops_early_gives_nothing(tmp_path):
    """The rest might unbind or replace what came before: no stale commands."""
    lua = write_config(tmp_path, 'hl.bind("SUPER + Q", hl.dsp.exec_cmd("old"))\nerror("boom")\n'
                       'hl.unbind("SUPER + Q")\nhl.bind("SUPER + Q", hl.dsp.exec_cmd("new"))\n')
    assert luaread.read(lua, roots=[lua.parent]) is None


def test_without_an_interpreter_nothing_is_read(tmp_path, monkeypatch):
    lua = write_config(tmp_path)
    monkeypatch.setattr(luaread, "INTERPRETERS", ("no-such-lua-here",))
    assert luaread.read(lua) is None
    assert luaread.annotate([{"modmask": 64, "key": "Q"}], None) == [None]


def test_only_the_same_combo_submap_and_kind_pair():
    recs = [Record("SUPER + Q", "exec_cmd", "kitty", "", "", "", 0),
            Record("SUPER + C", "window.close", "", "", "", "", 0),
            Record("SUPER + Escape", "submap", "reset", "", "x", "", 0)]
    live = [
        {"modmask": 64, "key": "q", "submap": "", "dispatcher": "HL.Dispatcher(exec_cmd)"},
        {"modmask": 64, "key": "C", "submap": "", "dispatcher": "HL.Dispatcher(exec_cmd)"},
        {"modmask": 64, "key": "Escape", "submap": "", "dispatcher": "HL.Dispatcher(submap)"},
        {"modmask": 64, "key": "Escape", "submap": "x", "dispatcher": "HL.Dispatcher(submap)"},
        {"modmask": 64, "key": "Q", "submap": "", "dispatcher": "HL.Dispatcher(exec_cmd)"},
        {"modmask": 64, "key": "W", "submap": "", "dispatcher": "exec", "arg": "x"},
    ]
    got = luaread.annotate(live, recs)
    assert got[0] is not None and got[0].arg == "kitty"
    assert got[1] is None  # close vs exec_cmd: not this one
    assert got[2] is None and got[3] is not None  # submap must match
    assert got[4] is None  # each record pairs once
    assert got[5] is None  # a .conf-shaped item is left alone


@pytest.mark.parametrize("kind,arg,mouse,want", [
    ("exec_cmd", "kitty", False, ("exec", "kitty")),
    ("focus", "workspace=3", False, ("workspace", "3")),
    ("focus", "workspace=+1", False, ("workspace", "+1")),
    ("window.move", "workspace=2", False, ("movetoworkspace", "2")),
    ("focus", "direction=left", False, ("movefocus", "l")),
    ("window.move", "direction=down", False, ("movewindow", "d")),
    ("window.resize", "relative=true\x1fx=-80\x1fy=0", False, ("resizeactive", "-80 0")),
    ("window.resize", "", True, ("mouse", "resizewindow")),
    ("window.drag", "", True, ("mouse", "movewindow")),
    ("window.close", "", False, ("killactive", "")),
    ("window.fullscreen", "mode=maximized", False, ("fullscreen", "")),
    ("layout", "togglesplit", False, ("layoutmsg", "togglesplit")),
    ("submap", "reset", False, ("submap", "reset")),
    ("group.next", "", False, ("changegroupactive", "f")),
    ("window.something_new", "a=1", False, ("something_new", "a=1")),
])
def test_lua_actions_in_conf_terms(kind, arg, mouse, want):
    assert luaread.conf_action(Record("SUPER + Q", kind, arg, "", "", "", 0,
                                      mouse=mouse)) == want


@pytest.mark.parametrize("line,want", [
    ('hl.bind("A", hl.dsp.exec_cmd("x --daemon")) -- запуск', "запуск"),
    ('hl.bind("A", hl.dsp.exec_cmd("x --daemon"))', ""),
    ("hl.bind('A', hl.dsp.exec_cmd('it\\'s -- not'))  --  да", "да"),
    ('hl.bind("A", hl.dsp.exec_cmd([[x -- y]]))', ""),
])
def test_trailing_comment(line, want):
    assert luaread.trailing_comment(line) == want


def test_driver_output_escapes_round_trip():
    out = "bind\t1\tSUPER + Q\texec_cmd\ta\\tb\\nc\\\\d\t\t\t\t0\t0\t0\t0\nend\tok\n"
    assert [r.arg for r in luaread.parse_output(out)] == ["a\tb\nc\\d"]
    assert luaread.parse_output("bind\tSUPER + Q\n") is None  # no end line: cut short



@needs_lua
def test_the_api_forms_a_real_config_uses(tmp_path):
    lua = write_config(tmp_path, """
for _, m in ipairs(hl.get_monitors()) do error("no monitors here") end
local kb = hl.bind("SUPER + A", hl.dsp.exec_cmd("gone"))
kb:set_enabled(false)
kb:remove()
hl.define_submap("resize", "reset", function()
    hl.bind("left", hl.dsp.window.resize({ x = -10, y = 0 }))
    hl.bind("SUPER + S", hl.dsp.exec_cmd(hl.get_current_submap()))
end)
""")
    recs = luaread.read(lua, roots=[lua.parent])
    assert [(r.keys, r.submap, r.arg) for r in recs] == [
        ("left", "resize", "x=-10\x1fy=0"), ("SUPER + S", "resize", "resize")]


@needs_lua
def test_a_helper_comment_does_not_name_every_bind(tmp_path):
    lua = write_config(tmp_path, """
local function b(k, c) hl.bind(k, hl.dsp.exec_cmd(c)) end -- wrapper helper
b("SUPER + A", "alpha")
b("SUPER + B", "beta")
""")
    recs = luaread.read(lua, roots=[lua.parent])
    binds = luaread.annotate(live_of(recs), recs, [lua.parent])
    assert [names.bind_name(x).text for x in binds] == ["alpha", "beta"]


@needs_lua
def test_odd_characters_stay_data(tmp_path):
    lua = write_config(tmp_path, """
hl.bind("SUPER + A", hl.dsp.exec_cmd("a\\u{2028}b\\u{85}c\\x1cunbind"))
hl.bind("SUPER + B", hl.dsp.focus({ workspace = "1\\31direction=left" }))
""")
    recs = luaread.read(lua, roots=[lua.parent])
    assert recs[0].arg == "a\u2028b\x85c\x1cunbind"
    assert luaread.pairs_of(recs[1].arg) == {"workspace": "1 direction=left"}


@needs_lua
def test_a_chunk_name_cannot_point_the_reader_elsewhere(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x -- TOP SECRET\n")
    lua = write_config(tmp_path, f"""
load("hl.bind('SUPER + Z', hl.dsp.exec_cmd('z'))", "@/dev/zero")()
load("hl.bind('SUPER + Y', hl.dsp.exec_cmd('y'))", "@{secret}")()
""")
    recs = luaread.read(lua, roots=[lua.parent])
    assert [(r.file, r.line) for r in recs] == [("", 0), ("", 0)]


def test_annotate_reads_only_regular_files_below_the_roots(tmp_path):
    inside = tmp_path / "hypr"
    inside.mkdir()
    fifo = inside / "fifo.lua"
    os.mkfifo(fifo)
    (tmp_path / "secret.lua").write_text("hl.bind('SUPER + Q', x) -- TOP SECRET\n")
    (inside / "link.lua").symlink_to(tmp_path / "secret.lua")
    live = [{"modmask": 64, "key": "Q", "submap": "", "dispatcher": "HL.Dispatcher(exec_cmd)"}]
    for file in (str(fifo), str(tmp_path / "secret.lua"), str(inside / "link.lua"),
                 "/dev/zero"):
        rec = Record("SUPER + Q", "exec_cmd", "kitty", "", "", file, 1)
        b = luaread.annotate(live, [rec], [inside])[0]  # a FIFO would hang here
        assert b is not None and b.comment == "" and b.above == "", file


def test_root_slash_is_refused(tmp_path):
    assert luaread.safe_roots([Path("/"), Path(""), tmp_path]) == [tmp_path.resolve()]


@needs_lua
def test_lua_init_is_ignored(tmp_path, monkeypatch):
    victim = tmp_path / "victim"
    monkeypatch.setattr(luaread, "ENV_KEYS", (*luaread.ENV_KEYS, "LUA_INIT", "LUA_INIT_5_4"))
    monkeypatch.setenv("LUA_INIT", f'os.execute("touch {victim}-1")')
    monkeypatch.setenv("LUA_INIT_5_4", f'os.execute("touch {victim}-2")')
    lua = write_config(tmp_path, 'hl.bind("SUPER + A", hl.dsp.exec_cmd("a"))\n')
    assert [r.arg for r in luaread.read(lua, roots=[lua.parent])] == ["a"]
    assert list(tmp_path.glob("victim*")) == []


@needs_lua
def test_too_much_output_gives_nothing(tmp_path):
    lua = write_config(tmp_path, 'local s = string.rep("x", 100000)\n'
                       'for i = 1, 30 do hl.bind("SUPER + A", hl.dsp.exec_cmd(s)) end\n')
    assert luaread.read(lua, roots=[lua.parent]) is None


@needs_lua
@pytest.mark.skipif(shutil.which("prlimit") is None, reason="no prlimit")
def test_memory_is_capped(tmp_path):
    lua = write_config(tmp_path, 'local t = {}\n'
                       'for i = 1, 64 do t[i] = string.rep("x", 2^24) .. i end\n'
                       'hl.bind("SUPER + A", hl.dsp.exec_cmd("a"))\n')
    assert luaread.read(lua, roots=[lua.parent], timeout=10) is None  # 1 GiB > the cap


@needs_lua
def test_a_linked_config_directory_still_reads(tmp_path):
    """dotfiles managers link ~/.config/hypr; the config names files by the link."""
    real = tmp_path / "dotfiles" / "hypr"
    real.mkdir(parents=True)
    link = tmp_path / "hypr"
    link.symlink_to(real)
    (real / "hyprland.lua").write_text(f'dofile("{link}/more.lua")\n')
    (real / "more.lua").write_text('hl.bind("SUPER + Q", hl.dsp.exec_cmd("kitty"))\n')
    recs = luaread.read(link / "hyprland.lua", roots=[link])
    assert [r.arg for r in recs] == ["kitty"]
