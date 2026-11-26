"""The Appearance page in the real window: values shown, a change applied.

    python3 gui_appearance.py REPO STATE_DIR OUT.json [SHOTS_DIR]

Run by test_gui_appearance.py on a private Xvfb with a stub gsettings first in
PATH and HOME in a temporary folder. Not collected by pytest.
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
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from settings_hub import settings  # noqa: E402
from settings_hub import theme as hub_theme  # noqa: E402
from settings_hub.backends import appearance as ap  # noqa: E402
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


errors = []
sys.excepthook = lambda kind, value, tb: errors.append(f"{kind.__name__}: {value}")

app = Gtk.Application(application_id="io.github.whyslab.SettingsHubLook",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
workers = Workers()
history = History(state_dir / "history.jsonl")
theme = hub_theme.Theme(Gdk.Display.get_default())
hub = settings.Settings(state_dir / "settings.json")
settings.register(history, hub)
# what app.py does with the setting
hub.subscribe(lambda key, value: key == "appearance.own_font" and theme.set_own_font(value))
win = Window(app, history, workers, state_dir, {}, settings=hub)
win.set_default_size(920, 1400)
win.present()
out: dict = {}

win.show_page("appearance")
spin(2.5)
page = win._pages["appearance"]
out["font"] = page.font_button.get_font_desc().to_string()
out["mono"] = page.mono_button.get_font_desc().to_string()
out["scale_label"] = page.scale_label.get_label()
out["panel"] = page.panel_value.get_label()
out["kitty"] = page.kitty_value.get_label()
out["icons"] = list(page.icon_names)
sel = page.icon_dropdown.get_selected()
out["icon_selected"] = page.icon_names[sel] if 0 <= sel < len(page.icon_names) else None
out["sample_icons"] = 0
child = page.icon_sample.get_first_child()
while child is not None:
    out["sample_icons"] += 1
    child = child.get_next_sibling()
out["cursor_rows"] = sorted(k for k in page.rows if k.startswith("cursor:"))
out["panel_same_on"] = page.panel_same.get_sensitive()
out["kitty_same_on"] = page.kitty_same.get_sensitive()
out["font_note"] = page.rows["font"].subtitle_label.get_label().partition("\n")[2]
look = page.look.look
look.values[ap.MONO] = "Nope Mono 11"
page.show_look(look, set())
out["missing_note"] = page.rows["mono"].subtitle_label.get_label().partition("\n")[2]
look.values[ap.MONO] = "Adwaita Mono 11"
page.show_look(look, set())
shoot("appearance")

# A user's font choice goes through the controller (as the dialog would set it).
page.font_button.set_font_desc(Pango.FontDescription.from_string("DejaVu Serif 13"))
spin(1.5)
# "The same for the terminal": kitty takes the monospace family, keeps its size.
page.kitty_same.emit("clicked")
spin(1.5)
out["after_font"] = page.look.value(ap.FONT)
out["after_kitty"] = page.look.value(ap.KITTY_FONT)

# The window's own font: Onest, or (switched off) the interface font.
def family() -> str:
    spin(0.3)
    return page.scale_label.get_pango_context().get_font_description().get_family() or ""


out["own_font_on"] = page.own_font.get_active()
out["family_own"] = family()
page.own_font.set_active(False)
out["family_system"] = family()
out["gtk_font"] = Gtk.Settings.get_default().props.gtk_font_name
history.execute(history.plan_undo_last())
out["own_font_after_undo"] = page.own_font.get_active()
out["family_after_undo"] = family()
out["history"] = [[e.key for e in g.entries] for g in history.groups()]
out["errors"] = errors
shoot("appearance-after")

workers.stop_all(2)
out_path.write_text(json.dumps(out, ensure_ascii=False))
