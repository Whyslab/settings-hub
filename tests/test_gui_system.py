"""Sound and Network pages on a private Xvfb (live: needs GTK4)."""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

SOURCES = ('[{"name":"usb.monitor","description":"Monitor","mute":false,"volume":{},'
           '"properties":{"device.class":"monitor"}},'
           '{"name":"mic","description":"Mic","mute":false,"volume":{},'
           '"properties":{"device.class":"sound"}}]')
SINKS = ('[{"name":"usb","description":"G435","mute":false,"volume":{},"properties":{}},'
         '{"name":"speakers","description":"Speakers","mute":false,"volume":{},"properties":{}}]')


def stub(directory, name, body, log):
    path = directory / name
    path.write_text(f'#!/bin/sh\necho "{name} $*" >>"{log}"\n{body}\nexit 0\n')
    path.chmod(0o755)


@pytest.mark.live
def test_opening_the_pages_changes_nothing_and_keeps_the_switch(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    log = tmp_path / "calls.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    stub(stubs, "pactl", f"""case "$*" in
  *"json list sinks"*) echo '{SINKS}' ;;
  *"json list sources"*) echo '{SOURCES}' ;;
  get-default-sink) echo speakers ;;
  get-default-source) echo usb.monitor ;;
esac""", log)  # the sink in use is not the first one; the source in use is a monitor
    stub(stubs, "bluetoothctl", """case "$*" in
  show) printf 'Controller A\\n\\tPowered: yes\\n' ;;
  "devices Connected") echo 'Device AA:BB Phones' ;;
esac""", log)
    stub(stubs, "nmcli", 'case "$*" in "radio wifi") echo enabled ;; esac', log)
    stub(stubs, "tailscale", "", log)
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1", PATH=f"{stubs}:{os.environ['PATH']}")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_system_pages.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "gtk_box_append" not in done.stderr, done.stderr[-3000:]
    calls = log.read_text()
    assert "pactl set-" not in calls, calls
    r = json.loads(out.read_text())
    assert r["history_groups"] == 0
    assert (r["off_label"], r["off_sensitive"]) == ("Выключить", True)
    assert r["undone_groups"] == [[r["mode_group"]]]
    assert r["on_label"] == "Включить"
    assert r["sink_selected"] == 1  # speakers, as in use
    assert r["source_names"] == ["usb.monitor", "mic"]  # in use, so it stays visible
    assert r["source_selected"] == 0
    assert r["bt_switch_in_group"] is True
    assert not any(r["missing_rows"].values())
    assert r["kept_page"] == "network"  # on screen: SUPER+I does not move it
    assert r["start_page"] == "sound"  # hidden: starts over
    assert r["search_kept"] is True
    assert r["window_undo"] is True
    assert r["applied_on_leave"] == 0
    assert r["applied_on_enter"] == 1
    assert r["focus_after_enter_is_none"] is True  # so Ctrl+Z undoes the change
    assert r["asked"] == 1
    assert r["wifi_back_on"] is True
    assert "radio wifi off" not in calls
