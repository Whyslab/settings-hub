"""Common page machinery: lazy build, refresh on show, reveal a row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..history import History  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from ..workers import Workers  # noqa: E402


@dataclass
class Context:
    """What a page may use from the window."""

    history: History
    workers: Workers
    status: Callable[[str], None]  # one line at the bottom of the window
    undo_last: Callable[[], None]
    backends: dict[str, Any] = field(default_factory=dict)  # by History backend name


class Page:
    def __init__(self, page_id: str, ctx: Context) -> None:
        self.page_id = page_id
        self.ctx = ctx
        self.rows: dict[str, Row] = {}  # row id -> row, for search results
        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._box.add_css_class("sh-page")
        self.widget = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        clamp.append(self._box)
        self.widget.set_child(clamp)
        self.build()

    # ---- for subclasses ------------------------------------------------

    def build(self) -> None:
        """Create the widgets (called once)."""
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-read the sources and update widgets without firing handlers.

        Called every time the window is shown and every time the page is
        opened: the window keeps no state of its own.
        """

    def add_group(self, group: Group) -> Group:
        self._box.append(group)
        return group

    # ---- used by the window --------------------------------------------

    def focus_first(self) -> bool:
        return self._box.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def reveal(self, row_id: str) -> None:
        """Scroll to a row and tint it for a moment (opened from search)."""
        row = self.rows.get(row_id)
        if row is None:
            return
        row.grab_focus()  # the viewport scrolls to the focused child
        row.highlight()
        GLib.idle_add(self._scroll_to, row)

    def _scroll_to(self, row: Gtk.Widget) -> bool:
        """Put the row near the top, with its group heading still visible."""
        ok, point = row.compute_point(self._box, Graphene.Point())
        if ok:
            adj = self.widget.get_vadjustment()
            top = max(0.0, point.y - 40)
            adj.set_value(min(top, adj.get_upper() - adj.get_page_size()))
        return False


class PlaceholderPage(Page):
    """A page whose settings arrive in a later version."""

    def build(self) -> None:
        group = self.add_group(Group(note=strings.PLACEHOLDER_NOTE))
        group.add(Row(strings.PLACEHOLDER_TITLE))
