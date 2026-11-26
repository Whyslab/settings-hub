"""The Panel page's backend and controller without GTK: HyprPanel's config.json."""

import json
import os
import threading

import pytest

from settings_hub import strings
from settings_hub.backends import notifications as nb
from settings_hub.backends import panel as pb
from settings_hub.controllers import panel as ctl
from settings_hub.history import History

LAYOUT = {"*": {"left": ["dashboard", "workspaces"], "middle": ["clock"],
                "right": ["volume", "custom/timer", "power"]}}


class Now:
    def submit(self, _name, fn, on_done=None, key=None):
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        if on_done:
            on_done(result, error)


class Later:
    def __init__(self):
        self.jobs = []

    def submit(self, _name, fn, on_done=None, key=None):
        self.jobs = [j for j in self.jobs if j[0] != key or key is None] + [(key, fn, on_done)]

    def run(self):
        while self.jobs:
            _key, fn, on_done = self.jobs.pop(0)
            try:
                result, error = fn(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            if on_done:
                on_done(result, error)


class View:
    def __init__(self):
        self.shown = []
        self.said = []

    def show_panel(self, info, pending):
        self.shown.append((info, pending))

    def status(self, text):
        self.said.append(text)


def no_run(argv):
    return 1, ""


@pytest.fixture
def conf(tmp_path):
    path = tmp_path / "hyprpanel" / "config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "theme.font.name": "JetBrainsMono Nerd Font", "theme.font.size": "10px",
        "bar.layouts": LAYOUT, "theme.bar.floating": True,
        "theme.bar.buttons.background": "#123456", "menus.clock.weather.unit": "metric",
        "bar.clock.format": "%H:%M %d %a",
    }, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)
    (path.parent / "modules.json").write_text(json.dumps(
        {"custom/timer": {}, "custom/cpu": {}, "bad name": {}}))
    return path


def make(conf, workers=None):
    backend = pb.Backend(workers or Now(), runner=no_run, config=conf)
    history = History()
    pb.register(history, backend)
    view = View()
    return ctl.Controller(backend, history, view), history, view


# ---- cleaning ---------------------------------------------------------------------


@pytest.mark.parametrize("key, value", [
    (pb.LOCATION, "left"), (pb.AUTOHIDE, "always"), (pb.FLOATING, 1),
    (pb.OPACITY, "50"), (pb.OPACITY, True), (pb.CLOCK, ""), (pb.CLOCK, "a\nb"),
    (pb.CLOCK, "x" * 61), (pb.FONT, 'Evil"; } * { color: red'), (pb.FONT, "A\\B"),
    (pb.FONT_SIZE, "10"), (pb.FONT_SIZE, "big"), (pb.FONT_SIZE, "10px; color:red"),
    (pb.LAYOUTS, []), (pb.LAYOUTS, {}), (pb.LAYOUTS, {"bad key!": {"left": []}}),
    (pb.LAYOUTS, {"*": {"left": ["$(rm -rf ~)"]}}), (pb.LAYOUTS, {"*": {"left": "clock"}}),
    (pb.LAYOUTS, {"*": {"left": ["clock"] * 61}}),
])
def test_clean_refuses(key, value):
    with pytest.raises(ValueError):
        pb.clean(key, value)


def test_clean_clamps_and_keeps():
    assert pb.clean(pb.OPACITY, 140) == 100 and pb.clean(pb.OPACITY, -3) == 0
    assert pb.clean(pb.SCALING, 10) == pb.SCALING_MIN
    assert pb.clean(pb.FONT_SIZE, "1.2rem") == "1.2rem"
    assert pb.clean(pb.LAYOUTS, LAYOUT) == LAYOUT
    with pytest.raises(KeyError):
        pb.clean("theme.bar.buttons.background", "#fff")


def test_size_px():
    assert pb.size_px("10px") == 10 and pb.size_px("1.2rem") == pytest.approx(19.2)
    assert pb.size_px("12pt") == 16 and pb.size_px("huge") is None
    assert pb.px_text(3) == "6px" and pb.px_text(13.0) == "13px"


# ---- the file ----------------------------------------------------------------------


def test_probe_reads_defaults_and_customs(conf):
    info = pb.Backend(Now(), runner=no_run, config=conf).probe()
    assert info.found and not info.running
    assert info.values[pb.LOCATION] == "top" and info.values[pb.FLOATING] is True
    assert info.values[pb.CLOCK] == "%H:%M %d %a"
    assert info.custom == ["custom/cpu", "custom/timer"]  # "bad name" is not a module
    assert info.other_monitors == []


