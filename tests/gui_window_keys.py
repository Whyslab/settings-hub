"""Drive the real Window's key controller in-process. Run by test_gui_window.py.

    python3 gui_window_keys.py REPO STATE_DIR OUT.json

The caller isolates the environment (temporary HOME, private Xvfb and D-Bus,
no Wayland or Hyprland variables). Keys are emitted on the window's own
EventControllerKey with the keycode of the Latin letter and the keyval the
Russian layout would give (Cyrillic_a for the F key), which is what Hyprland
delivers with "ru" active. No synthetic input reaches any display.
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
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
win = Window(app, History(state_dir / "history.jsonl"), Workers(), state_dir, {})
win.open_page("history")
spin(0.5)
controllers = win.observe_controllers()
keys = next(controllers.get_item(i) for i in range(controllers.get_n_items())
            if isinstance(controllers.get_item(i), Gtk.EventControllerKey))
display = win.get_display()
CTRL = Gdk.ModifierType.CONTROL_MASK


def press(latin: int, keyval: int, state=CTRL) -> bool:
    ok, found = display.map_keyval(latin)
    handled = keys.emit("key-pressed", keyval, found[0].keycode, state)
    keys.emit("key-released", keyval, found[0].keycode, state)
    spin(0.1)
    return handled


def in_search() -> bool:
    return win._in_search_field(win.get_focus())


r: dict = {"focus_on_open_in_search": in_search()}
r["ru_ctrl_f_handled"] = press(Gdk.KEY_f, Gdk.KEY_Cyrillic_a)
r["ru_ctrl_f_search"] = in_search()
win.sidebar.focus_list()
spin(0.1)
r["us_ctrl_f_handled"] = press(Gdk.KEY_f, Gdk.KEY_f)
r["us_ctrl_f_search"] = in_search()
win.sidebar.focus_list()
spin(0.1)
r["plain_ru_a_handled"] = press(Gdk.KEY_f, Gdk.KEY_Cyrillic_a, Gdk.ModifierType(0))
r["plain_ru_a_search"] = in_search()
r["status_before_undo"] = win.status.get_visible()
r["ru_ctrl_z_handled"] = press(Gdk.KEY_z, Gdk.KEY_Cyrillic_ya)
r["status_after_undo"] = win.status.get_label() if win.status.get_visible() else ""
Path(out_path).write_text(json.dumps(r))
