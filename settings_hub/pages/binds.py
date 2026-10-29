"""The "Binds" page: every key combination, grouped, with search; rebind,
disable, revert, add.

Only widgets live here; controllers.binds.Controller decides what to write,
and this page is its view. Key capture is widgets.keycapture.KeyCapture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import binds as bb  # noqa: E402
from ..controllers import binds as ctl  # noqa: E402
from ..widgets.keycapture import Captured, KeyCapture  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


class BindRow(Row):
    def __init__(self, model: ctl.RowModel, page: BindsPage) -> None:
        keys = Gtk.Label(label=model.combo)
        keys.add_css_class("sh-keys")
        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if model.live_ok is False:
            warn = Gtk.Label(label="!", tooltip_text=strings.BN_MISMATCH)
            warn.add_css_class("sh-bind-warn")
            suffix.append(warn)
        suffix.append(keys)
        menu = Gtk.MenuButton(tooltip_text=strings.BN_MENU, has_frame=False)
        menu.set_child(Gtk.Label(label="⋯"))  # no drop-down arrow, like macOS
        menu.add_css_class("sh-bind-menu")
        menu.set_sensitive(model.editable)
        suffix.append(menu)
        super().__init__(model.name, model.detail, suffix=suffix, row_id=model.id)
        self.model, self.keys, self.menu = model, keys, menu
        self.items: dict[str, Gtk.Button] = {}
        menu.set_popover(self._popover(page))
        for label in (self.title_label, self.subtitle_label):
            label.set_wrap(False)
            label.set_ellipsize(Pango.EllipsizeMode.END)
        if model.disabled:
            self.add_css_class("sh-bind-disabled")

    def _popover(self, page: BindsPage) -> Gtk.Popover:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        popover = Gtk.Popover(child=box)
        m = self.model

        def item(key: str, label: str, fn: Callable[[], None]) -> None:
            button = Gtk.Button(label=label)
            button.add_css_class("flat")
            button.add_css_class("sh-menu-item")
            button.get_child().set_xalign(0)

            def clicked(_b) -> None:
                popover.popdown()
                fn()

            button.connect("clicked", clicked)
            box.append(button)
            self.items[key] = button

        if m.movable and not m.disabled:
            item("rebind", strings.BN_REBIND, lambda: page.start_rebind(m.id))
        if not m.disabled:
            if len(m.actions) > 1:
                for i, (action, name) in enumerate(m.actions):
                    item(f"disable.{i}", strings.BN_DISABLE_ONE.format(name=name),
                         lambda a=action: page.controller.disable(m.id, a))
                item("disable", strings.BN_DISABLE_ALL, lambda: page.controller.disable(m.id))
            else:
                item("disable", strings.BN_DISABLE, lambda: page.controller.disable(m.id))
        if m.managed:
            item("revert", strings.BN_REVERT, lambda: page.controller.revert(m.id))
        return popover

    def set_capturing(self, on: bool) -> None:
        if on:
            self.keys.set_label(strings.BN_PRESS)
            self.keys.add_css_class("sh-capturing")
        else:
            self.keys.set_label(self.model.combo)
            self.keys.remove_css_class("sh-capturing")


class BindsPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(bb.BACKEND)
        if backend is None:  # normally created by the app, with the History applier
            backend = bb.Backend(self.ctx.workers)
            bb.register(self.ctx.history, backend)
            self.ctx.backends[bb.BACKEND] = backend
        self.backend = backend
        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self.capture: KeyCapture | None = None
        self.capture_inhibit = True  # False: tests emulate a compositor that refuses
        self.bind_rows: dict[str, BindRow] = {}
        self._groups: list[Group] = []
        self._pending_rows: tuple[list[ctl.RowModel], bool] | None = None
        self._editable = False

        self.setup_group = self.add_group(Group())
        self.setup_row = self.setup_group.add(Row(" ", " "))
        self.setup_group.set_visible(False)

        self.search = Gtk.SearchEntry(placeholder_text=strings.BN_SEARCH, hexpand=True)
        self.search.add_css_class("sh-page-search")
        self.search.connect("search-changed", lambda *_: self._filter())
        self._box.append(self.search)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._box.append(self.list_box)
        self.nothing = Gtk.Label(label=strings.BN_NOTHING, visible=False)
        self.nothing.add_css_class("sh-group-note")
        self._box.append(self.nothing)

        self._build_add()
        self.refresh()

    def _build_add(self) -> None:
        group = self.add_group(Group(strings.BN_ADD_GROUP, strings.BN_NOTE))
        self.add_group_widget = group
        self.add_entry = Gtk.Entry(placeholder_text=strings.BN_ADD_COMMAND_HINT,
                                   width_chars=28)
        self.add_entry.connect("changed", lambda *_: self._update_add())
        self.rows["add"] = group.add(Row(strings.BN_ADD_COMMAND, suffix=self.add_entry,
                                         row_id="add"))
        self.add_keys = Gtk.Label()
        self.add_combo: Captured | None = None
        self._show_add_combo()
        self.add_capture_button = Gtk.Button(label=strings.BN_ADD_COMBO_BUTTON)
        self.add_capture_button.connect("clicked", lambda *_: self.start_add_capture())
        self.add_button = Gtk.Button(label=strings.BN_ADD_BUTTON, sensitive=False)
        self.add_button.add_css_class("suggested-action")
        self.add_button.connect("clicked", lambda *_: self._add())
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(self.add_keys)
        box.append(self.add_capture_button)
        box.append(self.add_button)
        group.add(Row(strings.BN_ADD_COMBO, suffix=box))

    # ---- page protocol ------------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- the controller's view ----------------------------------------------

    def show_setup(self, lua: Path | None, not_sourced: bool, error: str,
                   live_known: bool) -> None:
        if lua is not None:
            title, hint = strings.BN_LUA, strings.BN_LUA_HINT.format(path=lua)
        elif error:
            title, hint = strings.BN_READ_FAILED, error
        elif not_sourced:
            title, hint = strings.BN_NOT_SOURCED, strings.BN_NOT_SOURCED_HINT
        elif not live_known:
            title, hint = strings.BN_SETUP_GROUP, strings.BN_LIVE_UNKNOWN
        else:
            self.setup_group.set_visible(False)
            return
        self.setup_row.title_label.set_label(title)
        self.setup_row.subtitle_label.set_label(hint)
        self.setup_row.subtitle_label.set_visible(True)
        self.setup_group.set_visible(True)

    def show_rows(self, rows: list[ctl.RowModel], editable: bool) -> None:
        if self.capture is not None:
            self._pending_rows = (rows, editable)  # rebuilt when the capture ends
            return
        self._editable = editable
        for group in self._groups:
            self.list_box.remove(group)
        self._groups, self.bind_rows = [], {}
        current: Group | None = None
        title = None
        for model in rows:
            if model.group_title != title:
                title = model.group_title
                current = Group(title)
                self._groups.append(current)
                self.list_box.append(current)
            row = BindRow(model, self)
            current.add(row)
            self.bind_rows[model.id] = row
        if rows:
            self.rows["list"] = self.bind_rows[rows[0].id]
        self.add_group_widget.set_sensitive(editable)
        self._filter()

    def status(self, text: str) -> None:
        if text:
            self.ctx.status(text)

    def ask_conflict(self, combo: str, occupant: str, on_replace: Callable[[], None]) -> None:
        dialog = Gtk.AlertDialog(
            message=strings.BN_CONFLICT_TITLE.format(combo=combo),
            detail=strings.BN_CONFLICT_BODY.format(name=occupant),
            buttons=[strings.BN_CONFLICT_REPLACE, strings.BN_CONFLICT_CANCEL],
            cancel_button=1, default_button=1, modal=True)

        def answered(dlg, result) -> None:
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                return
            if choice == 0:
                on_replace()

        dialog.choose(self.widget.get_root(), None, answered)

    # ---- search -------------------------------------------------------------

    def _filter(self) -> None:
        query = self.search.get_text()
        any_shown = False
        for group in self._groups:
            shown = False
            row = group.list.get_first_child()
            while row is not None:
                if isinstance(row, BindRow):
                    visible = row.model.matches(query)
                    row.set_visible(visible)
                    shown = shown or visible
                row = row.get_next_sibling()
            group.set_visible(shown)
            any_shown = any_shown or shown
        self.nothing.set_visible(bool(self._groups) and not any_shown)

    # ---- capture ------------------------------------------------------------

    def _start_capture(self, on_done: Callable[[Captured | None], None]) -> bool:
        if self.capture is not None or not self._editable:
            return False
        self.capture = KeyCapture(self.widget, on_done, self.backend.hyprctl,
                                  inhibit=self.capture_inhibit)
        self.ctx.status(f"{strings.BN_PRESS} {strings.BN_PRESS_HINT}")
        self.capture.start()
        return True

    def _capture_ended(self) -> None:
        self.capture = None
        if self._pending_rows is not None:
            rows, editable = self._pending_rows
            self._pending_rows = None
            self.show_rows(rows, editable)

    def start_rebind(self, row_id: str) -> None:
        row = self.bind_rows.get(row_id)
        if row is None:
            return

        def done(result: Captured | None) -> None:
            row.set_capturing(False)
            self._capture_ended()
            if result is not None:
                self.controller.rebind(row_id, result.mask, result.key)

        if self._start_capture(done):
            row.set_capturing(True)

    def start_add_capture(self) -> None:
        def done(result: Captured | None) -> None:
            self.add_capture_button.set_sensitive(True)
            self._capture_ended()
            if result is not None:
                self.add_combo = result
            self.add_keys.remove_css_class("sh-capturing")
            self._show_add_combo()
            self._update_add()

        if self._start_capture(done):
            self.add_capture_button.set_sensitive(False)
            self.add_keys.set_label(strings.BN_PRESS)
            self.add_keys.remove_css_class("sh-value")
            self.add_keys.add_css_class("sh-keys")
            self.add_keys.add_css_class("sh-capturing")

    def _show_add_combo(self) -> None:
        """The chosen combination as a key cap; "not set" as plain dim text."""
        chosen = self.add_combo is not None
        self.add_keys.set_label(self.add_combo.label if chosen else strings.BN_ADD_COMBO_NONE)
        for cls, on in (("sh-keys", chosen), ("sh-value", not chosen)):
            if on:
                self.add_keys.add_css_class(cls)
            else:
                self.add_keys.remove_css_class(cls)

    def _update_add(self) -> None:
        self.add_button.set_sensitive(bool(self.add_entry.get_text().strip()
                                           and self.add_combo is not None))

    def _add(self) -> None:
        if self.add_combo is None:
            return
        self.controller.add(self.add_entry.get_text(), self.add_combo.mask, self.add_combo.key)
        self.add_entry.set_text("")
        self.add_combo = None
        self._show_add_combo()
        self._update_add()


PAGE = BindsPage