def test_write_keeps_other_keys_mode_and_unicode(conf):
    raw = json.loads(conf.read_text())
    raw["dashboard.name"] = "Богдан"
    conf.write_text(json.dumps(raw, ensure_ascii=False))
    os.chmod(conf, 0o600)
    backend = pb.Backend(Now(), runner=no_run, config=conf)
    backend.set(pb.LOCATION, "bottom")
    after = json.loads(conf.read_text())
    assert after["theme.bar.location"] == "bottom"
    assert after["theme.bar.buttons.background"] == "#123456"  # the theme's colours stay
    assert after["dashboard.name"] == "Богдан" and "Богдан" in conf.read_text()
    assert (conf.stat().st_mode & 0o777) == 0o600
    backend.set(pb.LOCATION, "top")  # the default: the key goes, HyprPanel's own applies
    assert "theme.bar.location" not in json.loads(conf.read_text())


def test_broken_file_is_never_overwritten(conf):
    conf.write_text("{ not json")
    backend = pb.Backend(Now(), runner=no_run, config=conf)
    with pytest.raises(ValueError):
        backend.set(pb.LOCATION, "bottom")
    assert conf.read_text() == "{ not json"


def test_symlinked_config_stays_a_symlink(tmp_path, conf):
    real = tmp_path / "real.json"
    real.write_text(conf.read_text())
    conf.unlink()
    conf.symlink_to(real)
    pb.Backend(Now(), runner=no_run, config=conf).set(pb.FLOATING, False)
    assert conf.is_symlink() and "theme.bar.floating" not in json.loads(real.read_text())


