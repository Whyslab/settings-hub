"""The Lock screen page in the real window: preview, apply, undo, restore.

    python3 gui_lockscreen.py REPO STATE_DIR OUT.json [SHOTS_DIR]

Run by test_gui_lockscreen.py on a private Xvfb with HOME in a temporary folder
that holds a hand-made hyprlock.conf, colors.conf, stub status scripts, a
wallpaper and a copy of the simulator. hyprlock is never started.
Not collected by pytest.
"""

import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, out_path = (Path(a) for a in sys.argv[1:4])
shots = Path(sys.argv[4]) if len(sys.argv) > 4 else None
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub import settings  # noqa: E402
from settings_hub.backends import lockscreen as lk  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def wait(check, seconds: float = 25.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        spin(0.2)
    return False


def shoot(name: str) -> None:
    if shots is not None:
        spin(0.6)
        subprocess.run(["magick", "import", "-window", "root", str(shots / f"{name}.png")],
                       check=False)


errors = []


def _caught(kind, value, tb) -> None:
    errors.append(f"{kind.__name__}: {value}")
    traceback.print_exception(kind, value, tb)  # a failure outside a callback is said too


sys.excepthook = _caught

app = Gtk.Application(application_id="io.github.whyslab.SettingsHubLock",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
history = History(state_dir / "history.jsonl")
win = Window(app, history, Workers(), state_dir, {},
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 1400)
win.present()
conf = Path.home() / ".config" / "hypr" / "hyprlock.conf"
hand = conf.read_text()
out: dict = {}

win.show_page("lockscreen")
page = win._pages["lockscreen"]
out["preview_first"] = wait(lambda: page.picture.get_paintable() is not None)
out["state_hand"] = page.state_row.title_label.get_label()
out["restore_hidden"] = not page.restore_row.get_visible()
shoot("lock-hand")

# A preset and a switch: a new picture, nothing written yet.
first = page.picture.get_paintable()
page.controls["preset"].widget.set_selected(1)  # "center"
page.controls["battery"].widget.set_active(True)
out["preview_redrawn"] = wait(lambda: page.picture.get_paintable() is not first
                              and not page.picture_note.get_visible())
out["file_untouched"] = conf.read_text() == hand
out["options_saved"] = json.loads(
    (Path.home() / ".config" / "settings-hub" / "lockscreen.json").read_text())
shoot("lock-center")

# Apply: the hand-made file is copied first, then replaced; one History item.
page.apply_button.emit("clicked")
out["applied"] = wait(lambda: lk.is_ours(conf.read_text()))
spin(1.0)
backups = sorted((conf.parent / "backups").glob("*-settings-hub-lock/hyprlock.conf"))
out["backup_is_hand"] = bool(backups) and backups[0].read_text() == hand
out["history_groups"] = len(history.groups())
written = conf.read_text()
out["written_has_field"] = written.count("input-field {") == 1
out["written_keeps_hook"] = "# wallpaper-theme" in written
out["state_ours"] = page.state_row.title_label.get_label()
out["restore_shown"] = page.restore_row.get_visible()

# Everything off: the password field stays.
for part in lk.PARTS:
    page.controls[part].widget.set_active(False)
spin(0.5)
page.apply_button.emit("clicked")
wait(lambda: "$TIME" not in conf.read_text())
spin(0.5)
bare = conf.read_text()
out["bare_has_field"] = bare.count("input-field {") == 1
out["bare_has_no_poweroff"] = "poweroff" not in bare
shoot("lock-bare")

# Ctrl+Z twice: the hand-made file again, byte for byte.
for _ in range(2):
    history.execute(history.plan_undo_last())
    spin(0.5)
out["undone_to_hand"] = conf.read_text() == hand

# Apply again, then "Restore": the hand-made file once more, through History too.
page.apply_button.emit("clicked")
wait(lambda: lk.is_ours(conf.read_text()))
spin(0.5)
page.restore_button.emit("clicked")
out["restored"] = wait(lambda: conf.read_text() == hand)
spin(0.5)
out["history_after_restore"] = len(history.groups())
out["errors"] = errors
Path(out_path).write_text(json.dumps(out, ensure_ascii=False))
