"""The Monitor, Notifications, Autostart and Updates backends (no GTK, no session)."""

import json
from datetime import date

import pytest

from settings_hub import history as hist
from settings_hub.backends import autostart as ab
from settings_hub.backends import monitor as mb
from settings_hub.backends import notifications as nb
from settings_hub.backends import updates as upd
from settings_hub.binds import luaread


def undo(log):
    return log.execute(log.plan_undo_last())


# ---- updates ------------------------------------------------------------------


def test_updates_parse_skips_noise():
    text = "linux 7.2.14-arch1-1 -> 7.2.15-arch1-1\n:: warning\n\nfoo 1 -> 2 [ignored]\n"
    assert upd.parse_updates(text) == [
        upd.Package("linux", "7.2.14-arch1-1", "7.2.15-arch1-1"), upd.Package("foo", "1", "2")]
    assert upd.parse_updates("yay-bin 12 -> 13", aur=True)[0].aur


def test_updates_last_full_upgrade_reads_the_last_one(tmp_path):
    log = tmp_path / "pacman.log"
    log.write_text("[2026-11-01T10:00:00+0100] [PACMAN] starting full system upgrade\n"
                   "[2026-11-02T10:00:00+0100] [ALPM] upgraded x\n"
                   "[2026-11-14T17:17:21+0100] [PACMAN] starting full system upgrade\n"
                   "[2026-11-15T09:00:00+0100] [PACMAN] Running 'pacman -S foo'\n")
    assert upd.last_full_upgrade(log) == date(2026, 11, 14)
    assert upd.last_full_upgrade(tmp_path / "missing") is None


def test_updates_reboot_needed_when_the_running_kernel_has_no_modules(tmp_path):
    (tmp_path / "7.2.15-arch1-1").mkdir()
    assert not upd.reboot_needed("7.2.15-arch1-1", tmp_path)
    assert upd.reboot_needed("7.2.14-arch1-1", tmp_path)
    assert not upd.reboot_needed("7.2.14-arch1-1", tmp_path / "none")  # no modules dir: unknown


def test_updates_probe_counts_checkupdates_answers(monkeypatch):
    monkeypatch.setattr(upd.shutil, "which",
                        lambda name: "/bin/x" if name == "checkupdates" else None)
    calls = []

    def runner(argv, _timeout):
        calls.append(argv[0])
        if argv[0] == "checkupdates":
            return answer
        return 0, "orphan1\norphan2\n"

    answer = (2, "")  # checkupdates: nothing
    info = upd.probe(runner)
    assert info.checked and info.packages == [] and info.orphans == ["orphan1", "orphan2"]
    answer = (1, "")  # failed (no network)
    info = upd.probe(runner)
    assert not info.checked and info.error
    calls.clear()
    info = upd.probe(runner, check=False)
    assert "checkupdates" not in calls and not info.checked


def test_updates_terminal_waits_for_enter(monkeypatch):
    monkeypatch.setattr(upd.shutil, "which", lambda name: "/bin/kitty" if name == "kitty" else None)
    argv = upd.terminal_command("sudo pacman -Syu", "T", "done")
    assert argv[:3] == ["kitty", "--title", "T"]
    assert argv[-1].startswith("sudo pacman -Syu;") and "read -r _" in argv[-1]
    monkeypatch.setattr(upd.shutil, "which", lambda _name: None)
    assert upd.terminal_command("x", "T", "done") is None


# ---- notifications ----------------------------------------------------------


class Panel:
    """A stand-in for `hyprpanel` and `gsettings`."""

    def __init__(self, dnd=False, up=True):
        self.dnd, self.up, self.calls = dnd, up, []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["hyprpanel", "toggleDnd"]:
            if not self.up:
                return 1, ""
            self.dnd = not self.dnd
            return 0, "Enabled\n" if self.dnd else "Disabled\n"
        if argv[0] == "gsettings":
            return 0, ("[<{'id': <uint32 3>, 'app-name': <'kitty'>}>, "
                       "<{'id': <uint32 2>, 'app-name': <'Telegram'>}>, "
                       "<{'id': <uint32 1>, 'app-name': <'kitty'>}>]")
        return 0, ""


def test_notifications_read_dnd_leaves_it_as_it_was():
    panel = Panel(dnd=True)
    b = nb.Backend(None, runner=panel, config=None)
    assert b.read_dnd() is True and panel.dnd is True
    panel.dnd = False
    assert b.read_dnd() is False and panel.dnd is False
    assert nb.Backend(None, runner=Panel(up=False)).read_dnd() is None


