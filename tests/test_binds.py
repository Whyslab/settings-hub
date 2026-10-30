"""Binds: parsing, names, conflicts, the managed block, History. No GTK.

Everything runs on an anonymised copy of hyprland.conf in a temporary HOME
with a stub hyprctl (binds_env.World); hyprland.conf itself is never written.
"""

import hashlib
import json

import pytest
from binds_env import CONF, LIVE, SOURCE_LINE, World
from conftest import load_json

from settings_hub import strings
from settings_hub.backends import binds as bb
from settings_hub.binds import conflicts, names, parser, writer
from settings_hub.binds.parser import Combo, modmask
from settings_hub.controllers import binds as ctl

ALT = modmask("ALT")


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.close()


def by_line(cfg, line):
    return next(b for b in cfg.binds if b.line == line and b.file.name == "hyprland.conf")


def effective(cfg, mods, key):
    combo = Combo.of(mods, key)
    return [b.dispatcher for b in cfg.binds if b.combo == combo and not b.submap]


# ---- parser -----------------------------------------------------------------


def test_fixture_has_66_binds_with_type_file_and_line(world):
    cfg = parser.parse(world.conf, world.own)
    assert len(cfg.binds) == 66
    assert all(b.keyword.startswith("bind") and b.file == world.conf and b.line > 0
               for b in cfg.binds)
    assert len({b.line for b in cfg.binds}) == 66
    kill = by_line(cfg, 42)
    assert (kill.keyword, kill.mods, kill.modmask, kill.key, kill.dispatcher) == \
        ("bind", "SUPER", 64, "C", "killactive")  # $mainMod expanded
    assert by_line(cfg, 41).arg == "kitty"  # $terminal expanded
    mute, lower = by_line(cfg, 81), by_line(cfg, 82)
    assert (mute.keyword, mute.flags, mute.modmask) == ("bindl", "l", 0)
    assert (lower.keyword, lower.flags) == ("bindel", "el")
    assert mute.arg == "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"  # comment stripped
    drag = by_line(cfg, 132)
    assert (drag.keyword, drag.dispatcher, drag.arg) == ("bindm", "mouse", "movewindow")
    sysmon = by_line(cfg, 269)
    assert (sysmon.key, sysmon.keycode) == ("code:49", 49)
    assert by_line(cfg, 138).rest == " cyclenext,"
    # Sourced files are read in order, after the lines before them.
    assert [p.name for p in cfg.files[:3]] == ["hyprland.conf", "animations.conf",
                                               "hyprland.conf"]
    assert cfg.files[2].parent.name == "wallpaper-theme"
    assert cfg.own_sourced is True and cfg.missing == [world.own]


def test_parser_unbind_submap_bindd_escapes_and_sources(tmp_path):
    extra = tmp_path / "extra.conf"
    extra.write_text("bind = SUPER, X, exec, from-extra\n")
    main = tmp_path / "hyprland.conf"
    main.write_text(
        "$mod = SUPER\n"
        "bind = $mod, A, exec, one\n"
        "bind = $mod, A, exec, two  # a comment\n"
        "bindd = $mod, B, Open the thing, exec, thing --x ## not a comment\n"
        "general {\n    bind = SUPER, Z, exec, not-a-bind\n}\n"
        "unbind = SUPER, A\n"
        "submap = resize\n"
        "binde = , right, resizeactive, 10 0\n"
        "submap = reset\n"
        "source = ./extra.conf\n"
        "bind = SUPERSHIFT, Y, exec, joined-mods\n")
    cfg = parser.parse(main)
    assert [(b.key, b.dispatcher, b.arg) for b in cfg.binds] == [
        ("B", "exec", "thing --x # not a comment"),
        ("right", "resizeactive", "10 0"),
        ("X", "exec", "from-extra"),
        ("Y", "exec", "joined-mods"),
    ]
    assert cfg.binds[0].description == "Open the thing"
    assert cfg.binds[0].rest == " Open the thing, exec, thing --x ## not a comment"
    assert cfg.binds[1].submap == "resize" and cfg.binds[2].submap == ""
    assert cfg.binds[3].modmask == 65
    assert [b.arg for b in cfg.unbinds[0].removed] == ["one", "two"]
    assert len(cfg.defs) == 6


