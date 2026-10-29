"""The real Binds page on a private Xvfb (live: needs this machine's GTK4).

Isolation as in plan section 4 (binds_env.World and test_gui.xvfb): a copy of
hyprland.conf in a temporary HOME, the stub hyprctl, a private D-Bus session.
Key presses reach the capture through its own key controller's signal (see
gui_binds.py); no synthetic input is sent to any display.
"""

import json
import os
import subprocess

import pytest
from binds_env import World
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name

from settings_hub import strings


def run(world: World, display: str, tmp_path) -> dict:
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "gui.json"
    env = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11", GSK_RENDERER="cairo",
               NO_AT_BRIDGE="1", GTK_A11Y="none", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_binds.py"), str(ROOT), str(world.root),
         str(tmp_path / "history.jsonl"), str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(out.read_text())


@pytest.mark.live
def test_binds_page(tmp_path, monkeypatch, xvfb):  # noqa: F811
    world = World(tmp_path / "w", monkeypatch, capture_ready=True)
    try:
        r = run(world, xvfb, tmp_path)
    finally:
        world.close()
    # 65 combinations from the file, plus the capture submap's bind that only the
    # live list has (settings-hub.conf is not in this HOME yet).
    assert r["rows"] == 66 and r["setup_visible"] is False
    assert r["groups"][:2] == [strings.BN_GROUPS["apps"], strings.BN_GROUPS["windows"]]
    assert r["groups"][-1] == strings.BN_GROUPS["live"]
    assert {"list", "add"} <= set(r["search_rows"])
    assert r["alt_keys"] == "Alt + Tab"
    assert r["alt_menu"] == ["disable", "disable.0", "disable.1", "rebind"]
    assert r["search_visible"] == ["SUPER SHIFT, T"]
    # Capture: the fallback (no inhibitor on X11), then Super+Shift+K.
    assert r["capturing_label"] == strings.BN_PRESS and r["is_capturing"] is True
    assert r["mode"] == "submap" and r["token_during"] is True
    assert r["calls_during"][-2] == "hyprctl dispatch submap settings-hub-capture"
    assert r["calls_during"][-1].startswith("hyprctl dispatch exec sleep 15; ")
    assert r["modifier_only"] is True and r["still_capturing"] is True
    assert r["handled"] is True
    assert r["captured"] == ["Super + Shift + K"]
    assert r["captured_raw"] == [["ALT, Tab", 65, "K"]]
    assert r["block"] == ["unbind = ALT, Tab  # hyprland.conf:138",
                          "bind = SUPER SHIFT, K, cyclenext,  # hyprland.conf:138",
                          "bind = SUPER SHIFT, K, bringactivetotop,  # hyprland.conf:139"]
    assert r["token_after"] is False and r["is_capturing_after"] is False
    after = r["calls_after"][len(r["calls_during"]):]
    assert after[0] == "hyprctl dispatch submap reset"
    assert after[1:4] == ["hyprctl configerrors", "hyprctl reload", "hyprctl configerrors"]
    assert strings.BN_MOVED_FROM.format(combo="Alt + Tab") in r["new_row_detail"]
    assert "revert" in r["new_row_menu"]
    assert r["history"] == [["ALT, Tab", "SUPER SHIFT, K"]]
    # Esc: nothing written, the submap is left again.
    assert r["esc_block_same"] is True and r["esc_label"] == "Super + E"
    assert r["esc_calls"][-1] == "hyprctl dispatch submap reset"
    assert not any("reload" in c for c in r["esc_calls"])
    # An occupied combination asks with the occupant's name, writes nothing yet.
    assert r["asks"] == [["Super + C", strings.BN_DISPATCHERS["killactive"]]]
    assert r["block_after_ask"] is True
    # Add.
    assert r["add_keys"] == "Super + Ctrl + N" and r["add_sensitive"] is True
    assert r["add_block"] == ["bind = SUPER CTRL, N, exec, kitty --title notes  # settings-hub"]
    # Lua: read-only, nothing written.
    assert r["lua_is_bn_lua"] is True
    assert r["lua_menus"] is False and r["lua_add"] is False and r["lua_block_same"] is True
