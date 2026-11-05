"""The desktop variables: what is sent to Hyprland and what is remembered."""

import json
import re
import shutil
import subprocess

import pytest

from settings_hub.controllers import variables as ctl
from settings_hub.variables import VARS, get
from settings_hub.variables import backend as hypr


class Hyprctl:
    """A hyprctl that answers like 0.57 under a Lua config (or like an old one)."""

    def __init__(self, lua=True, live=None, takes=None):
        self.lua = lua
        self.live = live or {}
        self.takes = takes or {}  # what a change makes the live value
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        verb = argv[1]
        if verb == "getoption":
            value = self.live.get(argv[2], 0)
            kind = ("bool" if isinstance(value, bool) else "float" if isinstance(value, float)
                    else "int" if isinstance(value, int) else "str")
            return 0, json.dumps({"option": argv[2], kind: value, "set": True}), ""
        if verb == "eval":
            if not self.lua:
                return 0, "unknown request", ""
            if "nosuch" in argv[2]:
                return 7, "error: unknown config key", ""
            self.live.update(self.takes)
            return 0, "ok", ""
        if verb == "keyword":
            if self.lua:
                return 0, "unknown request", ""
            return 0, "ok", ""
        if verb == "reload":
            return 0, "ok", ""
        return 0, "", ""


def backend(tmp_path, run):
    return hypr.Backend(None, runner=run, state=tmp_path / "vars.json",
                        lua=tmp_path / "vars.lua", env={}, cursor_dirs=())


def test_a_change_goes_through_eval_under_a_lua_config(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    b = backend(tmp_path, run)
    result = b.apply_now({"general:gaps_in": 9})
    assert result.ok and result.values == {"general:gaps_in": 9}
    code = next(c for c in run.calls if c[1] == "eval")
    assert "gaps_in = 9" in code[2]
    assert not [c for c in run.calls if c[1] == "keyword"]
    assert "gaps_in = 9" in (tmp_path / "vars.lua").read_text()


def test_a_conf_hyprland_falls_back_to_keyword(tmp_path):
    run = Hyprctl(lua=False, live={"general:gaps_in": 9})
    result = backend(tmp_path, run).apply_now({"general:gaps_in": 9})
    assert result.ok
    assert ["hyprctl", "keyword", "general:gaps_in", "9"] in run.calls


def test_only_ok_from_eval_counts(tmp_path):
    """Hyprland words this refusal in a way no list of prefixes would catch."""
    run = Hyprctl(lua=False, live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})

    def conf(argv):
        if argv[1] == "eval":
            run.calls.append(argv)
            return 0, "eval is only supported with the lua config manager", ""
        return run(argv)

    result = backend(tmp_path, conf).apply_now({"general:gaps_in": 9})
    assert any(c[1] == "keyword" for c in run.calls)
    assert result.ok


