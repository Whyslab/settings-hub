"""Bluetooth through BlueZ's D-Bus (faked): parsing, actions, the search timer."""

import pytest

from settings_hub import strings
from settings_hub.backends import bluez as bz
from settings_hub.controllers import bluetooth as btctl

HCI = "/org/bluez/hci0"
PODS = HCI + "/dev_08_E6_4B_B6_58_20"
MOUSE = HCI + "/dev_AA_BB_CC_DD_EE_01"
NAMELESS = HCI + "/dev_AA_BB_CC_DD_EE_02"


def objects(discovering=False, pods_connected=False):
    return {
        "/org/bluez": {"org.bluez.AgentManager1": {}},
        HCI: {bz.ADAPTER: {"Powered": True, "Discovering": discovering}},
        PODS: {bz.DEVICE: {"Address": "08:E6:4B:B6:58:20", "Alias": "AirPods",
                           "Paired": True, "Connected": pods_connected, "Adapter": HCI,
                           "Icon": "audio-headphones"},
               bz.BATTERY: {"Percentage": 80}},
        MOUSE: {bz.DEVICE: {"Address": "AA:BB:CC:DD:EE:01", "Alias": "Mouse",
                            "Paired": False, "Connected": False, "Adapter": HCI}},
        NAMELESS: {bz.DEVICE: {"Address": "AA:BB:CC:DD:EE:02",
                               "Alias": "AA-BB-CC-DD-EE-02", "Paired": False, "Adapter": HCI,
                               "Name": None}},
    }


class FakeBus:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail or {}  # method -> BluetoothError text

    def __call__(self, path, iface, method, args, reply, timeout):
        self.calls.append((path, method, args))
        if method in self.fail:
            raise bz.BluetoothError(self.fail[method])
        if method == "GetManagedObjects":
            return (objects(),)
        if method == "Get":  # UUIDs after pairing: audio only
            return (["0000110b-0000-1000-8000-00805f9b34fb"],)
        return ()


class Workers:
    """Runs a job at once, like a worker that finished immediately."""

    def submit(self, _name, fn, on_done=None, key=None):
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        if on_done:
            on_done(result, error)


def backend(bus):
    return bz.Backend(Workers(), call=bus, variant=lambda kind, value: (kind, value))


def test_parse_splits_paired_from_new_and_drops_nameless():
    state = bz.parse(objects())
    assert (state.adapter, state.powered, state.searching) == (HCI, True, False)
    assert [d.name for d in state.paired] == ["AirPods"]
    assert state.paired[0].battery == 80
    # A device whose only "name" is its address cannot be told apart from others.
    assert [d.name for d in state.found] == ["Mouse"]


def test_pair_trusts_then_connects():
    bus = FakeBus()
    backend(bus).pair(MOUSE, input_ok=True)
    assert [c[1] for c in bus.calls] == ["Pair", "Set", "Connect"]
    assert bus.calls[1][2] == ("(ssv)", (bz.DEVICE, "Trusted", ("b", True)))


def test_pair_of_an_already_paired_device_still_connects():
    bus = FakeBus(fail={"Pair": strings.BT_ERR_ALREADY})
    backend(bus).pair(MOUSE, input_ok=True)
    assert [c[1] for c in bus.calls] == ["Pair", "Set", "Connect"]


def test_forget_asks_the_adapter():
    bus = FakeBus()
    backend(bus).forget(PODS)
    assert bus.calls == [(HCI, "RemoveDevice", ("(o)", (PODS,)))]


class View:
    def __init__(self):
        self.shown = []
        self.statuses = []

    def show_bluetooth(self, state, busy, searching):
        self.shown.append((state, busy, searching))

    def status(self, text):
        self.statuses.append(text)


def controller(bus):
    timers = []
    view = View()
    ctl = btctl.Controller(backend(bus), view, lambda s, fn: timers.append(fn) or len(timers),
                           lambda handle: None)
    ctl.refresh()
    return ctl, view, timers


def test_connect_reports_the_device_by_name():
    ctl, view, _ = controller(FakeBus())
    ctl.connect(PODS)
    assert view.statuses[-1] == strings.BT_DONE_CONNECT.format(name="AirPods")
    assert ctl.busy == set()


def test_failure_says_why():
    ctl, view, _ = controller(FakeBus(fail={"Connect": strings.BT_ERR_UNREACHABLE}))
    ctl.connect(PODS)
    assert view.statuses[-1] == strings.BT_FAILED.format(
        name="AirPods", error=strings.BT_ERR_UNREACHABLE)


