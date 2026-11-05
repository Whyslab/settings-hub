"""A page built from the variable table: widgets, live values and edits.

The same class serves "Окна и вид" and "Клавиатура и мышь"; pages/windows.py
and pages/input.py only name it. Rows come from variables.grouped(page), the
labels from strings, the logic from controllers.variables.Controller.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import strings, variables  # noqa: E402
from ..controllers import variables as ctl  # noqa: E402
from ..variables import backend as hypr  # noqa: E402
from ..widgets import fields  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


def choice_labels(var: variables.Var, themes: list[str] | None = None) -> list[tuple[str, str]]:
    """[(value, label)] for a choice: the cursor theme is its own list."""
    if var.option == "cursor:theme":
        names = themes or []
        return [(name, name) for name in names]
    labels = strings.VAR_CHOICES.get(var.option, {})
    return [(value, labels.get(value) or strings.CHOICE_LABELS.get(value, value))
            for value in var.choices]


class VariablesPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(hypr.BACKEND)
        if backend is None:  # normally created by the app, with a History applier
            backend = hypr.Backend(self.ctx.workers)
            hypr.register(self.ctx.history, backend)
            self.ctx.backends[hypr.BACKEND] = backend
        self.backend = backend
        self.controls: dict[str, fields.Control] = {}
        self.page_options = [v.option for v in variables.for_page(self.page_id)]
        themes = backend.cursor_themes() if any(
            v.option == "cursor:theme" for v in variables.for_page(self.page_id)) else None

        for group_id, members in variables.grouped(self.page_id):
            group = self.add_group(Group(strings.VAR_GROUPS[self.page_id][group_id]))
            for var in members:
                control = fields.make(
                    var,
                    lambda value, option=var.option: self.controller.edit(option, value),
                    choice_labels(var, themes),
                )
                self.controls[var.option] = control
                label, hint = strings.VARS[var.option][:2]
                row = group.add(Row(label, hint, suffix=control.widget,
                                    row_id=var.option))
                self.rows[var.option] = row

        reset = self.add_group(Group())
        button = Gtk.Button(label=strings.VAR_RESET_BUTTON)
        button.connect("clicked", lambda *_: self.confirm(
            strings.VAR_RESET, strings.VAR_RESET_ASK, strings.VAR_RESET_BUTTON,
            lambda: self.controller.reset(self.page_options)))
        self.rows["reset"] = reset.add(Row(strings.VAR_RESET, strings.VAR_RESET_HINT,
                                           suffix=button, row_id="reset"))

        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- the controller's view -----------------------------------------

    def show_values(self, values: dict[str, Any]) -> None:
        root = self.widget.get_root()
        focus = root.get_focus() if root is not None else None
        for option, value in values.items():
            control = self.controls.get(option)
            if control is None:
                continue
            if (isinstance(control, fields.EntryControl) and focus is not None
                    and (focus is control.entry or focus.is_ancestor(control.entry))):
                continue  # being typed in: a refresh must not take the text away
            control.set(value)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = VariablesPage