def test_live_list_reconciled(world):
    cfg = parser.parse(world.conf, world.own)
    live = json.loads(LIVE.read_text())
    found, extra = parser.reconcile(cfg.binds, live)
    assert all(found) and extra == []
    live[1]["arg"] = "something else"  # SUPER+C differs in the live session
    found, extra = parser.reconcile(cfg.binds, live)
    assert [b.line for b, ok in zip(cfg.binds, found, strict=True) if not ok] == [42]
    assert [e["arg"] for e in extra] == ["something else"]


# ---- names ------------------------------------------------------------------


def test_names_human_for_at_least_90_percent(world):
    cfg = parser.parse(world.conf, world.own)
    human = [names.bind_name(b, cfg).human for b in cfg.binds]
    assert sum(human) / len(human) >= 0.9
    expected = load_json("hypr/names.json")
    for line, name in expected.items():
        assert names.bind_name(by_line(cfg, int(line)), cfg).text == name, line
    assert names.bind_name(by_line(cfg, 42), cfg).text == strings.BN_DISPATCHERS["killactive"]
    assert names.bind_name(by_line(cfg, 103), cfg).text == \
        strings.BN_WITH_ARG["workspace"].format(arg="2")  # a run: not the comment above 102
    sysmon = next(n for p, n in strings.BN_COMMANDS if "sysmon" in p)
    assert names.bind_name(by_line(cfg, 269), cfg) == names.Name(sysmon, "dictionary")


def test_key_labels():
    assert names.combo_label(modmask("SUPER SHIFT"), "N") == "Super + Shift + N"
    assert names.combo_label(64, "code:49") == "Super + `"
    assert names.combo_label(0, "XF86AudioMute") == strings.BN_KEYS["xf86audiomute"]
    assert names.combo_label(modmask("SUPER CTRL"), "up") == "Super + Ctrl + " + \
        strings.BN_KEYS["up"]
    assert names.combo_label(ALT, "Tab") == "Alt + Tab"


# ---- conflicts --------------------------------------------------------------


def test_alt_tab_is_one_entry_not_a_conflict(world):
    cfg = parser.parse(world.conf, world.own)
    entries = conflicts.entries(cfg.binds)
    assert len(entries) == 65
    alt_tab = next(e for e in entries if e.key == "ALT, Tab")
    assert [b.dispatcher for b in alt_tab.binds] == ["cyclenext", "bringactivetotop"]
    assert conflicts.conflict(entries, alt_tab.combo, alt_tab.actions()) is None
    kill = next(e for e in entries if e.key == "SUPER, C")
    other = conflicts.conflict(entries, kill.combo, alt_tab.actions(), exclude=alt_tab)
    assert other is kill
    assert conflicts.conflict(entries, Combo.of("SUPER", "c"), alt_tab.actions()) is kill
    assert conflicts.conflict(entries, Combo.of("SUPER CTRL", "K"), alt_tab.actions()) is None


@pytest.mark.parametrize("a,b", [
    ("grave", "code:49"), ("Escape", "code:9"), ("Page_Down", "Next"), ("page_up", "Prior"),
    ("K", "code:45"), ("XF86AudioMute", "code:121"), ("Tab", "TAB"),
])
def test_keysym_and_keycode_spellings_of_one_key_are_one_combination(a, b):
    assert Combo.of("SUPER", a) == Combo.of("SUPER", b)


