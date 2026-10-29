"""The resident Gtk.Application.

    app.py --daemon                 start hidden (exec-once at login); exits at
                                    once if another copy already owns the name
    app.py [--page ID]              show the window (asks the running copy if any)
    app.py --color-scheme dark      force light/dark (for screenshots)

One copy per session, owned on D-Bus as io.github.whyslab.SettingsHub. The
hotkey script bin/settings-open calls its `open(s)` action through gdbus, which
is much faster than starting Python. The window class is the prgname,
"settings-hub" (that is what Hyprland window rules match on this setup).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, PRGNAME  # noqa: E402
from .backends import screen_sleep  # noqa: E402
from .history import History  # noqa: E402
from .theme import SCHEMES, Theme  # noqa: E402
from .window import Window  # noqa: E402
from .workers import Workers  # noqa: E402

log = logging.getLogger("settings_hub")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "settings-hub"


def setup_logging(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # The process runs for the whole session; keep the log small.
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            directory / "app.log", maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def hook(kind, value, tb) -> None:  # exceptions in GTK callbacks end up here
        log.error("unhandled", exc_info=(kind, value, tb))

    sys.excepthook = hook


class App(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.add_main_option("daemon", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Start hidden and wait for the open action", None)
        self.add_main_option("page", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Open this page", "ID")
        self.add_main_option("color-scheme", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Force the light or dark look (for screenshots)", "light|dark")
        self.start_hidden = False
        self.initial_page = ""
        self.forced_scheme: str | None = None
        self.window: Window | None = None
        self.workers: Workers | None = None

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        page = options.lookup_value("page", GLib.VariantType.new("s"))
        self.initial_page = page.get_string() if page else ""
        scheme = options.lookup_value("color-scheme", GLib.VariantType.new("s"))
        if scheme is not None:
            if scheme.get_string() not in SCHEMES:
                print("--color-scheme must be light or dark", file=sys.stderr)
                return 2
            self.forced_scheme = scheme.get_string()
        try:
            self.register(None)
        except GLib.Error as exc:
            print(f"settings-hub: cannot register on D-Bus: {exc.message}", file=sys.stderr)
            return 1
        if self.get_is_remote():
            if options.contains("daemon"):
                return 0  # already running; a second background copy is not needed
            self.activate_action("open", GLib.Variant("s", self.initial_page))
            return 0
        self.start_hidden = options.contains("daemon")
        return -1

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        directory = state_dir()
        setup_logging(directory)
        Theme(Gdk.Display.get_default(), self.forced_scheme)
        self.workers = Workers()
        history = History()
        # Appliers are registered at start, so undo works before a page is opened.
        backends = {screen_sleep.BACKEND: screen_sleep.Backend(self.workers)}
        screen_sleep.register(history, backends[screen_sleep.BACKEND])
        self.window = Window(self, history, self.workers, directory, backends)

        open_action = Gio.SimpleAction.new("open", GLib.VariantType.new("s"))
        open_action.connect("activate", lambda _a, v: self.window.open_page(v.get_string()))
        self.add_action(open_action)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.hold()
        log.info("started (pid %d)", os.getpid())

    def do_activate(self) -> None:
        if self.start_hidden:
            self.start_hidden = False
            return
        self.window.open_page(self.initial_page)

    def do_shutdown(self) -> None:
        if self.workers is not None:
            self.workers.stop_all(timeout=1)
        log.info("stopped")
        Gtk.Application.do_shutdown(self)


def main(argv: list[str]) -> int:
    GLib.set_prgname(PRGNAME)
    return App().run(argv)
