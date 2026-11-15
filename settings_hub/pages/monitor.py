"""The "Monitor" page: resolution and refresh rate, scale, on/off per output.

A change shows at once and asks "Keep?"; with no answer within CONFIRM_S the
old setting comes back (a wrong mode can leave the screen black, so the person
may not be able to answer). Kept: saved for the next login and logged as one
History entry.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import monitor as mb  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

CONFIRM_S = 15


def mode_label(mode: str) -> str:
    parsed = mb.parse_mode(mode)
    if parsed is None:
        return mode
    w, h, rate = parsed
    return strings.MON_MODE_VALUE.format(width=w, height=h, rate=f"{rate:g}")


class MonitorPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(mb.BACKEND)
        if backend is None:
            backend = mb.Backend(self.ctx.workers)
            mb.register(self.ctx.history, backend)
            self.ctx.backends[mb.BACKEND] = backend
        self.backend = backend
        self.info: mb.Info | None = None
        self._busy = False  # a change is being tried or waits for "Keep?"
        self._quiet = False
        self._shape: list[tuple] = []  # what the groups were built for

        self.banner = self.add_group(Group())
        self.banner_row = self.banner.add(Row(""))
        self.banner.set_visible(False)
        self.groups: list[Group] = []
        self.note = Gtk.Label(label=strings.MON_NOTE, xalign=0, wrap=True)
        self.note.add_css_class("sh-group-note")
        self._box.append(self.note)

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        if not self._busy:
            self.ctx.workers.submit(mb.WORKER, self.backend.probe, self._show, key="probe")

    def _show(self, info: mb.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.MON_READ_FAILED.format(error=error))
            return
        if self._busy:
            return
        self.info = info
        banner = ""
        if not info.monitors:
            banner = strings.MON_NONE
        elif not info.lua:
            banner = strings.MON_NOT_LUA
        elif not info.loaded:
            banner = strings.MON_NOT_LOADED
        self.banner_row.title_label.set_label(banner)
        self.banner.set_visible(bool(banner))
        self._build_groups(info)

    def _build_groups(self, info: mb.Info) -> None:
        for group in self.groups:
            self._box.remove(group)
        self.groups = []
        enabled_count = sum(m.enabled for m in info.monitors)
        self._quiet = True
        try:
            for index, monitor in enumerate(info.monitors):
                group = Group(strings.MON_GROUP.format(
                    name=monitor.name, description=monitor.description or "—"))
                self._box.insert_child_after(group, self.groups[-1] if self.groups
                                             else self.banner)
                self.groups.append(group)
                current = monitor.setting()

                modes = Gtk.DropDown.new_from_strings([mode_label(m) for m in monitor.modes])
                modes.set_selected(monitor.modes.index(current["mode"]))
                modes.connect("notify::selected", lambda dd, m=monitor: self._picked_mode(m, dd))
                row = group.add(Row(strings.MON_MODE, suffix=modes,
                                    row_id=f"mode.{monitor.name}"))
                if index == 0:
                    self.rows["mode"] = row

                scales = mb.scales_for(monitor.width, monitor.height, monitor.scale)
                scale_dd = Gtk.DropDown.new_from_strings(
                    [strings.MON_SCALE_VALUE.format(percent=f"{s * 100:g}") for s in scales])
                closest = min(range(len(scales)), key=lambda i: abs(scales[i] - monitor.scale))
                scale_dd.set_selected(closest)
                scale_dd.connect("notify::selected",
                                 lambda dd, m=monitor, sc=scales: self._picked_scale(m, dd, sc))
                row = group.add(Row(strings.MON_SCALE, strings.MON_SCALE_HINT, suffix=scale_dd,
                                    row_id=f"scale.{monitor.name}"))
                if index == 0:
                    self.rows["scale"] = row

                if len(info.monitors) > 1:
                    switch = Gtk.Switch(active=monitor.enabled, valign=Gtk.Align.CENTER)
                    # the last screen that is on cannot be turned off from itself
                    switch.set_sensitive(info.lua and not (monitor.enabled
                                                           and enabled_count <= 1))
                    switch.connect("notify::active",
                                   lambda sw, _p, m=monitor: self._picked_enabled(m, sw))
                    row = group.add(Row(strings.MON_ENABLED, strings.MON_ENABLED_HINT,
                                        suffix=switch, row_id=f"enabled.{monitor.name}"))
                    if index == 0:
                        self.rows["enabled"] = row
                for widget in (modes, scale_dd):
                    widget.set_sensitive(info.lua and monitor.enabled)
        finally:
            self._quiet = False

    # ---- changes --------------------------------------------------------

    def _picked_mode(self, monitor: mb.Monitor, dd: Gtk.DropDown) -> None:
        index = dd.get_selected()
        if self._quiet or index >= len(monitor.modes):
            return
        self._change(monitor, {**monitor.setting(), "mode": monitor.modes[index]})

    def _picked_scale(self, monitor: mb.Monitor, dd: Gtk.DropDown, scales: list[float]) -> None:
        index = dd.get_selected()
        if self._quiet or index >= len(scales):
            return
        self._change(monitor, {**monitor.setting(), "scale": scales[index]})

    def _picked_enabled(self, monitor: mb.Monitor, switch: Gtk.Switch) -> None:
        if self._quiet:
            return
        self._change(monitor, {**monitor.setting(), "enabled": switch.get_active()})

    def _change(self, monitor: mb.Monitor, after: dict[str, Any]) -> None:
        before = monitor.setting()
        if after == before or self._busy:
            return
        self._busy = True

        def tried(_result, error: BaseException | None) -> None:
            if error is not None:
                self._busy = False
                self.ctx.status(strings.MON_FAILED.format(error=error))
                self.refresh()
                return
            self._ask(monitor.name, before, after)

        self.ctx.workers.submit(mb.WORKER, lambda: self.backend.try_live(monitor.name, after),
                                tried, key="try")

    def _ask(self, name: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        cancel = Gio.Cancellable()
        timer = GLib.timeout_add_seconds(CONFIRM_S, lambda: cancel.cancel() or False)
        dialog = Gtk.AlertDialog(
            message=strings.MON_CONFIRM,
            detail=strings.MON_CONFIRM_DETAIL.format(seconds=CONFIRM_S),
            # Enter means Revert: a person facing a black screen may press it
            buttons=[strings.MON_KEEP, strings.MON_REVERT], cancel_button=1,
            default_button=1, modal=True)

        def answered(dlg, result) -> None:
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                choice = 1  # no answer in time, or the dialog was closed
            if not cancel.is_cancelled():
                GLib.source_remove(timer)
            if choice == 0:
                self._keep(name, before, after)
            else:
                self._revert(name, before)

        dialog.choose(self.widget.get_root(), cancel, answered)

    def _keep(self, name: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        def done(_result, error: BaseException | None) -> None:
            self._busy = False
            if error is not None:
                self.ctx.status(strings.MON_FAILED.format(error=error))
            else:
                self.ctx.history.record([(mb.BACKEND, mb.MONITOR_KEY + name,
                                          strings.MON_LABEL.format(name=name), before, after)])
                self.ctx.status(strings.MON_APPLIED)
            self.refresh()

        self.ctx.workers.submit(mb.WORKER, lambda: self.backend.save(name, after), done,
                                key="keep")

    def _revert(self, name: str, before: dict[str, Any]) -> None:
        def done(_result, error: BaseException | None) -> None:
            self._busy = False
            self.ctx.status(strings.MON_FAILED.format(error=error) if error is not None
                            else strings.MON_REVERTED)
            self.refresh()

        self.ctx.workers.submit(mb.WORKER, lambda: self.backend.restore(name, before), done,
                                key="revert")


PAGE = MonitorPage
