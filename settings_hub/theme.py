"""The window's own look, independent of the system GTK theme.

1. The process uses GTK's built-in theme ("Default"), whatever gtk-theme-name
   the desktop sets; if something sets it back, notify::gtk-theme-name sets it
   again -- only when the value differs, or the handler would call itself.
2. style/base.css is loaded at priority USER + 100, above ~/.config/gtk-4.0/gtk.css.
3. base.css uses only literal colours and its own --sh-* variables, never named
   @colors: a gtk.css full of @define-color would otherwise leak in through the
   built-in theme.
4. Light/dark follows Gtk.Settings:gtk-interface-color-scheme (base.css has
   @media (prefers-color-scheme: dark)). If the platform does not say, the
   GNOME color-scheme setting is used. A forced scheme (for screenshots) wins.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GObject, Gtk  # noqa: E402

from . import registry  # noqa: E402

log = logging.getLogger(__name__)

THEME = "Default"
CSS_PATH = registry.ROOT / "style" / "base.css"
PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_USER + 100

SCHEMES = {
    "light": Gtk.InterfaceColorScheme.LIGHT,
    "dark": Gtk.InterfaceColorScheme.DARK,
}
_GNOME = {"prefer-dark": Gtk.InterfaceColorScheme.DARK,
          "prefer-light": Gtk.InterfaceColorScheme.LIGHT}


class Theme:
    def __init__(self, display: Gdk.Display, forced_scheme: str | None = None) -> None:
        self.settings = Gtk.Settings.get_for_display(display)
        self._forced = SCHEMES.get(forced_scheme or "")
        self._gnome: Gio.Settings | None = None

        self._keep_theme()
        self.settings.connect("notify::gtk-theme-name", lambda *_: self._keep_theme())

        self.provider = Gtk.CssProvider()
        self.provider.connect("parsing-error", self._on_css_error)
        self.provider.load_from_path(str(CSS_PATH))
        # Since GTK 4.20 each provider answers @media (prefers-color-scheme)
        # from its own property; GTK binds it only for the providers it
        # creates itself, so ours follows the settings value explicitly.
        self.settings.bind_property("gtk-interface-color-scheme", self.provider,
                                    "prefers-color-scheme",
                                    GObject.BindingFlags.SYNC_CREATE)
        Gtk.StyleContext.add_provider_for_display(display, self.provider, PRIORITY)

        if self._forced is not None:
            self._set_scheme(self._forced)
            self.settings.connect("notify::gtk-interface-color-scheme",
                                  lambda *_: self._set_scheme(self._forced))
        elif self.settings.get_property("gtk-interface-color-scheme") in (
                Gtk.InterfaceColorScheme.DEFAULT, Gtk.InterfaceColorScheme.UNSUPPORTED):
            self._follow_gnome()

    def _keep_theme(self) -> None:
        if self.settings.get_property("gtk-theme-name") != THEME:
            self.settings.set_property("gtk-theme-name", THEME)

    def _set_scheme(self, scheme: Gtk.InterfaceColorScheme) -> None:
        if self.settings.get_property("gtk-interface-color-scheme") != scheme:
            self.settings.set_property("gtk-interface-color-scheme", scheme)

    def _follow_gnome(self) -> None:
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.desktop.interface", True) if source else None
        if schema is None or not schema.has_key("color-scheme"):
            return
        self._gnome = Gio.Settings.new("org.gnome.desktop.interface")
        self._gnome.connect("changed::color-scheme", lambda *_: self._apply_gnome())
        self._apply_gnome()

    def _apply_gnome(self) -> None:
        value = self._gnome.get_string("color-scheme") if self._gnome else ""
        self._set_scheme(_GNOME.get(value, Gtk.InterfaceColorScheme.DEFAULT))

    def is_dark(self) -> bool:
        return self.settings.get_property(
            "gtk-interface-color-scheme") == Gtk.InterfaceColorScheme.DARK

    @staticmethod
    def _on_css_error(_provider, section, error) -> None:
        log.warning("base.css: %s at %s", error.message, section.to_string())