def test_a_broken_state_file_is_kept_aside_when_written(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    b = backend(tmp_path, run)
    (tmp_path / "vars.json").write_text("{broken")
    assert b.read_all() is not None
    assert (tmp_path / "vars.json").read_text() == "{broken"  # reading moves nothing
    assert b.remembers(["general:gaps_in"]) is True  # so reset rewrites the Lua file
    b.apply_now({"general:gaps_in": 9})
    kept = list(tmp_path.glob("vars.json.bad-*"))
    assert len(kept) == 1 and kept[0].read_text() == "{broken"


def test_reset_with_a_broken_state_file_unpins_everything(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    c = controller(tmp_path, run)
    c.backend.apply_now({"general:gaps_in": 9})
    (tmp_path / "vars.json").write_text("{broken")
    c.reset(["general:gaps_in"])
    assert "gaps_in" not in (tmp_path / "vars.lua").read_text()
    assert [p.read_text() for p in tmp_path.glob("vars.json.bad-*")] == ["{broken"]
    assert any(a[1] == "reload" for a in run.calls)


def test_reset_gives_the_session_the_configs_cursor_after_the_reload(tmp_path):
    run = Hyprctl()
    c = controller(tmp_path, run)
    c.backend.env = {"XCURSOR_THEME": "Login"}
    c.backend.apply_now({"cursor:theme": "Mine"})
    c.reset(["cursor:theme"])
    setcursor = [i for i, a in enumerate(run.calls) if a[1] == "setcursor"]
    reload = next(i for i, a in enumerate(run.calls) if a[1] == "reload")
    assert run.calls[setcursor[-1]][2] == "Login" and setcursor[-1] > reload
    c.backend.env = {"XCURSOR_THEME": "Mine"}  # after a re-login with Mine kept
    assert c.backend.read_one("cursor:theme") == "Login"


def test_a_failed_reload_keeps_what_was_remembered(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    c = controller(tmp_path, run)
    c.backend.apply_now({"general:gaps_in": 9})

    def broken(argv):
        return (1, "error: reload", "") if argv[1] == "reload" else run(argv)

    c.backend.run = broken
    c.reset(["general:gaps_in"])
    assert "gaps_in = 9" in (tmp_path / "vars.lua").read_text()
    assert "reload" in c.view.messages[-1]


def test_a_value_hyprland_did_not_take_is_said_out_loud(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4})  # says ok, stays 4
    c = controller(tmp_path, run)
    c.values["general:gaps_in"] = 4
    c.edit("general:gaps_in", 9)
    assert c.history.items == []
    assert c.view.shown["general:gaps_in"] == 4
    assert "4" in c.view.messages[-1] and "Применено" not in c.view.messages[-1]


def test_a_refused_value_is_reported_and_not_remembered(tmp_path):
    def run(argv):
        return (7, "error: nope", "") if argv[1] == "eval" else (0, "unknown request", "")

    b = backend(tmp_path, run)
    result = b.apply_now({"general:gaps_in": 9})
    assert not result.ok and "error: nope" in result.message
    assert not (tmp_path / "vars.lua").exists()
    assert not (tmp_path / "vars.json").exists()


def test_what_hyprland_really_uses_is_what_is_remembered(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 7})  # not the 9
    b = backend(tmp_path, run)
    result = b.apply_now({"general:gaps_in": 9})
    assert result.values == {"general:gaps_in": 7}
    assert json.loads((tmp_path / "vars.json").read_text()) == {"general:gaps_in": 7}


def test_coming_back_to_the_configs_value_forgets_it(tmp_path):
    """An undo must not pin the old value over later edits of hyprland.lua."""
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    b = backend(tmp_path, run)
    b.apply_now({"general:gaps_in": 9})
    assert "gaps_in = 9" in (tmp_path / "vars.lua").read_text()
    run.takes = {"general:gaps_in": 4}
    b.apply({"general:gaps_in": 4})  # how History undoes
    assert json.loads((tmp_path / "vars.json").read_text()) == {}
    assert "gaps_in" not in (tmp_path / "vars.lua").read_text()


def test_a_second_change_keeps_the_configs_value_as_the_base(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4}, takes={"general:gaps_in": 9})
    b = backend(tmp_path, run)
    b.apply_now({"general:gaps_in": 9})
    run.takes = {"general:gaps_in": 12}
    b.apply_now({"general:gaps_in": 12})
    assert json.loads((tmp_path / "vars-base.json").read_text()) == {"general:gaps_in": 4}
    assert json.loads((tmp_path / "vars.json").read_text()) == {"general:gaps_in": 12}


def test_every_lua_name_is_an_identifier():
    for var in VARS:
        for part in var.lua_path:
            assert re.fullmatch(r"[a-z_][a-z0-9_]*", part), var.option
    assert get("input:touchpad:tap-to-click").lua_path == ("input", "touchpad", "tap_to_click")


def all_values():
    return {v.option: ("Bibata-Modern-Classic" if v.option == "cursor:theme" else v.default)
            for v in VARS}


