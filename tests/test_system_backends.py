"""Sound, network, power and modes without GTK: parsers, History, honest logging."""

import json
import threading
from dataclasses import replace

import pytest

from settings_hub import history as hist
from settings_hub import modes as hub_modes
from settings_hub.backends import audio, network, power
from settings_hub.controllers import audio as audio_ctl
from settings_hub.controllers import modes as mode_ctl
from settings_hub.controllers import power as power_ctl
from settings_hub.workers import Workers

SOURCES = json.dumps([
    {"name": "alsa_output.usb.analog-stereo.monitor", "description": "Monitor of G435",
     "monitor_source": "alsa_output.usb.analog-stereo", "mute": False,
     "volume": {"l": {"value_percent": "100%"}},
     "properties": {"device.class": "monitor"}},
    {"name": "alsa_input.usb.mono-fallback", "description": "G435", "monitor_source": "",
     "mute": True, "volume": {"mono": {"value_percent": "60%"}},
     "properties": {"device.class": "sound"}},
])
SINKS = json.dumps([
    {"name": "alsa_output.usb.analog-stereo", "description": "G435", "mute": False,
     "monitor_source": "alsa_output.usb.analog-stereo.monitor",
     "volume": {"l": {"value_percent": "40%"}, "r": {"value_percent": "45%"}},
     "properties": {"device.class": "sound"}},
])


def pactl(argv):
    answers = {
        "pactl -f json list sinks": SINKS,
        "pactl -f json list sources": SOURCES,
        "pactl get-default-sink": "alsa_output.usb.analog-stereo\n",
        "pactl get-default-source": "alsa_input.usb.mono-fallback\n",
    }
    return 0, answers.get(" ".join(argv), ""), ""


def test_monitors_are_not_offered_as_microphones():
    probe = audio.Backend(None, runner=pactl).probe()
    assert [d.name for d in probe.sources] == ["alsa_input.usb.mono-fallback"]
    assert [d.name for d in probe.sinks] == ["alsa_output.usb.analog-stereo"]  # has monitor_source
    assert probe.sinks[0].volume == 45
    assert probe.sources[0].mute is True


def test_a_monitor_in_use_stays_visible_so_it_can_be_changed():
    def run(argv):
        if argv[1:] == ["get-default-source"]:
            return 0, "alsa_output.usb.analog-stereo.monitor\n", ""
        return pactl(argv)

    probe = audio.Backend(None, runner=run).probe()
    assert [d.name for d in probe.sources] == ["alsa_output.usb.analog-stereo.monitor",
                                               "alsa_input.usb.mono-fallback"]


def test_audio_history_keys_survive_dots_in_device_names():
    b = audio.Backend(None, runner=pactl)
    key = audio.key_volume("sink", "alsa_output.usb.analog-stereo")
    assert b.read([key, audio.DEFAULT_KEYS["source"]]) == {
        key: 45, audio.DEFAULT_KEYS["source"]: "alsa_input.usb.mono-fallback"}
    calls = []
    b.run = lambda argv: (calls.append(argv), (0, "", ""))[1]
    b.apply({key: 30})
    assert calls == [["pactl", "set-sink-volume", "alsa_output.usb.analog-stereo", "30%"]]


def test_a_refused_audio_change_raises_for_history():
    b = audio.Backend(None, runner=lambda _a: (1, "", "no such device"))
    with pytest.raises(RuntimeError, match="no such device"):
        b.apply({audio.DEFAULT_KEYS["sink"]: "gone"})


def test_nmcli_escapes_and_saved_wifi_only():
    wifi = network.parse_wifi("*:Дом\\:5G:72:WPA2\n :Сосед:38:WPA2\n :::\n")
    assert [(w.ssid, w.signal, w.in_use) for w in wifi] == [
        ("Дом:5G", 72, True), ("Сосед", 38, False)]
    saved = network.parse_saved("Дом\\:5G:802-11-wireless:yes\nlan:802-3-ethernet:yes\n")
    assert [(s.name, s.active) for s in saved] == [("Дом:5G", True)]


def test_bluetooth_and_tailscale_parsers():
    assert [d.name for d in network.parse_bluetooth_devices("Device AA:BB Мои наушники\njunk\n")] \
        == ["Мои наушники"]
    assert network.parse_tailscale('{"BackendState":"Running","TailscaleIPs":["100.1.1.1"]}') \
        == ("Running", ["100.1.1.1"])
    assert network.parse_tailscale("not json") == ("", [])


