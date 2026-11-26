"""The home screen's lists: big tiles, pinned rows, command tiles. No GTK."""

import json
import re
import subprocess

import pytest
from conftest import ROOT

from settings_hub import home_items, registry, settings


def make(tmp_path):
    return settings.Settings(tmp_path / "settings.json")


def test_defaults_and_round_trip(tmp_path):
    s = make(tmp_path)
    assert s.get("home.tiles") == list(settings.HOME_TILES)
    assert s.get("home.pins") == [] and s.get("home.commands") == []
    s.set("home.tiles", ["sound", "themes"])
    s.set("home.pins", ["panel#clock"])
    s.set("home.commands", [{"name": " Файлы ", "cmd": "nautilus"}])
    again = make(tmp_path)
    assert again.get("home.tiles") == ["sound", "themes"]
    assert again.get("home.commands") == [{"name": "Файлы", "cmd": "nautilus"}]
    assert "Файлы" in s.path.read_text(encoding="utf-8")  # not \\u escapes


def test_get_returns_a_copy(tmp_path):
    s = make(tmp_path)
    tiles = s.get("home.tiles")
    tiles.clear()
    assert s.get("home.tiles") == list(settings.HOME_TILES)


@pytest.mark.parametrize(("key", "value"), [
    ("home.tiles", ["sound", "nope"]),
    ("home.tiles", "sound"),
    ("home.tiles", list(settings.HOME_TILES) + ["sound"]),  # more than there are
    ("home.pins", ["no-hash"]),
    ("home.pins", ["Panel#clock"]),
    ("home.pins", ["panel#clock x"]),
    ("home.pins", ["panel#a#b"]),
    ("home.pins", [f"panel#r{i}" for i in range(21)]),
    ("home.commands", [{"name": "x"}]),
    ("home.commands", [{"name": "", "cmd": "ls"}]),
    ("home.commands", [{"name": "x", "cmd": "ls\nrm -rf ~"}]),
    ("home.commands", [{"name": "x", "cmd": "a" * 301}]),
    ("home.commands", [{"name": "x" * 41, "cmd": "ls"}]),
    ("home.commands", ["ls"]),
    ("home.commands", [{"name": "x", "cmd": 5}]),
    ("home.commands", [{"name": "x\ud800", "cmd": "ls"}]),  # a lone surrogate
    ("home.commands", [{"name": "x", "cmd": "echo safe\u202e; rm -rf ~"}]),  # bidi override
    ("home.commands", [{"name": "x", "cmd": "ls\u200b"}]),  # zero width
    ("home.commands", [{"name": "x", "cmd": "ls\u2028rm"}]),  # line separator
    ("home.commands", [{"name": "x", "cmd": "ls\x85rm"}]),  # C1 next line
    ("home.commands", [{"name": "x", "cmd": "-x foo"}]),  # read as hyprctl's option
    ("home.pins", ["panel#clock\u202e"]),
])
def test_bad_values_are_refused(tmp_path, key, value):
    s = make(tmp_path)
    before = s.get(key)
    with pytest.raises(ValueError):
        s.set(key, value)
    assert s.get(key) == before


def test_a_name_may_hold_icons_and_emoji(tmp_path):
    s = make(tmp_path)
    name = "\uf489 Btop \U0001f468\u200d\U0001f4bb"  # Nerd Font glyph, ZWJ emoji
    s.set("home.commands", [{"name": name, "cmd": "kitty -e btop"}])
    assert s.get("home.commands")[0]["name"] == name
    with pytest.raises(ValueError):  # not in the command, which runs
        s.set("home.commands", [{"name": "x", "cmd": "echo \uf489\u200d"}])
    with pytest.raises(ValueError):  # bidi stays out of the name too
        s.set("home.commands", [{"name": "a\u202eb", "cmd": "ls"}])


def test_duplicates_are_dropped(tmp_path):
    s = make(tmp_path)
    s.set("home.tiles", ["sound", "sound", "power"])
    assert s.get("home.tiles") == ["sound", "power"]


def test_one_bad_item_in_the_file_costs_only_itself(tmp_path, caplog):
    secret = "curl -H 'Authorization:\tBearer abc123'"
    (tmp_path / "settings.json").write_text(json.dumps(
        {"home.commands": [{"name": "ok", "cmd": "ls"}, {"name": "bad", "cmd": secret},
                           {"name": "ok2", "cmd": "btop"}],
         "home.pins": ["panel#clock", "x", "general#appearance.own_font"],
         "home.tiles": ["sound", "gone", "power"]}))
    s = make(tmp_path)
    assert [c["name"] for c in s.get("home.commands")] == ["ok", "ok2"]
    assert s.get("home.pins") == ["panel#clock", "general#appearance.own_font"]
    assert s.get("home.tiles") == ["sound", "power"]
    assert "abc123" not in caplog.text  # the dropped value is not logged
    s.set("appearance.theme", "dark")  # the next save keeps the good items
    assert [c["name"] for c in make(tmp_path).get("home.commands")] == ["ok", "ok2"]


def test_a_long_list_in_the_file_is_cut_not_dropped(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps(
        {"home.pins": [f"panel#r{i}" for i in range(30)]}))
    assert len(make(tmp_path).get("home.pins")) == 20


