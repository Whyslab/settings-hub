"""The real Wallpaper and Animations pages on a private Xvfb (live: needs GTK4).

Isolation as in plan section 4 (see test_gui.py and step3_env.py). Real magick
makes the thumbnails here -- into the temporary HOME's cache, never the real
one; everything else is a stub. No synthetic input.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT, load_json
from step3_env import World
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name


def run(world: World, display: str, tmp_path) -> dict:
    (world.stubs / "magick").unlink()  # real thumbnails, written under tmp_path
    for t, name in (("desktop", "amber.jpg"), ("lock", "forest.png"), ("sddm", "amber.jpg")):
        (world.state / f"{t}.path").write_text(str(world.library / name) + "\n")
    (world.state / "random.conf").write_text("desktop=off\nlock=off\nsddm=off\n")
    (world.root / "theme-mode").write_text("vivid\n")
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "gui.json"
    env = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11", GSK_RENDERER="cairo",
               NO_AT_BRIDGE="1", GTK_A11Y="none", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_step3.py"), str(ROOT), str(world.root),
         str(tmp_path / "history.jsonl"), str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(out.read_text())


@pytest.mark.live
def test_wallpaper_and_animations_pages(tmp_path, monkeypatch, xvfb):  # noqa: F811
    world = World(tmp_path / "w", monkeypatch)
    try:
        r = run(world, xvfb, tmp_path)
    finally:
        world.close()
    labels = load_json("labels_ru.json")
    # Wallpaper.
    assert {"target", "grid", "rofi", "random"} <= set(r["wp_rows"])
    assert "theme" not in r["wp_rows"]  # moved to the Themes page
    assert r["wp_tiles"] == ["amber.jpg", "blue-dusk.jpg", "forest.png", "graphite.webp",
                             "plasma.jpg"]
    assert r["wp_textures"] is True and r["wp_thumbs"] == 5
    assert r["wp_marked"] == ["amber.jpg"] and r["wp_marked_lock"] == ["forest.png"]
    lib = world.library
    assert r["wp_set_calls"] == [f"wallpaper.sh set lock {lib / 'graphite.webp'}"]
    assert r["wp_marked_after"] == ["graphite.webp"]
    assert r["wp_groups"] == [["wallpaper.lock"]]
    assert r["wp_group_count"] == 2  # picture, random
    # Animations.
    assert {"presets", "open", "close", "workspaces", "layers"} <= set(r["an_rows"])
    assert labels["preset_dissolve"] in r["an_tiles"]
    assert labels["category_open"] in r["an_group_titles"]
    assert r["an_marked"] == ["dissolve"]
    assert r["an_close_selected"] == "mosaic" and r["an_speed_layers"] == ["slow"]
    assert r["an_tuning_after_variant"]["overrides"]["close"] == "fade"
    assert r["an_preset_file"] == "slide" and r["an_marked_after"] == ["slide"]
    assert r["an_close_after_preset"] is None  # a preset resets the categories
    assert r["an_conf_exists"] is True and r["an_reloads"] == 3
    assert r["an_preview_calls"] == ["anim-preview.sh cat open var -", "reopen 0"]
    assert r["an_visibility"][:1] == [False] and r["an_visible_at_end"] is True