def test_undo_to_no_connection_with_nothing_active_sends_no_change():
    calls = []
    b = network.Backend(None, runner=lambda a: (calls.append(a), (0, "", ""))[1])
    b.apply({network.WIFI_CONNECTION: ""})
    assert not any("up" in c or "down" in c for c in calls)


def test_power_checks_what_it_is_given():
    calls = []
    b = power.Backend(None, runner=lambda a: (calls.append(a), (0, "", ""))[1])
    assert b.set_profile("turbo")[0] is False and calls == []
    assert b.set_brightness(0)[0] is True
    assert calls == [["brightnessctl", "set", "1%"]]  # never a black screen


class SyncWorkers:
    def submit(self, _name, fn, on_done=None, key=None):
        result = fn()
        if on_done is not None:
            on_done(result, None)


def test_undo_reads_only_what_it_needs_and_does_not_wait(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda _name: "/bin/x")
    calls = []

    def run(argv):
        calls.append(argv)
        return 0, "enabled\n" if argv[1:] == ["radio", "wifi"] else "", ""

    b = network.Backend(None, runner=run)
    assert b.read([network.WIFI_RADIO]) == {network.WIFI_RADIO: True}
    assert calls == [["nmcli", "radio", "wifi"]]
    calls.clear()
    b.apply({network.WIFI_CONNECTION: "Дом"})
    assert calls == [["nmcli", "-w", "0", "connection", "up", "Дом"]]


def test_undoing_a_first_connection_takes_it_down(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda _name: "/bin/x")
    calls = []

    def run(argv):
        calls.append(argv)
        return 0, "Дом:802-11-wireless:yes\n", ""

    network.Backend(None, runner=run).apply({network.WIFI_CONNECTION: ""})
    assert calls[-1] == ["nmcli", "-w", "0", "connection", "down", "Дом"]


def test_connected_to_nothing_is_an_answer(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda _name: "/bin/x")
    b = network.Backend(None, runner=lambda _argv: (0, "Дом:802-11-wireless:no\n", ""))
    assert b.read([network.WIFI_CONNECTION]) == {network.WIFI_CONNECTION: ""}


class NetView:
    def __init__(self):
        self.messages, self.later = [], []

    def status(self, text):
        self.messages.append(text)

    def refresh_later(self, seconds):
        self.later.append(seconds)

    def show_network(self, _info):
        pass


def test_a_slow_connection_is_logged_and_looked_at_again(monkeypatch):
    from settings_hub.controllers import network as net_ctl

    monkeypatch.setattr(network.shutil, "which", lambda _name: "/bin/x")
    b = network.Backend(SyncWorkers(), runner=lambda _argv: (3, "", "Timeout 8 sec expired"))
    c = net_ctl.Controller(b, Log(), NetView())
    c.refresh = lambda: None
    c.connect("Дом")
    assert [(i[3], i[4]) for i in c.history.items] == [("", "Дом")]
    assert "Не удалось" not in c.view.messages[-1] and "Дом" in c.view.messages[-1]
    assert c.view.later == [network.SETTLE_S]


def test_undo_of_a_first_connection_fails_when_nothing_can_be_read(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda _name: "/bin/x")
    b = network.Backend(None, runner=lambda _argv: (8, "", "NetworkManager is not running"))
    with pytest.raises(RuntimeError):
        b.apply({network.WIFI_CONNECTION: ""})


def test_power_reads_only_what_it_is_asked():
    calls = []

    def run(argv):
        calls.append(argv)
        return 0, "500", ""

    power.Backend(None, runner=run).read([power.BRIGHTNESS_KEY])
    assert calls == [["brightnessctl", "get"], ["brightnessctl", "max"]]


class SliderView:
    def __init__(self):
        self.messages, self.shown = [], []

    def status(self, text):
        self.messages.append(text)

    def show_brightness(self, percent):
        self.shown.append(percent)

    def show_volume(self, _kind, percent):
        self.shown.append(percent)


class Log:
    def __init__(self):
        self.items = []

    def record(self, items):
        self.items.extend(items)