def test_other_keys_stay_apart():
    assert Combo.of("SUPER", "grave") != Combo.of("SUPER", "code:50")
    assert Combo.of("SUPER", "grave") != Combo.of("SUPER SHIFT", "code:49")
    assert Combo.of("SUPER", "XF86Launch5") == Combo.of("SUPER", "xf86launch5")  # not in the table
    assert Combo.of("SUPER", "mouse:272") != Combo.of("SUPER", "code:272")


def test_a_captured_keysym_conflicts_with_a_keycode_bind(world):
    """The capture reports the key under Esc as "grave"; the config binds it as code:49."""
    cfg = parser.parse(world.conf, world.own)
    entries = conflicts.entries(cfg.binds)
    sysmon = next(e for e in entries if e.key == "SUPER, code:49")
    alt_tab = next(e for e in entries if e.key == "ALT, Tab")
    assert conflicts.conflict(entries, Combo.of("SUPER", "grave"), alt_tab.actions()) is sysmon


def test_replacing_a_keycode_bind_by_its_keysym_unbinds_the_keycode_spelling(world):
    """Hyprland's unbind matches the spelling, so the occupant is unbound as code:49."""
    moved = world.backend.change(world.backend.op_rebind("SUPER, Q", 64, "grave"))
    assert moved.after["SUPER, grave"] == [
        "unbind = SUPER, code:49  # hyprland.conf:269",
        "bind = SUPER, grave, exec, kitty  # hyprland.conf:41"]
    cfg = parser.parse(world.conf, world.own)
    assert [b.arg for b in cfg.binds if b.combo == Combo.of("SUPER", "code:49")] == ["kitty"]


# ---- writer -----------------------------------------------------------------


def test_rebind_alt_tab_moves_both_actions(world):
    main = sha(world.conf)
    commit = world.backend.change(world.backend.op_rebind("ALT, Tab", ALT, "grave"))
    assert commit.changed and commit.before == {"ALT, Tab": [], "ALT, grave": []}
    assert commit.after == {
        "ALT, Tab": ["unbind = ALT, Tab  # hyprland.conf:138"],
        "ALT, grave": ["bind = ALT, grave, cyclenext,  # hyprland.conf:138",
                       "bind = ALT, grave, bringactivetotop,  # hyprland.conf:139"],
    }
    cfg = parser.parse(world.conf, world.own)
    assert effective(cfg, "ALT", "Tab") == []
    assert effective(cfg, "ALT", "grave") == ["cyclenext", "bringactivetotop"]
    assert world.calls_of() == ["hyprctl configerrors", "hyprctl reload",
                                "hyprctl configerrors"]
    assert sha(world.conf) == main
    assert world.own.read_text().startswith(writer.TEMPLATE.split("# >>>")[0])


def test_disable_second_action_keeps_the_first(world):
    alt_tab = ("bind", "bringactivetotop", "", "")
    commit = world.backend.change(world.backend.op_disable("ALT, Tab", [alt_tab]))
    assert commit.after["ALT, Tab"] == ["unbind = ALT, Tab  # hyprland.conf:138",
                                        "bind = ALT, Tab, cyclenext,  # hyprland.conf:138"]
    cfg = parser.parse(world.conf, world.own)
    assert effective(cfg, "ALT", "Tab") == ["cyclenext"]
    assert [e.key for e in bb.disabled_entries(cfg)] == ["ALT, Tab"]


