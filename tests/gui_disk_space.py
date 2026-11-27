"""Open the System page in-process and use its disk space part. Run by test_gui_disk_space.py.

    python3 gui_disk_space.py REPO STATE_DIR HOME OUT.json

The page gets a disk backend for HOME (a temporary folder): du runs for real
there, while systemctl and gio are answered here -- "empty the Trash" removes
HOME's Trash only, never the real one. Not collected by pytest.
"""

import json
import os
import pwd
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, home, out_path = (Path(a) for a in sys.argv[1:5])
sys.path.insert(0, str(repo))
real_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
trash = home / ".local" / "share" / "Trash"
if home.resolve() == real_home or real_home in trash.resolve().parents \
        or not trash.resolve().is_relative_to(home.resolve()):
    sys.exit("refusing to run: HOME must be a temporary folder, not the real one")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub import settings, strings  # noqa: E402
from settings_hub.backends import disk_space as ds  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402

errors = []


def _caught(kind, value, tb) -> None:
    errors.append(f"{kind.__name__}: {value}")
    traceback.print_exception(kind, value, tb)


sys.excepthook = _caught


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def wait(check, seconds: float = 15.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        spin(0.1)
    return False


calls: list[list[str]] = []
# While they exist: a count stalls for 3 s after it has looked at the trash (so it
# ends with old numbers), and counting the trash takes 1 s.
slow_count = home / "slow-count"
slow_trash = home / "slow-trash"


def run(argv, **kwargs):
    calls.append(list(argv))
    if ds.DU in argv:
        if slow_trash.exists() and "-s" in argv:
            time.sleep(1)
        return subprocess.run(argv, **kwargs)
    if argv[0] == ds.SYSTEMCTL:
        if slow_count.exists():
            time.sleep(3)
        return subprocess.CompletedProcess(argv, 0, "enabled\n", "")
    if argv == [ds.GIO, "trash", "--empty"]:
        for sub in ("files", "info"):
            shutil.rmtree(trash / sub, ignore_errors=True)
            (trash / sub).mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0, "", "")
    raise AssertionError(f"unexpected command {argv}")


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubDisk",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
# the temporary home as the only disk: a local one (Steam is read), with no other
# disks' trash to count
(home / "mounts").write_text(f"tmpfs {home} tmpfs rw 0 0\nsrv:/x {home}/nas nfs4 rw 0 0\n")
space = ds.Backend(run=run, home=home, pacman_conf=home / "pacman.conf",
                   mounts_file=home / "mounts")
backends = {ds.BACKEND: space}
win = Window(app, history, workers, state_dir, backends,
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 1400)
win.present()
win.show_page("system")
page = win._pages["system"]
if page.space is not space or space.run is not run:  # not an assert: python -O
    sys.exit("refusing to run: the page is not using the fake backend")
out: dict = {}
out["counted"] = wait(lambda: page.usage_row.title_label.get_label().startswith(
    "Домашняя папка:"))
wait(lambda: page._mounts is not None, 5)
out["mount_titles"] = [r.title_label.get_label() for r in page._mount_rows]
out["disk_row_is_first_mount"] = page.rows["disk"] is page._mount_rows[0]
out["folders"] = [r.title_label.get_label() for r in page._folder_rows]
out["folder_paths"] = [r.subtitle_label.get_label() for r in page._folder_rows]
out["trash_hint"] = page.trash_row.subtitle_label.get_label()
out["trash_sensitive"] = page.trash_button.get_sensitive()
out["games_visible"] = page.games_row.get_visible()
out["games_hint"] = page.games_row.subtitle_label.get_label()
out["packages_hint"] = page.packages_row.subtitle_label.get_label()
out["missing_rows"] = [r for r in strings.PAGES["system"]["rows"] if r not in page.rows]

# Opening a folder goes to the file manager (recorded here)
opened = []
page.open_folder = opened.append
page._folder_rows[0].open_button.emit("clicked")
out["opened"] = [str(p) for p in opened]
pages_opened = []
page.ctx.open_page = pages_opened.append
for child in (page.packages_row.suffix_box.get_last_child(),):
    child.emit("clicked")
out["pages_opened"] = pages_opened

# The Trash: "no" changes nothing, "yes" empties it and says so
asked = []
page.confirm = lambda message, detail, ok, on_yes, on_no=None: asked.append(
    (message, detail, ok)) or (on_no and on_no())
slow_trash.write_text("")
page.trash_button.emit("clicked")
spin(0.3)  # the first count of the trash is running now
page.trash_button.emit("clicked")  # a double click: one count, one dialog
wait(lambda: asked, 5)
spin(1.5)
slow_trash.unlink()
spin(0.3)
out["asked_times"] = len(asked)
out["asked"] = asked[-1] if asked else None
out["sensitive_after_no"] = page.trash_button.get_sensitive()
out["gio_after_no"] = sum(1 for c in calls if c[0] == ds.GIO)
# Trashed after the last count: the dialog counts again, so it says 2, not 1
(trash / "files" / "new.txt").write_text("x")
(trash / "info" / "new.txt.trashinfo").write_text("[Trash Info]\n")
page.confirm = lambda message, detail, ok, on_yes, on_no=None: asked.append(
    (message, detail, ok)) or on_yes()
# A slow count starts first; it ends after the emptying and must not bring the old
# numbers back
slow_count.write_text("")
page._count()
spin(1)  # it has counted the trash (2 items) and stalls
page.trash_button.emit("clicked")
wait(lambda: page.trash_row.subtitle_label.get_label() == strings.SYS_TRASH_NONE, 10)
out["asked_fresh"] = asked[-1][1]
out["emptied_before_count"] = page._counting
wait(lambda: not page._counting, 10)
slow_count.unlink()
spin(0.3)
out["gio_after_yes"] = [c for c in calls if c[0] == ds.GIO]
out["trash_after"] = page.trash_row.subtitle_label.get_label()
out["trash_sensitive_after"] = page.trash_button.get_sensitive()
out["status_after"] = win.status.get_label()

# Shown again soon: no new count of the home folder (only a look at the trash);
# "Recount" counts again
du_runs = sum(1 for c in calls if "--max-depth=1" in c)
win.show_page("sound")
spin(0.3)
win.show_page("system")
spin(1.5)
out["recounted_on_show"] = sum(1 for c in calls if "--max-depth=1" in c) - du_runs
page.recount.emit("clicked")
wait(lambda: sum(1 for c in calls if "--max-depth=1" in c) > du_runs and not page._counting, 10)
out["recounted_on_click"] = sum(1 for c in calls if "--max-depth=1" in c) - du_runs

# A nearly full disk is marked
page._show_mounts((ds.Mount("/", "/dev/x", "ext4", 100 * 1024 ** 3, 95 * 1024 ** 3,
                            5 * 1024 ** 3),), None)
row = page._mount_rows[0]
out["low_hint"] = row.subtitle_label.get_label()
out["low_marked"] = row.bar.has_css_class("sh-full") and \
    row.subtitle_label.has_css_class("sh-warning")
out["low_value"] = row.value_label.get_label()
out["errors"] = errors
out_path.write_text(json.dumps(out, ensure_ascii=False))
workers.stop_all(timeout=2)
