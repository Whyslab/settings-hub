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
from . import settings as hub_settings  # noqa: E402
from .backends import (  # noqa: E402
    animations,
    audio,
    binds,
    game_binds,
    network,
    power,
    screen_sleep,
    wallpaper,
)
from .history import History  # noqa: E402
from .theme import SCHEMES, Theme  # noqa: E402
from .variables import backend as hypr_vars  # noqa: E402
from .widgets import rows as row_widgets  # noqa: E402
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
        self.settings: hub_settings.Settings | None = None
        self.theme: Theme | None = None

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
        # First, so even a copy whose start failed below can be asked to quit
        # (install.sh does that before starting the new code).
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        open_action = Gio.SimpleAction.new("open", GLib.VariantType.new("s"))
        open_action.connect("activate", lambda _a, v: self._open(v.get_string()))
        self.add_action(open_action)
        self.theme = Theme(Gdk.Display.get_default(), self.forced_scheme)
        self.settings = hub_settings.Settings()
        self.theme.set_scheme(str(self.settings.get("appearance.theme")))
        row_widgets.set_highlight_ms(int(self.settings.get("appearance.highlight_ms")))
        self.workers = Workers()
        history = History(keep=int(self.settings.get("behavior.history_keep")))
        hub_settings.register(history, self.settings)
        # Appliers are registered at start, so undo works before a page is opened.
        backends = {screen_sleep.BACKEND: screen_sleep.Backend(self.workers)}
        screen_sleep.register(history, backends[screen_sleep.BACKEND])
        backends[wallpaper.BACKEND] = backends[wallpaper.THEME] = wallpaper.Backend(self.workers)
        wallpaper.register(history, backends[wallpaper.BACKEND])
        # The animations module itself is loaded on first use (page or undo).
        backends[animations.BACKEND] = animations.Backend(self.workers)
        animations.register(history, backends[animations.BACKEND])
        backends[binds.BACKEND] = binds.Backend(self.workers)
        binds.register(history, backends[binds.BACKEND])
        backends[hypr_vars.BACKEND] = hypr_vars.Backend(self.workers)
        hypr_vars.register(history, backends[hypr_vars.BACKEND])
        backends[audio.BACKEND] = audio.Backend(self.workers)
        audio.register(history, backends[audio.BACKEND])
        backends[network.BACKEND] = network.Backend(self.workers)
        network.register(history, backends[network.BACKEND])
        backends[power.BACKEND] = power.Backend(self.workers)
        power.register(history, backends[power.BACKEND])
        backends[game_binds.BACKEND] = game_binds.Backend(self.workers)
        game_binds.register(history, backends[game_binds.BACKEND])
        # A reinstall keeps the games file: bring its text up to this version.
        self.workers.submit(game_binds.WORKER, backends[game_binds.BACKEND].sync)
        # A window that crashed mid-capture may have left Hyprland in the capture
        # submap; leave it (only if we are in it), on the worker, without waiting.
        backends[binds.BACKEND].reset_submap()
        self.window = Window(self, history, self.workers, directory, backends,
                             settings=self.settings)
        self.settings.subscribe(self._on_setting)

        self.hold()
        log.info("started (pid %d)", os.getpid())

    def _on_setting(self, key: str, value) -> None:
        """Apply a changed setting at once (the General page's promise)."""
        if self.window is None:
            return
        if key == "appearance.theme":
            self.theme.set_scheme(str(value))
        elif key == "appearance.transition":
            self.window.stack.set_transition_type(self.window.transition())
        elif key == "appearance.sidebar_width":
            self.window.sidebar.set_width(int(value))
        elif key == "appearance.highlight_ms":
            row_widgets.set_highlight_ms(int(value))
        elif key == "appearance.status_ms":
            pass  # read when the next message appears
        elif key in ("appearance.window_width", "appearance.window_height"):
            width = int(self.settings.get("appearance.window_width"))
            height = int(self.settings.get("appearance.window_height"))
            if not self.window.settings.get("appearance.remember_size"):
                self.window.set_default_size(width, height)
        elif key == "behavior.history_keep":
            self.window.history.keep = int(value)
        elif key == "behavior.preload_s":
            self.window.set_preload(int(value))
        elif key == "behavior.search_limit":
            self.window.sidebar.search_limit = int(value)

    def do_activate(self) -> None:
        if self.start_hidden:
            self.start_hidden = False
            return
        self._open(self.initial_page)

    def _open(self, page: str) -> None:
        if self.window is None:
            # The start failed (see the log): leave, so the next press of the
            # hotkey starts a fresh copy instead of asking this one forever.
            log.error("no window (the start failed); quitting")
            self.quit()
            return
        self.window.open_page(page)

    def do_shutdown(self) -> None:
        if self.workers is not None:
            self.workers.stop_all(timeout=1)
        log.info("stopped")
        Gtk.Application.do_shutdown(self)


def main(argv: list[str]) -> int:
    GLib.set_prgname(PRGNAME)
    return App().run(argv)
