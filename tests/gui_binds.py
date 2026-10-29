"""Drive the real Binds page in-process. Run by test_gui_binds.py.

    python3 gui_binds.py REPO ROOT HISTORY OUT.json

The caller has isolated the environment (binds_env.World: a temporary HOME with
a copy of hyprland.conf, the stub hyprctl first in PATH, XDG_RUNTIME_DIR in the
temporary directory), a private Xvfb display and D-Bus session.

No synthetic input: a key press is delivered by emitting the capture's own
Gtk.EventControllerKey "key-pressed" signal with a keyval, the display's
keycode for it and a modifier state - exactly the handler a real press runs.
Results go to OUT.json; the test asserts them. Not collected by pytest.
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
repo, root, history_path, out_path = (Path(a) for a in sys.argv[1:5])
sys.path.insert(0, str(repo))

# Never the real hyprctl: the stub must be what PATH finds.
assert (shutil.which("hyprctl") or "").startswith(str(root) + "/"), shutil.which("hyprctl")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from settings_hub import pages, strings  # noqa: E402
from settings_hub.backends import binds as bb  # noqa: E402
from settings_hub.binds import capture, names  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.widgets import keycapture  # noqa: E402
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
    log = root / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def block() -> list[str]:
    own = Path.home() / ".config" / "hypr" / "settings-hub.conf"
    if not own.exists():
        return []
    text = own.read_text()
    return [x for x in text.split("# >>> settings-hub binds")[1]
            .split("# <<< settings-hub binds")[0].splitlines() if x.strip()]


def press(page, keyval: int, state: Gdk.ModifierType) -> bool:
    display = page.widget.get_display()
    ok, keys = display.map_keyval(Gdk.keyval_to_lower(keyval))
    keycode = keys[0].keycode if ok and keys else 0
    return page.capture.controller.emit("key-pressed", keyval, keycode, state)


SUPER = Gdk.ModifierType.SUPER_MASK
SHIFT = Gdk.ModifierType.SHIFT_MASK

Gtk.init()
workers = Workers()
history = History(history_path)
backend = bb.Backend(workers)
bb.register(history, backend)
statuses: list[str] = []
ctx = pages.Context(history, workers, statuses.append, lambda: None, {bb.BACKEND: backend})
win = Gtk.Window(title="test")
win.set_default_size(920, 900)
page = pages.create("binds", ctx)
win.set_child(page.widget)
win.present()
r: dict = {}

until(lambda: len(page.bind_rows) > 0)
spin(0.3)
r["rows"] = len(page.bind_rows)
r["groups"] = [g.heading.get_label() for g in page._groups]
r["setup_visible"] = page.setup_group.get_visible()
r["search_rows"] = sorted(page.rows)
alt = page.bind_rows["ALT, Tab"]
r["alt_title"] = alt.title_label.get_label()
r["alt_keys"] = alt.keys.get_label()
r["alt_menu"] = sorted(alt.items)

page.search.set_text("timer.py")
until(lambda: not page.bind_rows["SUPER, Q"].get_visible())
r["search_visible"] = [i for i, row in page.bind_rows.items() if row.get_visible()]
page.search.set_text("")
until(lambda: page.bind_rows["SUPER, Q"].get_visible())

# ---- rebind ALT+Tab by capturing Super+Shift+K --------------------------------
captured: list = []
original = page.controller.rebind


def recording_rebind(row_id, mask, key, replace=False):
    captured.append((row_id, mask, key, names.combo_label(mask, key)))
    original(row_id, mask, key, replace)


page.controller.rebind = recording_rebind
page.start_rebind("ALT, Tab")
r["capturing_label"] = alt.keys.get_label()
r["is_capturing"] = keycapture.is_capturing(win)
spin(0.6)  # X11 never grants the inhibitor: after 300 ms the fallback runs
r["mode"] = page.capture.mode
token_file = capture.token_path()
r["token_during"] = token_file.exists() and len(token_file.read_text().strip()) == 32
r["calls_during"] = calls()
r["modifier_only"] = press(page, Gdk.KEY_Shift_L, SHIFT)
r["still_capturing"] = page.capture is not None
r["handled"] = press(page, Gdk.KEY_K, SUPER | SHIFT)
r["captured"] = [c[3] for c in captured]
r["captured_raw"] = [list(c[:3]) for c in captured]
until(lambda: len(block()) >= 3)
spin(0.3)
r["block"] = block()
r["token_after"] = token_file.exists()
r["calls_after"] = calls()
r["is_capturing_after"] = keycapture.is_capturing(win)
until(lambda: "SUPER SHIFT, K" in page.bind_rows)
r["new_row_detail"] = page.bind_rows["SUPER SHIFT, K"].subtitle_label.get_label()
r["new_row_menu"] = sorted(page.bind_rows["SUPER SHIFT, K"].items)
r["history"] = [[e.key for e in g.entries] for g in history.groups()]

# ---- Esc cancels and writes nothing ---------------------------------------------
before = block()
n_calls = len(calls())
page.start_rebind("SUPER, E")
spin(0.5)
press(page, Gdk.KEY_Escape, Gdk.ModifierType(0))
spin(0.3)
r["esc_block_same"] = block() == before
r["esc_calls"] = calls()[n_calls:]
r["esc_label"] = page.bind_rows["SUPER, E"].keys.get_label()

# ---- an occupied combination asks first ------------------------------------------
asks: list = []
page.ask_conflict = lambda combo, occupant, on_replace: asks.append([combo, occupant])
page.start_rebind("SUPER, Q")
spin(0.5)
press(page, Gdk.KEY_c, SUPER)
spin(0.3)
r["asks"] = asks
r["block_after_ask"] = block() == r["block"]

# ---- add a bind ---------------------------------------------------------------------
page.add_entry.set_text("kitty --title notes")
page.start_add_capture()
spin(0.5)
press(page, Gdk.KEY_n, SUPER | Gdk.ModifierType.CONTROL_MASK)
r["add_keys"] = page.add_keys.get_label()
r["add_sensitive"] = page.add_button.get_sensitive()
page.add_button.emit("clicked")
until(lambda: any("SUPER CTRL, N, exec, kitty --title notes" in x for x in block()))
r["add_block"] = [x for x in block() if "settings-hub" in x]

# ---- hyprland.lua turns the editor off ----------------------------------------------
lua = Path.home() / ".config" / "hypr" / "hyprland.lua"
lua.write_text("-- lua\n")
text_before = block()
page.refresh()
until(lambda: page.setup_group.get_visible())
spin(0.3)
r["lua_title"] = page.setup_row.title_label.get_label()
r["lua_menus"] = any(row.menu.get_sensitive() for row in page.bind_rows.values())
r["lua_add"] = page.add_group_widget.get_sensitive()
page.controller.disable("SUPER, E")
spin(0.5)
r["lua_block_same"] = block() == text_before
r["statuses"] = statuses

workers.stop_all(2)
r["lua_is_bn_lua"] = r["lua_title"] == strings.BN_LUA
Path(out_path).write_text(json.dumps(r, ensure_ascii=False, indent=1))
