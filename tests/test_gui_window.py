"""Window keys on a private Xvfb (live: needs GTK4). See gui_window_keys.py."""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

from settings_hub import strings


@pytest.mark.live
def test_ctrl_letters_work_in_the_russian_layout(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "keys.json"
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_window_keys.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["focus_on_open_in_search"] is False
    assert r["ru_ctrl_f_handled"] is True and r["ru_ctrl_f_search"] is True
    assert r["us_ctrl_f_handled"] is True and r["us_ctrl_f_search"] is True
    assert r["plain_ru_a_handled"] is False and r["plain_ru_a_search"] is False
    assert r["ru_ctrl_z_handled"] is True
    assert r["status_after_undo"] == strings.HISTORY_NOTHING_TO_UNDO
