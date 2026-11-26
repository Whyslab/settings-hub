"""The Panel page in the real window: values shown, buttons write config.json.

    python3 gui_panel.py REPO STATE_DIR OUT.json [SHOTS_DIR]

Run by test_gui_panel.py on a private Xvfb with HOME in a temporary folder.
Not collected by pytest.
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
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from settings_hub import settings  # noqa: E402
from settings_hub.backends import panel as pb  # noqa: E402
from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402


def spin(seconds: float) -> None:
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)


def shoot(name: str) -> None:
    if shots is not None:
        spin(0.6)
        subprocess.run(["magick", "import", "-window", "root", str(shots / f"{name}.png")],
                       check=False)


def buttons(group) -> list:
    """Every Gtk.Button under a page group, in order."""
    found = []

    def walk(widget):
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button) and not isinstance(child, Gtk.MenuButton):
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(group)
    return found


errors = []
sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")

app = Gtk.Application(application_id="io.github.whyslab.SettingsHubPanel",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
win = Window(app, history, workers, state_dir, {},
             settings=settings.Settings(state_dir / "settings.json"))
win.set_default_size(920, 1400)
win.present()
config = Path.home() / ".config" / "hyprpanel" / "config.json"
out: dict = {}

win.show_page("panel")
spin(2.5)
page = win._pages["panel"]
out["floating"] = page.controls[pb.FLOATING].value()
out["opacity"] = page.controls[pb.OPACITY].value()
out["font_size"] = page.controls[pb.FONT_SIZE].value()
out["font"] = page.font_button.get_font_desc().get_family()
out["clock_entry"] = page.clock_entry.get_text()
out["clock_entry_visible"] = page.clock_entry.get_visible()
out["clock_selected"] = page.clock_dropdown.get_selected()
out["right_rows"] = len(buttons(page.section_groups["right"])) // 3
out["add_names"] = list(page.add_names)
shoot("panel")

# A preset clock, a switch, a number (written once it rests).
page.clock_dropdown.set_selected(1)  # "%H:%M:%S"
page.controls[pb.FLOATING].widget.set_active(False)
spin(1.0)
for value in (60, 50, 40):
    page._changed(pb.OPACITY, value)  # what each click on - does
    spin(0.1)
spin(1.5)
# Modules: the first one on the right goes down, the last one is removed.
right = buttons(page.section_groups["right"])
right[1].emit("clicked")  # "down" of the first module
spin(1.0)
right = buttons(page.section_groups["right"])
right[-1].emit("clicked")  # "remove" of the last module
spin(1.0)
# Add one from the list into the left section.
page.add_section.set_selected(0)
page.add_dropdown.set_selected(page.add_names.index("custom/cpu"))
page.add_button.emit("clicked")
spin(1.0)
# The font: a family the dialog would give.
page.font_button.set_font_desc(Pango.FontDescription.from_string("Adwaita Sans 11"))
spin(1.0)
shoot("panel-after")

out["config"] = json.loads(config.read_text())
out["mode"] = oct(config.stat().st_mode & 0o777)
out["history"] = [[e.key for e in g.entries] for g in history.groups()]
out["errors"] = errors
workers.stop_all(2)
out_path.write_text(json.dumps(out, ensure_ascii=False))
