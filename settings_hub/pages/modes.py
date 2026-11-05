"""The "Modes" page: one click sets up the desktop for what comes next."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import modes as hub_modes  # noqa: E402
from .. import strings  # noqa: E402
from ..controllers import modes as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


class ModesPage(Page):
    def build(self) -> None:
        self.controller = ctl.Controller(self.ctx.history, self.ctx.workers, self)
        group = self.add_group(Group(strings.MODES_GROUP))
        self.buttons: dict[str, tuple[Row, Gtk.Button]] = {}
        self._on_group: dict[str, list[str]] = {}  # an active mode -> its History groups
        for mode in hub_modes.MODES:
            title, hint = strings.MODES[mode.id][:2]
            button = Gtk.Button(label=strings.MODE_APPLY)
            button.connect("clicked", lambda *_a, mode_id=mode.id: self._clicked(mode_id))
            row = group.add(Row(title, hint, suffix=button, row_id=mode.id))
            self.rows[mode.id] = row
            self.buttons[mode.id] = (row, button)
        note = self.add_group(Group())
        note.add(Row(strings.MODES_NOTE, strings.MODES_NOTE_HINT))
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- the controller's view -----------------------------------------

    def _clicked(self, mode_id: str) -> None:
        group_ids = self._on_group.pop(mode_id, None)
        if group_ids is None:
            self.controller.apply(mode_id)
        elif self.ctx.undo_group is not None:
            self.buttons[mode_id][1].set_sensitive(False)  # once: the refresh shows the rest
            self.ctx.undo_group(group_ids)  # back to how it was before the mode

    def show_active(self, active: set[str]) -> None:
        groups = self.ctx.history.groups() if active else []
        self._on_group.clear()
        for mode_id, (row, button) in self.buttons.items():
            hint = strings.MODES[mode_id][1]
            if mode_id in active:
                row.title_label.set_label(
                    f"{strings.MODES[mode_id][0]} · {strings.MODE_IS_ON}")
                group_ids = hub_modes.groups_that_turned_on(
                    hub_modes.BY_ID[mode_id], groups, strings.HISTORY_UNDO_PREFIX)
                button.set_label(strings.MODE_TURN_OFF)
                # Without its groups (on by coincidence) there is nothing to go back to.
                button.set_sensitive(bool(group_ids))
                if group_ids:
                    self._on_group[mode_id] = group_ids
            else:
                row.title_label.set_label(strings.MODES[mode_id][0])
                button.set_label(strings.MODE_APPLY)
                button.set_sensitive(True)
            row.subtitle_label.set_label(hint)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = ModesPage
