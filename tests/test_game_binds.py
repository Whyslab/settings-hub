"""Game binds: the list, the generated Lua (run by a real Lua with a stub `hl`),
the backend's files and reload, and the controller's History items."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from settings_hub import history as hist
from settings_hub.backends import game_binds as gb
from settings_hub.binds import writer
from settings_hub.controllers.game_binds import Controller
from settings_hub.workers import Workers

LUA = shutil.which("lua") or shutil.which("lua5.4") or shutil.which("luajit")
needs_lua = pytest.mark.skipif(LUA is None, reason="no Lua interpreter")

# ---- the list ----------------------------------------------------------------


def test_missing_state_gives_defaults_off():
    state = gb.normalize(None)
    assert state == {"enabled": False, "patterns": ["dota2", "steam_app_*"],
                     "combos": ["SUPER + V", "SUPER + D"]}
    state["patterns"].append("x")  # a copy, not the module's DEFAULT
    assert gb.DEFAULT["patterns"] == ["dota2", "steam_app_*"]


def test_normalize_drops_junk_and_duplicates():
    state = gb.normalize({
        "enabled": "yes",  # only True counts
        "patterns": ["dota2", "DOTA2", "  ", 5, "a\nb", "x" * 101, " cs2 "],
        "combos": ["SUPER + V", "super+v", "SUPER", 'SUPER + "', "SHIFT + SUPER + K", 7],
    })
    assert state == {"enabled": False, "patterns": ["dota2", "cs2"],
                     "combos": ["SUPER + V", "SUPER + SHIFT + K"]}


def test_every_modifier_order_is_unbound():
    assert gb.spellings("SUPER + V") == ["SUPER + V"]
    assert sorted(gb.spellings("SUPER + SHIFT + X")) == ["SHIFT + SUPER + X", "SUPER + SHIFT + X"]
    assert len(gb.spellings("SUPER + CTRL + ALT + SHIFT + X")) == 24
    text = gb.build_lua({**ON, "combos": ["SUPER + SHIFT + X"]})
    assert '"SHIFT + SUPER + X"' in text


@pytest.mark.parametrize("text, expected", [
    ("dota2", "dota2"), ("steam_app_**", "steam_app_*"), ("Игра", None),
    ("*a*b*c*d", "*a*b*c*d"), ("*a*b*c*d*", None), ("a?b?c?d?e", "a?b?c?d?e"), ("a?b?c?d?e?", None),
])
def test_pattern_rules(text, expected):
    assert gb.clean_pattern(text) == expected


@pytest.mark.parametrize("mask, key, text", [
    (64, "V", "SUPER + V"),
    (65, "N", "SUPER + SHIFT + N"),
    (64 | 4 | 8, "Escape", "SUPER + CTRL + ALT + Escape"),
    (8, "Tab", "ALT + Tab"),
    (0, "F12", "F12"),
])
def test_combo_spelling_round_trip(mask, key, text):
    assert gb.combo_of(mask, key) == text
    assert gb.parse_combo(text) == (mask, key)
    assert gb.clean_combo(text) == text


# ---- patterns: the Lua pattern and the Python test agree ------------------------

CASES = [
    ("dota2", "dota2", True), ("dota2", "Dota2", True), ("dota2", "dota22", False),
    ("steam_app_*", "steam_app_570", True), ("steam_app_*", "steam", False),
    ("*minecraft*", "com.mojang.minecraft.Launcher", True),
    ("cs?", "cs2", True), ("cs?", "cs22", False),
    ("a.b", "a.b", True), ("a.b", "axb", False),  # "." is literal
    ("x-y", "x-y", True), ("(x)", "(x)", True), ("50%", "50%", True),
    ("[ab]", "a", False), ("[ab]", "[ab]", True), ("^go$", "^go$", True),
]


@pytest.mark.parametrize("pattern, cls, expected", CASES)
def test_python_glob(pattern, cls, expected):
    assert gb.matches(pattern, cls) is expected


@needs_lua
def test_lua_pattern_matches_like_python(tmp_path):
    script = tmp_path / "m.lua"
    lines = [f"print(string.match(string.lower({gb.lua_str(c)}), "
             f"{gb.lua_str(gb.lua_pattern(p))}) ~= nil)" for p, c, _ in CASES]
    script.write_text("\n".join(lines) + "\n")
    out = subprocess.run([LUA, str(script)], capture_output=True, text=True, check=True).stdout
    assert out.split() == [str(e).lower() for _, _, e in CASES]


# ---- the generated Lua, run with a stub hl ---------------------------------------

DRIVER = r"""
local calls, handlers, active = {}, {}, nil
local function win(cls)
    if cls == "" then return nil end
    return { class = cls, initial_class = cls }
