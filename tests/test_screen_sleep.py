"""Screen and sleep: backend, page logic and History, isolated (plan section 4).

Everything runs against copies of screen-sleep's modules in a temporary HOME,
with stub programs; see screen_sleep_env.py. No GTK here: the page's logic
lives in controllers.screen_sleep and is driven with a fake clock.
"""

import ast
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

import pytest
from conftest import ROOT, load_json
from screen_sleep_env import SS_FIXTURES, FakeTimers, FakeView, World

from settings_hub import loader, strings
from settings_hub.backends import screen_sleep as backend_mod
from settings_hub.controllers import screen_sleep as ctl

HELPER = ROOT / "settings_hub" / "helpers" / "caffeine.py"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.close()


@pytest.fixture
def battery(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, power="battery")
    yield w
    w.close()


def page(w: World):
    """The controller with a fake view and clock, shown once (like on map)."""
    view, timers = FakeView(), FakeTimers()
    c = ctl.Controller(w.backend, w.history, view, timers)
    c.refresh()
    w.loop.pump()
    return c, view, timers


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diff(a, b, prefix=""):
    """Paths of the leaves that differ between two nested dicts."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out += diff(a.get(key), b.get(key), f"{prefix}{key}.")
        return out
    return [] if a == b else [prefix.rstrip(".")]


# ---- writing one field ----------------------------------------------------------

def test_editing_battery_dim_changes_only_that_field(world):
    c, view, timers = page(world)
    before_cfg, before_block = world.cfg(), sha(world.hypridle)
    c.edit("idle.battery.dim", {"enabled": True, "minutes": 9})
    timers.advance(1.4, world.loop)
    assert world.cfg() == before_cfg  # not before 1.5 s
    timers.advance(0.2, world.loop)
    assert diff(before_cfg, world.cfg()) == ["idle.battery.dim.minutes"]
    assert world.cfg()["idle"]["battery"]["dim"] == {"enabled": True, "minutes": 9}
    # On AC power the battery set is not active: hypridle is left alone.
    assert sha(world.hypridle) == before_block
    assert world.calls_of("pkill") == []
    assert world.calls_of("hyprctl") and not [
        line for line in world.calls_of("hyprctl") if "dispatch exec" in line]
    assert strings.SS_APPLIED_LATER in view.statuses
    groups = world.history.groups()
    assert len(groups) == 1
    (entry,) = groups[0].entries
    assert (entry.backend, entry.key, entry.before, entry.after) == (
        "screen-sleep", "idle.battery.dim", {"enabled": True, "minutes": 5},
        {"enabled": True, "minutes": 9})


def test_editing_the_active_set_rewrites_the_block_and_restarts_once(battery):
    c, view, timers = page(battery)
    c.edit("idle.battery.lock", {"enabled": True, "minutes": 11})
    c.edit("idle.battery.suspend", {"enabled": False, "minutes": 20})
    timers.advance(1.6, battery.loop)
    cfg = battery.cfg()
    expected = battery.ss.idle.render(battery.hypridle.read_text(), cfg["idle"]["battery"],
                                      "battery")
    assert battery.hypridle.read_text() == expected  # same as idle.render for the data
    assert "$lock_timeout" in battery.block() and "660" in battery.block()
    assert "suspend_timeout" not in battery.block()
    assert len(battery.calls_of("pkill")) == 1
    assert ["hyprctl dispatch exec hypridle"] == [
        line for line in battery.calls_of("hyprctl") if "dispatch" in line]
    assert len(battery.history.groups()) == 1  # two fields within 1.5 s: one action
    assert strings.SS_APPLIED.format(profile=strings.SS_PROFILES["battery"]) in view.statuses


def test_power_is_asked_again_right_before_applying(battery):
    c, _view, timers = page(battery)
    c.edit("idle.battery.dim", {"enabled": True, "minutes": 3})
    battery.power["ac"] = True  # plugged in while the change waited
    timers.advance(1.6, battery.loop)
    assert battery.cfg()["idle"]["battery"]["dim"]["minutes"] == 3
    assert battery.calls_of("pkill") == []


def test_preset_is_one_group_of_four_and_undo_restores_all(battery):
    c, view, _timers = page(battery)
    h0 = sha(battery.config)
    c.preset("battery", "movie")
    battery.loop.pump()
    steps = battery.cfg()["idle"]["battery"]
    assert [steps[s]["enabled"] for s in ctl.STEPS] == [False] * 4
    assert [steps[s]["minutes"] for s in ctl.STEPS] == [5, 7, 8, 20]  # minutes kept
    (group,) = battery.history.groups()
    assert len(group.entries) == 4
    assert group.label == strings.SS_PRESET_LABEL.format(
        preset=strings.SS_PRESETS["movie"], profile=strings.SS_PROFILES["battery"])
    assert "$" not in battery.block()  # every step off: no timeouts left in the block
    plan = battery.history.plan_undo_last()
    assert not plan.flagged
    battery.history.execute(plan)
    battery.loop.pump()
    assert sha(battery.config) == h0
    assert "$suspend_timeout" in battery.block()
    assert len(battery.calls_of("pkill")) == 2  # the preset, then the undo


def test_ordering_warning(world):
    c, view, _t = page(world)
    assert view.order == {"ac": False, "battery": False}
    c.edit("idle.ac.lock", {"enabled": True, "minutes": 30})  # lock before dim (60)
    assert view.order["ac"] is True
    c.edit("idle.ac.dim", {"enabled": False, "minutes": 60})  # off steps do not count
    assert view.order["ac"] is False


# ---- night filter ---------------------------------------------------------------

def test_schedule_switch_clears_manual_override(world):
    cfg = world.cfg()
    cfg["night"]["manual_override"] = True
    world.write_cfg(cfg)
    c, view, _t = page(world)
    assert view.values[ctl.OVERRIDE] is True  # the page shows "On schedule" off
    c.schedule_toggled(True)
    world.loop.pump()
    assert world.cfg()["night"]["manual_override"] is False
    assert diff(cfg, world.cfg()) == ["night.manual_override"]
    expected = world.backend.scheduled_temperature(world.cfg()["night"])
    assert f"hyprctl hyprsunset temperature {expected}" in world.calls_of("hyprctl")
    (group,) = world.history.groups()
    keys = {e.key: (e.before, e.after) for e in group.entries}
    assert keys["night.manual_override"] == (True, False)


def test_slider_series_is_one_group_and_turns_schedule_off(world):
    c, view, timers = page(world)
    assert view.values["night.current_temp"] == 4300
    c.slider_moved(5000)
    assert view.values[ctl.OVERRIDE] is True  # "On schedule" went off at once
    timers.advance(0.05, world.loop)
    c.slider_moved(4500)
    timers.advance(0.13, world.loop)
    temps = [x for x in world.calls_of("hyprctl") if re.search(r"temperature \d", x)]
    assert temps == ["hyprctl hyprsunset temperature 4500"]  # live, 120 ms, newest only
    assert world.cfg()["night"]["manual_override"] is False  # not before the series ends
    timers.advance(0.6, world.loop)
    assert world.cfg()["night"]["manual_override"] is True
    (group,) = world.history.groups()
    assert {(e.backend, e.key, e.before, e.after) for e in group.entries} == {
        ("night", "night.current_temp", 4300, 4500),
        ("screen-sleep", "night.manual_override", False, True)}
    assert group.label == strings.SS_LABEL_SLIDER
    # Undo: the temperature and the schedule come back together.
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert world.cfg()["night"]["manual_override"] is False
    assert "hyprctl hyprsunset temperature 4300" in world.calls_of("hyprctl")


@pytest.mark.parametrize("how", ["released", "focus-out"])
def test_release_or_focus_out_ends_the_series_at_once(world, how):
    c, _view, timers = page(world)
    c.slider_moved(3000)
    timers.advance(0.01, world.loop)
    c.slider_done()  # GestureClick released / EventControllerFocus leave call this
    world.loop.pump()
    assert "hyprctl hyprsunset temperature 3000" in world.calls_of("hyprctl")
    assert world.cfg()["night"]["manual_override"] is True
    assert len(world.history.groups()) == 1
    c.slider_done()  # a second end (both controllers fire) does nothing
    timers.advance(1, world.loop)
    assert len(world.history.groups()) == 1


def test_off_now(world):
    c, view, _t = page(world)
    c.off_now()
    world.loop.pump()
    assert "hyprctl hyprsunset temperature 6500" in world.calls_of("hyprctl")
    assert view.values["night.current_temp"] == 6500
    assert world.cfg()["night"]["manual_override"] is True
    assert len(world.history.groups()) == 1


def test_target_and_times_are_written_after_1_5_s(world):
    c, _view, timers = page(world)
    before = world.cfg()
    c.edit("night.target_temp", 3100)
    c.edit("night.on", [22, 30])
    timers.advance(1.6, world.loop)
    assert sorted(diff(before, world.cfg())) == [
        "night.on_hour", "night.on_minute", "night.target_temp"]
    assert world.calls_of("pkill") == []
    (group,) = world.history.groups()
    assert {e.key for e in group.entries} == {
        "night.target_temp", "night.on_hour", "night.on_minute"}


# ---- re-reading -----------------------------------------------------------------

def test_daemon_change_of_manual_override_is_shown_fresh(world):
    c, view, timers = page(world)
    assert view.values[ctl.OVERRIDE] is False
    cfg = world.cfg()
    cfg["night"]["manual_override"] = True
    world.write_cfg(cfg)  # the daemon, between two shows
    c.refresh()  # the next show
    world.loop.pump()
    assert view.values[ctl.OVERRIDE] is True
    cfg["night"]["manual_override"] = False
    world.write_cfg(cfg)  # and again while the page is open
    c.set_visible(True)
    timers.advance(5.0, world.loop)
    assert view.values[ctl.OVERRIDE] is False


def test_typed_value_survives_a_reread_before_it_is_written(world):
    c, view, timers = page(world)
    c.set_visible(True)
    timers.advance(4.0, world.loop)  # the next 5 s re-read is 1 s away
    c.edit("idle.ac.lock", {"enabled": True, "minutes": 33})
    cfg = world.cfg()
    cfg["night"]["target_temp"] = 3000  # something else changes meanwhile
    world.write_cfg(cfg)
    shows = len(view.shows)
    timers.advance(1.0, world.loop)  # the re-read fires before the 1.5 s write
    assert ("idle.ac.lock", {"enabled": True, "minutes": 70}) not in view.shows[shows:]
    assert ("night.target_temp", 3000) in view.shows[shows:]  # the rest is fresh
    timers.advance(0.6, world.loop)  # now the write
    assert world.cfg()["idle"]["ac"]["lock"]["minutes"] == 33
    assert world.cfg()["night"]["target_temp"] == 3000  # the other change survived


def test_focused_field_is_not_overwritten(world):
    c, view, _t = page(world)
    view.focus.add("idle.ac.dim")
    cfg = world.cfg()
    cfg["idle"]["ac"]["dim"]["minutes"] = 44
    world.write_cfg(cfg)
    view.shows.clear()
    c.refresh()
    world.loop.pump()
    assert not [s for s in view.shows if s[0] == "idle.ac.dim"]
    view.focus.clear()
    c.refresh()
    world.loop.pump()
    assert ("idle.ac.dim", {"enabled": True, "minutes": 44}) in view.shows


def test_change_younger_than_10_s_is_not_overwritten(world):
    c, view, timers = page(world)
    c.edit("idle.ac.dim", {"enabled": True, "minutes": 33})
    timers.advance(1.6, world.loop)
    assert world.cfg()["idle"]["ac"]["dim"]["minutes"] == 33
    assert "idle.ac.dim" not in c.pending  # written; only the 10 s rule is left
    cfg = world.cfg()
    cfg["idle"]["ac"]["dim"]["minutes"] = 50  # someone else, 2 s after the edit
    world.write_cfg(cfg)
    view.shows.clear()
    timers.advance(2.0)
    c.refresh()
    world.loop.pump()
    assert not [s for s in view.shows if s[0] == "idle.ac.dim"]
    timers.advance(7.0)  # 10.6 s after the edit
    c.refresh()
    world.loop.pump()
    assert ("idle.ac.dim", {"enabled": True, "minutes": 50}) in view.shows


def test_slider_is_not_moved_by_a_reread_during_a_series(world):
    c, view, timers = page(world)
    c.slider_moved(3500)
    (world.root / "temperature").write_text("4300\n")
    view.shows.clear()
    c.refresh()
    world.loop.pump()
    assert not [s for s in view.shows if s[0] == "night.current_temp"]
    timers.advance(11, world.loop)
    (world.root / "temperature").write_text("3900\n")  # the daemon's next ramp step
    c.refresh()
    world.loop.pump()
    assert view.values["night.current_temp"] == 3900


# ---- History --------------------------------------------------------------------

def test_undo_returns_config_to_its_previous_sha256(battery):
    c, _view, timers = page(battery)
    h0, block0 = sha(battery.config), battery.block()
    c.edit("idle.battery.dim", {"enabled": True, "minutes": 2})
    timers.advance(1.6, battery.loop)
    assert sha(battery.config) != h0
    battery.history.execute(battery.history.plan_undo_last())
    battery.loop.pump()
    assert sha(battery.config) == h0
    assert battery.block() == block0


def test_return_to_moment_restarts_hypridle_at_most_once(battery):
    c, _view, timers = page(battery)
    c.edit("idle.battery.dim", {"enabled": True, "minutes": 4})
    timers.advance(1.6, battery.loop)
    first = battery.history.groups()[0].id
    h1, block1 = sha(battery.config), battery.block()
    c.preset("battery", "eco")
    battery.loop.pump()
    c.edit("night.target_temp", 3300)
    c.edit("idle.battery.lock", {"enabled": True, "minutes": 40})
    timers.advance(1.6, battery.loop)
    c.slider_moved(3000)
    c.slider_done()
    battery.loop.pump()
    restarts = len(battery.calls_of("pkill"))
    plan = battery.history.plan_return_to(first)
    assert not plan.flagged
    result = battery.history.execute(plan)
    battery.loop.pump()
    assert not result.errors
    assert sha(battery.config) == h1
    assert battery.block() == block1
    assert len(battery.calls_of("pkill")) - restarts <= 1
    assert "hyprctl hyprsunset temperature 4300" in battery.calls_of("hyprctl")


def test_undo_after_an_outside_change_is_flagged(world):
    c, _view, timers = page(world)
    c.edit("night.target_temp", 3500)
    timers.advance(1.6, world.loop)
    cfg = world.cfg()
    cfg["night"]["target_temp"] = 3600
    world.write_cfg(cfg)
    plan = world.history.plan_undo_last()
    assert [g.id for g in plan.flagged] == [world.history.groups()[-1].id]


def test_undo_shows_the_value_at_once_despite_the_10_s_rule(world):
    c, view, timers = page(world)
    c.edit("idle.ac.dpms", {"enabled": True, "minutes": 99})
    timers.advance(1.6, world.loop)
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()  # the applier's write, then the page's re-read
    assert view.values["idle.ac.dpms"] == {"enabled": True, "minutes": 80}


# ---- not configured, not loadable -----------------------------------------------

def test_missing_config_is_never_created(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, config=False)
    try:
        assert w.backend.state() == ("missing", "")
        c, view, timers = page(w)
        assert view.setup == ("missing", "")
        c.edit("night.target_temp", 3000)
        timers.advance(2, w.loop)
        assert any(strings.SS_WRITE_FAILED.split(":")[0] in s for s in view.statuses)
        with pytest.raises(backend_mod.NotConfigured):
            w.backend.read([ctl.TARGET])
        assert not w.config.exists()
    finally:
        w.close()


def test_broken_modules_are_reported(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    try:
        other = backend_mod.Backend(w.loop.workers, tmp_path / "nowhere")
        state, detail = other.state()
        assert state == "error" and "not found" in detail
        view = FakeView()
        ctl.Controller(other, w.history, view, FakeTimers()).refresh()
        assert view.setup[0] == "error"
        assert other.old_window() is None
    finally:
        w.close()


# ---- stay awake -----------------------------------------------------------------

def helper_env(_w: World) -> dict:
    return dict(os.environ)  # HOME, XDG_* and PATH already point at the world


def test_caffeine_helper_runs_isolated_and_writes_its_pid_in_tmp(world):
    pid_file = world.state_dir / "caffeine.pid"
    run = subprocess.run([sys.executable, "-I", str(HELPER), "on", "--dir", str(world.ss_dir)],
                         cwd="/", env=helper_env(world), capture_output=True, text=True,
                         timeout=10)
    assert run.returncode == 0, run.stderr
    pid = int(pid_file.read_text())
    assert world.calls_of("systemd-inhibit")[0].startswith(
        "systemd-inhibit --what=idle:sleep")
    os.kill(pid, 0)  # alive, and not our child: the helper has exited
    run = subprocess.run([sys.executable, "-I", str(HELPER), "off", "--dir", str(world.ss_dir)],
                         cwd="/", env=helper_env(world), capture_output=True, text=True,
                         timeout=10)
    assert run.returncode == 0, run.stderr
    assert not pid_file.exists()
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        time.sleep(0.05)
    else:
        pytest.fail("systemd-inhibit stub still running")
    assert list(world.ss_dir.rglob("__pycache__")) == []


def test_caffeine_helper_imports_only_the_standard_library():
    tree = ast.parse(HELPER.read_text())
    names = {alias.name.split(".")[0] for node in ast.walk(tree)
             if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module}
    assert names <= set(sys.stdlib_module_names), names
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level]


def test_caffeine_helper_reports_bad_usage_and_missing_modules(world, tmp_path):
    run = subprocess.run([sys.executable, "-I", str(HELPER), "maybe"], capture_output=True,
                         text=True, timeout=10)
    assert run.returncode == 2
    run = subprocess.run([sys.executable, "-I", str(HELPER), "on", "--dir",
                          str(tmp_path / "none")], capture_output=True, text=True, timeout=10)
    assert run.returncode == 1 and "screen-sleep modules" in run.stderr


def test_caffeine_switch_through_the_page_and_undo(world):
    c, view, _t = page(world)
    assert view.values["caffeine"] is False
    c.caffeine_toggled(True)
    world.loop.pump()
    assert (world.state_dir / "caffeine.pid").exists()
    assert view.values["caffeine"] is True
    (group,) = world.history.groups()
    assert (group.entries[0].key, group.entries[0].after) == ("caffeine", True)
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert not (world.state_dir / "caffeine.pid").exists()
    assert view.values["caffeine"] is False


# ---- one apply at a time --------------------------------------------------------

def test_never_two_apply_profile_at_once(battery, monkeypatch):
    lock = threading.Lock()
    state = {"now": 0, "max": 0, "calls": 0}
    real = battery.ss.idle.apply_profile

    def counted(cfg, power):
        with lock:
            state["now"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["now"])
        try:
            time.sleep(0.02)
            return real(cfg, power)
        finally:
            with lock:
                state["now"] -= 1

    monkeypatch.setattr(battery.ss.idle, "apply_profile", counted)
    applier = battery.history.applier("screen-sleep")

    def hammer(k):
        for i in range(5):
            battery.backend.queue_write({"idle.battery.dim": {"enabled": True,
                                                              "minutes": 1 + k * 10 + i}})
            applier.apply({"idle.battery.lock": {"enabled": True, "minutes": 2 + i}})

    threads = [threading.Thread(target=hammer, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    battery.loop.pump(timeout=60)
    assert state["max"] == 1
    assert 1 <= state["calls"] < 40  # coalesced: far fewer restarts than writes
    cfg = battery.cfg()["idle"]["battery"]
    expected = battery.ss.idle.build_managed_block(cfg, "battery").strip()
    assert battery.block() == expected


# ---- the old window's abilities, the limits, search ----------------------------

def test_readme_maps_every_ability_of_the_old_window_to_a_widget():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d) \| ([^|]+) \| ([^|]+) \|$", text, re.M)
    points = {int(n): re.findall(r"`([^`]+)`", ids) for n, _what, ids in rows}
    assert sorted(points) == [1, 2, 3, 4, 5, 6]
    for n, ids in points.items():
        assert ids, n
        for widget_id in ids:
            assert widget_id in ctl.WIDGETS, (n, widget_id)
    for n, _what, ids in ctl.OLD_WINDOW:
        assert set(ids) <= set(points[n]), n
    assert "night.target" in points[4] and "night.schedule" in points[4]


def test_limits_match_screen_sleep(world):
    common = world.ss.common
    assert (ctl.MIN_TEMP, ctl.MAX_TEMP, ctl.SLEEP_MARK_TEMP) == (
        common.MIN_TEMP, common.MAX_TEMP, common.NIGHT_MARK_TEMP)
    assert (ctl.MIN_MINUTES, ctl.MAX_MINUTES) == (common.MIN_MINUTES, common.MAX_MINUTES)
    assert (ctl.RAMP_STEP, ctl.RAMP_INTERVAL_MIN) == (common.RAMP_STEP, common.RAMP_INTERVAL_MIN)
    assert ctl.STEPS == common.STEPS and ctl.PROFILES == common.PROFILES
    assert set(strings.SS_PRESETS.values()) == set(common.PRESETS)
    assert strings.SS_STEPS == common.STEP_LABELS
    assert set(ctl.fields_from_config(common.default_config())) >= {
        f"idle.{p}.{s}" for p in ctl.PROFILES for s in ctl.STEPS}


@pytest.mark.parametrize("case", load_json("search_cases.json")["top_row"],
                         ids=lambda c: c["row"])
def test_search_lands_on_the_right_row(case):
    from settings_hub import search

    rows = [r for r in search.search(case["query"]) if r.page_id == case["page"] and r.row_id]
    assert rows and rows[0].row_id == case["row"]


def test_every_searchable_row_is_registered_by_the_page():
    """The GUI test checks the built page; this catches a typo without GTK."""
    source = (ROOT / "settings_hub" / "pages" / "screen_sleep.py").read_text()
    registered = set(re.findall(r'self\.rows\["([a-z-]+)"\]', source)) | set(ctl.PROFILES)
    assert set(strings.SS_ROWS) <= registered
    assert set(re.findall(r'row_id="([a-z-]+)"', source)) <= set(strings.SS_ROWS)


def test_fields_and_paths_round_trip():
    cfg = json.loads((SS_FIXTURES / "config.json").read_text())
    fields = ctl.fields_from_config(cfg)
    rebuilt = copy.deepcopy(cfg)
    for key, value in fields.items():
        for path, v in ctl.to_paths(key, value).items():
            backend_mod.set_path(rebuilt, path, v)
            assert ctl.field_of(path) == key
    assert rebuilt == cfg
    with pytest.raises(KeyError):
        backend_mod.set_path(rebuilt, "night.nope", 1)


def test_loader_is_what_the_backend_uses(world):
    assert world.backend.ss.common.__name__ == f"{loader.SS_PACKAGE}.common"
    assert "common" not in sys.modules


def test_isolation_catches_absolute_programs(world):
    """The guard that keeps tests away from the real /usr/bin/pkill."""
    run = world.ss.idle.subprocess.run(["/usr/bin/pkill", "-x", "hypridle"])
    assert run.returncode == 0 and world.calls_of("pkill") == ["pkill -x hypridle"]
    with pytest.raises(AssertionError, match="real program"):
        world.ss.idle.subprocess.run(["/usr/bin/true"])
    assert "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ
    assert str(world.ss.idle.HYPRIDLE_CONF).startswith(str(world.root))
