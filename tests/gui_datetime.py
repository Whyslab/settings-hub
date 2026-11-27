"""Open the Date, time and language page in-process and use it. Run by
test_gui_datetime.py.

    python3 gui_datetime.py REPO STATE_DIR OUT.json

The page gets a time/language backend whose commands are answered here (no
timedatectl or localectl runs), and a Hyprland variables backend kept in
memory. Not collected by pytest.
"""

import json
import sys
import threading
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, out_path = (Path(a) for a in sys.argv[1:4])
sys.path.insert(0, str(repo))

import subprocess  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub import settings, strings  # noqa: E402
from settings_hub.backends import timelang as tl  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.variables import backend as hypr  # noqa: E402
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


def wait(check, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        spin(0.05)
    return False


system = {"zone": "Europe/Oslo", "ntp": "yes", "lang": "ru_RU.UTF-8", "lc_time": "",
          "x11": ["ru,us", "pc105", ",", "terminate:ctrl_alt_bksp,grp:shifts_toggle"],
          "deny": False, "down": True, "slow": 0.0}  # down: nothing answers (the first opening)
calls: list[list[str]] = []
lock = threading.Lock()
asking = [0, 0]  # password dialogs open now, most at once
ZONES = "America/New_York\nEurope/Kyiv\nEurope/Oslo\nUTC\n"


def run(argv, **kwargs):
    argv = list(argv)
    calls.append(argv)
    ok = subprocess.CompletedProcess(argv, 0, "", "")
    if system["down"] and argv[0] in (tl.TIMEDATECTL, tl.LOCALECTL):
        return subprocess.CompletedProcess(argv, 1, "", "Failed to connect to bus\n")
    if argv[0] == tl.TIMEDATECTL:
        if argv[1] == "show":
            return subprocess.CompletedProcess(argv, 0, (
                f"Timezone={system['zone']}\nNTP={system['ntp']}\nNTPSynchronized=yes\n"
                "CanNTP=yes\n"), "")
        if argv[1] == "list-timezones":
            return subprocess.CompletedProcess(argv, 0, ZONES, "")
    if argv[0] == tl.LOCALECTL and argv[1] == "status":
        extra = f"\n               LC_TIME={system['lc_time']}" if system["lc_time"] else ""
        x = system["x11"]
        return subprocess.CompletedProcess(argv, 0, (
            f"System Locale: LANG={system['lang']}{extra}\n    VC Keymap: us\n"
            f"   X11 Layout: {x[0]}\n    X11 Model: {x[1]}\n  X11 Variant: {x[2]}\n"
            f"  X11 Options: {x[3]}\n"), "")
    if argv[0] == tl.LOCALE:
        return subprocess.CompletedProcess(argv, 0, "C\nC.utf8\nen_US.utf8\nru_RU.utf8\n", "")
    if "set-timezone" in argv or "set-ntp" in argv or "set-locale" in argv \
            or "set-x11-keymap" in argv:
        if system["deny"]:
            return subprocess.CompletedProcess(argv, 1, "", "Failed: Access denied\n")
        with lock:
            asking[0] += 1
            asking[1] = max(asking)
        time.sleep(system["slow"])  # the password dialog open
        with lock:
            asking[0] -= 1
        if "set-timezone" in argv:
            system["zone"] = argv[-1]
        elif "set-ntp" in argv:
            system["ntp"] = "yes" if argv[-1] == "true" else "no"
        elif "set-locale" in argv:
            for item in argv[2:]:
                key, _, value = item.partition("=")
                system["lang" if key == "LANG" else "lc_time"] = value
        else:
            system["x11"] = [argv[3], argv[4], argv[5], argv[6]]
        return ok
    raise AssertionError(f"unexpected command {argv}")


class FakeHypr:
    """The Hyprland variables backend, in memory."""

    def __init__(self, workers):
        self.workers = workers
        self.values = {"input:kb_layout": "us,ru,no", "input:kb_options": "grp:win_space_toggle"}
        self.applied: list[dict] = []

    def read_one(self, option):
        return self.values.get(option, "")

    def queue_read_all(self, on_done):
        self.workers.submit(hypr.WORKER_READ, lambda: dict(self.values), on_done)

    def apply_now(self, values, read_back=True):
        self.applied.append(dict(values))
        self.values.update(values)
        return hypr.ApplyResult(True, "", dict(values))

    def read(self, keys):
        return {k: self.values.get(k) for k in keys}

    def apply(self, values):
        self.apply_now(values)


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubDatetime",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
backend = tl.Backend(workers, run=run, xkb_rules=repo / "tests" / "fixtures" / "base.lst")
fake = FakeHypr(workers)
backends = {tl.BACKEND: backend, hypr.BACKEND: fake}
tl.register(history, backend)
history.register(hypr.BACKEND, fake)
win = Window(app, history, workers, state_dir, backends,
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 1300)
win.present()
win.show_page("datetime")
page = win._pages["datetime"]
if page.backend is not backend:
    sys.exit("refusing to run: the page is not using the fake backend")
out: dict = {}


def selected(dropdown):
    item = dropdown.get_selected_item()
    return item.get_string() if item is not None else None


# opened while nothing answers: said, nothing breaks
wait(lambda: page.info is not None)
spin(0.3)
out["down_ntp_hint"] = page.rows["ntp"].subtitle_label.get_label()
out["down_login_hint"] = page.login_row.subtitle_label.get_label()
out["down_zone_sensitive"] = page.zone_dropdown.get_sensitive()
out["down_locale"] = selected(page.locale_dropdown)  # unknown: none, not the first one
out["down_errors"] = list(errors)
system["down"] = False
page.info = None
page.refresh()


def layouts():
    return [r.title_label.get_label() for r in page._layout_rows]


out["read"] = wait(lambda: page.info is not None and len(page._layout_rows) == 3)
out["now"] = page.now_label.get_label()
out["zone"] = selected(page.zone_dropdown)
out["ntp"] = page.ntp_switch.get_active()
out["ntp_hint"] = page.rows["ntp"].subtitle_label.get_label()
out["locale"] = selected(page.locale_dropdown)
out["layouts"] = layouts()
out["switch"] = selected(page.switch_dropdown)
out["login_hint"] = page.login_row.subtitle_label.get_label()
out["login_sensitive"] = page.login_button.get_sensitive()
out["add_first"] = selected(page.add_dropdown)
out["missing_rows"] = [r for r in strings.TL_ROWS if r not in page.rows]
out["history_on_open"] = len(history.entries())

# Time zone: asks (the fake says yes), goes to History, says so
page.zone_dropdown.set_selected(page._zones.index("America/New_York"))
wait(lambda: system["zone"] == "America/New_York" and not page._asking)
spin(0.3)
out["zone_after"] = selected(page.zone_dropdown)
out["now_tooltip_after"] = page.now_label.get_tooltip_text()  # the new zone's offset
out["zone_status"] = win.status.get_label()
out["zone_history"] = [(e.backend, e.key, e.before, e.after) for e in history.entries()]

# A refused password: nothing changes, the switch goes back, nothing in History
system["deny"] = True
page.ntp_switch.set_active(False)
wait(lambda: not page._asking and "пароль" in win.status.get_label())
spin(0.5)
out["denied_status"] = win.status.get_label()
out["ntp_after_deny"] = page.ntp_switch.get_active()
out["history_after_deny"] = len(history.entries())
system["deny"] = False

# Ctrl+Z puts the time zone back (through the same command), while the window
# keeps answering; a second Ctrl+Z meanwhile waits its turn
system["slow"] = 1.5
started = time.monotonic()
win.undo_last()
out["undo_returned_s"] = time.monotonic() - started
out["undo_status"] = win.status.get_label()
spin(0.2)
win.undo_last()
out["second_undo_status"] = win.status.get_label()
wait(lambda: not win._reverting, 10)
system["slow"] = 0.0
spin(0.3)
out["zone_undone"] = system["zone"]
out["undo_recorded"] = history.entries()[-1].after


class ThreadCheck:
    """An applier that may touch GTK: it must run on the GTK thread."""

    def __init__(self):
        self.values, self.main = {"k": 1}, []

    def read(self, keys):
        return {k: self.values.get(k) for k in keys}

    def apply(self, values):
        self.main.append(threading.current_thread() is threading.main_thread())
        self.values.update(values)


# A revert of both kinds at once: only the password one leaves the GTK thread
check = ThreadCheck()
history.register("thread-check", check)
g1 = history.record([("thread-check", "k", "K", 1, 2)])
check.values["k"] = 2
g2 = history.record([(tl.BACKEND, "timezone", "Zone", system["zone"], "UTC")])
system["zone"] = "UTC"
system["slow"] = 1.0
win.undo_group([g1, g2])
spin(0.2)  # while it waits for the password, a change on the page waits its turn
page.zone_dropdown.set_selected(page._zones.index("Europe/Kyiv"))
wait(lambda: not win._reverting and not page._asking and system["zone"] == "Europe/Kyiv")
system["slow"] = 0.0
spin(0.3)
out["mixed_main_thread"] = check.main
out["mixed_zone"] = system["zone"]
out["mixed_k"] = check.values["k"]
out["mixed_recorded"] = sorted(e.backend for e in history.entries()[-3:-1])
out["dialogs_at_once"] = asking[1]

# System language: the other locale settings are kept
system["lc_time"] = "en_US.UTF-8"
page.refresh()
wait(lambda: page.info is not None and page.info.locale.get("LC_TIME") == "en_US.UTF-8")
page.locale_dropdown.set_selected(page._locales.index("en_US.UTF-8"))
wait(lambda: system["lang"] == "en_US.UTF-8" and not page._asking)
out["locale_call"] = next((c for c in calls if "set-locale" in c), None)

# Login screen keyboard: as this session, other options kept
wait(lambda: page.login_button.get_sensitive())
page.login_button.emit("clicked")
wait(lambda: system["x11"][0] == "us,ru,no" and not page._asking)
spin(0.3)
out["login_call"] = next((c for c in calls if "set-x11-keymap" in c), None)
out["login_hint_after"] = page.login_row.subtitle_label.get_label()
out["login_sensitive_after"] = page.login_button.get_sensitive()

# The session's layouts: up, remove, add, switch
page._layout_rows[1].up.emit("clicked")
wait(lambda: fake.values["input:kb_layout"] == "ru,us,no")
spin(0.3)
out["after_up"] = layouts()
page._layout_rows[2].remove.emit("clicked")
wait(lambda: fake.values["input:kb_layout"] == "ru,us")
spin(0.3)
# what the person picked stays picked when the page reads again
pick = page._addable.index("ua")
page.add_dropdown.set_selected(pick)
page.keys.refresh()
spin(0.5)
out["pick_kept"] = page._addable[page.add_dropdown.get_selected()]
first = page._addable[0]
page.add_dropdown.set_selected(0)
page.add_button.emit("clicked")
wait(lambda: fake.values["input:kb_layout"] == f"ru,us,{first}")
spin(0.3)
out["after_add"] = fake.values["input:kb_layout"]
page.switch_dropdown.set_selected(page._switches.index("grp:alt_shift_toggle"))
wait(lambda: "alt_shift" in fake.values["input:kb_options"])
spin(0.3)
out["options_after"] = fake.values["input:kb_options"]
out["layout_history"] = [e.after for e in history.entries() if e.backend == hypr.BACKEND]
# no switch with several layouts: the login screen must not get that
fake.values["input:kb_options"] = ""
page.keys.refresh()
wait(lambda: not page.login_button.get_sensitive())
spin(0.3)
out["unsafe_login_sensitive"] = page.login_button.get_sensitive()
out["unsafe_login_hint"] = page.login_row.subtitle_label.get_label()
# the last layout cannot be removed
fake.values["input:kb_layout"] = "us"
page.keys.refresh()
wait(lambda: len(page._layout_rows) == 1 and "США" in layouts()[0])
spin(0.2)
out["last_removable"] = page._layout_rows[0].remove.get_sensitive()
out["errors"] = errors
out["commands"] = [c for c in calls if any(s in c for s in (
    "set-timezone", "set-ntp", "set-locale", "set-x11-keymap"))]
out_path.write_text(json.dumps(out, ensure_ascii=False))
workers.stop_all(timeout=2)