def test_rebind_keeps_bindl_and_bindel(world):
    b = world.backend
    b.change(b.op_rebind(", XF86AudioMute", modmask("SUPER CTRL"), "M"))
    b.change(b.op_rebind(", XF86AudioLowerVolume", modmask("SUPER CTRL"), "minus"))
    cfg = parser.parse(world.conf, world.own)
    mute = next(x for x in cfg.binds if x.key == "M" and x.modmask == modmask("SUPER CTRL"))
    lower = next(x for x in cfg.binds if x.key == "minus")
    assert (mute.keyword, mute.arg) == ("bindl", "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
    assert (lower.keyword, lower.arg) == ("bindel", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-")
    assert effective(cfg, "", "XF86AudioMute") == []


def test_rewriting_the_same_is_a_no_op(world):
    commit = world.backend.change(world.backend.op_rebind("ALT, Tab", ALT, "grave"))
    before = (world.own.read_bytes(), world.own.stat().st_mtime_ns)
    world.clear_calls()
    again = world.backend.apply_lines(commit.after)
    assert again.changed is False
    assert (world.own.read_bytes(), world.own.stat().st_mtime_ns) == before
    assert world.calls_of() == []
    # Disabling what is already disabled plans no new lines either.
    twice = world.backend.change(world.backend.op_disable("ALT, grave"))
    assert twice.changed
    world.clear_calls()
    assert world.backend.change(world.backend.op_disable("ALT, Tab")).changed is False
    assert world.calls_of() == []


def test_config_errors_restore_the_previous_block(world):
    b = world.backend
    b.change(b.op_rebind("SUPER, Q", modmask("SUPER CTRL"), "Q"))
    good = world.own.read_text()
    (world.root / "bad").write_text("ALT, grave")
    world.clear_calls()
    with pytest.raises(writer.ConfigErrors) as err:
        b.change(b.op_rebind("ALT, Tab", ALT, "grave"))
    assert "invalid key" in err.value.errors[0]
    assert world.own.read_text() == good
    assert world.calls_of() == ["hyprctl configerrors", "hyprctl reload",
                                "hyprctl configerrors", "hyprctl reload"]


def test_old_config_errors_do_not_block_a_write(world):
    (world.root / "old-errors").write_text("error in hyprland.conf:5\n")
    assert world.backend.change(world.backend.op_rebind("ALT, Tab", ALT, "grave")).changed


def test_lua_config_means_nothing_is_written(world):
    world.lua.write_text("-- lua\n")
    with pytest.raises(writer.LuaActive):
        world.backend.change(world.backend.op_rebind("ALT, Tab", ALT, "grave"))
    with pytest.raises(writer.LuaActive):
        world.backend.apply_lines({"ALT, Tab": ["unbind = ALT, Tab"]})
    assert not world.own.exists() and world.calls_of() == []
    assert world.backend.load().lua == world.lua


def test_a_later_file_redefining_the_combination_is_refused(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    try:
        later = w.hypr / "later.conf"
        later.write_text("bind = ALT, grave, exec, later\n")
        w.conf.write_text(w.conf.read_text() + "source = ~/.config/hypr/later.conf\n")
        with pytest.raises(writer.LaterDefinition) as err:
            w.backend.change(w.backend.op_rebind("ALT, Tab", ALT, "grave"))
        assert err.value.where == "later.conf:1"
        assert not w.own.exists() and w.calls_of() == []
    finally:
        w.close()


def test_add_replace_and_revert(world):
    b = world.backend
    added = b.change(b.op_add(modmask("SUPER CTRL"), "K", "kitty --title a#b"))
    assert added.after == {"SUPER CTRL, K": [
        "bind = SUPER CTRL, K, exec, kitty --title a##b  # settings-hub"]}
    cfg = parser.parse(world.conf, world.own)
    assert next(x for x in cfg.binds if x.key == "K").arg == "kitty --title a#b"
    # Replace an occupied combination: the occupant is unbound, then the bind moves in.
    moved = b.change(b.op_rebind("SUPER, Q", 64, "C"))
    assert moved.after["SUPER, C"] == ["unbind = SUPER, C  # hyprland.conf:42",
                                      "bind = SUPER, C, exec, kitty  # hyprland.conf:41"]
    reverted = b.change(b.op_revert("SUPER, C"))
    assert reverted.after == {"SUPER, C": [], "SUPER, Q": []}  # both back, one action
    cfg = parser.parse(world.conf, world.own)
    assert effective(cfg, "SUPER", "C") == ["killactive"]
    assert effective(cfg, "SUPER", "Q") == ["exec"]


def test_missing_own_file_is_created_from_the_template_in_tmp(world):
    assert not world.own.exists()
    world.backend.change(world.backend.op_disable("SUPER, E"))
    text = world.own.read_text()
    assert text.startswith(writer.TEMPLATE.split("# >>>")[0])
    assert world.block() == ["unbind = SUPER, E  # hyprland.conf:44"]
    assert SOURCE_LINE in world.conf.read_text()  # the copy, never the real file


# ---- controller and History -------------------------------------------------


class View:
    def __init__(self) -> None:
        self.rows: list[ctl.RowModel] = []
        self.statuses: list[str] = []
        self.asks: list = []
        self.setup = None

    def show_setup(self, lua, not_sourced, error, live_known) -> None:
        self.setup = (lua, not_sourced, error, live_known)

    def show_rows(self, rows, editable) -> None:
        self.rows, self.editable = rows, editable

    def status(self, text) -> None:
        self.statuses.append(text)

    def ask_conflict(self, combo, occupant, on_replace) -> None:
        self.asks.append((combo, occupant, on_replace))


def controller(world):
    view = View()
    c = ctl.Controller(world.backend, world.history, view)
    c.refresh()
    world.loop.pump()
    return c, view


def test_rows_grouped_named_and_checked_against_hyprland(world):
    c, view = controller(world)
    assert view.setup == (None, False, "", True)
    rows = view.rows
    assert len(rows) == 65 and view.editable
    assert all(r.live_ok is True for r in rows)
    titles = list(dict.fromkeys(r.group_title for r in rows))
    assert titles[:3] == [strings.BN_GROUPS["apps"], strings.BN_GROUPS["windows"],
                          strings.BN_GROUPS["workspaces"]]
    alt = c.models["ALT, Tab"]
    assert alt.combo == "Alt + Tab" and len(alt.actions) == 2 and alt.movable
    assert not c.models["SUPER, mouse:272"].movable  # a mouse bind keeps its button
    assert c.models["SUPER SHIFT, T"].matches("timer.py")
    assert c.models["SUPER SHIFT, T"].matches("Super + Shift + T")


def test_conflict_asks_with_the_occupants_name(world):
    c, view = controller(world)
    c.rebind("ALT, Tab", 64, "C")
    world.loop.pump()
    assert len(view.asks) == 1 and not world.own.exists()
    combo, occupant, replace = view.asks[0]
    assert (combo, occupant) == ("Super + C", strings.BN_DISPATCHERS["killactive"])
    replace()  # "Replace"
    world.loop.pump()
    cfg = parser.parse(world.conf, world.own)
    assert effective(cfg, "SUPER", "C") == ["cyclenext", "bringactivetotop"]


def test_history_per_combination_and_group_undo(world):
    c, view = controller(world)
    c.rebind("ALT, Tab", ALT, "grave")
    world.loop.pump()
    groups = world.history.groups()
    assert len(groups) == 1
    items = {e.key: (e.before, e.after) for e in groups[0].entries}
    assert items == {
        "ALT, Tab": ([], ["unbind = ALT, Tab  # hyprland.conf:138"]),
        "ALT, grave": ([], ["bind = ALT, grave, cyclenext,  # hyprland.conf:138",
                            "bind = ALT, grave, bringactivetotop,  # hyprland.conf:139"]),
    }
    assert {e.backend for e in groups[0].entries} == {bb.BACKEND}
    assert view.statuses[-1].startswith(strings.BN_DONE_REBIND.split("{")[0])
    world.clear_calls()
    plan = world.history.plan_undo_last(strings.HISTORY_UNDO_PREFIX)
    assert plan.flagged == [] and sorted(k for _b, k in plan.targets) == ["ALT, Tab",
                                                                          "ALT, grave"]
    result = world.history.execute(plan)
    world.loop.pump()
    assert result.errors == {} and world.block() == []
    assert world.calls_of().count("hyprctl reload") == 1  # both items, one write
    cfg = parser.parse(world.conf, world.own)
    assert effective(cfg, "ALT", "Tab") == ["cyclenext", "bringactivetotop"]
    assert effective(cfg, "ALT", "grave") == []


def test_disabling_one_action_is_its_own_group(world):
    c, _view = controller(world)
    c.rebind("ALT, Tab", ALT, "grave")
    world.loop.pump()
    c.disable("ALT, grave", ("bind", "bringactivetotop", "", ""))
    world.loop.pump()
    assert [len(g.entries) for g in world.history.groups()] == [2, 1]
    assert effective(parser.parse(world.conf, world.own), "ALT", "grave") == ["cyclenext"]
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert effective(parser.parse(world.conf, world.own), "ALT", "grave") == \
        ["cyclenext", "bringactivetotop"]


def test_revert_row_and_disabled_rows(world):
    c, view = controller(world)
    c.disable("SUPER, E")
    world.loop.pump()
    row = c.models["SUPER, E"]
    assert row.disabled and row.managed and row.group == "disabled"
    c.revert("SUPER, E")
    world.loop.pump()
    assert world.block() == [] and not c.models["SUPER, E"].disabled
    assert [g.label for g in world.history.groups()][-1] == \
        strings.BN_LABEL_REVERT.format(name=row.name)


def test_lua_config_turns_the_page_read_only(world):
    world.lua.write_text("-- lua\n")
    c, view = controller(world)
    assert view.setup[0] == world.lua and view.editable is False
    assert not any(r.editable for r in view.rows)
    # hyprland.conf is not read any more: the rows are Hyprland's own list
    assert view.rows and all(r.id.startswith("lua|") for r in view.rows)
    assert len(view.rows) == len(world.backend.live())
    c.rebind("ALT, Tab", ALT, "grave")
    c.disable("SUPER, E")
    world.loop.pump()
    assert not world.own.exists() and world.history.groups() == []


def test_unsourced_own_file_is_reported(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, sourced=False)
    try:
        _c, view = controller(w)
        assert view.setup[1] is True
    finally:
        w.close()


def test_fixture_is_the_anonymised_live_shape():
    text = CONF.read_text()
    assert "/home/" not in text and text.count("\nbind") >= 60


def test_moving_an_added_bind_keeps_its_origin(world):
    b = world.backend
    b.change(b.op_add(modmask("SUPER CTRL"), "K", "kitty"))
    moved = b.change(b.op_rebind("SUPER CTRL, K", modmask("SUPER CTRL"), "L"))
    assert moved.after == {"SUPER CTRL, K": [],
                           "SUPER CTRL, L": ["bind = SUPER CTRL, L, exec, kitty  # settings-hub"]}


def test_a_symlinked_own_file_stays_a_link(world):
    target = world.root / "dotfiles" / "settings-hub.conf"
    target.parent.mkdir()
    target.write_text(writer.TEMPLATE)
    world.own.symlink_to(target)
    world.backend.change(world.backend.op_disable("SUPER, E"))
    assert world.own.is_symlink()
    assert "unbind = SUPER, E" in target.read_text()


def test_lua_dispatchers_are_shown_by_kind():
    """Hyprland 0.57 with a Lua config reports the dispatcher as "HL.Dispatcher(exec_cmd)"
    or "function: 0x…" and arg as an internal number; neither number is shown."""
    item = {"modmask": 64, "key": "Q", "dispatcher": "HL.Dispatcher(exec_cmd)", "arg": "6",
            "description": "", "submap": ""}
    b = ctl._live_bind(item)
    assert (b.dispatcher, b.arg) == ("exec_cmd", "")
    b = ctl._live_bind(dict(item, dispatcher="function: 0x55bd772b88c0", arg="160"))
    assert (b.dispatcher, b.arg) == (strings.BN_LUA_FUNCTION, "")
    b = ctl._live_bind(dict(item, description="Терминал"))
    assert names.bind_name(b).text == "Терминал"
