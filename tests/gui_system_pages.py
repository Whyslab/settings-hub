"""Build the real Sound and Network pages in-process. Run by test_gui_system.py.

    python3 gui_system_pages.py REPO STATE_DIR OUT.json

The caller isolates the environment and puts stub pactl, nmcli, bluetoothctl and
tailscale first in PATH; each stub logs its arguments. Not collected by pytest.
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
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from settings_hub import registry, settings  # noqa: E402
from settings_hub.backends import audio, network  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.variables import Var  # noqa: E402
from settings_hub.widgets import fields  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def inside(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.get_parent()
    return False


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
backends = {audio.BACKEND: audio.Backend(workers), network.BACKEND: network.Backend(workers)}
audio.register(history, backends[audio.BACKEND])
network.register(history, backends[network.BACKEND])
win = Window(app, history, workers, state_dir, backends,
             settings=settings.Settings(state_dir / "settings.json"))
win.show_page("sound")
spin(2)
win.show_page("network")
spin(2)
net = win._pages["network"]
net.refresh()
spin(2)
sound = win._pages["sound"]

# SUPER+I on a window that is on screen stays on its page; a hidden one starts over.
win.present()
spin(0.5)
win.open_page("")
spin(0.2)
kept_page = win.current
win.set_visible(False)
win.settings.set("behavior.start_page", "sound")
win.open_page("")
spin(0.2)
start_page = win.current
win.show_page("network")
spin(0.2)

# Ctrl+Z: a text field keeps it, elsewhere it is the window's undo.
undone = []
real_undo = win.undo_last
win.undo_last = lambda: undone.append(True)
ZKEY = Gdk.KEY_z
ZCODE = 52  # evdev z + 8
win.set_focus(win.sidebar.entry)
spin(0.2)
search_kept = (win._on_key_pressed(None, ZKEY, ZCODE, Gdk.ModifierType.CONTROL_MASK) is False
               and not undone)
win.set_focus(net.wifi_switch)
spin(0.2)
window_undo = (win._on_key_pressed(None, ZKEY, ZCODE, Gdk.ModifierType.CONTROL_MASK) is True
               and undone == [True])
win.undo_last = real_undo

# A text field applies on Enter only.
applied = []
control = fields.make(Var("input:kb_layout", "str", ""), lambda *a: applied.append(a))
holder = Gtk.Window()
line = Gtk.Box()
line.append(control.widget)
other = Gtk.Button()
line.append(other)
holder.set_child(line)
holder.present()
spin(0.3)
control.entry.grab_focus()
spin(0.1)
control.entry.set_text("half")
other.grab_focus()
spin(0.2)
applied_on_leave = len(applied)
control.entry.emit("activate")
spin(0.1)
applied_on_enter = len(applied)
focus_after_enter = holder.get_focus()
holder.destroy()

# Wi-Fi off asks first; the real dialog closed by hand counts as "no".
win.present()
spin(0.3)
before = set(Gtk.Window.list_toplevels())
net.wifi_switch.set_active(False)
spin(0.5)
dialogs = [w for w in Gtk.Window.list_toplevels() if w not in before]
asked = len(dialogs)
for dialog in dialogs:
    dialog.close()
spin(0.5)
wifi_back_on = net.wifi_switch.get_active()

history_groups = len(history.groups())  # opening the pages must log nothing

# An active mode offers "Turn off", which undoes the group that turned it on.
history.record([("hypr", "general:gaps_in", "Отступы", 4, 0),
                ("hypr", "decoration:rounding", "Скругление", 12, 0)])
mode_group = history.groups()[-1].id
win.show_page("modes")
spin(0.5)
modes_page = win._pages["modes"]
undone_groups = []
modes_page.ctx.undo_group = undone_groups.append
modes_page.show_active({"game"})
_row, off_button = modes_page.buttons["game"]
off_label, off_sensitive = off_button.get_label(), off_button.get_sensitive()
off_button.emit("clicked")
modes_page.show_active(set())
on_label = off_button.get_label()

out = {
    "off_label": off_label,
    "off_sensitive": off_sensitive,
    "undone_groups": undone_groups,
    "mode_group": mode_group,
    "on_label": on_label,
    "kept_page": kept_page,
    "start_page": start_page,
    "search_kept": search_kept,
    "window_undo": window_undo,
    "applied_on_leave": applied_on_leave,
    "applied_on_enter": applied_on_enter,
    "focus_after_enter_is_none": focus_after_enter is None,
    "asked": asked,
    "wifi_back_on": wifi_back_on,
    "history_groups": history_groups,
    "sink_selected": sound.kinds["sink"].dropdown.get_selected(),
    "source_selected": sound.kinds["source"].dropdown.get_selected(),
    "source_names": sound.kinds["source"].names,
    "bt_switch_in_group": inside(net.bt_switch, net.bt_group),
    "missing_rows": {p.id: [r for r in registry.rows(p.id)
                            if p.id in win._pages and r not in win._pages[p.id].rows]
                     for p in registry.PAGES},
}
out_path.write_text(json.dumps(out))