def test_search_ticks_and_stops_by_itself():
    bus = FakeBus()
    ctl, view, timers = controller(bus)
    ctl.start_search()
    assert ctl.searching and ("StartDiscovery" in [c[1] for c in bus.calls])
    for _ in range(bz.SEARCH_S // btctl.TICK_S + 1):
        if not timers:
            break
        timers.pop(0)()
    assert not ctl.searching
    assert [c[1] for c in bus.calls].count("StopDiscovery") == 1


def test_stop_search_is_harmless_twice():
    bus = FakeBus()
    ctl, _view, _timers = controller(bus)
    ctl.start_search()
    ctl.stop_search()
    ctl.stop_search()
    assert [c[1] for c in bus.calls].count("StopDiscovery") == 1


@pytest.mark.parametrize("powered", [False])
def test_no_search_with_the_radio_off(powered):
    bus = FakeBus()
    ctl, view, _ = controller(bus)
    ctl.state = bz.State(HCI, powered, False, ())
    ctl.start_search()
    assert not ctl.searching and view.statuses[-1] == strings.BT_ERR_OFF


def test_a_failed_read_says_why_in_the_list_and_stops_searching():
    bus = FakeBus(fail={"GetManagedObjects": strings.BT_ERR_NO_BLUEZ})
    ctl, view, _ = controller(bus)
    state, busy, searching = view.shown[-1]
    assert (state.adapter, state.error, searching) == ("", strings.BT_ERR_NO_BLUEZ, False)
    assert ctl.state is None
    ctl.start_search()  # nothing to search with
    assert "StartDiscovery" not in [c[1] for c in bus.calls]


def test_names_lose_invisible_and_direction_characters():
    assert bz.clean_name("Air‮Pods​\x07") == "AirPods"
    objs = objects()
    objs[MOUSE][bz.DEVICE]["Alias"] = "‮Mouse"
    assert [d.name for d in bz.parse(objs).found] == ["Mouse"]


def test_input_and_unknown_devices_count_as_risky():
    def dev(icon):
        return bz.Device("/p", "AA", "x", icon, False, False)
    assert not bz.risky(dev("audio-headphones"))
    assert bz.risky(dev("input-keyboard"))
    assert bz.risky(dev("input-mouse"))
    assert bz.risky(dev(""))


def test_pairing_stops_the_search_first():
    bus = FakeBus()
    ctl, _view, _ = controller(bus)
    ctl.start_search()
    ctl.pair(MOUSE)
    methods = [c[1] for c in bus.calls if c[1] != "GetManagedObjects"]
    assert methods == ["StartDiscovery", "StopDiscovery", "Pair", "Get", "Set", "Connect"]
    assert not ctl.searching


def test_a_failed_read_during_a_search_still_stops_discovery():
    bus = FakeBus()
    ctl, _view, _ = controller(bus)
    ctl.start_search()
    bus.fail["GetManagedObjects"] = strings.BT_ERR_TIMEOUT
    ctl.refresh()
    assert "StopDiscovery" in [c[1] for c in bus.calls]
    assert not ctl.searching


def test_a_quick_stop_and_start_keeps_one_chain_of_ticks():
    class Deferred(Workers):
        """Holds jobs until run(): like a busy worker thread."""

        def __init__(self):
            self.queue = []

        def submit(self, _name, fn, on_done=None, key=None):
            self.queue.append((fn, on_done))

        def run(self):
            while self.queue:
                fn, on_done = self.queue.pop(0)
                Workers.submit(self, None, fn, on_done)

    bus = FakeBus()
    workers = Deferred()
    timers, cancelled = [], []
    be = bz.Backend(workers, call=bus, variant=lambda k, v: (k, v))
    ctl = btctl.Controller(be, View(), lambda s, fn: timers.append(fn) or len(timers),
                           cancelled.append)
    ctl.refresh()
    workers.run()
    ctl.start_search()
    ctl.stop_search()
    ctl.start_search()
    workers.run()
    live = len(timers) - len(cancelled)
    assert live == 1


class HidBus(FakeBus):
    """A device that announced itself as headphones but offers a keyboard service."""

    def __call__(self, path, iface, method, args, reply, timeout):
        if method == "Get":
            self.calls.append((path, method, args))
            return (["0000110b-0000-1000-8000-00805f9b34fb",
                     "00001124-0000-1000-8000-00805F9B34FB"],)
        return super().__call__(path, iface, method, args, reply, timeout)


def test_fake_headphones_that_offer_a_keyboard_are_forgotten_before_trust():
    bus = HidBus()
    with pytest.raises(bz.BluetoothError) as caught:
        backend(bus).pair(MOUSE)
    assert str(caught.value) == strings.BT_ERR_IS_INPUT
    methods = [c[1] for c in bus.calls]
    assert methods == ["Pair", "Get", "RemoveDevice"]  # never Set Trusted, never Connect


def test_after_the_input_warning_a_keyboard_may_pair():
    bus = HidBus()
    backend(bus).pair(MOUSE, input_ok=True)
    assert [c[1] for c in bus.calls] == ["Pair", "Set", "Connect"]


def test_only_plain_audio_is_not_risky():
    def dev(icon, uuids=()):
        return bz.Device("/p", "AA", "x", icon, False, False, uuids=frozenset(uuids))
    assert not bz.risky(dev("audio-headset"))
    assert bz.risky(dev("phone"))
    assert bz.risky(dev("computer"))
    assert bz.risky(dev("audio-headset", ["00001124-0000-1000-8000-00805f9b34fb"]))
