"""Drive the real Wallpaper and Animations pages in-process. Run by test_gui_step3.py.

    python3 gui_step3.py REPO ROOT HISTORY OUT.json

The caller has isolated the environment (step3_env.World's directories: a
temporary HOME with the stub wallpaper.sh, stub wallpaper-theme, magick,
hyprctl in PATH, a copy of rofi_hub in SETTINGS_HUB_ROFI_DIR with a stub
anim-preview.sh), a private Xvfb display and D-Bus session. Widgets are driven
through their own API (emitting "child-activated", set_active, set_selected,
"clicked"), which runs exactly the handlers real input would; no synthetic
input. Results go to OUT.json; the test asserts them.
Not collected by pytest (no test_ prefix): it needs the system's PyGObject.
"""

import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, root, history_path, out_path = (Path(a) for a in sys.argv[1:5])
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from settings_hub import pages, strings  # noqa: E402
from settings_hub.backends import animations as an  # noqa: E402
from settings_hub.backends import wallpaper as wp  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def calls() -> list[str]:
    log = root / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def until(fn, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        spin(0.05)
    return False


Gtk.init()
workers = Workers()
history = History(history_path)
wallpaper = wp.Backend(workers)
animations = an.Backend(workers)
wp.register(history, wallpaper)
an.register(history, animations)
statuses: list[str] = []
backends = {wp.BACKEND: wallpaper, wp.THEME: wallpaper, an.BACKEND: animations}
ctx = pages.Context(history, workers, statuses.append, lambda: None, backends)
win = Gtk.Window(title="test")
win.set_default_size(920, 900)
stack = Gtk.Stack()
win.set_child(stack)
r: dict = {}

# ---- Wallpaper ---------------------------------------------------------------
page = pages.create("wallpaper", ctx)
stack.add_named(page.widget, "wallpaper")
win.present()
spin(0.5)
r["wp_rows"] = sorted(page.rows)
r["wp_tiles"] = [t.image.name for t in page.tiles]
r["wp_textures"] = until(lambda: all(t.picture.get_paintable() for t in page.tiles))
r["wp_thumbs"] = len(list(wallpaper.paths.thumbs.glob("*.jpg")))
r["wp_marked"] = [t.image.name for t in page.tiles if t.has_css_class("sh-current")]
r["wp_theme_active"] = [m for m, b in page.theme_buttons.items() if b.get_active()]
r["wp_theme_hint"] = page.theme_row.subtitle_label.get_label()
r["wp_random"] = {t: s.get_active() for t, s in page.random_switches.items()}

page.target_buttons["lock"].set_active(True)
spin(0.1)
r["wp_marked_lock"] = [t.image.name for t in page.tiles if t.has_css_class("sh-current")]
tile = next(t for t in page.tiles if t.image.name == "graphite.webp")
page.flow.emit("child-activated", tile)
until(lambda: any(c.startswith("wallpaper.sh set") for c in calls()))
spin(0.5)
r["wp_set_calls"] = [c for c in calls() if c.startswith("wallpaper.sh set")]
r["wp_marked_after"] = [t.image.name for t in page.tiles if t.has_css_class("sh-current")]
r["wp_groups"] = [[e.key for e in g.entries] for g in history.groups()]

page.random_switches["sddm"].set_active(True)
until(lambda: "wallpaper.sh random sddm on" in calls())
spin(0.3)
page.theme_buttons["tinted"].set_active(True)
until(lambda: "wallpaper-theme mode tinted" in calls())
spin(0.5)
r["wp_theme_hint_after"] = page.theme_row.subtitle_label.get_label()
r["wp_group_count"] = len(history.groups())
r["wp_statuses"] = statuses[-3:]

# ---- Animations ----------------------------------------------------------------
apage = pages.create("animations", ctx)
stack.add_named(apage.widget, "animations")
stack.set_visible_child_name("animations")
spin(0.5)
r["an_rows"] = sorted(apage.rows)
r["an_tiles"] = [t.choice.name for t in apage.tiles]
r["an_marked"] = [t.choice.id for t in apage.tiles if t.has_css_class("sh-current")]
r["an_preset_hint"] = apage.preset_row.subtitle_label.get_label()
r["an_group_titles"] = [g.heading.get_label() for g in apage._main if g.heading]
dropdown, ids = apage.dropdowns["close"]
r["an_close_selected"] = ids[dropdown.get_selected()]
r["an_speed_layers"] = [s for s, b in apage.speed_buttons["layers"].items() if b.get_active()]

before = len(history.groups())
fade = ids.index("fade")
dropdown.set_selected(fade)
until(lambda: len(history.groups()) > before)
r["an_tuning_after_variant"] = json.loads(
    (Path.home() / ".config" / "rofi-launcher" / "animation-tuning.json").read_text())
apage.speed_buttons["open"]["fast"].set_active(True)
until(lambda: len(history.groups()) > before + 1)
tile = next(t for t in apage.tiles if t.choice.id == "slide")
apage.flow.emit("child-activated", tile)
until(lambda: len(history.groups()) > before + 2)
spin(0.3)
r["an_preset_file"] = (Path.home() / ".config" / "rofi-launcher" / "animation-preset"
                       ).read_text().strip()
r["an_marked_after"] = [t.choice.id for t in apage.tiles if t.has_css_class("sh-current")]
r["an_close_after_preset"] = ids[dropdown.get_selected()]
r["an_conf_exists"] = (Path.home() / ".config" / "hypr" / "animations.conf").is_file()

# Look: the window hides while the script runs and comes back afterwards.
seen_hidden = []
win.connect("notify::visible", lambda w, _p: seen_hidden.append(w.get_visible()))
apage.preview_buttons[1].emit("clicked")  # the first category's button
until(lambda: any(c.startswith("anim-preview.sh") for c in calls()))
spin(0.5)
r["an_preview_calls"] = [c for c in calls() if c.startswith(("anim-preview.sh", "reopen"))]
r["an_visibility"] = seen_hidden
r["an_visible_at_end"] = win.get_visible()
r["an_reloads"] = len([c for c in calls() if c == "hyprctl reload"])
r["an_statuses"] = statuses[-3:]
r["strings_ok"] = strings.AN_PREVIEW != ""

workers.stop_all(2)
out_path.write_text(json.dumps(r, ensure_ascii=False, indent=1))
