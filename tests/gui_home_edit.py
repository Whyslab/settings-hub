"""The home editor in the real window: tiles, pins and commands follow the settings.

    python3 gui_home_edit.py REPO STATE_DIR OUT.json [SHOTS_DIR]

Run by test_gui_home_edit.py on a private Xvfb with HOME in a temporary folder
and a hyprctl stub that logs its arguments. Not collected by pytest.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, out_path = (Path(a) for a in sys.argv[1:4])
shots = Path(sys.argv[4]) if len(sys.argv) > 4 else None
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub import registry, settings  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def shoot(name: str) -> None:
    if shots is not None:
        spin(0.6)
        subprocess.run(["magick", "import", "-window", "root", str(shots / f"{name}.png")],
                       check=False)


def small_titles(home) -> list[str]:
    """Tooltips of the page buttons at the bottom of the home screen."""
    grid = home.extra.get_last_child()
    out, child = [], grid.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button):
            out.append(child.get_tooltip_text())
        child = child.get_next_sibling()
    return out


errors = []
sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")

app = Gtk.Application(application_id="io.github.whyslab.SettingsHubHomeEdit",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
history = History(state_dir / "history.jsonl")
hub = settings.Settings(state_dir / "settings.json")
settings.register(history, hub)
win = Window(app, history, Workers(), state_dir, {}, settings=hub)
win.set_default_size(920, 1100)
win.present()
win.open_page("")
spin(1.5)
home = win.home
out: dict = {"tiles_start": [t.page_id for t in home.tiles],
             "all_tiles": sorted(home.all_tiles)}
refreshed: list[str] = []
themes_tile = home.all_tiles["themes"]
real_refresh = themes_tile.refresh
themes_tile.refresh = lambda: (refreshed.append("themes"), real_refresh())

home.edit_button.emit("clicked")
spin(0.5)
editor = home.editor
out["edit_child"] = home.stack.get_visible_child_name()
shoot("editor")

# A big tile off, then one moved: the home screen follows, History logs each.
editor._toggle_tile("themes", False)
spin(0.4)
out["tiles_off"] = [t.page_id for t in home.tiles]
out["themes_small"] = registry.title("themes") in small_titles(home)
out["themes_refreshed_off"] = len(refreshed)
editor._move_tile(0, 1)
spin(0.4)
out["tiles_moved"] = [t.page_id for t in home.tiles]
out["tile_rows"] = editor.tiles_group.list.observe_children().get_n_items()

# Pinning from the search.
editor.search.set_text("свой шрифт")
spin(0.8)
out["results"] = editor.results.list.observe_children().get_n_items()
editor._pin("general#appearance.own_font")
editor._pin("panel#clock")
spin(0.4)
out["pins"] = list(home.pin_buttons)
out["pinned_label"] = editor.results.get_visible()

# Commands: a bad one is refused with a note, a good one becomes a tile.
editor.name_entry.set_text("")
editor.cmd_entry.set_text("echo hi")
editor._add_command()
out["bad_note"] = editor.add_note.get_visible()
editor.name_entry.set_text("Привет")
editor.cmd_entry.set_text('echo "hi there"')
editor._add_command()
spin(0.4)
out["commands"] = hub.get("home.commands")
out["entries_cleared"] = editor.name_entry.get_text() == "" and not editor.add_note.get_visible()
shoot("editor-filled")

# Escape leaves the editor; the window stays.
from gi.repository import Gdk  # noqa: E402

editor.cmd_entry.set_text("half typed")
editor.cmd_entry.grab_focus()
spin(0.2)
win._on_key_pressed(None, Gdk.KEY_Escape, 9, Gdk.ModifierType(0))
win._on_key_released(None, Gdk.KEY_Escape, 9, None)
spin(0.2)
out["esc_cleared"] = editor.cmd_entry.get_text() == ""
out["esc_still_editing"] = home.editing
win._on_key_pressed(None, Gdk.KEY_Escape, 9, Gdk.ModifierType(0))
win._on_key_released(None, Gdk.KEY_Escape, 9, None)
spin(0.3)
out["esc_child"] = home.stack.get_visible_child_name()
out["esc_visible"] = win.get_visible()
home.edit(True)
spin(0.3)
editor.done.emit("clicked")
spin(0.4)
out["back_child"] = home.stack.get_visible_child_name()
shoot("home")

# The switch tile flips the setting; Ctrl+Z (History) flips it and the switch back.
own_font = home.pin_switches["appearance.own_font"][0]
out["switch_start"] = own_font.get_active()
home.pin_buttons["general#appearance.own_font"].emit("clicked")
spin(0.4)
out["setting_flipped"] = hub.get("appearance.own_font")
out["switch_flipped"] = home.pin_switches["appearance.own_font"][0].get_active()
history.execute(history.plan_undo_last())
spin(0.4)
out["setting_undone"] = hub.get("appearance.own_font")
out["switch_undone"] = home.pin_switches["appearance.own_font"][0].get_active()

# An open-pin opens its page at its row; a command tile runs through hyprctl.
home.pin_buttons["panel#clock"].emit("clicked")
spin(1.0)
out["opened"] = win.current
win.show_page("home")
spin(0.3)
home.command_buttons[0].emit("clicked")
home.command_buttons[0].emit("clicked")  # a double click
spin(1.0)

# Undo all the list changes: the home screen is back to where it started.
for _ in range(6):
    plan = history.plan_undo_last()
    if plan is None:
        break
    history.execute(plan)
    spin(0.3)
out["tiles_undone"] = [t.page_id for t in home.tiles]
out["themes_refreshed_back"] = len(refreshed) - out["themes_refreshed_off"]
out["pins_undone"] = hub.get("home.pins")
out["file"] = json.loads((state_dir / "settings.json").read_text())
out["errors"] = errors
Path(out_path).write_text(json.dumps(out, ensure_ascii=False))
