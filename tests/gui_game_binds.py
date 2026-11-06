"""Drive the real Game binds page in-process. Run by test_gui_game_binds.py.

    python3 gui_game_binds.py REPO STUBS OUT.json SHOT.png

The caller isolates HOME, puts a stub hyprctl first in PATH (it logs its
arguments to STUBS/calls.log) and gives a private Xvfb and D-Bus session.
Clicks are the buttons' own "clicked" signals; the key press is the capture's
own "key-pressed" signal - no synthetic input. Not collected by pytest.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, stubs, out_path, shot_path = (Path(a) for a in sys.argv[1:5])
sys.path.insert(0, str(repo))
assert (shutil.which("hyprctl") or "").startswith(str(stubs) + "/"), shutil.which("hyprctl")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from settings_hub import pages, strings  # noqa: E402
from settings_hub.backends import game_binds as gb  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.005)


def until(fn, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        spin(0.05)
    return False


def calls() -> list[str]:
    log = stubs / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def rows(group) -> list[tuple[str, str]]:
    out = []
    row = group.list.get_first_child()
    while row is not None:
        out.append((row.title_label.get_label(),
                    row.subtitle_label.get_label() if row.subtitle_label.get_visible() else ""))
        row = row.get_next_sibling()
    return out


def remove_button(group, title: str) -> Gtk.Button:
    row = group.list.get_first_child()
    while row is not None:
        if row.title_label.get_label() == title:
            inner = row.get_child()
            return inner.get_last_child()
        row = row.get_next_sibling()
    raise LookupError(title)


def state() -> dict:
    return json.loads(gb.state_path().read_text())


Gtk.init()
workers = Workers()
history = History(Path(os.environ["XDG_STATE_HOME"]) / "settings-hub" / "history.jsonl")
backend = gb.Backend(workers)
gb.register(history, backend)
statuses: list[str] = []
ctx = pages.Context(history, workers, statuses.append, lambda: None, {gb.BACKEND: backend})
win = Gtk.Window(title="test")
win.set_default_size(760, 1100)
page = pages.create("game-binds", ctx)
win.set_child(page.widget)
win.present()
page.refresh()
r: dict = {}

until(lambda: page._probe.classes)
spin(0.3)
r["calls_on_open"] = calls()
r["switch_on_open"] = page.switch.get_active()
r["games_on_open"] = rows(page.games)
r["combos_on_open"] = rows(page.combos)
r["open_choices"] = page._classes
r["not_loaded_visible"] = page.not_loaded.get_visible()
r["file_written_on_open"] = gb.lua_path().exists()
r["search_rows"] = sorted(page.rows)

page.switch.set_active(True)
until(lambda: gb.state_path().exists())
workers.wait_idle(5)
spin(0.3)
r["enabled_state"] = state()["enabled"]
r["lua_after_on"] = gb.lua_path().read_text()
r["reload_calls"] = [c for c in calls() if c == "hyprctl reload config-only"]

page.open_dropdown.set_selected(page._classes.index("kitty"))
page.open_add.emit("clicked")
workers.wait_idle(5)
page.entry.set_text("  cs2  ")
page.entry.emit("activate")
workers.wait_idle(5)
spin(0.3)
r["entry_after"] = page.entry.get_text()
r["patterns_after_add"] = state()["patterns"]
r["open_choices_after"] = page._classes

remove_button(page.combos, "Super + D").emit("clicked")
workers.wait_idle(5)
spin(0.3)
r["combos_after_remove"] = state()["combos"]

page.capture_inhibit = False  # Xvfb grants no shortcut inhibitor: the submap path
page.press.emit("clicked")
until(lambda: page.capture is not None and page.capture.controller is not None)
display = page.widget.get_display()
ok, keys = display.map_keyval(Gdk.KEY_n)
page.capture.controller.emit("key-pressed", Gdk.KEY_N, keys[0].keycode if ok else 0,
                             Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.SHIFT_MASK)
until(lambda: page.capture is None)
workers.wait_idle(5)
spin(0.5)
r["combos_after_capture"] = state()["combos"]
r["press_label"] = page.press.get_label()
r["combo_rows_after"] = rows(page.combos)
r["history_groups"] = len(history.groups())
r["statuses"] = statuses
r["lua_final"] = gb.lua_path().read_text()

# what a person sees
paintable = Gtk.WidgetPaintable.new(win)
snap = Gtk.Snapshot()
w, h = win.get_width(), win.get_height()
paintable.snapshot(snap, w, h)
node = snap.to_node()
if node is not None:
    win.get_renderer().render_texture(node, None).save_to_png(str(shot_path))
r["strings_ok"] = strings.GB_PRESS == page.press.get_label()

out_path.write_text(json.dumps(r, ensure_ascii=False, indent=1))
workers.stop_all(timeout=1)