end
hl = {
    get_active_window = function() return active end,
    unbind = function(c) calls[#calls + 1] = "unbind " .. c end,
    exec_cmd = function(c) calls[#calls + 1] = "exec " .. c end,
    on = function(ev, cb) handlers[ev] = cb end,
}
local function flush(tag) print(tag .. "|" .. table.concat(calls, ";")); calls = {} end
active = win(arg[2])
dofile(arg[1])
flush("load")
for i = 3, #arg do
    local kind, cls = arg[i]:match("^(%w+):(.*)$")
    active = win(cls)
    if kind == "focus" then
        if handlers["window.active"] then handlers["window.active"](active) end
    else
        if handlers["window.class"] then handlers["window.class"](active) end
    end
    flush(arg[i])
end
"""

ON = {"enabled": True, "patterns": ["dota2", "steam_app_*"], "combos": ["SUPER + V", "SUPER + D"]}
OFF_BOTH = "unbind SUPER + V;unbind SUPER + D"
RELOAD = "exec hyprctl reload config-only"


def run_lua(tmp_path: Path, state: dict, active: str, *steps: str) -> list[str]:
    games = tmp_path / "games.lua"
    games.write_text(gb.build_lua(state))
    driver = tmp_path / "driver.lua"
    driver.write_text(DRIVER)
    done = subprocess.run([LUA, str(driver), str(games), active, *steps],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


@needs_lua
def test_lua_off_does_nothing(tmp_path):
    assert run_lua(tmp_path, {**ON, "enabled": False}, "dota2", "focus:dota2") == [
        "load|", "focus:dota2|"]


@needs_lua
def test_lua_empty_lists_do_nothing(tmp_path):
    assert run_lua(tmp_path, {**ON, "combos": []}, "dota2", "focus:dota2") == [
        "load|", "focus:dota2|"]


@needs_lua
def test_lua_focus_in_and_out(tmp_path):
    out = run_lua(tmp_path, ON, "kitty",
                  "focus:dota2",           # into the game: off
                  "focus:steam_app_570",   # game to game: nothing more
                  "focus:firefox",         # out: one reload
                  "focus:kitty",           # still out: nothing
                  "focus:")                # empty workspace: nothing
    assert out == ["load|", f"focus:dota2|{OFF_BOTH}", "focus:steam_app_570|",
                   f"focus:firefox|{RELOAD}", "focus:kitty|", "focus:|"]


@needs_lua
def test_lua_game_focused_at_load(tmp_path):
    """Login or a reload while the game is focused: off at once; leaving reloads."""
    out = run_lua(tmp_path, ON, "dota2", "focus:dota2", "focus:")
    assert out == [f"load|{OFF_BOTH}", "focus:dota2|", f"focus:|{RELOAD}"]


@needs_lua
def test_lua_class_set_late(tmp_path):
    """A window that gets its game class after it got focus."""
    out = run_lua(tmp_path, ON, "", "focus:wine", "class:steam_app_1")
    assert out == ["load|", "focus:wine|", f"class:steam_app_1|{OFF_BOTH}"]


@needs_lua
def test_lua_never_counts_our_window(tmp_path):
    out = run_lua(tmp_path, {**ON, "patterns": ["*"]}, "", f"focus:{gb.OWN_CLASS}", "focus:x")
    assert out == ["load|", f"focus:{gb.OWN_CLASS}|", f"focus:x|{OFF_BOTH}"]


@pytest.mark.skipif(shutil.which("luac") is None, reason="no luac")
def test_generated_lua_parses_with_odd_text(tmp_path):
    state = {"enabled": True, "patterns": ['a"b', "c\\d", "ё*", "]]--"],
             "combos": ["SUPER + bracketright", "CTRL + ALT + Delete"]}
    path = tmp_path / "g.lua"
    path.write_text(gb.build_lua(state))
    subprocess.run(["luac", "-p", str(path)], check=True)


def test_settings_hub_lua_loads_games_file_last():
    text = writer.lua_text("/d", "/b", "/c")
    assert text.rstrip().endswith('pcall(dofile, "/c/hypr/settings-hub-games.lua")')
    assert text.index(writer.LUA_END) < text.index("settings-hub-games.lua")


# ---- the backend ----------------------------------------------------------------


class FakeHyprctl:
    def __init__(self, replies: dict[str, tuple[int, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        return self.replies.get(" ".join(args), (0, "ok"))


def backend(tmp_path: Path, hyprctl=None, workers=None) -> gb.Backend:
    return gb.Backend(workers or Workers(lambda fn: fn()), hyprctl or FakeHyprctl(),
                      state_file=tmp_path / "state" / "games.json",
                      lua_file=tmp_path / "hypr" / gb.LUA_FILE)


def test_save_writes_both_files_without_hyprland(tmp_path):
    fake = FakeHyprctl()
    be = backend(tmp_path, fake)
    assert be.save(ON) == (True, "")
    assert be.load() == ON
    assert "local combos = { \"SUPER + V\", \"SUPER + D\" }" in be.lua_file.read_text()
    assert fake.calls == []  # no session -> no reload


def test_save_reloads_and_reports_a_failed_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    fake = FakeHyprctl()
    assert backend(tmp_path, fake).save(ON) == (True, "")
    assert fake.calls == [["reload", "config-only"]]
    bad = FakeHyprctl({"reload config-only": (1, "error: no")})
    assert backend(tmp_path, bad).save(ON) == (True, "error: no")  # saved; a warning


def test_broken_state_file_reads_as_defaults(tmp_path):
    be = backend(tmp_path)
    be.state_file.parent.mkdir(parents=True)
    be.state_file.write_text("{not json")
    assert be.load() == gb.normalize(None)


def test_probe_reads_actions_classes_and_install(tmp_path):
    binds = [
        {"modmask": 64, "key": "V", "submap": "", "has_description": True,
         "description": "Окно плавает", "dispatcher": "function: 0x1", "arg": "19"},
        {"modmask": 64, "key": "Q", "submap": "", "has_description": False,
         "description": "", "dispatcher": "HL.Dispatcher(exec_cmd)", "arg": "9"},
        {"modmask": 64, "key": "D", "submap": "resize", "has_description": True,
         "description": "в подкарте", "dispatcher": "x", "arg": ""},
    ]
    clients = [{"class": "kitty"}, {"class": "dota2"}, {"class": "Kitty"},
               {"class": gb.OWN_CLASS}, {"class": ""}]
    fake = FakeHyprctl({"binds -j": (0, json.dumps(binds)),
                        "clients -j": (0, json.dumps(clients))})
    be = backend(tmp_path, fake)
    probe = be.probe(["SUPER + V", "SUPER + Q", "SUPER + D"])
    assert probe.actions == {"SUPER + V": "Окно плавает", "SUPER + Q": ""}  # D only in a submap
    assert probe.classes == ["dota2", "kitty"]
    assert probe.loaded is False
    (tmp_path / "hypr").mkdir(exist_ok=True)
    (tmp_path / "hypr" / "settings-hub.lua").write_text(writer.lua_text("/d", "/b", "/c"))
    assert be.probe([]).loaded is False  # no hyprland.lua: a .conf Hyprland never reads it
    (tmp_path / "hypr" / "hyprland.lua").write_text('-- dofile("settings-hub.lua")\n')
    assert be.probe([]).loaded is False  # only in a comment
    (tmp_path / "hypr" / "hyprland.lua").write_text('dofile(home .. "/settings-hub.lua")\n')
    assert be.probe([]).loaded is True


def test_probe_survives_no_hyprland(tmp_path):
    fake = FakeHyprctl({"binds -j": (127, ""), "clients -j": (0, "garbage")})
    probe = backend(tmp_path, fake).probe(["SUPER + V"])
    assert probe.actions == {} and probe.classes == []


# ---- the controller and History ---------------------------------------------------


class View:
    def __init__(self) -> None:
        self.states: list[dict] = []
        self.texts: list[str] = []

    def show_state(self, state):
        self.states.append(state)

    def show_probe(self, probe):
        pass

    def status(self, text):
        self.texts.append(text)


def make(tmp_path, hyprctl=None):
    workers = Workers(lambda fn: fn())
    be = backend(tmp_path, hyprctl, workers)
    log = hist.History(tmp_path / "history.jsonl")
    gb.register(log, be)
    view = View()
    return Controller(be, log, view), be, log, view, workers


def test_changes_are_saved_and_undoable(tmp_path):
    ctl, be, log, view, workers = make(tmp_path)
    ctl.set_enabled(True)
    workers.wait_idle(5)
    assert ctl.add_pattern(" cs2 ")
    workers.wait_idle(5)
    assert ctl.add_combo(65, "N")
    workers.wait_idle(5)
    ctl.remove_combo("SUPER + D")
    workers.wait_idle(5)
    assert be.load() == {"enabled": True, "patterns": ["dota2", "steam_app_*", "cs2"],
                         "combos": ["SUPER + V", "SUPER + SHIFT + N"]}
    assert len(log.groups()) == 4
    log.execute(log.plan_undo_last())
    assert be.load()["combos"] == ["SUPER + V", "SUPER + D", "SUPER + SHIFT + N"]
    assert "local combos" in be.lua_file.read_text()


def test_duplicates_and_bad_input_change_nothing(tmp_path):
    ctl, be, log, view, workers = make(tmp_path)
    assert not ctl.add_pattern("DOTA2")
    assert not ctl.add_pattern("   ")
    assert not ctl.add_combo(64, "v")
    assert not ctl.add_combo(64, 'x"')
    workers.wait_idle(5)
    assert log.groups() == [] and not be.state_file.exists()
    assert len(view.texts) == 4


def test_failed_reload_is_a_warning_and_still_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    ctl, be, log, view, workers = make(tmp_path, FakeHyprctl({"reload config-only": (1, "boom")}))
    ctl.set_enabled(True)
    workers.wait_idle(5)
    # the files were written, only the reload failed: saved, undoable, a warning
    assert be.load()["enabled"] is True and view.states[-1] == be.load()
    assert len(log.groups()) == 1
    assert "boom" in view.texts[-1] and "Сохранено" in view.texts[-1]


def test_unwritable_files_bring_back_the_old_list(tmp_path):
    ctl, be, log, view, workers = make(tmp_path)
    be.state_file.parent.mkdir(parents=True)
    be.state_file.parent.chmod(0o500)
    try:
        ctl.set_enabled(True)
        workers.wait_idle(5)
    finally:
        be.state_file.parent.chmod(0o700)
    assert view.states[-1]["enabled"] is False and log.groups() == []
    assert view.texts[-1].startswith("Не удалось сохранить")


def test_quick_changes_each_get_their_history_group(tmp_path):
    ctl, be, log, view, workers = make(tmp_path)
    ctl.set_enabled(True)
    ctl.add_pattern("a1")
    ctl.add_pattern("b2")
    workers.wait_idle(5)
    assert len(log.groups()) == 3
    assert be.load()["patterns"][-2:] == ["a1", "b2"]


def test_sync_rewrites_an_old_body_only(tmp_path):
    be = backend(tmp_path)
    assert be.sync() is False and not be.lua_file.exists()  # no list yet: nothing
    be.save(ON)
    assert be.sync() is False
    be.lua_file.write_text("-- an older version\n")
    assert be.sync() is True
    assert be.lua_file.read_text() == gb.build_lua(ON)
