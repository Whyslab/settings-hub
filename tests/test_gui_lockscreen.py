"""The Lock screen page in the real window (gui_lockscreen.py on Xvfb)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

SIMULATOR = Path.home() / ".local" / "share" / "hyprlock-sim" / "simlock.py"
COLORS = """$font = DejaVu Sans
$c_black = rgba(0, 0, 0, 1.0)
$c_white = rgba(255, 255, 255, 1.0)
$c_grey_light = rgba(205, 205, 208, 0.88)
$c_grey_label = rgba(255, 255, 255, 0.62)
$c_dock_panel = rgba(20, 20, 26, 0.50)
$c_dock_border = rgba(255, 255, 255, 0.20)
$c_glass_fill = rgba(255, 255, 255, 0.10)
$c_input_ring = rgba(255, 255, 255, 0.30)
$c_caps_ring = rgba(255, 200, 0, 1.0)
$c_num_ring = rgba(0, 200, 255, 1.0)
$c_both_ring = rgba(255, 0, 200, 1.0)
$c_check_ring = rgba(0, 255, 0, 1.0)
$c_fail_ring = rgba(255, 0, 0, 1.0)
"""


def hand_made(home: Path) -> str:
    hook = home / ".local" / "state" / "wallpaper-theme" / "hyprlock.conf"
    return f"""# сделано руками
source = ~/.config/hypr/colors.conf
source = {hook}  # wallpaper-theme

background {{
    monitor =
    color = $c_black
}}

input-field {{
    monitor =
    size = 300, 50
    placeholder_text = Пароль
}}
"""


@pytest.mark.live
def test_lockscreen_in_the_window(tmp_path, xvfb):  # noqa: F811
    if not SIMULATOR.is_file() or shutil.which("magick") is None:
        pytest.skip("needs ~/.local/share/hyprlock-sim/simlock.py and ImageMagick")
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    hypr = home / ".config" / "hypr"
    (hypr / "scripts").mkdir(parents=True)
    (hypr / "colors.conf").write_text(COLORS)
    for name, value in (("cpu", "12%"), ("ram", "3.1G (40%)"), ("temp", "55°C"),
                        ("battery", "80%"), ("wifi", "Home (70%)")):
        script = hypr / "scripts" / f"lock-status-{name}.sh"
        script.write_text(f"#!/bin/sh\necho '{value}'\n")
        script.chmod(0o755)
    hook = home / ".local" / "state" / "wallpaper-theme" / "hyprlock.conf"
    hook.parent.mkdir(parents=True)
    hook.write_text("# wallpaper-theme\n")
    (hypr / "hyprlock.conf").write_text(hand_made(home))
    wall = home / ".local" / "state" / "hypr-wallpaper" / "lock.img"
    wall.parent.mkdir(parents=True)
    subprocess.run(["magick", "-size", "1280x720", "gradient:#203040-#402050", f"png:{wall}"],
                   check=True, timeout=30)
    sim = home / ".local" / "share" / "hyprlock-sim"
    sim.mkdir(parents=True)
    shutil.copy(SIMULATOR, sim / "simlock.py")
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "out.json"
    shots = os.environ.get("SH_SHOTS", "")
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1")
    args = [str(ROOT), str(state), str(out)] + ([shots] if shots else [])
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_lockscreen.py"), *args],
        env=env, capture_output=True, text=True, timeout=180)
    said = "\n".join(line for line in done.stderr.splitlines()
                     if "HYPRLAND_INSTANCE_SIGNATURE" not in line)  # no Hyprland here
    assert done.returncode == 0, said[-3000:]
    assert "Traceback" not in done.stderr, said[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == []
    assert r["preview_first"] is True
    assert "руками" in r["state_hand"] and r["restore_hidden"] is True
    assert r["preview_redrawn"] is True and r["file_untouched"] is True
    assert r["options_saved"]["preset"] == "center" and r["options_saved"]["battery"] is True
    assert r["applied"] is True and r["backup_is_hand"] is True
    assert r["history_groups"] == 1
    assert r["written_has_field"] and r["written_keeps_hook"]
    assert r["state_ours"] == "Сейчас стоит вариант отсюда"
    assert r["restore_shown"] is True
    assert r["bare_has_field"] is True and r["bare_has_no_poweroff"] is True
    assert r["undone_to_hand"] is True
    assert r["restored"] is True
