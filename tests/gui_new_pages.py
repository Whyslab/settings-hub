"""Open the Monitor, Notifications, Autostart and Updates pages in-process.
Run by test_gui_new_pages.py.

    python3 gui_new_pages.py REPO STATE_DIR OUT.json

The caller isolates the environment and puts stubs first in PATH (hyprctl,
hyprpanel, gsettings, checkupdates, pacman, notify-send, kitty...); each logs
its arguments. Not collected by pytest.
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

from settings_hub import settings  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def texts(widget) -> list[str]:
    out = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label) and child.get_visible() and child.get_label():
            out.append(child.get_label())
        out += texts(child)
        child = child.get_next_sibling()
    return out


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
win = Window(app, history, workers, state_dir, {},
             settings=settings.Settings(state_dir / "settings.json"))
win.present()
result = {}
for page_id in ("monitor", "notifications", "autostart", "updates"):
    win.show_page(page_id)
    spin(2.5)
    workers.wait_idle(10)
    spin(0.5)
    result[page_id] = texts(win._pages[page_id].widget)
result["history_groups"] = len(history.groups())

# Then pick another scale and another mode, answer nothing: each is tried live
# and comes back by itself (the wait made short).
import os  # noqa: E402

from settings_hub.pages import monitor as monitor_page  # noqa: E402

with open(os.environ["SH_TEST_CALL_LOG"], "a") as log:
    log.write("== change ==\n")
monitor_page.CONFIRM_S = 1
win.show_page("monitor")
spin(0.5)


def dropdowns(widget) -> list:
    out = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.DropDown):
            out.append(child)
        out += dropdowns(child)
        child = child.get_next_sibling()
    return out


def pick(nth: int, label: str) -> None:
    dd = dropdowns(win._pages["monitor"].widget)[nth]
    model = dd.get_model()
    labels = [model.get_string(i) for i in range(model.get_n_items())]
    dd.set_selected(labels.index(label))
    spin(3.5)
    workers.wait_idle(10)
    spin(0.5)


pick(1, "125 %")
pick(0, "1920×1080, 40 Гц")
result["history_after_change"] = len(history.groups())
out_path.write_text(json.dumps(result, ensure_ascii=False))
workers.stop_all(timeout=2)
