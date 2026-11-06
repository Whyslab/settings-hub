"""The Game binds page on a private Xvfb with a stub hyprctl (live: needs GTK4)."""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

BINDS = json.dumps([
    {"modmask": 64, "key": "V", "submap": "", "has_description": True,
     "description": "Окно плавает", "dispatcher": "function: 0x1", "arg": "19"},
    {"modmask": 65, "key": "N", "submap": "", "has_description": False,
     "description": "", "dispatcher": "HL.Dispatcher(exec_cmd)", "arg": "4"},
])
CLIENTS = json.dumps([{"class": "kitty"}, {"class": "dota2"}, {"class": "firefox"},
                      {"class": "steam_app_570"}, {"class": "io.github.whyslab.SettingsHub"}])


@pytest.mark.live
def test_game_binds_page(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    (home / ".local" / "state" / "settings-hub").mkdir(parents=True)
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = stubs / "calls.log"
    hyprctl = stubs / "hyprctl"
    hyprctl.write_text(f"""#!/bin/sh
echo "hyprctl $*" >>"{log}"
case "$*" in
  "binds -j") echo '{BINDS}' ;;
  "clients -j") echo '{CLIENTS}' ;;
  *) echo ok ;;
esac
""")
    hyprctl.chmod(0o755)
    out = tmp_path / "out.json"
    shot = tmp_path / "page.png"
    env = {k: v for k, v in os.environ.items() if k != "WAYLAND_DISPLAY"}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), XDG_RUNTIME_DIR=str(tmp_path),
               HYPRLAND_INSTANCE_SIGNATURE="test-not-real",  # reloads go to the stub
               DISPLAY=xvfb, GDK_BACKEND="x11", GSK_RENDERER="cairo", NO_AT_BRIDGE="1",
               GTK_A11Y="none", PYTHONDONTWRITEBYTECODE="1",
               PATH=f"{stubs}:{os.environ['PATH']}")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_game_binds.py"), str(ROOT), str(stubs), str(out), str(shot)],
        env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "Gtk-CRITICAL" not in done.stderr, done.stderr[-3000:]
    r = json.loads(out.read_text())
    if os.environ.get("GB_SHOT"):
        shot.replace(os.environ["GB_SHOT"])

    # Opening the page reads and changes nothing.
    assert r["calls_on_open"] == ["hyprctl binds -j", "hyprctl clients -j"]
    assert r["file_written_on_open"] is False
    assert r["switch_on_open"] is False
    assert r["games_on_open"] == [["dota2", ""], ["steam_app_*", ""]]
    assert r["combos_on_open"] == [["Super + V", "Окно плавает"],
                                   ["Super + D", "Сейчас ни на что не назначено"]]
    assert r["open_choices"] == ["firefox", "kitty"]  # games and our own window left out
    assert r["not_loaded_visible"] is True  # no settings-hub.lua in this home
    assert {"enabled", "games", "combos"} <= set(r["search_rows"])

    # Switching on writes the list and reloads Hyprland once.
    assert r["enabled_state"] is True
    assert 'local combos = { "SUPER + V", "SUPER + D" }' in r["lua_after_on"]
    assert r["reload_calls"] == ["hyprctl reload config-only"]

    assert r["patterns_after_add"] == ["dota2", "steam_app_*", "kitty", "cs2"]
    assert r["entry_after"] == ""
    assert r["open_choices_after"] == ["firefox"]
    assert r["combos_after_remove"] == ["SUPER + V"]

    assert r["combos_after_capture"] == ["SUPER + V", "SUPER + SHIFT + N"]
    assert r["press_label"] == "Нажать сочетание"
    assert r["combo_rows_after"] == [["Super + V", "Окно плавает"],
                                     ["Super + Shift + N", "Назначено (без описания)"]]
    assert r["history_groups"] == 5
    assert 'local combos = { "SUPER + V", "SUPER + SHIFT + N" }' in r["lua_final"]
    assert shot.exists() or os.environ.get("GB_SHOT")