def test_a_surrogate_in_the_file_does_not_break_saving(tmp_path):
    (tmp_path / "settings.json").write_text(
        '{"home.commands": [{"name": "x\\ud800", "cmd": "echo"}], "appearance.theme": "dark"}')
    s = make(tmp_path)
    assert s.get("home.commands") == []
    s.set("appearance.theme", "light")
    assert make(tmp_path).get("appearance.theme") == "light"


def test_a_broken_file_keeps_the_defaults(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps(
        {"home.tiles": ["nope"], "home.pins": "x", "home.commands": [{"cmd": "ls"}],
         "appearance.theme": "dark"}))
    s = make(tmp_path)
    assert s.get("home.tiles") == []  # the only item was bad: none is left
    assert s.get("home.pins") == [] and s.get("home.commands") == []  # not lists / bad
    assert s.get("appearance.theme") == "dark"  # the rest still read


def test_general_reset_leaves_the_home_lists(tmp_path):
    s = make(tmp_path)
    s.set("home.pins", ["panel#clock"])
    s.set("appearance.theme", "dark")
    items = s.reset(groups=settings.GROUPS)
    assert [k for k, _b, _a in items] == ["appearance.theme"]
    assert s.get("home.pins") == ["panel#clock"]


def test_home_lists_are_not_rows_of_the_general_page():
    assert not [k for k in registry.rows("general") if k.startswith("home.")]


def test_pins():
    own = home_items.pin_of("general#appearance.own_font")
    assert own.switch == "appearance.own_font" and own.page_id == "general"
    number = home_items.pin_of("general#behavior.history_keep")
    assert number is not None and number.switch == ""  # opens the page
    clock = home_items.pin_of("panel#clock")
    assert clock.row_title and clock.page_title and clock.switch == ""
    assert home_items.pin_of("panel#nope") is None
    assert home_items.pin_of("nope#clock") is None
    assert home_items.pin_of("general#home.pins") is None
    assert [p.address for p in home_items.valid_pins(
        ["panel#clock", "gone#x", "general#appearance.own_font"])] == [
        "panel#clock", "general#appearance.own_font"]


def test_every_search_row_can_be_pinned():
    for page in registry.PAGES:
        for row_id in registry.rows(page.id):
            address = home_items.address(page.id, row_id)
            assert settings.PIN.fullmatch(address), address
            assert home_items.pin_of(address) is not None, address


def test_moved():
    assert home_items.moved([1, 2, 3], 0, 1) == [2, 1, 3]
    assert home_items.moved([1, 2, 3], 2, 1) == [1, 2, 3]
    assert home_items.moved([1, 2, 3], 0, -1) == [1, 2, 3]
    items = [1, 2]
    home_items.moved(items, 0, 1)
    assert items == [1, 2]  # a copy


def test_command_goes_as_an_argument():
    argv = home_items.command_argv('kitty -e sh -c "echo $HOME; ls"')
    assert argv[:2] == ["sh", "-c"] and "$HOME" not in argv[2]
    assert argv[4] == 'hl.dsp.exec_cmd("kitty -e sh -c \\"echo $HOME; ls\\"")'
    assert argv[5:] == ["exec", 'kitty -e sh -c "echo $HOME; ls"']


def test_fallback_only_on_the_conf_answer(tmp_path):
    """Under Lua an error that merely quotes the phrase must not trigger the plain form."""
    log = tmp_path / "log"
    stub = tmp_path / "hyprctl"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >>"{log}"\n'
                    'echo "error: [string] Invalid dispatcher here"\n')
    stub.chmod(0o755)
    subprocess.run(home_items.command_argv("Invalid dispatcher"),
                   env={"PATH": f"{tmp_path}:/usr/bin"}, check=True, timeout=5)
    assert len(log.read_text().splitlines()) == 1


def test_command_reaches_hyprctl_unchanged(tmp_path):
    log = tmp_path / "log"
    stub = tmp_path / "hyprctl"
    stub.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done >>"{log}"\n'
                    'echo "Invalid dispatcher"\n')
    stub.chmod(0o755)
    cmd = "notify-send 'a b' \"$(id)\" `x`; touch /tmp/never"
    argv = home_items.command_argv(cmd)
    subprocess.run(argv, env={"PATH": f"{tmp_path}:/usr/bin"}, check=True, timeout=5)
    lines = log.read_text().splitlines()
    assert lines[0] == "dispatch" and lines[1].startswith("hl.dsp.exec_cmd(")
    assert lines[2:] == ["dispatch", "exec", cmd]  # the .conf fallback, as one argument


def test_run_command_detaches():
    seen = {}

    def spawn(argv, **kw):
        seen.update(argv=argv, **kw)

    home_items.run_command("btop", spawn=spawn)
    assert seen["argv"] == home_items.command_argv("btop")
    assert seen["start_new_session"] is True and seen["stdin"] == subprocess.DEVNULL


def test_every_page_has_a_line_icon():
    text = (ROOT / "settings_hub" / "widgets" / "icons.py").read_text(encoding="utf-8")
    shapes = set(re.findall(r'^    "([a-z-]+)":', text, re.M))
    assert {p.id for p in registry.PAGES} <= shapes
    assert {"command", "edit"} <= shapes
