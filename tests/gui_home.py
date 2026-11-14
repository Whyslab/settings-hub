"""The home tiles and the sidebar around them, in-process. Run by test_gui_window.py.

    python3 gui_home.py REPO STATE_DIR OUT.json

The caller isolates the environment (temporary HOME, private Xvfb and D-Bus,
no Wayland or Hyprland variables, logging stubs first in PATH). Nothing is
applied: the click below goes to a strip of its own, not to a tile.
Not collected by pytest (no test_ prefix): it needs the system's PyGObject.
"""

import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, out_path = (Path(a) for a in sys.argv[1:4])
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub.history import History  # noqa: E402
from settings_hub.home import HOME, TILE_PAGES, Seg  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def snapshot() -> dict:
    return {
        "current": win.current,
        "child": win.stack.get_visible_child_name(),
        "sidebar": win.sidebar.get_visible(),
        "title": win.title.get_visible(),
    }


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
win = Window(app, History(state_dir / "history.jsonl"), Workers(), state_dir, {})
win.open_page("")
spin(1.0)
r: dict = {"open": snapshot()}
r["focus_on_first_tile"] = win.get_focus() is win.home.tiles[0].top.get_first_child()
r["tiles"] = [t.page_id for t in win.home.tiles]
r["tile_pages"] = list(TILE_PAGES)
r["first_row_is_home"] = win.sidebar.list.get_row_at_index(0).page_id == HOME

win.home.entry.set_text("зв")  # typed on the tiles
spin(0.6)
r["typed"] = snapshot()
r["typed_home_entry"] = win.home.entry.get_text()
r["typed_sidebar_entry"] = win.sidebar.entry.get_text()
r["typed_focus_in_sidebar"] = win.sidebar.contains_focus(win.get_focus())
r["typed_searching"] = win.sidebar.searching

win.sidebar.clear_search()
spin(0.6)
r["cleared"] = snapshot()
focus = win.get_focus()
r["cleared_focus_in_home_search"] = focus is not None and (
    focus is win.home.entry or focus.is_ancestor(win.home.entry))

# A click on a strip button: the look stays, the button waits for the refresh.
picked: list[str] = []
seg = Seg([("a", "A"), ("b", "B")], picked.append)
seg.buttons["a"].set_active(True)
r["click_picked"] = picked
r["click_look_kept"] = seg.buttons["a"].get_active() is False
r["click_locked"] = not seg.buttons["a"].get_sensitive()
seg.show({"a"})  # the refresh
r["click_shown"] = seg.buttons["a"].get_active() and seg.buttons["a"].get_sensitive()

win.show_page("sound")
spin(0.3)
r["page"] = snapshot()
r["page_selected"] = win.sidebar.list.get_selected_row().page_id

# Up from the first page in the list moves onto "Home" but does not open it.
win.show_page("screen-sleep")
spin(0.2)
win.sidebar.list.get_selected_row().grab_focus()
win.sidebar.list.emit("move-cursor", Gtk.MovementStep.DISPLAY_LINES, -1, False, False)
spin(0.3)
r["up_from_first"] = snapshot()

win.sidebar.list.emit("row-activated", win.sidebar.list.get_row_at_index(0))  # "Home"
spin(0.3)
r["back"] = snapshot()

win.show_page("no-such-page")
spin(0.2)
r["unknown"] = snapshot()

r["history_groups"] = len(win.history.groups())  # before the settings change below
win.settings.set("behavior.start_page", "last")
win.show_page("power")
win.set_visible(False)  # unmap: remembers the page
spin(0.3)
win.current = None
r["last_page"] = win.start_page()
Path(out_path).write_text(json.dumps(r))
