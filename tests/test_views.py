"""Every widget a controller talks to has every method the controller calls."""

import inspect

import pytest

pytest.importorskip("gi")

from settings_hub import home  # noqa: E402
from settings_hub.controllers import audio as audctl  # noqa: E402
from settings_hub.controllers import bluetooth as btctl  # noqa: E402
from settings_hub.controllers import network as netctl  # noqa: E402
from settings_hub.pages import network as netpage  # noqa: E402
from settings_hub.pages import sound  # noqa: E402

# The home tile's network controller never joins: only the page offers that.
OPTIONAL = {(netctl.View, "join_finished")}


def methods(protocol):
    return [name for name, _ in inspect.getmembers(protocol, inspect.isfunction)
            if not name.startswith("_")]


@pytest.mark.parametrize("protocol, view", [
    (audctl.View, sound.SoundPage),
    (audctl.View, home.SoundTile),
    (netctl.View, netpage.NetworkPage),
    (netctl.View, home.NetworkTile),
    (btctl.View, netpage.NetworkPage),
])
def test_view_has_every_method(protocol, view):
    missing = [m for m in methods(protocol)
               if not hasattr(view, m) and (protocol, m) not in OPTIONAL]
    assert missing == []


def test_one_row_per_network_name_and_a_twin_offers_the_protected_kind():
    from settings_hub.backends import network as net
    from settings_hub.backends import nm_wifi

    rows = netpage.one_per_name([
        net.Wifi("Home", 80, "WPA2", True),
        net.Wifi("Home", 50, "WPA2", False),      # another point of the network in use
        net.Wifi("Mesh", 70, "WPA2", False),
        net.Wifi("Mesh", 75, "WPA2", False),      # same name, stronger, later in the list
        net.Wifi("Twin", 90, "", False),          # an open twin, stronger
        net.Wifi("Twin", 40, "WPA2", False),
        net.Wifi("", 30, "WPA2", False),          # nameless: not joinable from the list
    ])
    assert [(w.ssid, w.signal, kind, mixed) for w, kind, mixed in rows] == [
        ("Mesh", 75, nm_wifi.PERSONAL, False),
        ("Twin", 40, nm_wifi.PERSONAL, True),
    ]