@pytest.mark.skipif(shutil.which("luac") is None, reason="needs luac")
def test_the_whole_file_is_valid_lua(tmp_path):
    path = tmp_path / "vars.lua"
    path.write_text(hypr.build_lua(all_values()))
    done = subprocess.run(["luac", "-p", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(shutil.which("Hyprland") is None, reason="needs Hyprland 0.57+")
def test_hyprland_knows_every_option_by_its_lua_name(tmp_path):
    version = subprocess.run(["Hyprland", "--version"], capture_output=True, text=True).stdout
    if not any(f"Hyprland 0.{n}" in version for n in range(57, 100)):
        pytest.skip("Hyprland before 0.57 has no Lua config")
    path = tmp_path / "vars.lua"
    path.write_text(hypr.build_lua(all_values()))
    done = subprocess.run(["Hyprland", "--verify-config", "-c", str(path)],
                          capture_output=True, text=True, timeout=60)
    assert "config ok" in done.stdout, done.stdout + done.stderr


def test_text_is_quoted_for_lua_not_for_json():
    assert hypr._lua('а"б') == '"а\\"б"'
    text = hypr.build_lua({"cursor:theme": "Курсор"})
    assert 'hl.env("XCURSOR_THEME", "Курсор")' in text


class SyncWorkers:
    def submit(self, _name, fn, on_done=None, key=None):
        result = fn()
        if on_done is not None:
            on_done(result, None)


class View:
    def __init__(self):
        self.shown, self.messages = {}, []

    def show_values(self, values):
        self.shown.update(values)

    def status(self, text):
        self.messages.append(text)


class History:
    def __init__(self):
        self.items = []

    def record(self, items):
        self.items.append(list(items))


def controller(tmp_path, run):
    b = backend(tmp_path, run)
    b.workers = SyncWorkers()
    return ctl.Controller(b, History(), View())


def test_an_unchanged_value_sends_nothing(tmp_path):
    """Enter on an untouched field must not reset the layout."""
    run = Hyprctl(live={"input:kb_layout": "us,ru"})
    c = controller(tmp_path, run)
    c.values["input:kb_layout"] = "us,ru"
    c.edit("input:kb_layout", "us,ru")
    assert run.calls == [] and c.history.items == []


def test_a_text_field_does_nothing_before_the_first_read(tmp_path):
    run = Hyprctl()
    c = controller(tmp_path, run)
    c.edit("input:kb_layout", "")
    assert run.calls == []


def test_an_empty_layout_is_refused(tmp_path):
    run = Hyprctl()
    c = controller(tmp_path, run)
    c.values["input:kb_layout"] = "us,ru"
    c.edit("input:kb_layout", "  ")
    assert run.calls == []
    assert c.view.shown["input:kb_layout"] == "us,ru"


def test_a_failed_change_puts_the_field_back(tmp_path):
    def run(argv):
        if argv[1] == "getoption":
            return 0, json.dumps({"option": argv[2], "int": 4, "set": True}), ""
        return 7, "error: nope", ""

    c = controller(tmp_path, run)
    c.values["general:gaps_in"] = 4
    c.edit("general:gaps_in", 9)
    assert c.view.shown["general:gaps_in"] == 4
    assert c.history.items == []
    assert "error: nope" in c.view.messages[-1]


def test_reset_with_nothing_remembered_does_not_reload(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4})
    c = controller(tmp_path, run)
    c.reset(["general:gaps_in"])
    assert not [call for call in run.calls if call[1] == "reload"]
    assert c.history.items == []


def test_reset_forgets_and_logs_only_what_changed(tmp_path):
    run = Hyprctl(live={"general:gaps_in": 4, "general:gaps_out": 6},
                  takes={"general:gaps_in": 9})
    c = controller(tmp_path, run)
    c.backend.apply_now({"general:gaps_in": 9})

    real = run.__call__

    def after_reload(argv):
        if argv[1] == "reload":
            run.live["general:gaps_in"] = 4
        return real(argv)

    c.backend.run = after_reload
    c.reset(["general:gaps_in", "general:gaps_out"])
    assert ["hyprctl", "reload", "config-only"] in run.calls
    assert json.loads((tmp_path / "vars.json").read_text()) == {}
    assert "gaps_in" not in (tmp_path / "vars.lua").read_text()
    assert [i[1] for i in c.history.items[0]] == ["general:gaps_in"]
