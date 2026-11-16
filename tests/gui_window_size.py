"""Build the real Window and report its default size. Run by test_gui_window.py.

    python3 gui_window_size.py REPO STATE_DIR OUT.json

The caller isolates the environment like for gui_window_keys.py; the settings
come from its XDG_CONFIG_HOME. Not collected by pytest (no test_ prefix).
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
repo, state_dir, out_path = (Path(a) for a in sys.argv[1:4])
sys.path.insert(0, str(repo))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

from settings_hub.history import History  # noqa: E402
from settings_hub.window import Window  # noqa: E402
from settings_hub.workers import Workers  # noqa: E402

app = Gtk.Application(application_id="io.github.whyslab.SettingsHubTest",
                      flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
win = Window(app, History(state_dir / "history.jsonl"), Workers(), state_dir, {})
width, height = win.get_default_size()
out_path.write_text(json.dumps({"width": width, "height": height}))