def brightness(works=True):
    state = {"now": 50}

    def run(argv):
        if argv[:2] == ["brightnessctl", "set"]:
            if not works:
                return 1, "", "denied"
            state["now"] = int(argv[2].rstrip("%"))
            return 0, "", ""
        if argv[:2] == ["brightnessctl", "get"]:
            return 0, str(state["now"] * 10), ""
        if argv[:2] == ["brightnessctl", "max"]:
            return 0, "1000", ""
        return 1, "", ""

    backend = power.Backend(SyncWorkers(), runner=run)
    c = power_ctl.Controller(backend, Log(), SliderView())
    c.info = power.Power(brightness=50)
    return c


def test_a_failed_brightness_is_not_logged_as_done():
    c = brightness(works=False)
    c.brightness_moved(33)
    c.commit_brightness()
    assert c.history.items == []
    assert "denied" in c.view.messages[0]


def test_each_brightness_series_starts_from_the_last_one():
    c = brightness()
    c.brightness_moved(60)
    c.commit_brightness()
    c.brightness_moved(70)
    c.commit_brightness()
    assert [(i[3], i[4]) for i in c.history.items] == [(50, 60), (60, 70)]


def volume(works=True):
    state = {"now": 50}

    def run(argv):
        if argv[1] == "set-sink-volume":
            if not works:
                return 1, "", "denied"
            state["now"] = int(argv[3].rstrip("%"))
            return 0, "", ""
        if argv[1:] == ["-f", "json", "list", "sinks"]:
            return 0, json.dumps([{"name": "out", "description": "O", "mute": False, "volume": {
                "l": {"value_percent": f"{state['now']}%"}}}]), ""
        if argv[1:] == ["get-default-sink"]:
            return 0, "out\n", ""
        return 0, "[]", ""

    backend = audio.Backend(SyncWorkers(), runner=run)
    c = audio_ctl.Controller(backend, Log(), SliderView())
    c.audio = backend.probe()
    return c


def test_a_drag_stays_on_its_device_when_the_default_changes():
    c = volume()
    c.volume_moved("sink", 60)
    c.audio = replace(c.audio, default_sink="other")
    c.volume_moved("sink", 70)
    c.commit_volume("sink")
    assert [i[1] for i in c.history.items] == [audio.key_volume("sink", "out")]


def test_a_failed_volume_is_not_logged_as_done():
    c = volume(works=False)
    c.volume_moved("sink", 33)
    c.commit_volume("sink")
    assert c.history.items == []
    assert "denied" in c.view.messages[0]


def test_each_volume_series_starts_from_the_last_one():
    c = volume()
    c.volume_moved("sink", 60)
    c.commit_volume("sink")
    c.volume_moved("sink", 70)
    c.commit_volume("sink")
    assert [(i[3], i[4]) for i in c.history.items] == [(50, 60), (60, 70)]


class Quiet:
    def show_active(self, _active):
        pass

    def status(self, text):
        self.text = text


class Held:
    """An applier the test can hold while the page asks for more."""

    def __init__(self):
        self.go = threading.Event()
        self.applied = []

    def read(self, keys):
        self.go.wait(5)
        return {k: 1 for k in keys}

    def apply(self, values):
        self.applied.append(values)


def test_a_refresh_does_not_replace_a_queued_mode(tmp_path):
    """Replaced, the mode never ran and every Apply button stayed dead."""
    workers = Workers(lambda fn: fn())
    log = hist.History(tmp_path / "history.jsonl")
    held = Held()
    for backend in ("hypr", "power", "screen-sleep", "night"):
        log.register(backend, held)
    c = mode_ctl.Controller(log, workers, Quiet())
    c.refresh()  # running
    c.apply("game")  # queued
    c.refresh()  # queued
    held.go.set()
    assert workers.wait_idle(10)
    assert held.applied
    assert c.pending is False
    workers.stop_all(2)


class Applier:
    def __init__(self, values, fail=False, partial=None):
        self.values, self.fail, self.partial = dict(values), fail, partial or {}

    def read(self, keys):
        return {k: self.values[k] for k in keys if k in self.values}

    def apply(self, values):
        if self.fail:
            self.values.update(self.partial)
            raise RuntimeError("refused")
        self.values.update(values)


class History:
    def __init__(self, appliers):
        self.appliers, self.items = appliers, []

    def applier(self, backend):
        return self.appliers.get(backend)

    def record(self, items):
        self.items = list(items)


