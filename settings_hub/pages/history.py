"""The History page: every change as one line per user action, and undo."""

from __future__ import annotations

from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

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
        self.undo_button = Gtk.Button(label=strings.HISTORY_UNDO_BUTTON)
        self.undo_button.connect("clicked", lambda *_: self.ctx.undo_last())
        undo = self.add_group(Group(strings.HISTORY_UNDO_GROUP))
        self.rows["undo"] = undo.add(Row(
            strings.HISTORY_UNDO_ROW, strings.HISTORY_UNDO_HINT,
            suffix=self.undo_button, row_id="undo",
        ))
        self.log = self.add_group(Group(strings.HISTORY_LOG_GROUP))
        self.refresh()

    def refresh(self) -> None:
        groups = self.ctx.history.groups()
        self.undo_button.set_sensitive(bool(groups))
        self.log.clear()
        shown = list(reversed(groups))[:SHOWN]
        if not shown:
            self.rows["log"] = self.log.add(Row(strings.HISTORY_EMPTY, row_id="log"))
            return
        for i, group in enumerate(shown):
            row = self.log.add(Row(group.label, describe(group), row_id=group.id))
            if i == 0:
                self.rows["log"] = row


PAGE = HistoryPage
