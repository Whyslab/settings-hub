"""Dispatches for either config format, run under a stub hyprctl."""

import os
import subprocess

import pytest

from settings_hub import hypr

# Replies like the real thing: a .conf Hyprland rejects `hl.dsp.*`, a Lua one
# rejects everything else.
HYPRCTL = """#!/bin/sh
printf '%s\\n' "$*" >>"$T/calls.log"
if [ -e "$T/lua" ]; then
    case "$2" in hl.dsp.*) echo ok ;; *) echo "error: syntax error" ;; esac
else
    case "$2" in hl.dsp.*) echo "Invalid dispatcher" ;; *) echo ok ;; esac
fi
"""
MATCH = r"class:^(settings-hub|io\.github\.whyslab\.SettingsHub)$"


def run(tmp_path, command, lua):
    stub = tmp_path / "hyprctl"
    stub.write_text(HYPRCTL)
    stub.chmod(0o755)
    if lua:
        (tmp_path / "lua").touch()
    env = dict(os.environ, T=str(tmp_path), PATH=f"{tmp_path}:/usr/bin:/bin")
    subprocess.run(command, env=env, check=True, timeout=10)
    return (tmp_path / "calls.log").read_text().splitlines()


def test_lua_str_escapes_for_lua():
    assert hypr.lua_str(MATCH) == r'"class:^(settings-hub|io\\.github\\.whyslab\\.SettingsHub)$"'
    assert hypr.lua_str('a "b"') == r'"a \"b\""'


@pytest.mark.parametrize("lua", [False, True])
def test_dual_dispatch_uses_the_form_the_config_takes(tmp_path, lua):
    lua_form = f"hl.dsp.focus({{ window = {hypr.lua_str(MATCH)} }})"
    calls = run(tmp_path, hypr.dual_dispatch(lua_form, "focuswindow", MATCH), lua)
    if lua:
        assert calls == [f"dispatch {lua_form}"]
    else:
        assert calls == [f"dispatch {lua_form}", f"dispatch focuswindow {MATCH}"]


def test_arguments_are_not_shell_code(tmp_path):
    calls = run(tmp_path, hypr.dual_dispatch("hl.dsp.x()", "exec", "$(touch pwned); `id`"), False)
    assert calls[-1] == "dispatch exec $(touch pwned); `id`"
    assert not (tmp_path / "pwned").exists()


def test_under_lua_a_failed_lua_form_is_not_retried_in_the_plain_form(tmp_path):
    # Lua runs `hyprctl dispatch <text>` as hl.dispatch(<text>): plain text is code.
    command = hypr.dual_dispatch("hl.dsp.nonsense()", "exec", "x")
    stub = tmp_path / "hyprctl"
    stub.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >>\"$T/calls.log\"\n"
                    "echo 'error: attempt to call nil'\n")
    stub.chmod(0o755)
    env = dict(os.environ, T=str(tmp_path), PATH=f"{tmp_path}:/usr/bin:/bin")
    subprocess.run(command, env=env, check=True, timeout=10)
    assert (tmp_path / "calls.log").read_text().splitlines() == ["dispatch hl.dsp.nonsense()"]


@pytest.mark.parametrize(("text", "want"), [
    ('safe_dofile(home .. "/.config/hypr/settings-hub.lua")\n', True),
    ('local f = home .. "/.config/hypr/settings-hub.lua"\nsafe_dofile(f)\n', True),
    ('-- dofile(home .. "/.config/hypr/settings-hub.lua")\n', False),
    ('x = 1 -- see settings-hub.lua\n', False),
    ('--[[\ndofile("settings-hub.lua")\n]]\nx = 1\n', False),
    ('--[==[ settings-hub.lua ]==] x = 1\n', False),
])
def test_loads_settings_hub_ignores_comments(text, want):
    assert hypr.loads_settings_hub(text) is want



def test_window_float_command_is_idempotent():
    """0.57.1 reads float's unknown action words as "toggle": "set" un-floated
    the window the rule had floated (09.11.2026). Only "enable" is a no-op."""
    pytest.importorskip("gi")
    from settings_hub import window

    lua = window.FLOAT_COMMAND[4]
    assert 'action = "enable"' in lua
    assert '"set"' not in lua and '"toggle"' not in lua


def _client(**over):
    c = {"class": "io.github.whyslab.SettingsHub", "initialTitle": "Настройки",
         "hidden": False, "floating": True, "fullscreen": 0, "size": [920, 640]}
    c.update(over)
    return c


def test_window_rule_carries_the_size_and_replaces_the_installed_one():
    """Without a size the window mapped at 634x679 and was resized mid-animation
    (15.11.2026); the same name replaces the rule of settings-hub.lua."""
    pytest.importorskip("gi")
    from settings_hub import window
    from settings_hub.binds import writer

    code = window.rule_code(1000, 700, False)
    assert 'size = "1000 700"' in code
    assert "float = true" in code and "center = true" in code
    match = writer.main_rule_match()
    assert f"match = {match}," in code
    assert 'initial_title = "^(Настройки)$"' in match  # dialogs keep their own size
    installed = writer.lua_text("/d", "/b", "/c")
    rule = installed.split("hl.window_rule({", 2)[1]
    assert '"settings-hub",' in rule and f"match  = {match}," in rule


def test_window_is_fixed_after_the_map_only_when_it_is_off():
    pytest.importorskip("gi")
    import json

    from settings_hub import window

    def fix(*clients, size=(920, 640)):
        return window.needs_fix(json.dumps(list(clients)), *size, False)

    assert fix(_client()) is False
    assert fix(_client(size=[921, 639])) is False  # rounding on a scaled monitor
    assert fix(_client(), _client(initialTitle="Удалить?", size=[400, 200])) is False
    assert fix(_client(floating=False)) is True
    assert fix(_client(fullscreen=1)) is True
    assert fix(_client(size=[634, 679])) is True
    assert fix(_client(), size=(1000, 700)) is True
    assert fix() is False  # hidden again already: nothing to fix
    assert fix(_client(hidden=True)) is False
    assert fix(_client(), _client()) is True  # two main windows: unclear, fix
    assert window.needs_fix("", 920, 640, False) is True  # hyprctl failed
    assert fix({"class": "kitty"}) is False  # only other windows: ours is hidden


def test_window_rule_sends_maximize_both_ways():
    """0.57 appends a same-name rule's effects, the last value winning: a rule
    without `maximize` would leave an earlier `maximize = true` in force."""
    pytest.importorskip("gi")
    from settings_hub import window

    assert "maximize = true" in window.rule_code(920, 640, True)
    assert "maximize = false" in window.rule_code(920, 640, False)
    assert 'size = "920 640"' in window.rule_code(920, 640, True)  # for un-maximizing


def test_maximized_window_is_fixed_only_when_not_maximized():
    pytest.importorskip("gi")
    import json

    from settings_hub import window

    def fix(*clients):
        return window.needs_fix(json.dumps(list(clients)), 920, 640, True)

    assert fix(_client(fullscreen=1, size=[1260, 650])) is False  # its size is Hyprland's
    assert fix(_client(fullscreen=1, floating=False)) is True  # tiled: un-maximize gives a tile
    assert fix(_client()) is True  # floating at the General page's size
    assert fix(_client(fullscreen=2)) is True  # real full screen hides the bar
    assert fix() is False
    assert window.needs_fix("", 920, 640, True) is True
    assert window.MAXIMIZE_COMMAND[2].count("internal = 1, client = 1") == 1
