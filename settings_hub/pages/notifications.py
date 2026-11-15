"""The "Notifications" page: HyprPanel's popups, Do Not Disturb, the ignore list.

Every change is one History entry (Ctrl+Z undoes it). A number is written
when it has been still for SETTLE_MS, so clicking + five times is one entry.
Clearing the stored notifications cannot be undone and asks first.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import notifications as nb  # noqa: E402
from ..variables import Var  # noqa: E402
from ..widgets import fields  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

SETTLE_MS = 600


def label(key: str) -> str:
    return strings.NOTIF_LABELS.get(key, key)


class NotificationsPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(nb.BACKEND)
        if backend is None:
            backend = nb.Backend(self.ctx.workers)
            nb.register(self.ctx.history, backend)
            self.ctx.backends[nb.BACKEND] = backend
        self.backend = backend
        self.info: nb.Info | None = None
        self.ignore: list[str] = []
        self._pending: set[str] = set()  # keys being written: a refresh leaves them be
        self._settle = 0
        self._series_before: Any = None

        self.banner = self.add_group(Group())
        self.banner.add(Row(strings.NOTIF_NO_PANEL))
        self.banner.set_visible(False)

        show = self.add_group(Group(strings.NOTIF_SHOW_GROUP))
        self.controls: dict[str, fields.Control] = {}

        def control(key: str, var: Var, title: str, hint: str,
                    choices: list[tuple[str, str]] | None = None) -> None:
            ctl = fields.make(var, lambda value, k=key: self._changed(k, value), choices)
            self.controls[key] = ctl
            self.rows[key] = show.add(Row(title, hint, suffix=ctl.widget, row_id=key))

        control(nb.DND, Var(nb.DND, "bool", False), strings.NOTIF_DND, strings.NOTIF_DND_HINT)
        control(nb.POSITION, Var(nb.POSITION, "choice", nb.DEFAULTS[nb.POSITION],
                                 choices=nb.POSITIONS),
                strings.NOTIF_POSITION, strings.NOTIF_POSITION_HINT,
                [(p, strings.NOTIF_POSITIONS[p]) for p in nb.POSITIONS])
        control(nb.TIMEOUT, Var(nb.TIMEOUT, "int", 7, lo=nb.TIMEOUT_MIN_MS // 1000,
                                hi=nb.TIMEOUT_MAX_MS // 1000, step=1, unit=strings.UNIT_S),
                strings.NOTIF_TIMEOUT, strings.NOTIF_TIMEOUT_HINT)
        control(nb.ACTIVE_MONITOR, Var(nb.ACTIVE_MONITOR, "bool", True),
                strings.NOTIF_ACTIVE, strings.NOTIF_ACTIVE_HINT)
        control(nb.HOVER, Var(nb.HOVER, "bool", False),
                strings.NOTIF_HOVER, strings.NOTIF_HOVER_HINT)

        self.ignore_group = self.add_group(Group(strings.NOTIF_IGNORE_GROUP,
                                                 strings.NOTIF_IGNORE_NOTE))
        add = self.add_group(Group())
        self.app_model = Gtk.StringList()
        self.app_dropdown = Gtk.DropDown(model=self.app_model)
        self.app_dropdown.set_valign(Gtk.Align.CENTER)
        self.add_button = Gtk.Button(label=strings.NOTIF_ADD)
        self.add_button.connect("clicked", lambda *_: self._add_ignored())
        box = Gtk.Box(spacing=8)
        box.append(self.app_dropdown)
        box.append(self.add_button)
        self.rows[nb.IGNORE] = add.add(Row(strings.NOTIF_IGNORE_PICK, suffix=box,
                                           row_id=nb.IGNORE))

        store = self.add_group(Group(strings.NOTIF_STORE_GROUP))
        self.clear_button = Gtk.Button(label=strings.NOTIF_CLEAR)
        self.clear_button.add_css_class("destructive-action")
        self.clear_button.connect("clicked", lambda *_: self.confirm(
            strings.NOTIF_CLEAR_ASK, strings.NOTIF_CLEAR_DETAIL, strings.NOTIF_CLEAR,
            self._clear))
        self.stored_row = store.add(Row(strings.NOTIF_STORED_UNKNOWN, strings.NOTIF_STORED_HINT,
                                        suffix=self.clear_button, row_id="stored"))
        self.rows["stored"] = self.stored_row
        test = Gtk.Button(label=strings.NOTIF_TEST)
        test.connect("clicked", lambda *_: self._test())
        self.rows["test"] = store.add(Row(strings.NOTIF_TEST_ROW, strings.NOTIF_TEST_HINT,
                                          suffix=test, row_id="test"))

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(nb.WORKER, self.backend.probe, self._show, key="probe")

    def _reread(self) -> None:
        """After our own write: everything but Do Not Disturb, whose state is known
        (reading it flips it twice, so not after every change)."""
        self.ctx.workers.submit(nb.WORKER, lambda: self.backend.probe(with_dnd=False),
                                self._show, key="reread")

    def _show(self, info: nb.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.NOTIF_READ_FAILED.format(error=error))
            return
        if not info.dnd_read and self.info is not None:
            info.dnd, info.panel = self.info.dnd, info.panel or self.info.panel
        self.info = info
        self.banner.set_visible(not info.panel)
        for key, ctl in self.controls.items():
            if key in self._pending:
                continue
            if key == nb.DND:
                ctl.set(bool(info.dnd))
                ctl.widget.set_sensitive(info.dnd is not None)
            elif key == nb.TIMEOUT:
                ctl.set(round(info.values[key] / 1000))
            else:
                ctl.set(info.values[key])
        if nb.IGNORE not in self._pending:
            self.ignore = list(info.values[nb.IGNORE])
        self._show_ignore()
        if info.stored is None:
            self.stored_row.title_label.set_label(strings.NOTIF_STORED_UNKNOWN)
        else:
            self.stored_row.title_label.set_label(strings.NOTIF_STORED.format(count=info.stored))
        self.clear_button.set_sensitive(info.panel and bool(info.stored))

    def _show_ignore(self) -> None:
        self.ignore_group.clear()
        if not self.ignore:
            self.ignore_group.add(Row(strings.NOTIF_IGNORE_EMPTY))
        for name in self.ignore:
            button = Gtk.Button(label=strings.NOTIF_REMOVE)
            button.connect("clicked", lambda *_a, n=name: self._remove_ignored(n))
            self.ignore_group.add(Row(name, suffix=button))
        recent = [a for a in (self.info.apps if self.info else []) if a not in self.ignore]
        self.app_model.splice(0, self.app_model.get_n_items(),
                              recent or [strings.NOTIF_IGNORE_NO_RECENT])
        self._recent = recent
        self.app_dropdown.set_sensitive(bool(recent))
        self.add_button.set_sensitive(bool(recent))

    # ---- changes --------------------------------------------------------

    def _changed(self, key: str, value: Any) -> None:
        if self.info is None:
            return
        if key == nb.TIMEOUT:
            if self._series_before is None:
                self._series_before = self.info.values[nb.TIMEOUT]
            self._pending.add(key)
            if self._settle:
                GLib.source_remove(self._settle)
            self._settle = GLib.timeout_add(SETTLE_MS, self._timeout_rested, int(value) * 1000)
            return
        before = self.info.dnd if key == nb.DND else self.info.values[key]
        if key == nb.DND and before is None:
            before = not value  # unknown: the switch showed the opposite of what was picked
        self._write(key, before, value)

    def _timeout_rested(self, value: int) -> bool:
        self._settle = 0
        before, self._series_before = self._series_before, None
        self._write(nb.TIMEOUT, before, value)
        return False

    def _write(self, key: str, before: Any, after: Any) -> None:
        if before == after:
            self._pending.discard(key)
            return
        self._pending.add(key)
        self._seq = getattr(self, "_seq", 0) + 1
        # What it will be: a quick second change starts from this, not from the old read.
        if key == nb.DND:
            self.info.dnd = after
        else:
            self.info.values[key] = after

        def job() -> None:
            self.backend.apply({key: after})

        def done(_result, error: BaseException | None) -> None:
            self._pending.discard(key)
            if error is not None:
                self.ctx.status(strings.NOTIF_FAILED.format(error=error))
                self.refresh()  # the real state, Do Not Disturb included
                return
            self.ctx.history.record([(nb.BACKEND, key, label(key), before, after)])
            self.ctx.status(strings.NOTIF_APPLIED.format(name=label(key)))
            self._reread()

        # a key of its own: a queued change is never replaced, so none is left out of History
        self.ctx.workers.submit(nb.WORKER, job, done, key=("write", self._seq))

    def _add_ignored(self) -> None:
        index = self.app_dropdown.get_selected()
        recent = getattr(self, "_recent", [])
        if index == Gtk.INVALID_LIST_POSITION or index >= len(recent):
            return
        before = list(self.ignore)
        self.ignore = before + [recent[index].strip()]
        self._show_ignore()
        self._write(nb.IGNORE, before, list(self.ignore))

    def _remove_ignored(self, name: str) -> None:
        before = list(self.ignore)
        self.ignore = [n for n in before if n != name]
        self._show_ignore()
        self._write(nb.IGNORE, before, list(self.ignore))

    def _clear(self) -> None:
        def done(_result, error: BaseException | None) -> None:
            self.ctx.status(strings.NOTIF_FAILED.format(error=error) if error is not None
                            else strings.NOTIF_CLEARED)
            self.refresh()

        self.ctx.workers.submit(nb.WORKER, self.backend.clear, done, key="clear")

    def _test(self) -> None:
        def job() -> None:
            self.backend.test(strings.NOTIF_TEST_SUMMARY, strings.NOTIF_TEST_BODY,
                              strings.APP_TITLE)

        def done(_result, error: BaseException | None) -> None:
            if error is not None:
                self.ctx.status(strings.NOTIF_FAILED.format(error=error))

        self.ctx.workers.submit(nb.WORKER, job, done, key="test")


PAGE = NotificationsPage
