"""The "Default applications" page: which program opens links, folders, pictures, …

One drop-down per kind. A choice is written at once (backends.default_apps)
and is one History item, so Ctrl+Z gives back the previous program.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import default_apps as da  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


def labels(options: tuple[da.App, ...]) -> list[str]:
    """Names for a drop-down; two programs of one name get their file id too."""
    names = [a.name for a in options]
    return [f"{a.name} ({a.id.removesuffix('.desktop')})" if names.count(a.name) > 1 else a.name
            for a in options]


class DefaultAppsPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(da.BACKEND)
        if backend is None:
            backend = da.Backend(self.ctx.workers)
            da.register(self.ctx.history, backend)
            self.ctx.backends[da.BACKEND] = backend
        self.backend = backend
        self._quiet = False
        self._choices: dict[str, da.Choice] = {}
        self._ids: dict[str, list[str]] = {}  # kind -> desktop id of each drop-down item
        self.dropdowns: dict[str, Gtk.DropDown] = {}

        opens = self.add_group(Group(strings.DEFAPPS_GROUP, strings.DEFAPPS_NOTE))
        terminal = self.add_group(Group(strings.DEFAPPS_TERMINAL_GROUP,
                                        strings.DEFAPPS_TERMINAL_NOTE))
        titles = strings.PAGES["default-apps"]["rows"]
        for kind in da.ORDER:
            dropdown = Gtk.DropDown(model=Gtk.StringList(), enable_search=True,
                                    valign=Gtk.Align.CENTER)
            dropdown.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            dropdown.connect("notify::selected", self._on_selected, kind)
            dropdown.update_property([Gtk.AccessibleProperty.LABEL], [titles[kind][0]])
            self.dropdowns[kind] = dropdown
            group = terminal if kind == da.TERMINAL else opens
            self.rows[kind] = group.add(Row(titles[kind][0], strings.DEFAPPS_HINT[kind],
                                            suffix=dropdown, row_id=kind))

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(da.WORKER, self.backend.probe, self._show, key="probe")

    def _show(self, info: da.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.DEFAPPS_FAILED.format(error=error))
            return
        self._choices = info.choices
        self._quiet = True
        try:
            for kind, choice in info.choices.items():
                self._show_choice(kind, choice, info.shim)
        finally:
            self._quiet = False

    def _show_choice(self, kind: str, choice: da.Choice, shim: bool) -> None:
        dropdown = self.dropdowns[kind]
        ids = [a.id for a in choice.options]
        names = labels(choice.options)
        # Nothing chosen, or not one program for every format: say so instead of
        # naming a program (picking that program then sets it for all of them).
        if not choice.current or choice.mixed:
            ids = ["", *ids]
            names = [strings.DEFAPPS_VARIOUS if choice.mixed else strings.DEFAPPS_NONE, *names]
        self._ids[kind] = ids
        model = dropdown.get_model()
        model.splice(0, model.get_n_items(), names)
        dropdown.set_selected(0 if not ids[0] else ids.index(choice.current)
                              if choice.current in ids else 0)
        dropdown.set_sensitive(bool(choice.options))
        row = self.rows[kind]
        if not choice.options:
            note = strings.DEFAPPS_NO_APPS
        elif kind == da.TERMINAL and not shim:
            note = strings.DEFAPPS_NO_SHIM
        elif choice.mixed:
            note = strings.DEFAPPS_MIXED
        elif not choice.current:
            note = strings.DEFAPPS_NOT_CHOSEN
        else:
            note = strings.DEFAPPS_HINT[kind]
        row.subtitle_label.set_label(note)
        row.subtitle_label.set_visible(True)

    # ---- changes --------------------------------------------------------

    def _on_selected(self, dropdown: Gtk.DropDown, _pspec, kind: str) -> None:
        if self._quiet:
            return
        index = dropdown.get_selected()
        ids = self._ids.get(kind, [])
        if index == Gtk.INVALID_LIST_POSITION or index >= len(ids) or not ids[index]:
            return
        desktop_id = ids[index]
        title = strings.PAGES["default-apps"]["rows"][kind][0]
        choice = self._choices.get(kind)
        name = next((a.name for a in choice.options if a.id == desktop_id), desktop_id) \
            if choice is not None else desktop_id

        def done(result, error: BaseException | None) -> None:
            if error is not None:
                self.ctx.status(strings.DEFAPPS_FAILED.format(error=error))
            else:
                before, after = result
                if before != after:
                    self.ctx.history.record([(da.BACKEND, kind,
                                              strings.DEFAPPS_HISTORY.format(kind=title),
                                              before, after)])
                self.ctx.status(strings.DEFAPPS_SAVED.format(kind=title, app=name))
            self.refresh()

        self.ctx.workers.submit(da.WORKER, lambda: self.backend.choose(kind, desktop_id), done,
                                key=("choose", kind))


PAGE = DefaultAppsPage