def test_three_backends_share_the_lock(conf, monkeypatch):
    """Two writers at once: without the shared lock one change is lost."""
    panel = pb.Backend(Now(), runner=no_run, config=conf)
    notif = nb.Backend(Now(), runner=no_run, config=conf)
    original = nb.Backend._load
    gate = threading.Barrier(2, timeout=1)

    def slow_load(self):
        raw = original(self)
        try:
            gate.wait()  # both read before either writes, unless the lock serialises them
        except threading.BrokenBarrierError:
            pass
        return raw

    monkeypatch.setattr(nb.Backend, "_load", slow_load)
    threads = [threading.Thread(target=panel.set, args=(pb.LOCATION, "bottom")),
               threading.Thread(target=notif.write, args=({nb.POSITION: "top left"},))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    monkeypatch.setattr(nb.Backend, "_load", original)
    after = json.loads(conf.read_text())
    assert after["theme.bar.location"] == "bottom" and after[nb.POSITION] == "top left"


# ---- layouts --------------------------------------------------------------------------


def test_sections_of_and_with_sections():
    assert pb.sections_of(LAYOUT)["right"] == ["volume", "custom/timer", "power"]
    default = pb.sections_of(pb.DEFAULT_LAYOUTS)  # no "*": monitor 0's
    assert "systray" in default["right"]
    new = pb.with_sections(pb.DEFAULT_LAYOUTS, {"left": ["clock"], "middle": [], "right": []})
    assert new["0"] == {"left": ["clock"], "middle": [], "right": []}  # monitor 0 edited
    assert new["1"] == pb.DEFAULT_LAYOUTS["1"] and new["2"] == pb.DEFAULT_LAYOUTS["2"]
    both = {"*": LAYOUT["*"], "1": {"left": ["clock"]}}
    kept = pb.with_sections(both, {"left": [], "middle": [], "right": ["clock"]})
    assert kept["1"] == {"left": ["clock"]} and kept["*"]["right"] == ["clock"]


def test_other_monitors_are_reported(conf):
    raw = json.loads(conf.read_text())
    raw["bar.layouts"]["1"] = {"left": ["clock"], "middle": [], "right": []}
    conf.write_text(json.dumps(raw))
    info = pb.Backend(Now(), runner=no_run, config=conf).probe()
    assert info.other_monitors == ["1"]


def test_move_within_and_across_sections(conf):
    c, history, _view = make(conf)
    c.refresh()
    c.move("right", 0, 1)  # volume below custom/timer
    assert c.sections()["right"] == ["custom/timer", "volume", "power"]
    c.move("middle", 0, -1)  # clock past the top of the middle: end of the left
    assert c.sections()["left"] == ["dashboard", "workspaces", "clock"]
    assert c.sections()["middle"] == []
    c.move("left", 0, -1)  # nothing before the left section
    c.move("right", 2, 1)  # nothing after the right section
    on_disk = json.loads(conf.read_text())["bar.layouts"]["*"]
    assert on_disk["left"] == ["dashboard", "workspaces", "clock"]
    assert [g.entries[0].key for g in history.groups()] == ["bar.layouts", "bar.layouts"]


def test_add_remove_and_available(conf):
    c, history, view = make(conf)
    c.refresh()
    avail = c.available()
    assert "custom/cpu" in avail and "custom/timer" not in avail and "clock" not in avail
    c.add("custom/cpu", "left")
    assert c.sections()["left"][-1] == "custom/cpu"
    c.add("clock", "right")  # already there
    assert view.said[-1] == strings.PANEL_ALREADY.format(name=ctl.module_name("clock"))
    c.remove("right", 1)
    assert "custom/timer" not in json.loads(conf.read_text())["bar.layouts"]["*"]["right"]
    c.add("bad name", "left")  # not a module name: nothing happens
    assert len(history.groups()) == 2


def test_undo_restores_the_layout(conf):
    c, history, _view = make(conf)
    c.refresh()
    c.remove("left", 0)
    plan = history.plan_undo_last()
    history.execute(plan)
    assert json.loads(conf.read_text())["bar.layouts"] == LAYOUT


def test_first_change_without_layouts_edits_monitor_0(conf):
    raw = json.loads(conf.read_text())
    del raw["bar.layouts"]
    conf.write_text(json.dumps(raw))
    c, history, view = make(conf)
    c.refresh()
    assert view.shown[-1][0].other_monitors == ["1", "2"]
    c.remove("right", 0)  # HyprPanel's default for monitor 0, minus "volume"
    layouts = json.loads(conf.read_text())["bar.layouts"]
    assert "volume" not in layouts["0"]["right"]
    assert layouts["1"] == pb.DEFAULT_LAYOUTS["1"]  # the other screens keep theirs
    history.execute(history.plan_undo_last())  # back to no key at all: HyprPanel's default
    assert "bar.layouts" not in json.loads(conf.read_text())


# ---- the controller -------------------------------------------------------------------


def test_quick_changes_chain_in_history(conf):
    c, history, _view = make(conf, Later())
    c.backend.workers.run()  # nothing yet
    c.set(pb.OPACITY, 40)
    c.set(pb.OPACITY, 70)
    c.backend.workers.run()
    pairs = [(g.entries[0].before, g.entries[0].after) for g in history.groups()]
    assert pairs == [(100, 40), (40, 70)]
    assert c.pending == set()


def test_bad_value_is_refused_without_a_write(conf):
    before = conf.read_text()
    c, history, view = make(conf)
    c.set(pb.LOCATION, "left")
    assert conf.read_text() == before and view.said == [strings.PANEL_BAD_VALUE]
    assert history.groups() == []


def test_same_value_logs_nothing(conf):
    c, history, _view = make(conf)
    c.refresh()
    c.set(pb.CLOCK, "%H:%M %d %a")
    assert history.groups() == []


def test_module_names():
    assert ctl.module_name("clock") == strings.PANEL_MODULES["clock"]
    assert ctl.module_name("custom/cpu") == strings.PANEL_CUSTOM.format(name="cpu")
    assert ctl.module_name("whatever") == "whatever"
    assert set(pb.BUILTIN) <= set(strings.PANEL_MODULES)


# ---- restarting --------------------------------------------------------------------


def test_restart_waits_for_the_old_panel(tmp_path, conf, monkeypatch):
    script = tmp_path / "hyprpanel-fresh.sh"
    script.write_text("#!/bin/sh\n")
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["busctl", "--user"]:
            return 0, "PID=4242\nComm=gjs\n"
        return 0, "ok"

    backend = pb.Backend(Now(), runner=runner, config=conf, restart_script=script)
    alive = {"n": 3}
    killed = []
    real_exists = pb.Path.exists

    def exists(self):
        if str(self) == "/proc/4242":
            alive["n"] -= 1
            return alive["n"] > 0
        return real_exists(self)

    monkeypatch.setattr(pb.Path, "exists", exists)
    monkeypatch.setattr(pb.Path, "read_bytes",
                        lambda self: b"gjs\0-m\0/run/user/1000/hyprpanel-fresh.js\0")
    monkeypatch.setattr(pb.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    backend.restart()
    assert killed == [(4242, 15)] and alive["n"] == 0  # waited until it was gone
    dispatch = [c for c in calls if c[:2] == ["hyprctl", "dispatch"]]
    assert dispatch == [["hyprctl", "dispatch", f'hl.dsp.exec_cmd("{script}")']]


class FakePanel:
    """busctl and hyprctl as the restart sees them; /proc patched by the test."""

    def __init__(self, owner=4242, after_start=5151, answer="ok"):
        self.owner = owner
        self.after_start = after_start
        self.answer = answer
        self.started = False
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["busctl", "--user"]:
            pid = self.after_start if self.started else self.owner
            return (0, f"PID={pid}\n") if pid else (1, "")
        if argv[:2] == ["hyprctl", "dispatch"]:
            self.started = self.answer == "ok"
            return 0, self.answer
        return 1, ""


def patch_proc(monkeypatch, cmdlines, gone=()):
    real_exists = pb.Path.exists

    def exists(self):
        name = str(self)
        if name.startswith("/proc/") and name.count("/") == 2:
            return name.rsplit("/", 1)[1] not in gone
        return real_exists(self)

    def read_bytes(self):
        pid = str(self).split("/")[2]
        if pid not in cmdlines:
            raise OSError
        return cmdlines[pid]

    monkeypatch.setattr(pb.Path, "exists", exists)
    monkeypatch.setattr(pb.Path, "read_bytes", read_bytes)
    monkeypatch.setattr(pb.Backend, "_other_panels",
                        staticmethod(lambda: [int(p) for p, c in cmdlines.items()
                                              if b"gjs" in c and b"hyprpanel" in c]))
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)


PANEL = b"gjs\0-m\0/run/user/1000/hyprpanel-fresh.js\0"


def script_in(tmp_path):
    script = tmp_path / "hyprpanel-fresh.sh"
    script.write_text("#!/bin/sh\n")
    return script


def test_restart_kills_only_the_panel(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242)
    patch_proc(monkeypatch, {"4242": b"/usr/bin/dunst\0", "5151": PANEL}, gone={"4242"})
    monkeypatch.setattr(pb.Backend, "_other_panels", staticmethod(lambda: []))  # none yet
    killed = []
    monkeypatch.setattr(pb.os, "kill", lambda pid, sig: killed.append(pid))
    backend = pb.Backend(Now(), runner=fake, config=conf, restart_script=script_in(tmp_path))
    backend.restart()  # someone else owns the name and no panel runs: start it, kill nobody
    assert killed == [] and fake.started


def test_restart_refuses_a_second_panel(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242)
    patch_proc(monkeypatch, {"4242": b"/usr/bin/dunst\0", "777": PANEL})
    backend = pb.Backend(Now(), runner=fake, config=conf, restart_script=script_in(tmp_path))
    with pytest.raises(RuntimeError):
        backend.restart()
    assert not fake.started


def test_restart_reports_a_failed_start(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242, answer="error: attempt to call a nil value")
    patch_proc(monkeypatch, {"4242": PANEL}, gone={"4242"})
    monkeypatch.setattr(pb.os, "kill", lambda pid, sig: None)
    backend = pb.Backend(Now(), runner=fake, config=conf, restart_script=script_in(tmp_path))
    with pytest.raises(RuntimeError, match="nil value"):
        backend.restart()


def test_other_panels_needs_gjs_itself(tmp_path):
    proc = tmp_path / "proc"
    for pid, cmd in (("10", b"/usr/bin/gjs\0-m\0/run/user/1000/hyprpanel-fresh.js\0"),
                     ("11", b"vim\0gjs-hyprpanel-notes.txt\0"),
                     ("12", b"grep\0gjs\0hyprpanel\0"), ("13", b"gjs-console\0hyprpanel-app\0")):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "cmdline").write_bytes(cmd)
    (proc / "self").mkdir()
    assert sorted(pb.Backend._other_panels(proc)) == [10, 13]


