"""The Appearance page in the window (live: needs GTK4).

SH_SHOTS=DIR keeps screenshots for a look by eye.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

from settings_hub import strings

GSETTINGS = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = Path(__file__).with_name("gsettings.json")
with Path(__file__).with_name("calls.log").open("a") as fh:
    fh.write("gsettings " + " ".join(sys.argv[1:]) + "\n")
v = json.loads(state.read_text()) if state.exists() else {
    "font-name": "'Adwaita Sans 11'", "monospace-font-name": "'Adwaita Mono 11'",
    "text-scaling-factor": "1.25", "icon-theme": "'Adwaita'"}
a = sys.argv[1:]
if a[:2] == ["get", "org.gnome.desktop.interface"] and a[2] in v:
    print(v[a[2]])
elif a[:2] == ["set", "org.gnome.desktop.interface"]:
    v[a[2]] = a[3]
    state.write_text(json.dumps(v))
else:
    sys.exit(1)
'''


@pytest.mark.live
def test_appearance_in_the_window(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    conf = home / ".config"
    (conf / "kitty").mkdir(parents=True)
    (conf / "kitty" / "kitty.conf").write_text("font_family Adwaita Mono\nfont_size 13.0\n")
    (conf / "hyprpanel").mkdir()
    (conf / "hyprpanel" / "config.json").write_text('{"theme.font.name": "JetBrainsMono"}')
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("gsettings", GSETTINGS), ("hyprctl", "#!/bin/sh\nexit 1\n")):
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
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
         str(ROOT / "tests" / "gui_appearance.py"), *args],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Traceback" not in done.stderr, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == []
    assert r["font"] == "Adwaita Sans 11" and r["mono"] == "Adwaita Mono 11"
    assert r["scale_label"] == "125 %"
    assert r["panel"] == "JetBrainsMono" and r["kitty"] == "Adwaita Mono 13"
    assert "Adwaita" in r["icons"] and r["icon_selected"] == "Adwaita"  # hidden, but in use
    assert r["sample_icons"] > 0
    assert r["cursor_rows"] == ["cursor:size", "cursor:theme"]
    assert r["panel_same_on"] and not r["kitty_same_on"]  # kitty already has that family
    assert r["font_note"] == strings.LOOK_OWN_FONT_NOTE  # the window keeps Onest
    assert "Nope" in r["missing_note"]  # a font that is not there
    assert strings.LOOK_OWN_FONT_NOTE not in r["font_note_off"]  # the window follows it now
    assert r["after_font"] == "DejaVu Serif 13"
    assert r["history"][0] == ["look.font"]
    # the window's own font switch: Onest, the interface font, back by undo
    assert r["own_font_on"] and r["family_own"].startswith("Onest")
    assert r["family_system"] == r["gtk_font"].rsplit(" ", 1)[0]
    assert r["own_font_after_undo"] and r["family_after_undo"].startswith("Onest")
    calls = (tmp_path / "stubs" / "calls.log").read_text()
    assert "set org.gnome.desktop.interface font-name 'DejaVu Serif 13'" in calls
    assert "font-name=DejaVu Serif 13" in (conf / "gtk-4.0" / "settings.ini").read_text()
