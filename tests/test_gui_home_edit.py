"""The home editor in the real window (gui_home_edit.py on Xvfb)."""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

from settings_hub import settings


@pytest.mark.live
def test_home_editor_in_the_window(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    for name in ("hyprctl", "pactl", "nmcli", "bluetoothctl", "powerprofilesctl",
                 "brightnessctl", "systemctl", "notify-send", "wallpaper-theme"):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >>"{log}"\nexit 0\n')
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
         str(ROOT / "tests" / "gui_home_edit.py"), *args],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Traceback" not in done.stderr, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == []
    start = list(settings.HOME_TILES)
    assert r["tiles_start"] == start and r["all_tiles"] == sorted(start)
    assert r["esc_cleared"] is True and r["esc_still_editing"] is True
    assert r["themes_refreshed_back"] >= 1  # switched back on: fresh values
    assert r["edit_child"] == "edit" and r["back_child"] == "tiles"
    assert r["esc_child"] == "tiles" and r["esc_visible"] is True
    assert r["tiles_off"] == [p for p in start if p != "themes"] and r["themes_small"]
    assert r["tiles_moved"] == ["sound", "screen-sleep", "network", "power", "modes"]
    assert r["tile_rows"] == 6  # five on, one off
    assert r["results"] >= 1 and r["pinned_label"]
    assert r["pins"] == ["general#appearance.own_font", "panel#clock"]
    assert r["bad_note"] is True
    assert r["commands"] == [{"name": "Привет", "cmd": 'echo "hi there"'}]
    assert r["entries_cleared"] is True
    assert r["switch_start"] is True
    assert r["setting_flipped"] is False and r["switch_flipped"] is False
    assert r["setting_undone"] is True and r["switch_undone"] is True
    assert r["opened"] == "panel"
    assert r["tiles_undone"] == start and r["pins_undone"] == []
    assert r["file"] == {}  # every change undone: nothing left in settings.json
    calls = log.read_text().splitlines() if log.exists() else []
    runs = [c for c in calls if "exec_cmd" in c]
    assert runs == ['hyprctl dispatch hl.dsp.exec_cmd("echo \\"hi there\\"")'], runs
