"""Joining a new Wi-Fi network over NetworkManager's D-Bus (faked here)."""

import pytest

from settings_hub import strings
from settings_hub.backends import nm_wifi as nw

DEV = "/org/freedesktop/NetworkManager/Devices/3"
AP1 = "/org/freedesktop/NetworkManager/AccessPoint/1"
AP2 = "/org/freedesktop/NetworkManager/AccessPoint/2"
CONN = "/org/freedesktop/NetworkManager/Settings/9"
ACT = "/org/freedesktop/NetworkManager/ActiveConnection/5"


class FakeNM:
    """Answers the calls Joiner makes; records AddAndActivate and Delete."""

    def __init__(self, states=(2,), reason=0, points=None, save_fails=False, wait_breaks=False):
        self.states = list(states)  # what Active.State says, one per poll
        self.reason = reason
        self.points = points if points is not None else {
            AP1: {"Ssid": b"Home", "Strength": 40, "Flags": 1, "WpaFlags": 0, "RsnFlags": 0x188},
            AP2: {"Ssid": b"Home", "Strength": 80, "Flags": 1, "WpaFlags": 0, "RsnFlags": 0x588},
        }
        self.added = None
        self.deleted = []
        self.saved = []
        self.save_fails = save_fails
        self.wait_breaks = wait_breaks

    def __call__(self, path, iface, method, args, reply):
        if method == "GetDevices":
            return (["/org/freedesktop/NetworkManager/Devices/1", DEV],)
        if method == "GetAllAccessPoints":
            return (list(self.points),)
        if method == "Get":
            _kind, (_iface, name) = args
            if path in self.points:
                return (self.points[path][name],)
            if name == "DeviceType":
                return (2 if path == DEV else 32,)
            if name == "State":
                if self.wait_breaks:
                    raise ValueError("something unexpected")
                return (self.states.pop(0) if len(self.states) > 1 else self.states[0],)
            if name == "StateReason":
                return ((120, self.reason),)
            raise AssertionError(name)
        if method == "AddAndActivateConnection2":
            self.added = args
            return (CONN, ACT, {})
        if method == "Update2":
            if self.save_fails:
                raise RuntimeError("read-only")
            self.saved.append((path, args))
            return ({},)
        if method == "GetSettings":
            return ({"connection": {"id": "Home"}},)
        if method == "Delete":
            self.deleted.append(path)
            return ()
        raise AssertionError(method)


def joiner(fake, clock=None):
    ticks = iter(range(10_000))
    return nw.Joiner(call=fake, sleep=lambda _s: None,
                     clock=clock or (lambda: next(ticks) * 0.1),
                     variant=lambda kind, value: (kind, value))


def test_kinds_from_nmcli_and_from_flags():
    assert nw.security_kind("WPA2") == nw.PERSONAL
    assert nw.security_kind("WPA1 WPA2") == nw.PERSONAL
    assert nw.security_kind("WPA3") == nw.PERSONAL
    assert nw.security_kind("WPA2 802.1X") == nw.ENTERPRISE
    assert nw.security_kind("WEP") == nw.WEP
    assert nw.security_kind("") == nw.OPEN
    assert nw.security_kind("--") == nw.OPEN
    assert nw.security_kind("OWE") == nw.OWE
    assert nw.ap_kind(1, 0, 0x188) == nw.PERSONAL
    assert nw.ap_kind(1, 0, 0x400) == nw.PERSONAL  # WPA3 only
    assert nw.ap_kind(1, 0, 0x200) == nw.ENTERPRISE
    assert nw.ap_kind(0, 0, 0) == nw.OPEN
    assert nw.ap_kind(1, 0, 0) == nw.WEP
    assert nw.ap_kind(1, 0, 0x800) == nw.OWE


def test_join_sends_only_the_password_to_the_strongest_point():
    fake = FakeNM()
    joined = joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    assert joined == nw.Joined("Home", saved=True)
    settings, device, point, options = fake.added[1]
    assert (device, point) == (DEV, AP2)  # 80 beats 40
    assert settings == {"802-11-wireless-security": {"psk": ("s", "secret-pass")}}
    # In memory until it works, then written to disk.
    assert options == {"persist": ("s", "memory")}
    assert fake.saved == [(CONN, ("(a{sa{sv}}ua{sv})", ({}, nw.UPDATE_TO_DISK, {})))]
    assert fake.deleted == []


def test_open_network_sends_no_security_at_all():
    fake = FakeNM(points={AP1: {"Ssid": b"Cafe", "Strength": 50, "Flags": 0,
                                "WpaFlags": 0, "RsnFlags": 0}})
    joiner(fake).join("Cafe", "", expect=nw.OPEN)
    assert fake.added[1][0] == {}


def test_wrong_password_deletes_the_new_connection():
    fake = FakeNM(states=(1, 1, 4), reason=7)
    with pytest.raises(nw.JoinError) as caught:
        joiner(fake).join("Home", "wrong-pass", expect=nw.PERSONAL)
    assert str(caught.value) == strings.NET_JOIN_BAD_PASSWORD
    assert fake.deleted == [CONN]


def test_timeout_also_deletes_it():
    fake = FakeNM(states=(1,))
    with pytest.raises(nw.JoinError) as caught:
        joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    assert str(caught.value) == strings.NET_JOIN_TIMEOUT
    assert fake.deleted == [CONN]


