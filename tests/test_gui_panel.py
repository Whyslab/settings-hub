"""The Panel page in the real window (gui_panel.py on Xvfb)."""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

LAYOUT = {"*": {"left": ["dashboard"], "middle": ["clock"],
                "right": ["volume", "network", "power"]}}


@pytest.mark.live
def test_panel_in_the_window(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    conf = home / ".config"
    panel = conf / "hyprpanel"
    panel.mkdir(parents=True)
    (panel / "config.json").write_text(json.dumps({
        "theme.font.name": "JetBrainsMono Nerd Font", "theme.font.size": "10px",
        "theme.bar.floating": True, "theme.bar.opacity": 80, "bar.layouts": LAYOUT,
        "bar.clock.format": "%H:%M %d %a", "theme.bar.buttons.background": "#123456",
    }))
    (panel / "config.json").chmod(0o600)
    (panel / "modules.json").write_text(json.dumps({"custom/cpu": {}}))
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "hyprctl").write_text("#!/bin/sh\nexit 1\n")
    (stubs / "hyprctl").chmod(0o755)
    out = tmp_path / "out.json"
    shots = os.environ.get("SH_SHOTS", "")
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(conf),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1", PATH=f"{stubs}:{os.environ['PATH']}")
    args = [str(ROOT), str(state), str(out)] + ([shots] if shots else [])
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_panel.py"), *args],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Traceback" not in done.stderr, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == []
    assert r["floating"] is True and r["opacity"] == 80 and r["font_size"] == 10
    assert r["font"] == "JetBrainsMono Nerd Font"
    assert r["clock_entry"] == "%H:%M %d %a" and r["clock_selected"] == 2
    assert not r["clock_entry_visible"]  # a preset: no field
    assert r["right_rows"] == 3 and "custom/cpu" in r["add_names"]
    c = r["config"]
    assert c["bar.clock.format"] == "%H:%M:%S"
    assert "theme.bar.floating" not in c  # back to HyprPanel's default (False)
    assert c["theme.bar.opacity"] == 40
    assert c["bar.layouts"]["*"] == {"left": ["dashboard", "custom/cpu"], "middle": ["clock"],
                                     "right": ["network", "volume"]}
    assert c["theme.font.name"] == "Adwaita Sans"
    assert c["theme.bar.buttons.background"] == "#123456"
    assert r["mode"] == "0o600"
    keys = [k[0] for k in r["history"]]
    assert keys.count("theme.bar.opacity") == 1  # three clicks, one item
    assert keys.count("bar.layouts") == 3
