"""The four pages added on 15.11.2026 on a private Xvfb (live: needs GTK4).

Opening a page must change nothing: no `hyprctl eval`, no HyprPanel config
written, Do Not Disturb as it was (it is read by flipping it twice).
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name
from test_gui_system import stub

MONITORS = ('[{"name":"eDP-1","description":"Panel","width":1920,"height":1080,'
            '"refreshRate":60.02,"scale":1.5,"x":0,"y":0,"disabled":false,'
            '"availableModes":["1920x1080@60.02Hz","1920x1080@40.00Hz"]}]')


@pytest.mark.live
def test_new_pages_open_without_changing_anything(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.lua").write_text(
        'hl.on("hyprland.start", function()\n    -- The bar\n    hl.exec_cmd("waybar")\nend)\n')
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    log = tmp_path / "calls.log"
    dnd = tmp_path / "dnd"
    dnd.write_text("on")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    stub(stubs, "hyprctl", f"""case "$*" in
  "monitors all -j") echo '{MONITORS}' ;;
  "-j version") echo '{{"version": "0.57.2"}}' ;;
esac""", log)
    stub(stubs, "hyprpanel", f"""case "$*" in
  toggleDnd) if [ "$(cat {dnd})" = on ]; then echo off >{dnd}; echo Disabled;
             else echo on >{dnd}; echo Enabled; fi ;;
esac""", log)
    stub(stubs, "gsettings", "echo \"[<{'id': <uint32 1>, 'app-name': <'kitty'>}>]\"", log)
    stub(stubs, "checkupdates", "echo 'linux 1 -> 2'", log)
    for name in ("pacman", "yay", "paru", "notify-send", "kitty", "foot"):
        stub(stubs, name, "", log)
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
         str(ROOT / "tests" / "gui_new_pages.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Traceback" not in done.stderr, done.stderr[-3000:]
    calls = log.read_text()
    assert "hyprctl eval" not in calls and "clearNotifications" not in calls, calls
    assert "notify-send" not in calls and "kitty" not in calls, calls
    assert calls.count("hyprpanel toggleDnd") % 2 == 0 and dnd.read_text().strip() == "on"
    assert not (home / ".config" / "hyprpanel" / "config.json").exists()
    assert not (hypr / "settings-hub-monitors.lua").exists()
    assert not (hypr / "settings-hub-autostart.lua").exists()
    r = json.loads(out.read_text())
    assert r["history_groups"] == 0
    assert any("1920×1080, 60.02 Гц" in t for t in r["monitor"]), r["monitor"]
    assert any(t == "150 %" for t in r["monitor"]), r["monitor"]
    assert "kitty" in r["notifications"], r["notifications"]  # a recent sender to ignore
    assert "The bar" in r["autostart"] and "waybar" in r["autostart"], r["autostart"]
    assert "linux" in r["updates"] and "1 → 2" in r["updates"], r["updates"]
