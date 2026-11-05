"""The "General" page: the window's own settings from settings.FIELDS.

Each row is a field of settings.FIELDS; the control is the same one the
variable pages use (widgets.fields), the labels are in strings.HUB_SETTINGS.
A change is stored and logged as one History group; subscribers in app.py
apply the look at once.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import settings as hub_settings  # noqa: E402
from .. import strings  # noqa: E402
from ..variables import Var  # noqa: E402
from ..widgets import fields  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

BACKEND = "settings"


def as_var(field: hub_settings.Field) -> Var:
    """A settings.Field as the Var the widget factory understands."""
    return Var(option=field.key, kind=field.kind, default=field.default,
               lo=field.lo, hi=field.hi, step=field.step, choices=field.choices,
               page="general", group=field.group)


def choice_labels(field: hub_settings.Field) -> list[tuple[str, str]]:
    if field.key == "behavior.start_page":
        return [(hub_settings.START_PAGE_LAST, strings.HUB_START_LAST), *[
            (page_id, strings.PAGES[page_id]["title"])
            for page_id in hub_settings.START_PAGES[1:] if page_id in strings.PAGES
        ]]
    return [(value, strings.HUB_CHOICES.get(value, value)) for value in field.choices]


class GeneralPage(Page):
    def build(self) -> None:
        self.settings = self.ctx.settings
        if self.settings is None:  # a page built without the app (tests)
            self.settings = hub_settings.Settings()
            hub_settings.register(self.ctx.history, self.settings)
        self.controls: dict[str, fields.Control] = {}
        for group_id in self.settings.groups():
            group = self.add_group(Group(strings.HUB_GROUPS[group_id]))
            for field in self.settings.fields_of(group_id):
                control = fields.make(as_var(field),
                                      lambda value, key=field.key: self._changed(key, value),
                                      choice_labels(field))
                self.controls[field.key] = control
                label, hint = strings.HUB_SETTINGS[field.key][:2]
                row = group.add(Row(label, hint, suffix=control.widget,
                                    row_id=field.key))
                self.rows[field.key] = row

        reset = self.add_group(Group())
        button = Gtk.Button(label=strings.HUB_RESET_BUTTON)
        button.connect("clicked", lambda *_: self._reset())
        reset.add(Row(strings.HUB_RESET, strings.HUB_RESET_HINT, suffix=button,
                      row_id="reset"))
        self.rows["reset"] = reset
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        for key, control in self.controls.items():
            control.set(self.settings.get(key))

    # ---- signals --------------------------------------------------------

    def _changed(self, key: str, value: Any) -> None:
        before = self.settings.get(key)
        if before == value:
            return
        try:
            self.settings.set(key, value)
        except (KeyError, ValueError) as exc:
            self.ctx.status(strings.HUB_FAILED.format(error=exc))
            self.refresh()
            return
        self.ctx.history.record([
            (BACKEND, key, strings.HUB_SETTINGS[key][0], before, value)])
        self.ctx.status(strings.HUB_APPLIED.format(name=strings.HUB_SETTINGS[key][0]))

    def _reset(self) -> None:
        items = self.settings.reset()
        if not items:
            self.ctx.status(strings.HUB_NOTHING_CHANGED)
            return
        self.ctx.history.record([
            (BACKEND, key, strings.HUB_SETTINGS[key][0], before, after)
            for key, before, after in items
        ])
        self.refresh()
        self.ctx.status(strings.HUB_RESET_DONE)


PAGE = GeneralPage
