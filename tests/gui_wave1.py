"""Wi-Fi joining, Bluetooth devices, the mixer and undo/redo in the real window.

    python3 gui_wave1.py REPO STATE_DIR OUT.json [SHOTS_DIR]

Run by test_gui_wave1.py on a private Xvfb with a stub pactl and nmcli first in
PATH. NetworkManager and BlueZ are fakes passed to the backends: nothing here
reaches the system bus. Not collected by pytest.
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
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from settings_hub import settings, strings  # noqa: E402
from settings_hub.backends import audio, bluez, network, nm_wifi  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


def shoot(name: str) -> None:
    if shots is not None:
        spin(0.6)
        subprocess.run(["magick", "import", "-window", "root", str(shots / f"{name}.png")],
                       check=False)


class FakeJoiner:
    def __init__(self):
        self.attempts = []

    def join(self, ssid, password="", hidden=False, expect=""):
        self.attempts.append((ssid, password, hidden, expect))
        time.sleep(0.2)
        if password == "wrong-pass":
            raise nm_wifi.JoinError(strings.NET_JOIN_BAD_PASSWORD)
        return nm_wifi.Joined(ssid)


HCI = "/org/bluez/hci0"
PODS = HCI + "/dev_08_E6_4B_B6_58_20"
MOUSE = HCI + "/dev_AA_BB_CC_DD_EE_01"


class FakeBluez:
    def __init__(self):
        self.calls = []
        self.connected = False
        self.discovering = False

    def __call__(self, path, iface, method, args, reply, timeout):
        self.calls.append((path, method))
        if method == "GetManagedObjects":
            objects = {
                HCI: {bluez.ADAPTER: {"Powered": True, "Discovering": self.discovering}},
                PODS: {bluez.DEVICE: {"Address": "08:E6:4B:B6:58:20", "Alias": "AirPods",
                                      "Paired": True, "Connected": self.connected,
                                      "Adapter": HCI},
                       bluez.BATTERY: {"Percentage": 80}},
            }
            if self.discovering:
                objects[MOUSE] = {bluez.DEVICE: {"Address": "AA:BB:CC:DD:EE:01",
                                                 "Alias": "Mouse", "Name": "Mouse",
                                                 "Paired": False, "Adapter": HCI}}
            return (objects,)
        if method == "Connect":
            self.connected = True
        elif method == "StartDiscovery":
            self.discovering = True
        elif method == "StopDiscovery":
            self.discovering = False
        return ()


class KV:
    """A History applier over a dict, for Ctrl+Z / Ctrl+Shift+Z."""

    def __init__(self):
        self.values = {"a": 1, "b": 10}

    def read(self, keys):
        return {k: self.values.get(k) for k in keys}

    def apply(self, values):
        self.values.update(values)


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubWave1",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
joiner = FakeJoiner()
fake_bt = FakeBluez()
backends = {
    audio.BACKEND: audio.Backend(workers),
    network.BACKEND: network.Backend(workers, joiner=joiner),
    "bluez": bluez.Backend(workers, call=fake_bt, variant=lambda k, v: (k, v)),
}
audio.register(history, backends[audio.BACKEND])
network.register(history, backends[network.BACKEND])
kv = KV()
history.register("kv", kv)
win = Window(app, history, workers, state_dir, backends,
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 900)
win.present()
out: dict = {}

# ---- Wi-Fi --------------------------------------------------------------------
win.show_page("network")
spin(2.5)
net = win._pages["network"]
buttons = net._join_buttons
out["join_widgets"] = {ssid: [type(b).__name__, b.get_sensitive(), b.get_label()]
                       for ssid, b in buttons.items()}
titles = {}
row = net.visible_group.list.get_first_child()
while row is not None:
    titles[row.title_label.get_label()] = row.subtitle_label.get_label()
    row = row.get_next_sibling()
out["visible_titles"] = list(titles)
out["twin_subtitle"] = titles.get("Twin", "")
work_tip = buttons.get("Work").get_tooltip_text() if "Work" in buttons else None
out["work_tip"] = work_tip
shoot("network")

# An open password form survives a redraw; closing it forgets what was typed.
form_button = buttons["Neighbour"]
form = form_button.get_popover()
form_button.popup()
spin(0.5)
entry = [w for w in walk(form) if isinstance(w, Gtk.PasswordEntry)][0]
entry.set_text("half-typed")
net.controller.refresh()
spin(1.5)
out["form_kept"] = [form.get_visible(), entry.get_text(),
                    net._join_buttons.get("Neighbour") is form_button]
form.popdown()
spin(0.8)
out["form_cleared"] = entry.get_text()
out["redrawn_after_close"] = net._join_buttons.get("Neighbour") is not form_button
buttons = net._join_buttons
groups_before = len(history.groups())
def submit_form(ssid: str, text: str) -> None:
    """Open the network's form, type the password, press Enter."""
    button = net._join_buttons[ssid]
    button.popup()
    spin(0.4)
    field = [w for w in walk(button.get_popover()) if isinstance(w, Gtk.PasswordEntry)][0]
    field.set_text(text)
    field.emit("activate")


