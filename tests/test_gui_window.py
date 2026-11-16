"""Window keys on a private Xvfb (live: needs GTK4). See gui_window_keys.py."""

import json
import os
import re
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


@pytest.mark.live
def test_home_tiles_and_the_sidebar_around_them(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "home.json"
    # Every program a tile reads from is a stub that logs and says nothing.
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    for name in ("pactl", "nmcli", "bluetoothctl", "tailscale", "brightnessctl",
                 "powerprofilesctl", "busctl", "wallpaper-theme", "hyprctl", "systemctl",
                 "rfkill", "upower", "notify-send", "hyprsunset", "pgrep", "pkill"):
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >>"{log}"\nexit 0\n')
        stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(PATH=f"{stubs}:{os.environ['PATH']}",
               HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_home.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-3000:]
    r = json.loads(out.read_text())
    tiles = {"current": "home", "child": "home", "sidebar": False, "title": False}
    assert r["open"] == tiles  # the default start page is the tiles
    assert r["focus_on_first_tile"] is True
    assert r["tiles"] == r["tile_pages"]
    assert r["first_row_is_home"] is True
    # Typing on the tiles: the sidebar's search takes the text and shows results.
    assert r["typed"] == dict(tiles, sidebar=True)
    assert r["typed_home_entry"] == ""
    assert r["typed_sidebar_entry"] == "зв"
    assert r["typed_focus_in_sidebar"] is True and r["typed_searching"] is True
    assert r["cleared"] == tiles
    assert r["cleared_focus_in_home_search"] is True
    assert r["click_picked"] == ["a"]
    assert r["click_look_kept"] is True and r["click_locked"] is True
    assert r["click_shown"] is True
    assert r["up_from_first"] == {"current": "screen-sleep", "child": "screen-sleep",
                                  "sidebar": True, "title": True}
    assert r["page"] == {"current": "sound", "child": "sound", "sidebar": True, "title": True}
    assert r["page_selected"] == "sound"
    assert r["back"] == tiles
    assert r["unknown"] == tiles
    assert r["last_page"] == "power"
    # Opening, searching and walking pages changed nothing: no History, only reads.
    assert r["history_groups"] == 0
    calls = log.read_text().splitlines() if log.exists() else []
    assert calls, "the tiles read nothing: the stubs were not used"
    writes = [c for c in calls if re.search(
        r"\bset-|\bset\b|radio \w+ (on|off)|power (on|off)|dispatch|keyword|eval", c)]
    assert not writes, writes


@pytest.mark.live
def test_window_starts_with_remember_size_on(tmp_path, xvfb):  # noqa: F811
    """With "remember the size" on the window did not start at all (16.11.2026)."""
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    (state / "window.json").write_text('{"width": 1111, "height": 777}\n')
    config = home / ".config" / "settings-hub"
    config.mkdir(parents=True)
    (config / "settings.json").write_text('{"appearance.remember_size": true}\n')
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "size.json"
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
         str(ROOT / "tests" / "gui_window_size.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-3000:]
    assert json.loads(out.read_text()) == {"width": 1111, "height": 777}
