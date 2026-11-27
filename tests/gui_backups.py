"""Open the Backups page in-process and press its buttons. Run by test_gui_backups.py.

    python3 gui_backups.py REPO STATE_DIR CTRL_DIR BM_DIR STUB_SYSTEMCTL OUT.json

The page gets a backend that reads BM_DIR and calls STUB_SYSTEMCTL, which
answers `show` from CTRL_DIR (a file "running" marks bm-backup as running) and
`start` with the exit code in CTRL_DIR/start-rc. The buttons are pressed, so
the script refuses to run with the real systemctl. Not collected by pytest.
"""

import json
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, ctrl, bm_dir, stub, out_path = (Path(a) for a in sys.argv[1:7])
sys.path.insert(0, str(repo))
if not stub.is_file() or stub.resolve() == Path("/usr/bin/systemctl").resolve() \
        or "settings-hub stub" not in stub.read_text():
    sys.exit("refusing to run: the buttons would start real backups")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from settings_hub import settings  # noqa: E402
from settings_hub.backends import backups as bk  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.pages import backups as page_module  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402

page_module.POLL_S = 1
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


def texts(widget) -> list[str]:
    out = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label) and child.get_visible() and child.get_label() \
                and child.get_mapped():
            out.append(child.get_label())
        out += texts(child)
        child = child.get_next_sibling()
    return out


app = Gtk.Application(application_id="io.github.whyslab.SettingsHubBackups",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
backends = {bk.BACKEND: bk.Backend(workers, state_dir=bm_dir, systemctl=str(stub))}
win = Window(app, history, workers, state_dir, backends,
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 1200)
win.present()
win.show_page("backups")
page = win._pages["backups"]
out: dict = {}
wait(lambda: "32,9 GB, новых данных 149,4 MB" in texts(page.widget))
out["opened"] = texts(page.widget)

# No password: said, buttons come back
(ctrl / "start-rc").write_text("4")
page.buttons["backup"].emit("clicked")
wait(lambda: win.status.get_visible() and "пароль" in win.status.get_label())
wait(lambda: page.buttons["backup"].get_sensitive())
out["denied"] = win.status.get_label()
out["sensitive_after_denied"] = page.buttons["backup"].get_sensitive()

# Started: the copy runs, the page says so and looks again until it ends
(ctrl / "start-rc").write_text("0")
page.buttons["full"].emit("clicked")
wait(lambda: "Сейчас делается копия…" in texts(page.widget))
out["running"] = texts(page.widget)
out["started"] = win.status.get_label()
out["sensitive_while_running"] = page.buttons["backup"].get_sensitive()
out["unit_seen"] = wait(lambda: (ctrl / "running").exists(), 5)
spin(1.5)  # the page has looked again and seen it running
out["sensitive_while_running"] |= page.buttons["backup"].get_sensitive()
(ctrl / "running").unlink()
out["ended"] = wait(lambda: "Всё хорошо" in texts(page.widget), 10)
out["sensitive_after"] = page.buttons["backup"].get_sensitive()

# Leaving the page stops the looking
win.show_page("sound")
spin(0.5)
out["poll_after_leave"] = page._poll

# Started but skipped by systemd (a unit condition): said within a few seconds
win.show_page("backups")
spin(1)
(ctrl / "start-rc").write_text("skip")
page.buttons["backup"].emit("clicked")
out["skipped_soon"] = wait(lambda: any(t.startswith("Не запустилась") for t in texts(page.widget)),
                           8)
out["skipped_texts"] = texts(page.widget)[:4]
out["errors"] = errors
out_path.write_text(json.dumps(out, ensure_ascii=False))
workers.stop_all(timeout=2)