class View:
    def __init__(self):
        self.messages = []

    def show_active(self, _active):
        pass

    def status(self, text):
        self.messages.append(text)


def world(hypr_fail=False):
    hypr_keys = {k: 99 for b, k, _v in hub_modes.BY_ID["game"].items if b == "hypr"}
    return History({
        "hypr": Applier(hypr_keys, fail=hypr_fail),
        "power": Applier({"power.profile": "balanced", "power.brightness": 50}),
        "screen-sleep": Applier({"night.manual_override": True}),
    })


def test_a_mode_logs_one_group_with_what_changed():
    history = world()
    mode_ctl.Controller(history, SyncWorkers(), View()).apply("game")
    keys = {(i[0], i[1]) for i in history.items}
    assert ("power", "power.brightness") in keys
    assert ("hypr", "general:gaps_in") in keys


def test_history_does_not_claim_what_a_failed_backend_did_not_do():
    history = world(hypr_fail=True)
    view = View()
    mode_ctl.Controller(history, SyncWorkers(), view).apply("game")
    keys = {(i[0], i[1]) for i in history.items}
    assert ("power", "power.brightness") in keys  # this part did happen: it can be undone
    assert not [k for k in keys if k[0] == "hypr"]
    assert "refused" in view.messages[-1]


def test_turning_a_mode_off_finds_its_groups_and_undoes_only_them(tmp_path):
    log = hist.History(tmp_path / "history.jsonl")
    game = hub_modes.BY_ID["game"]
    log.record([("hypr", "general:gaps_in", "Отступы", 4, 0),
                ("hypr", "decoration:rounding", "Скругление", 12, 0),
                ("power", "power.brightness", "Яркость", 50, 100)])  # the mode
    first = log.groups()[-1].id
    log.record([("hypr", "general:gaps_in", "Отступы", 0, 5)])  # by hand
    log.record([("hypr", "cursor:theme", "Курсор", "A", "B")])  # unrelated
    log.record([("hypr", "general:gaps_in", "Отступы", 5, 0)])  # the mode again
    again = log.groups()[-1].id
    assert hub_modes.groups_that_turned_on(game, log.groups(), "Отмена") == [first, again]

    class Live:
        def read(self, keys):
            return {"general:gaps_in": 0, "decoration:rounding": 0, "power.brightness": 100}

        def apply(self, values):
            pass

    log.register("hypr", Live())
    log.register("power", Live())
    plan = log.plan_undo([first, again])
    assert plan.targets[("hypr", "general:gaps_in")] == 4  # as before the mode, not 5
    assert plan.targets[("power", "power.brightness")] == 50
    assert plan.flagged == []
    log.record([("hypr", "general:gaps_in", "Отмена: Отступы", 0, 4)])  # turned off
    assert hub_modes.groups_that_turned_on(game, log.groups(), "Отмена") == []


def test_another_modes_group_ends_the_search(tmp_path):
    log = hist.History(tmp_path / "history.jsonl")
    log.record([("hypr", "general:gaps_in", "Отступы", 4, 0)])  # game
    log.record([("hypr", "general:gaps_in", "Отступы", 0, 3),
                ("hypr", "general:gaps_out", "Края", 0, 6)])  # travel
    log.record([("hypr", "decoration:rounding", "Скругление", 8, 0)])  # game again
    found = hub_modes.groups_that_turned_on(hub_modes.BY_ID["game"], log.groups(), "Отмена")
    assert found == [log.groups()[-1].id]


def test_an_unrelated_undo_does_not_hide_the_mode(tmp_path):
    """Undoing a night filter change set the override to Game's own value."""
    log = hist.History(tmp_path / "history.jsonl")
    log.record([("hypr", "general:gaps_in", "Отступы", 4, 0),
                ("hypr", "decoration:rounding", "Скругление", 12, 0)])
    game_group = log.groups()[-1].id
    log.record([("screen-sleep", hub_modes.NIGHT_OVERRIDE, "Фильтр", False, True)])
    log.record([("screen-sleep", hub_modes.NIGHT_OVERRIDE, "Отмена: Фильтр", True, False),
                ("screen-sleep", "night.target_temp", "Отмена: Цель", 2300, 2600)])
    assert hub_modes.groups_that_turned_on(
        hub_modes.BY_ID["game"], log.groups(), "Отмена") == [game_group]
