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