def test_notifications_set_dnd_flips_only_when_needed():
    panel = Panel(dnd=False)
    b = nb.Backend(None, runner=panel)
    b.set_dnd(False)
    assert panel.dnd is False
    b.set_dnd(True)
    assert panel.dnd is True
    with pytest.raises(RuntimeError):
        nb.Backend(None, runner=Panel(up=False)).set_dnd(True)


def test_notifications_write_keeps_other_keys_mode_and_layout(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"bar.x": "ё", "notifications.position": "top"}, indent=2,
                                 ensure_ascii=False))
    config.chmod(0o600)
    b = nb.Backend(None, runner=Panel(), config=config)
    assert b.values()[nb.POSITION] == "top" and b.values()[nb.TIMEOUT] == 7000
    b.write({nb.TIMEOUT: 3000, nb.POSITION: "top right"})  # top right is the default
    raw = json.loads(config.read_text())
    assert raw == {"bar.x": "ё", "notifications.timeout": 3000}
    assert "ё" in config.read_text() and not config.read_text().endswith("\n")
    assert config.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        b.write({nb.POSITION: "middle"})
    assert json.loads(config.read_text()) == raw  # a refused value writes nothing


def test_notifications_never_overwrite_a_broken_config(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{ not json")
    with pytest.raises(ValueError):
        nb.Backend(None, runner=Panel(), config=config).write({nb.TIMEOUT: 3000})
    assert config.read_text() == "{ not json"


def test_notifications_ignore_list_is_cleaned():
    assert nb.clean(nb.IGNORE, [" kitty ", "kitty", "", 5, "x" * 200]) == ["kitty"]
    assert nb.clean(nb.TIMEOUT, 999999) == nb.TIMEOUT_MAX_MS


def test_notifications_stored_count_and_senders():
    count, apps = nb.parse_stored(Panel()(["gsettings"])[1])
    assert count == 3 and apps == ["kitty", "Telegram"]
    assert nb.parse_stored("@aa{sv} []") == (0, [])


def test_notifications_undo_through_history(tmp_path):
    config = tmp_path / "config.json"
    panel = Panel(dnd=False)
    b = nb.Backend(None, runner=panel, config=config)
    log = hist.History(tmp_path / "h.jsonl")
    nb.register(log, b)
    b.apply({nb.DND: True, nb.TIMEOUT: 2000})
    log.record([(nb.BACKEND, nb.DND, "dnd", False, True),
                (nb.BACKEND, nb.TIMEOUT, "t", 7000, 2000)])
    undo(log)
    assert panel.dnd is False and b.values()[nb.TIMEOUT] == 7000


# ---- autostart --------------------------------------------------------------


def test_autostart_command_from_desktop_exec():
    assert ab.command_from_exec("telegram-desktop -- %u") == "telegram-desktop --"
    assert ab.command_from_exec("app %F --x 100%%") == "app --x 100%"


def test_autostart_normalize_drops_bad_and_duplicate_items():
    state = ab.normalize({"items": [
        {"name": "A", "command": " a --x"}, {"command": "a --x"}, {"command": ""},
        {"command": "b 'open"}, "junk", {"name": 5, "command": "c"}]})
    assert state == {"items": [{"name": "A", "command": "a --x"}, {"name": "", "command": "c"}]}
    assert ab.normalize(None) == {"items": []}


def test_autostart_lua_escapes_and_names():
    text = ab.build_lua({"items": [{"name": "Tg", "command": 'sh -c "echo \\"x\\""'}]})
    assert 'hl.on("hyprland.start", function()' in text
    assert 'hl.exec_cmd("sh -c \\"echo \\\\\\"x\\\\\\"\\"")  -- Tg' in text
    assert "exec_cmd" not in ab.build_lua({"items": []})


def test_autostart_save_and_undo(tmp_path):
    b = ab.Backend(None, state_file=tmp_path / "a.json", hypr=tmp_path / "hypr")
    log = hist.History(tmp_path / "h.jsonl")
    ab.register(log, b)
    before = b.load()
    after = {"items": [{"name": "", "command": "foot"}]}
    b.save(after)
    log.record([(ab.BACKEND, ab.KEY, "auto", before, after)])
    assert 'hl.exec_cmd("foot")' in (tmp_path / "hypr" / ab.LUA_FILE).read_text()
    undo(log)
    assert b.load() == {"items": []}
    assert "exec_cmd" not in (tmp_path / "hypr" / ab.LUA_FILE).read_text()


@pytest.mark.skipif(luaread.interpreter() is None, reason="no lua5.4 / lua")
def test_autostart_reads_the_configs_login_commands_without_running_them(tmp_path):
    hypr = tmp_path / "hypr"
    hypr.mkdir()
    marker = tmp_path / "ran"
    (hypr / "hyprland.lua").write_text(
        'local home = os.getenv("HOME")\n'
        "hl.on(\"hyprland.start\", function()\n"
        "    -- Panel\n"
        f'    hl.exec_cmd("touch {marker}")\n'
        '    hl.exec_cmd("waybar") -- the bar\n'
        "end)\n"
        f'hl.exec_cmd("not at login")\n'
        f'pcall(dofile, "{hypr}/settings-hub.lua")\n')
    (hypr / "settings-hub.lua").write_text(f'pcall(dofile, "{hypr}/{ab.LUA_FILE}")\n')
    b = ab.Backend(None, state_file=tmp_path / "a.json", hypr=hypr)
    b.save({"items": [{"name": "", "command": "ours"}]})
    info = b.probe()
    assert [(s.command, s.name) for s in info.system] == [
        (f"touch {marker}", "Panel"), ("waybar", "the bar")]  # ours is not repeated
    assert info.loaded and not marker.exists()


# ---- monitor ----------------------------------------------------------------

MONITORS = json.dumps([{
    "name": "eDP-1", "description": "LG Display 0x060F", "width": 1920, "height": 1080,
    "refreshRate": 60.02, "scale": 1.5, "x": 0, "y": 0, "disabled": False,
    "availableModes": ["1920x1080@60.02Hz", "1920x1080@40.00Hz"]}])


class Hypr:
    def __init__(self, eval_answer="ok"):
        self.calls, self.eval_answer = [], eval_answer

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["monitors", "all"]:
            return 0, MONITORS
        if args == ["-j", "version"]:
            return 0, '{"version": "0.57.2"}'
        if args[0] == "eval":
            return (0 if self.eval_answer == "ok" else 7), self.eval_answer
        return 1, ""


def test_monitor_parse_and_scales():
    (m,) = mb.parse_monitors(MONITORS)
    assert m.modes == ["1920x1080@60.02", "1920x1080@40.00"]
    assert m.setting() == {"mode": "1920x1080@60.02", "scale": 1.5, "position": "0x0",
                           "enabled": True, "transform": 0}
    assert mb.scales_for(1920, 1080, 1.5) == [1.0, 1.2, 1.25, 1.5, 1.6, 2.0, 2.5, 3.0]
    assert 1.5 not in mb.scales_for(2560, 1440, 1.0) and 1.6 in mb.scales_for(2560, 1440, 1)
    assert mb.parse_monitors("garbage") == [] and mb.parse_monitors('[{"name": "a;b"}]') == []


def test_monitor_lua_call_is_checked_and_quoted():
    setting = {"mode": "1920x1080@60.02", "scale": 1.25, "position": "0x0", "enabled": True}
    assert mb.lua_call("eDP-1", setting) == (
        'hl.monitor({ output = "eDP-1", mode = "1920x1080@60.02", position = "0x0", '
        "scale = 1.25, transform = 0 })")
    assert "transform = 1 })" in mb.lua_call("eDP-1", {**setting, "transform": 1})
    assert mb.clean_setting({**setting, "transform": 9}) is None
    assert mb.lua_call("HDMI-A-1", {**setting, "enabled": False}) == \
        'hl.monitor({ output = "HDMI-A-1", disabled = true })'
    assert mb.clean_setting({**setting, "mode": '1920x1080"); os.exit() --'}) is None
    assert mb.clean_setting({**setting, "position": "0x0 })"}) is None
    assert mb.clean_setting({**setting, "scale": True}) is None


def test_monitor_try_live_needs_exactly_ok(tmp_path):
    setting = {"mode": "1920x1080@40.00", "scale": 1.5, "position": "0x0", "enabled": True}
    b = mb.Backend(None, hyprctl=Hypr(), state_file=tmp_path / "m.json", hypr=tmp_path)
    b.try_live("eDP-1", setting)
    with pytest.raises(RuntimeError):
        mb.Backend(None, hyprctl=Hypr("error: bad mode")).try_live("eDP-1", setting)
    with pytest.raises(ValueError):
        b.try_live("eDP-1; x", setting)


def test_monitor_save_and_undo(tmp_path):
    hypr = Hypr()
    b = mb.Backend(None, hyprctl=hypr, state_file=tmp_path / "m.json", hypr=tmp_path)
    log = hist.History(tmp_path / "h.jsonl")
    mb.register(log, b)
    before = mb.parse_monitors(MONITORS)[0].setting()
    after = {**before, "scale": 1.25}
    b.save("eDP-1", after)
    assert "scale = 1.25" in (tmp_path / mb.LUA_FILE).read_text()
    log.record([(mb.BACKEND, "monitor.eDP-1", "m", before, after)])
    hypr.calls.clear()
    undo(log)  # the stand-in still reports 1.5: a flagged plan still runs
    assert ["eval", mb.lua_call("eDP-1", before)] in hypr.calls
    assert "scale = 1.5" in (tmp_path / mb.LUA_FILE).read_text()
    assert b.probe().lua


def test_new_files_are_loaded_before_the_games_file():
    from settings_hub.binds import writer
    text = writer.lua_text("/d", "/b", "/c")
    assert text.index(ab.LUA_FILE) < text.index(mb.LUA_FILE) < text.index("settings-hub-games")


class FlakyPanel(Panel):
    """toggleDnd flips, but the answer of call number `lose` never arrives."""

    def __init__(self, dnd, lose):
        super().__init__(dnd=dnd)
        self.n, self.lose = 0, lose

    def __call__(self, argv):
        rc, out = super().__call__(argv)
        if argv[:2] == ["hyprpanel", "toggleDnd"]:
            self.n += 1
            if self.n == self.lose:
                return 124, ""
        return rc, out


@pytest.mark.parametrize("lose", [1, 2])
def test_notifications_a_lost_answer_makes_dnd_unknown_not_guessed(lose):
    assert nb.Backend(None, runner=FlakyPanel(True, lose)).read_dnd() is None


def test_notifications_set_dnd_needs_no_read_and_ends_in_the_wanted_state():
    for start in (False, True):
        for want in (False, True):
            panel = Panel(dnd=start)
            nb.Backend(None, runner=panel).set_dnd(want)
            assert panel.dnd is want
            assert len(panel.calls) == (1 if start != want else 2)


def test_notifications_sender_with_a_quote():
    text = "[<{'id': <uint32 1>, 'app-name': <\"Bob's app\">}>]"
    assert nb.parse_stored(text) == (1, ["Bob's app"])


def test_autostart_keeps_spacing_inside_quotes_and_refuses_new_lines():
    assert ab.clean_command('  notify-send "a  b" ') == 'notify-send "a  b"'
    assert ab.clean_command("a\nb") is None


def test_autostart_short_note_is_one_clipped_sentence():
    assert ab.short_note("Обои: демон и восстановление") == "Обои"
    assert ab.short_note("Окно пароля (polkit). Его служба") == "Окно пароля (polkit)"
    assert len(ab.short_note("x" * 300)) == ab.NOTE_MAX


@pytest.mark.skipif(luaread.interpreter() is None, reason="no lua5.4 / lua")
def test_binds_reader_does_not_run_start_handlers(tmp_path):
    lua = tmp_path / "hyprland.lua"
    lua.write_text('hl.on("hyprland.start", function() hl.exec_cmd("x") end)\n')
    assert "exec\t" not in luaread._run(lua, None, 2)
    assert "exec\t" in luaread._run(lua, None, 2, starts=True)


def test_monitor_restore_falls_back_to_a_reload(tmp_path):
    setting = {"mode": "1920x1080@60.02", "scale": 1.5, "position": "0x0", "enabled": True}

    class Stubborn(Hypr):
        def __call__(self, args):
            if args == ["reload", "config-only"]:
                self.calls.append(args)
                return 0, "ok"
            return super().__call__(args)

    hypr = Stubborn("error: busy")
    mb.Backend(None, hyprctl=hypr).restore("eDP-1", setting)
    assert sum(c[0] == "eval" for c in hypr.calls) == 3 and hypr.calls[-1] == ["reload",
                                                                                "config-only"]


def test_monitor_disabled_output_reporting_0x0_still_has_a_mode():
    raw = json.loads(MONITORS)
    raw[0].update(width=0, height=0, disabled=True)
    (m,) = mb.parse_monitors(json.dumps(raw))
    assert m.setting()["mode"] == "1920x1080@60.02" and not m.enabled
    assert mb.clean_setting({**m.setting(), "enabled": True}) is not None