def test_restart_waits_until_the_panel_is_back(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242, after_start=0)  # started, but never shows up
    patch_proc(monkeypatch, {"4242": b"/usr/bin/dunst\0"}, gone={"4242"})
    monkeypatch.setattr(pb.os, "kill", lambda pid, sig: None)
    clock = iter(range(0, 10000, 1))
    monkeypatch.setattr(pb.time, "monotonic", lambda: next(clock))
    backend = pb.Backend(Now(), runner=fake, config=conf, restart_script=script_in(tmp_path))
    with pytest.raises(RuntimeError, match="did not come back"):
        backend.restart()


def test_restart_when_the_panel_just_exited(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242)
    patch_proc(monkeypatch, {"4242": PANEL, "5151": PANEL}, gone={"4242"})

    def kill(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(pb.os, "kill", kill)
    backend = pb.Backend(Now(), runner=fake, config=conf, restart_script=script_in(tmp_path))
    backend.restart()
    assert fake.started


def test_restart_falls_back_to_a_conf_hyprland(tmp_path, conf, monkeypatch):
    fake = FakePanel(owner=4242)
    patch_proc(monkeypatch, {"4242": PANEL, "5151": PANEL}, gone={"4242"})
    monkeypatch.setattr(pb.os, "kill", lambda pid, sig: None)
    answers = iter(["Invalid dispatcher", "ok"])
    real = fake.__call__

    def runner(argv):
        if argv[:2] == ["hyprctl", "dispatch"]:
            fake.calls.append(argv)
            answer = next(answers)
            fake.started = answer == "ok"
            return 0, answer
        return real(argv)

    backend = pb.Backend(Now(), runner=runner, config=conf, restart_script=script_in(tmp_path))
    backend.restart()
    dispatches = [c for c in fake.calls if c[:2] == ["hyprctl", "dispatch"]]
    assert dispatches[0][2].startswith("hl.dsp.exec_cmd(")
    assert dispatches[1][2:] == ["exec", str(script_in(tmp_path))]


def test_restart_without_script_fails(tmp_path, conf):
    backend = pb.Backend(Now(), runner=no_run, config=conf,
                         restart_script=tmp_path / "missing.sh")
    with pytest.raises(RuntimeError):
        backend.restart()


def test_numbered_layouts_are_kept(conf):
    raw = json.loads(conf.read_text())
    raw["bar.layouts"] = {"0": {"left": ["clock"], "middle": [], "right": []},
                          "1": {"left": ["media"], "middle": [], "right": []}}
    conf.write_text(json.dumps(raw))
    c, _history, _view = make(conf)
    c.refresh()
    c.add("volume", "right")
    layouts = json.loads(conf.read_text())["bar.layouts"]
    assert layouts["0"]["right"] == ["volume"] and layouts["1"]["left"] == ["media"]


def test_unreadable_layout_is_never_replaced(conf):
    raw = json.loads(conf.read_text())
    raw["bar.layouts"] = {"*": {"left": ["custom/my module"], "middle": [], "right": []}}
    conf.write_text(json.dumps(raw))
    before = conf.read_text()
    c, history, view = make(conf)
    c.refresh()
    assert view.shown[-1][0].layouts_ok is False
    c.remove("left", 0)
    c.add("clock", "left")
    assert conf.read_text() == before and history.groups() == []
    assert view.said[-1] == strings.PANEL_LAYOUT_UNREADABLE
    with pytest.raises(ValueError):  # nor through History's applier
        c.backend.apply({pb.LAYOUTS: LAYOUT})
    assert conf.read_text() == before
    c.set(pb.LOCATION, "bottom")  # the rest of the page still works
    assert json.loads(conf.read_text())["theme.bar.location"] == "bottom"


def test_stale_read_keeps_a_move_in_flight(conf):
    c, history, _view = make(conf, Later())
    c.refresh()
    c.backend.workers.run()
    c.refresh()  # a read queued before the move: it sees the old layout
    c.move("right", 0, 1)
    probe = [j for j in c.backend.workers.jobs if j[0] == "probe"][0]
    c.backend.workers.jobs.remove(probe)
    c._read(probe[1](), None)  # it arrives while the move is still queued
    c.move("right", 1, 1)  # volume on: from the moved layout, not the old one
    c.backend.workers.run()
    on_disk = json.loads(conf.read_text())["bar.layouts"]["*"]["right"]
    assert on_disk == ["custom/timer", "power", "volume"]
    pairs = [(g.entries[0].before["*"]["right"], g.entries[0].after["*"]["right"])
             for g in history.groups()]
    assert pairs[0][1] == pairs[1][0]  # A->B, B->C: a chain, nothing lost
