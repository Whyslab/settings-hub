"""The History page: every change as one line, filters, return and export.

"Return to this moment" reverts every group newer than the one clicked; the
window asks its conflict question once (history.plan_return_to), exactly like
Ctrl+Z. Export writes the journal next to it as history-export.jsonl.
"""

from __future__ import annotations

from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..history import Group as HistoryGroup  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

SHOWN = 200  # the journal keeps 1000 entries; the page shows the newest groups


def describe(group: HistoryGroup) -> str:
    try:
        when = datetime.fromisoformat(group.ts).strftime("%d.%m %H:%M")
    except ValueError:
        when = group.ts
    names = [strings.BACKENDS.get(b, b) for b in group.backends]
    return " · ".join([when, *names])


class HistoryPage(Page):
    def build(self) -> None:
        self.filter = ""
        self._backends: list[str] = []
        self.undo_button = Gtk.Button(label=strings.HISTORY_UNDO_BUTTON)
        self.undo_button.connect("clicked", lambda *_: self.ctx.undo_last())
        undo = self.add_group(Group(strings.HISTORY_UNDO_GROUP))
        self.rows["undo"] = undo.add(Row(
            strings.HISTORY_UNDO_ROW, strings.HISTORY_UNDO_HINT,
            suffix=self.undo_button, row_id="undo",
        ))
        tools = self.add_group(Group())
        self.filter_dropdown = Gtk.DropDown.new_from_strings([strings.HISTORY_ALL])
        self.filter_dropdown.set_valign(Gtk.Align.CENTER)
        self.filter_dropdown.connect("notify::selected", self._on_filter)
        self.rows["filter"] = tools.add(Row(
            strings.HISTORY_FILTER, strings.HISTORY_FILTER_HINT,
            suffix=self.filter_dropdown, row_id="filter"))
        self.export_button = Gtk.Button(label=strings.HISTORY_EXPORT_BUTTON)
        self.export_button.connect("clicked", lambda *_: self._export())
        self.rows["export"] = tools.add(Row(
            strings.HISTORY_EXPORT, strings.HISTORY_EXPORT_HINT,
            suffix=self.export_button, row_id="export"))

        self.log = self.add_group(Group(strings.HISTORY_LOG_GROUP))
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        groups = self.ctx.history.groups()
        self.undo_button.set_sensitive(bool(groups))
        self._fill_filter(groups)
        self.log.clear()
        shown = [g for g in reversed(groups)
                 if not self.filter or self.filter in g.backends][:SHOWN]
        if not shown:
            text = strings.HISTORY_EMPTY_FILTER if self.filter else strings.HISTORY_EMPTY
            self.rows["log"] = self.log.add(Row(text, row_id="log"))
            return
        newest = groups[-1].id if groups else ""
        for group in shown:
            row = self.log.add(Row(
                group.label, describe(group), row_id=group.id,
                suffix=self._return_button(group, group.id != newest)))
            if group is shown[0]:
                self.rows["log"] = row

    # ---- filters ---------------------------------------------------------

    def _fill_filter(self, groups: list[HistoryGroup]) -> None:
        backends: list[str] = []
        for group in groups:
            for backend in group.backends:
                if backend not in backends:
                    backends.append(backend)
        if backends == self._backends:
            return
        self._backends = backends
        labels = [strings.HISTORY_ALL, *[strings.BACKENDS.get(b, b) for b in backends]]
        self.filter_dropdown.set_model(Gtk.StringList.new(labels))
        self._select_filter()

    def _select_filter(self) -> None:
        index = self._backends.index(self.filter) + 1 if self.filter in self._backends else 0
        self.filter_dropdown.set_selected(index)

    def _on_filter(self, dropdown: Gtk.DropDown, _pspec) -> None:
        index = dropdown.get_selected()
        self.filter = self._backends[index - 1] if 1 <= index <= len(self._backends) else ""
        self.refresh()

    # ---- export ----------------------------------------------------------

    def _export(self) -> None:
        entries = self.ctx.history.entries()
        path = self.ctx.history.path.with_name("history-export.jsonl")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(entry.to_json() + "\n" for entry in entries),
                            encoding="utf-8")
        except OSError as exc:
            self.ctx.status(strings.HISTORY_EXPORT_FAILED.format(error=exc))
            return
        self.ctx.status(strings.HISTORY_EXPORTED.format(path=path, count=len(entries)))

    # ---- returning to a moment -----------------------------------------

    def _return_button(self, group: HistoryGroup, available: bool) -> Gtk.Button:
        button = Gtk.Button(label=strings.HISTORY_RETURN)
        button.set_sensitive(available)
        button.connect("clicked", lambda *_a, group_id=group.id, label=group.label:
                       self._return_to(group_id, label))
        return button

    def _return_to(self, group_id: str, label: str) -> None:
        if self.ctx.return_to is None:
            return
        dialog = Gtk.AlertDialog(
            message=strings.HISTORY_RETURN_TITLE,
            detail=strings.HISTORY_RETURN_BODY.format(label=label),
            buttons=[strings.HISTORY_RETURN_OK, strings.HISTORY_CONFLICT_CANCEL],
            cancel_button=1, default_button=0, modal=True,
        )

        def answered(dlg, result) -> None:
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                return
            if choice == 0:
                self.ctx.return_to(group_id)

        dialog.choose(self.widget.get_root(), None, answered)


PAGE = HistoryPage
