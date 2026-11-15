"""The "Autostart" page: the person's own login programs, and the config's.

Adding or removing a program is one History entry. The programs hyprland.lua
starts itself are listed below for reference, read-only.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import autostart as ab  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


def installed_apps() -> list[tuple[str, str]]:
    """(name, command) of the programs a launcher would show, by name."""
    out: dict[str, tuple[str, str]] = {}
    for app in Gio.AppInfo.get_all():
        if not app.should_show():
            continue
        command = ab.command_from_exec(app.get_commandline() or "")
        name = app.get_display_name() or app.get_name() or ""
        if name and ab.clean_command(command) and name.lower() not in out:
            out[name.lower()] = (name, command)
    return [out[k] for k in sorted(out)]


class AutostartPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(ab.BACKEND)
        if backend is None:
            backend = ab.Backend(self.ctx.workers)
            ab.register(self.ctx.history, backend)
            self.ctx.backends[ab.BACKEND] = backend
        self.backend = backend
        self.state: dict[str, Any] = {"items": []}
        self._apps: list[tuple[str, str]] = []
        self._saving = False

        self.banner = self.add_group(Group())
        self.banner.add(Row(strings.AUTO_NOT_LOADED))
        self.banner.set_visible(False)

        self.own_group = self.add_group(Group(strings.AUTO_OWN_GROUP, strings.AUTO_OWN_NOTE))
        self.rows["own"] = self.own_group.add(Row(strings.AUTO_EMPTY, row_id="own"))

        add = self.add_group(Group(strings.AUTO_ADD_GROUP))
        self.app_model = Gtk.StringList()
        self.app_dropdown = Gtk.DropDown(model=self.app_model, enable_search=True)
        self.app_dropdown.set_expression(Gtk.PropertyExpression.new(
            Gtk.StringObject, None, "string"))
        self.app_dropdown.set_valign(Gtk.Align.CENTER)
        add_app = Gtk.Button(label=strings.AUTO_ADD)
        add_app.connect("clicked", lambda *_: self._add_app())
        box = Gtk.Box(spacing=8)
        box.append(self.app_dropdown)
        box.append(add_app)
        self.rows["add.app"] = add.add(Row(strings.AUTO_ADD_APP, strings.AUTO_ADD_APP_HINT,
                                           suffix=box, row_id="add.app"))
        self.entry = Gtk.Entry(placeholder_text=strings.AUTO_COMMAND_PLACEHOLDER)
        self.entry.set_width_chars(26)
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.connect("activate", lambda *_: self._add_command())
        add_cmd = Gtk.Button(label=strings.AUTO_ADD)
        add_cmd.connect("clicked", lambda *_: self._add_command())
        box = Gtk.Box(spacing=8)
        box.append(self.entry)
        box.append(add_cmd)
        self.rows["add.command"] = add.add(Row(strings.AUTO_ADD_COMMAND,
                                               strings.AUTO_ADD_COMMAND_HINT,
                                               suffix=box, row_id="add.command"))

        self.system_group = self.add_group(Group(strings.AUTO_SYSTEM_GROUP,
                                                 strings.AUTO_SYSTEM_NOTE))
        self.rows["system"] = self.system_group.add(Row("…", row_id="system"))

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        if not self._apps:
            self._apps = installed_apps()
            self.app_model.splice(0, self.app_model.get_n_items(),
                                  [name for name, _cmd in self._apps])
        self.ctx.workers.submit(ab.WORKER, self.backend.probe, self._show, key="probe")

    def _show(self, info: ab.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.AUTO_FAILED.format(error=error))
            return
        self.banner.set_visible(not info.loaded)
        if not self._saving:
            self.state = info.state
            self._show_own()
        self.system_group.clear()
        if info.system is None:
            self.rows["system"] = self.system_group.add(Row(strings.AUTO_SYSTEM_UNREAD,
                                                            row_id="system"))
        elif not info.system:
            self.rows["system"] = self.system_group.add(Row(strings.AUTO_SYSTEM_NONE,
                                                            row_id="system"))
        for index, start in enumerate(info.system or []):
            title = start.name or start.command
            row = Row(title, start.command if start.name else None)
            row.subtitle_label.set_selectable(True)
            self.system_group.add(row)
            if index == 0:
                self.rows["system"] = row

    def _show_own(self) -> None:
        self.own_group.clear()
        items = self.state["items"]
        if not items:
            self.rows["own"] = self.own_group.add(Row(strings.AUTO_EMPTY, row_id="own"))
        for index, item in enumerate(items):
            button = Gtk.Button(label=strings.AUTO_REMOVE)
            button.connect("clicked", lambda *_a, c=item["command"]: self._remove(c))
            row = Row(item["name"] or item["command"],
                      item["command"] if item["name"] else None, suffix=button)
            self.own_group.add(row)
            if index == 0:
                self.rows["own"] = row

    # ---- changes --------------------------------------------------------

    def _add(self, name: str, command: str) -> bool:
        clean = ab.clean_command(command)
        if clean is None:
            self.ctx.status(strings.AUTO_BAD)
            return False
        items = self.state["items"]
        if any(i["command"] == clean for i in items):
            self.ctx.status(strings.AUTO_DUPLICATE)
            return False
        if len(items) >= ab.MAX_ITEMS:
            self.ctx.status(strings.AUTO_FULL.format(count=ab.MAX_ITEMS))
            return False
        self._save({"items": [*items, {"name": name, "command": clean}]})
        return True

    def _add_app(self) -> None:
        index = self.app_dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self._apps):
            return
        self._add(*self._apps[index])

    def _add_command(self) -> None:
        if self._add("", self.entry.get_text()):
            self.entry.set_text("")

    def _remove(self, command: str) -> None:
        self._save({"items": [i for i in self.state["items"] if i["command"] != command]})

    def _save(self, after: dict[str, Any]) -> None:
        before = self.state
        after = ab.normalize(after)
        self.state = after
        self._saving = True
        self._show_own()

        def done(_result, error: BaseException | None) -> None:
            self._saving = False
            if error is not None:
                self.state = before
                self._show_own()
                self.ctx.status(strings.AUTO_FAILED.format(error=error))
                return
            self.ctx.history.record([(ab.BACKEND, ab.KEY, strings.AUTO_LABEL, before, after)])
            self.ctx.status(strings.AUTO_SAVED)
            self.refresh()

        self.ctx.workers.submit(ab.WORKER, lambda: self.backend.save(after), done,
                                key=("save", id(after)))


PAGE = AutostartPage