submit_form("Neighbour", "wrong-pass")
out["joining_label"] = buttons["Neighbour"].get_label()
spin(2.5)
out["join_error"] = net._join_errors.get("Neighbour")
reopened = net._join_buttons.get("Neighbour")
out["reopened"] = bool(reopened and reopened.get_popover().get_visible())
shoot("network-wrong-password")
if reopened:
    reopened.get_popover().popdown()
out["groups_after_failure"] = len(history.groups()) - groups_before
submit_form("Neighbour", "right-pass-1")
spin(2.5)
last = history.groups()[-1]
out["joined_entry"] = [last.entries[0].key, last.entries[0].after]
out["join_error_cleared"] = "Neighbour" not in net._join_errors
out["attempts"] = joiner.attempts

# ---- Bluetooth ------------------------------------------------------------------
bt_rows = [r for r in net._bt_rows]
out["bt_titles"] = [r.title_label.get_label() for r in bt_rows]
out["bt_subtitles"] = [r.subtitle_label.get_label() for r in bt_rows]
box = bt_rows[0].get_child().get_last_child()
connect_button = box.get_first_child()
out["bt_button"] = connect_button.get_label()
connect_button.emit("clicked")
spin(1.5)
out["bt_after_connect"] = [r.subtitle_label.get_label() for r in net._bt_rows]
net.search_button.emit("clicked")
spin(1.0)
out["search_label"] = net.search_button.get_label()
spin(3.5)  # one tick: the found device shows up
out["found"] = [r.title_label.get_label() for r in net._found_rows]
shoot("network-bluetooth")
out["found_subtitle"] = (net._found_rows[0].subtitle_label.get_label()
                         if net._found_rows else "")
asked = []
net.confirm = lambda message, detail, ok, on_yes, on_no=None: (
    asked.append((message, detail)), on_yes())
pair_button = net._found_rows[0].get_child().get_last_child() if net._found_rows else None
if pair_button is not None:
    pair_button.emit("clicked")
    spin(1.5)
out["pair_asked"] = asked
out["searching_after_pair"] = net.bt.searching
out["bt_calls"] = [m for _p, m in fake_bt.calls if m != "GetManagedObjects"]

# ---- the mixer ------------------------------------------------------------------
win.show_page("sound")
spin(2.5)
sound = win._pages["sound"]
out["apps"] = list(sound.app_rows)
out["apps_subtitles"] = [r.row.subtitle_label.get_label() for r in sound.app_rows.values()]
out["recorders"] = sound.recorders_label.get_label()
shoot("sound")
firefox = sound.app_rows.get("Firefox")
if firefox is not None:
    firefox.scale.set_value(55)
    spin(2.0)  # settles after 600 ms, then the commit reads the stream back
last = history.groups()[-1]
out["mixer_entry"] = [last.entries[0].key, last.entries[0].before, last.entries[0].after]

# ---- Ctrl+Z twice, Ctrl+Shift+Z ---------------------------------------------------
history.record([("kv", "a", "a", 1, 2)])
kv.values["a"] = 2
history.record([("kv", "b", "b", 10, 20)])
kv.values["b"] = 20
win.set_focus(None)
z, code = Gdk.KEY_z, 52
ctrl = Gdk.ModifierType.CONTROL_MASK
shift = Gdk.ModifierType.SHIFT_MASK
win._on_key_pressed(None, z, code, ctrl)
spin(0.3)
out["after_one_undo"] = dict(kv.values)
win._on_key_pressed(None, z, code, ctrl)
spin(0.3)
out["after_two_undos"] = dict(kv.values)
win._on_key_pressed(None, Gdk.KEY_Z, code, ctrl | shift)
spin(0.3)
out["after_redo"] = dict(kv.values)
win._on_key_pressed(None, Gdk.KEY_y, 29, ctrl)  # Ctrl+Y: the same
spin(0.3)
out["after_ctrl_y"] = dict(kv.values)
out["status"] = win.status.get_label()

workers.stop_all(timeout=1)
out_path.write_text(json.dumps(out, ensure_ascii=False))