def test_enterprise_and_short_passwords_are_refused_before_anything_is_sent():
    fake = FakeNM(points={AP1: {"Ssid": b"Work", "Strength": 50, "Flags": 1,
                                "WpaFlags": 0, "RsnFlags": 0x200}})
    with pytest.raises(nw.JoinError, match="другой защитой"):  # the page greys it out
        joiner(fake).join("Work", "whatever-long", expect=nw.PERSONAL)
    fake = FakeNM()
    with pytest.raises(nw.JoinError) as caught:
        joiner(fake).join("Home", "short", expect=nw.PERSONAL)
    assert str(caught.value) == strings.NET_JOIN_PASSWORD_LENGTH
    assert fake.added is None


def test_invisible_network_is_named_in_the_error():
    with pytest.raises(nw.JoinError, match="Elsewhere"):
        joiner(FakeNM()).join("Elsewhere", "secret-pass", expect=nw.PERSONAL)


def test_hidden_network_spells_out_every_setting():
    fake = FakeNM()
    joiner(fake).join("Secret", "secret-pass", hidden=True)
    settings, device, point, _options = fake.added[1]
    assert (device, point) == (DEV, "/")
    assert settings["802-11-wireless"]["hidden"] == ("b", True)
    assert settings["802-11-wireless"]["ssid"] == ("ay", b"Secret")
    assert settings["802-11-wireless-security"]["key-mgmt"] == ("s", "wpa-psk")


def test_names_longer_than_32_bytes_are_refused():
    with pytest.raises(nw.JoinError):
        joiner(FakeNM()).join("я" * 17, "secret-pass", hidden=True)  # 34 bytes


EVIL = "/org/freedesktop/NetworkManager/AccessPoint/66"


def test_an_open_twin_cannot_take_a_join_meant_for_a_protected_network():
    points = {AP1: {"Ssid": b"Home", "Strength": 40, "Flags": 1, "WpaFlags": 0,
                    "RsnFlags": 0x188},
              EVIL: {"Ssid": b"Home", "Strength": 99, "Flags": 0, "WpaFlags": 0,
                     "RsnFlags": 0}}
    fake = FakeNM(points=points)
    joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    assert fake.added[1][2] == AP1  # the weaker, real one


def test_only_an_open_twin_left_refuses_and_keeps_the_password():
    fake = FakeNM(points={EVIL: {"Ssid": b"Home", "Strength": 99, "Flags": 0,
                                 "WpaFlags": 0, "RsnFlags": 0}})
    with pytest.raises(nw.JoinError, match="другой защитой"):
        joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    with pytest.raises(nw.JoinError) as caught:
        joiner(fake).join("Home", "secret-pass")  # no expectation: no join at all
    assert str(caught.value) == strings.NET_JOIN_NO_KIND
    assert fake.added is None


def test_a_64_digit_hex_key_is_a_valid_password():
    key = "0123456789abcdef" * 4
    fake = FakeNM()
    joiner(fake).join("Home", key, expect=nw.PERSONAL)
    assert fake.added[1][0]["802-11-wireless-security"]["psk"] == ("s", key)
    with pytest.raises(nw.JoinError):
        joiner(FakeNM()).join("Home", "z" * 64, expect=nw.PERSONAL)


def test_a_hidden_network_needs_a_password():
    fake = FakeNM()
    with pytest.raises(nw.JoinError) as caught:
        joiner(fake).join("Secret", "", hidden=True)
    assert str(caught.value) == strings.NET_JOIN_HIDDEN_NEEDS_PASSWORD
    assert fake.added is None


def test_an_unexpected_error_while_waiting_still_deletes_the_connection():
    fake = FakeNM(wait_breaks=True)
    with pytest.raises(ValueError):
        joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    assert fake.deleted == [CONN]


def test_saving_that_fails_still_counts_as_connected():
    fake = FakeNM(save_fails=True)
    joined = joiner(fake).join("Home", "secret-pass", expect=nw.PERSONAL)
    assert joined == nw.Joined("Home", saved=False)
    assert fake.deleted == []


def test_networkmanager_gone_is_said_in_words():
    def broken(path, iface, method, args, reply):
        raise RuntimeError("The name org.freedesktop.NetworkManager was not provided")

    with pytest.raises(nw.JoinError, match="NetworkManager"):
        joiner(broken).join("Home", "secret-pass", expect=nw.PERSONAL)


def test_an_open_twin_of_an_enhanced_open_network_is_not_taken():
    owe = {"Ssid": b"Cafe", "Strength": 30, "Flags": 1, "WpaFlags": 0, "RsnFlags": 0x800}
    plain = {"Ssid": b"Cafe", "Strength": 90, "Flags": 0, "WpaFlags": 0, "RsnFlags": 0}
    fake = FakeNM(points={AP1: owe, EVIL: plain})
    joiner(fake).join("Cafe", "", expect=nw.OWE)
    assert fake.added[1][2] == AP1


def test_passwords_wpa2_cannot_take_are_refused_in_words():
    for bad in ("пароль-кириллицей", "tab\tinside", "short"):
        with pytest.raises(nw.JoinError) as caught:
            joiner(FakeNM()).join("Home", bad, expect=nw.PERSONAL)
        assert str(caught.value) == strings.NET_JOIN_PASSWORD_LENGTH
