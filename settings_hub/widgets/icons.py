"""Line icons in the text colour of the widget they sit in.

    icon = Icon("sound", size=18)

An icon is drawn from a small SVG with its stroke set to the widget's CSS
colour at draw time, so it follows the theme, a selected row, a hover; no icon
theme is involved (the window keeps away from the desktop's GTK theme). Without
librsvg it falls back to the page's coloured square from style/icons.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import registry  # noqa: E402

try:
    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg  # noqa: E402
except (ImportError, ValueError):  # librsvg's typelib is not installed
    Rsvg = None

log = logging.getLogger(__name__)

# 24x24, stroke only. One per page id, plus the ones the window itself uses.
SHAPES = {
    "screen-sleep": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "wallpaper": ('<rect x="3" y="5" width="18" height="14" rx="2"/>'
                  '<circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 3.5 3 3-2.5L20 17"/>'),
    "themes": ('<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/>'
               '<path d="M12 8h7.5M12 12h9M12 16h7.5"/>'),
    "animations": '<path d="M12 4l1.8 5.2L19 11l-5.2 1.8L12 18l-1.8-5.2L5 11l5.2-1.8z"/>',
    "binds": ('<rect x="3" y="6" width="18" height="12" rx="2"/>'
              '<path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8"/>'),
    "game-binds": ('<rect x="3" y="8" width="18" height="9" rx="4.5"/>'
                   '<path d="M8 11v3M6.5 12.5h3M16 12.5h.01"/>'),
    "windows": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/>',
    "input": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v3"/>',
    "general": ('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/>'
                '<circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>'),
    "system": ('<rect x="6" y="6" width="12" height="12" rx="2"/>'
               '<path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>'),
    "sound": '<path d="M5 10v4h3l4 3V7l-4 3z"/><path d="M16 9a4 4 0 0 1 0 6"/>',
    "network": ('<path d="M4 10a12 12 0 0 1 16 0"/><path d="M7 13.5a7.5 7.5 0 0 1 10 0"/>'
                '<path d="M12 17h.01"/>'),
    "power": '<rect x="3" y="8" width="16" height="8" rx="2"/><path d="M22 11v2"/>',
    "modes": '<path d="M5 17a8 8 0 1 1 14 0"/><path d="M12 13l3-4"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "home": '<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>',
    "chevron": '<path d="M9 6l6 6-6 6"/>',
}

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
       'stroke="{color}" stroke-opacity="{alpha}" stroke-width="1.8" '
       'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=256)
def _handle(name: str, color: str, alpha: str):
    try:
        return Rsvg.Handle.new_from_data(
            SVG.format(color=color, alpha=alpha, body=SHAPES[name]).encode())
    except Exception as exc:  # a broken shape must not take the window down
        log.warning("icon %s: %s", name, exc)
        return None


class Icon(Gtk.DrawingArea):
    def __init__(self, name: str, size: int = 18) -> None:
        super().__init__(content_width=size, content_height=size)
        self.name = name
        self.add_css_class("sh-glyph")
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.set_can_target(False)  # clicks go to the button around it
        self.set_draw_func(self._draw)
        # A selected or hovered row changes the colour; draw again with it.
        self.connect("state-flags-changed", lambda *_: self.queue_draw())

    def _draw(self, _area, cr, width: int, height: int) -> None:
        rgba = self.get_color()
        color = "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in
                                               (rgba.red, rgba.green, rgba.blue)))
        handle = _handle(self.name, color, f"{rgba.alpha:.3f}")
        if handle is None:
            return
        rect = Rsvg.Rectangle()
        rect.x, rect.y, rect.width, rect.height = 0, 0, width, height
        handle.render_document(cr, rect)


def icon(name: str, size: int = 18) -> Gtk.Widget:
    """A line icon; without librsvg the page's coloured square (or nothing)."""
    if Rsvg is not None and name in SHAPES:
        return Icon(name, size)
    page = registry.get(name)
    if page is not None:
        image = Gtk.Image.new_from_file(str(page.icon_path))
        image.set_pixel_size(size)
        image.add_css_class("sh-icon")
        return image
    return Gtk.Box(width_request=size, height_request=size)
