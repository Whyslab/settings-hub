"""Sidebar: search field, page list grouped by section, search results.

With an empty search field it lists the pages, grouped, each with its coloured
icon. While text is typed the same list shows search results instead
("Page" or "Page -> row"). Enter in the field opens the first result; Down
moves into the list. Emits "open" with (page_id, row_id or "").
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GObject, Gtk, Pango  # noqa: E402

from .. import registry, search, strings  # noqa: E402

WIDTH = 220


class NavRow(Gtk.ListBoxRow):
    def __init__(self, page: registry.PageInfo, row_id: str | None = None,
                 row_title: str | None = None) -> None:
        super().__init__()
        self.page_id = page.id
        self.group = page.group
        self.row_id = row_id
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_file(str(page.icon_path))
        icon.set_pixel_size(20)
        icon.add_css_class("sh-icon")
        icon.set_valign(Gtk.Align.CENTER)
        box.append(icon)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        texts.append(Gtk.Label(label=registry.title(page.id), xalign=0,
                               ellipsize=Pango.EllipsizeMode.END))
        if row_title:
            sub = Gtk.Label(label=row_title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.add_css_class("sh-subtitle")
            texts.append(sub)
        box.append(texts)
        self.set_child(box)


class Sidebar(Gtk.Box):
    __gsignals__ = {
        "open": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("sh-sidebar")
        self.set_size_request(WIDTH, -1)
        self.set_hexpand(False)
        self._index = search.Index()
        self._suppress = False

        self.entry = Gtk.SearchEntry(placeholder_text=strings.SEARCH_PLACEHOLDER)
        # Its natural width would otherwise widen the sidebar past WIDTH.
        self.entry.set_width_chars(1)
        self.entry.set_max_width_chars(1)
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", self._on_entry_activate)
        self.append(self.entry)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("sh-nav")
        self.list.set_header_func(self._header)
        self.list.connect("row-activated", self._on_row_activated)
        self.list.connect("row-selected", self._on_row_selected)
        self.list.set_placeholder(self._nothing_found())
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.list)
        self.append(scroller)

        self._searching = False
        self._fill_pages()

    @staticmethod
    def _nothing_found() -> Gtk.Widget:
        label = Gtk.Label(label=strings.SEARCH_NOTHING, margin_top=12)
        label.add_css_class("sh-dim")
        return label

    # ---- content ----------------------------------------------------------

    def _fill_pages(self) -> None:
        self._searching = False
        self.list.remove_all()
        for page in registry.PAGES:
            self.list.append(NavRow(page))
        self.list.invalidate_headers()

    def _fill_results(self, results: list[search.Result]) -> None:
        self._searching = True
        self.list.remove_all()
        for r in results:
            self.list.append(NavRow(registry.get(r.page_id), r.row_id, r.row_title))
        self.list.invalidate_headers()

    def _header(self, row: NavRow, before: NavRow | None) -> None:
        if self._searching or (before is not None and before.group == row.group):
            row.set_header(None)
            return
        label = Gtk.Label(label=strings.GROUPS[row.group], xalign=0)
        label.add_css_class("sh-nav-header")
        if before is None:
            label.add_css_class("first")
        row.set_header(label)

    # ---- state --------------------------------------------------------------

    def select_page(self, page_id: str) -> None:
        """Mark the page as current without emitting "open" again."""
        if self._searching:
            return
        for row in self._rows():
            if row.page_id == page_id:
                self._suppress = True
                self.list.select_row(row)
                self._suppress = False
                return

    def focus_search(self) -> None:
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def focus_list(self) -> None:
        row = self.list.get_selected_row() or self.list.get_row_at_index(0)
        if row is not None:
            row.grab_focus()

    def contains_focus(self, widget: Gtk.Widget | None) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = widget.get_parent()
        return False

    def clear_search(self) -> bool:
        """Empty the search field; True if there was something to clear."""
        if not self.entry.get_text():
            return False
        self.entry.set_text("")
        return True

    def _rows(self) -> list[NavRow]:
        out = []
        i = 0
        while (row := self.list.get_row_at_index(i)) is not None:
            out.append(row)
            i += 1
        return out

    # ---- signals ------------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        text = entry.get_text()
        if text.strip():
            self._fill_results(self._index.search(text))
        else:
            self._fill_pages()
            self.emit("open", "", "")  # re-select the page that is shown

    def _on_entry_activate(self, entry: Gtk.SearchEntry) -> None:
        # Search from the text itself: Enter can come before the field's
        # delayed search-changed has filled the list.
        results = self._index.search(entry.get_text(), limit=1)
        if results:
            first = results[0]
            entry.set_text("")
            self.emit("open", first.page_id, first.row_id or "")

    def _on_row_activated(self, _list, row: NavRow) -> None:
        self._open_row(row)

    def _on_row_selected(self, _list, row: NavRow | None) -> None:
        if row is not None and not self._suppress and not self._searching:
            self.emit("open", row.page_id, "")

    def _open_row(self, row: NavRow) -> None:
        page_id, row_id = row.page_id, row.row_id or ""
        if self._searching:
            # Back to the page list; the field's (delayed) search-changed then
            # refills it and re-selects the page that is shown.
            self.entry.set_text("")
        self.emit("open", page_id, row_id)
