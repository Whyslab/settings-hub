"""Rounded groups of rows, the building block of every page (macOS style).

    group = Group(title)            # a dim heading above a rounded box
    row = group.add(Row(label, subtitle, suffix=widget, row_id="undo"))

A row's inner box carries the separator, so separators are inset from the
left like on macOS; the last row has none.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

HIGHLIGHT_MS = 1500
_highlight_ms = HIGHLIGHT_MS


def set_highlight_ms(value: int) -> None:
    """How long a row from a search result stays tinted (the General page)."""
    global _highlight_ms
    _highlight_ms = max(100, int(value))


def highlight_ms() -> int:
    return _highlight_ms


class Row(Gtk.ListBoxRow):
    def __init__(self, title: str, subtitle: str | None = None,
                 suffix: Gtk.Widget | None = None, row_id: str | None = None,
                 activatable: bool = False, below: Gtk.Widget | None = None) -> None:
        """below: a full-width widget under the title line (a slider)."""
        super().__init__()
        self.row_id = row_id
        self.set_activatable(activatable)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                        valign=Gtk.Align.CENTER, hexpand=True)
        self.title_label = Gtk.Label(label=title, xalign=0, wrap=True)
        texts.append(self.title_label)
        self.subtitle_label = Gtk.Label(xalign=0, wrap=True, visible=bool(subtitle))
        self.subtitle_label.add_css_class("sh-subtitle")
        if subtitle:
            self.subtitle_label.set_label(subtitle)
        texts.append(self.subtitle_label)
        inner.append(texts)
        if suffix is not None:
            suffix.set_valign(Gtk.Align.CENTER)
            inner.append(suffix)
        if below is None:
            inner.add_css_class("sh-row-inner")
            self.set_child(inner)
        else:
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            outer.add_css_class("sh-row-inner")
            outer.append(inner)
            outer.append(below)
            self.set_child(outer)
        self._highlight_source = 0

    def highlight(self) -> None:
        """Tint the row for a moment (a search result was opened)."""
        if self._highlight_source:
            GLib.source_remove(self._highlight_source)
        self.add_css_class("sh-highlight")

        def clear() -> bool:
            self.remove_css_class("sh-highlight")
            self._highlight_source = 0
            return False

        self._highlight_source = GLib.timeout_add(_highlight_ms, clear)


class Group(Gtk.Box):
    def __init__(self, title: str | None = None, note: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.heading: Gtk.Label | None = None
        if not title:
            self.add_css_class("sh-untitled")
        if title:
            self.heading = Gtk.Label(label=title, xalign=0)
            self.heading.add_css_class("sh-group-title")
            self.append(self.heading)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("sh-group")
        self.list.set_overflow(Gtk.Overflow.HIDDEN)
        self.list.connect("row-activated", self._on_activated)
        self.append(self.list)
        if note:
            label = Gtk.Label(label=note, xalign=0, wrap=True)
            label.add_css_class("sh-group-note")
            self.append(label)
        self._handlers: dict[Row, callable] = {}

    def add(self, row: Row, on_activate=None) -> Row:
        self.list.append(row)
        if on_activate is not None:
            row.set_activatable(True)
            self._handlers[row] = on_activate
        return row

    def clear(self) -> None:
        self._handlers.clear()
        self.list.remove_all()

    def _on_activated(self, _list, row) -> None:
        handler = self._handlers.get(row)
        if handler is not None:
            handler()
