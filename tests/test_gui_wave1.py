"""Wi-Fi joining, Bluetooth, the mixer and redo in the window (live: needs GTK4).

SH_SHOTS=DIR keeps screenshots of the pages for a look by eye.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

from settings_hub import strings

PACTL = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = Path(__file__).with_name("pactl-state.json")
log = Path(__file__).with_name("calls.log")
with log.open("a") as fh:
    fh.write("pactl " + " ".join(sys.argv[1:]) + "\n")
s = json.loads(state.read_text()) if state.exists() else {"1": 100, "2": 60, "4": 40}
def stream(i, app, media, corked=False):
    v = s[i]
    return {"index": int(i), "mute": False, "corked": corked,
            "volume": {"front-left": {"value_percent": f"{v}%"}},
            "properties": {"application.name": app, "media.name": media}}
a = sys.argv[1:]
if a[:3] == ["-f", "json", "list"]:
    kind = a[3]
    if kind == "sinks":
        print('[{"index":1,"name":"speakers","description":"Speakers","mute":false,'
              '"volume":{},"properties":{}}]')
    elif kind == "sources":
        print('[{"index":57,"name":"spk.monitor","description":"Monitor","mute":false,'
              '"volume":{},"properties":{"device.class":"monitor"}},'
              '{"index":58,"name":"mic","description":"Mic","mute":false,"volume":{},'
              '"properties":{"device.class":"sound"}}]')
    elif kind == "sink-inputs":
        print(json.dumps([stream("1", "Firefox", "local-Spotify"),
                          stream("2", "Firefox", "YouTube", corked=True),
                          stream("4", "Telegram", "")]))
    elif kind == "source-outputs":
        print('[{"index":9,"source":57,"properties":{"application.name":"cava"}},'
              '{"index":10,"source":58,"properties":{"application.name":"Telegram"}}]')
elif a and a[0] == "get-default-sink":
    print("speakers")
elif a and a[0] == "get-default-source":
    print("mic")
elif a and a[0] == "set-sink-input-volume":
    s[a[1]] = int(a[2].rstrip("%"))
    state.write_text(json.dumps(s))
'''

NMCLI = r'''#!/bin/sh
echo "nmcli $*" >>"$(dirname "$0")/calls.log"
case "$*" in
  "radio wifi") echo enabled ;;
  *"device wifi list"*) printf '*:Home:80:WPA2\n :Neighbour:60:WPA2\n :Neighbour:30:WPA2\n'
                        printf ' :Cafe:50:\n :Work:40:WPA2 802.1X\n'
                        printf ' :Twin:90:\n :Twin:35:WPA2\n' ;;
  *"connection show"*) printf 'Home:802-11-wireless:yes\n' ;;
esac
exit 0
'''


@pytest.mark.live
def test_wave1_in_the_window(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("pactl", PACTL), ("nmcli", NMCLI),
                       ("bluetoothctl", "#!/bin/sh\nexit 1\n"),
                       ("tailscale", "#!/bin/sh\nexit 1\n")):
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    out = tmp_path / "out.json"
    shots = os.environ.get("SH_SHOTS", "")
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1", PATH=f"{stubs}:{os.environ['PATH']}")
    args = [str(ROOT), str(state), str(out)] + ([shots] if shots else [])
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_wave1.py"), *args],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Traceback" not in done.stderr, done.stderr[-3000:]
    r = json.loads(out.read_text())
    calls = (stubs / "calls.log").read_text()

    # Visible networks: a password form, a direct join, and a refusal with a reason.
    widgets = r["join_widgets"]
    assert widgets["Neighbour"][:2] == ["MenuButton", True]
    assert widgets["Cafe"][:2] == ["Button", True]
    assert widgets["Work"][:2] == ["Button", False]
    # A name seen with an open twin: one row, the password form, a warning.
    assert widgets["Twin"][:2] == ["MenuButton", True]
    assert r["twin_subtitle"].endswith(strings.NET_VISIBLE_MIXED)
    assert r["visible_titles"].count("Neighbour") == 1
    assert r["work_tip"] == strings.NET_JOIN_UNSUPPORTED_TIP
    assert "Home" not in widgets  # the network in use is not in the list
    assert r["form_kept"] == [True, "half-typed", True]
    assert r["form_cleared"] == ""
    assert r["redrawn_after_close"] is True
    # A wrong password: nothing logged, the form opens again and says why.
    assert r["joining_label"] == strings.NET_JOINING
    assert r["join_error"] == strings.NET_JOIN_BAD_PASSWORD
    assert r["reopened"] is True
    assert r["groups_after_failure"] == 0
    # The right one: logged as a connection change, the error is gone.
    assert r["joined_entry"] == ["wifi.connection", "Neighbour"]
    assert r["join_error_cleared"] is True
    assert r["attempts"] == [["Neighbour", "wrong-pass", False, "personal"],
                             ["Neighbour", "right-pass-1", False, "personal"]]
    assert "right-pass-1" not in calls  # never on a command line

    # Bluetooth: the paired AirPods, connect, a search that finds a mouse, pairing.
    assert r["bt_titles"] == ["AirPods"]
    assert r["bt_subtitles"] == [strings.BT_NOT_CONNECTED + strings.BT_BATTERY.format(
        percent=80)]
    assert r["bt_button"] == strings.BT_CONNECT
    assert r["bt_after_connect"][0].startswith(strings.BT_CONNECTED)
    assert r["search_label"] == strings.BT_SEARCH_STOP
    assert r["found"] == ["Mouse"]
    assert r["found_subtitle"].startswith(strings.BT_KIND_UNKNOWN)
    # Pairing asks first, warns (an unknown type could be a keyboard), stops the search.
    assert len(r["pair_asked"]) == 1
    assert r["pair_asked"][0][1] == strings.BT_PAIR_DETAIL_RISKY.format(
        kind=strings.BT_KIND_UNKNOWN, address="AA:BB:CC:DD:EE:01")
    assert r["searching_after_pair"] is False
    bt_calls = r["bt_calls"]
    assert bt_calls.index("StopDiscovery") < bt_calls.index("Pair"), bt_calls
    for method in ("Connect", "StartDiscovery", "Pair", "Set"):
        assert method in bt_calls, bt_calls

    # The mixer: one row per program, a microphone user (not the visualiser).
    assert r["apps"] == ["Firefox", "Telegram"]
    assert r["apps_subtitles"][0] == "local-Spotify"
    assert r["recorders"] == "Telegram"
    assert "set-sink-input-volume 1 55%" in calls and "set-sink-input-volume 2 55%" in calls
    assert r["mixer_entry"] == ["app.volume.Firefox", 100, 55]

    # Ctrl+Z twice goes two steps back; Ctrl+Shift+Z and Ctrl+Y put them back.
    assert r["after_one_undo"] == {"a": 2, "b": 10}
    assert r["after_two_undos"] == {"a": 1, "b": 10}
    assert r["after_redo"] == {"a": 2, "b": 10}
    assert r["after_ctrl_y"] == {"a": 2, "b": 20}
    assert r["status"].startswith(strings.HISTORY_REDONE.split("{")[0])
