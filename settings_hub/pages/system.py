"""The "System" page: what this computer is, and what needs attention.

Read-only: the information comes from files, systemctl and pacman; the page
re-reads it every time it is shown and offers one "check again" button.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import sysinfo  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

WORKER = "system-info"


def _gib(kib: int) -> str:
    return f"{kib / 1024 / 1024:.1f}"


def _gib_bytes(value: int) -> str:
    return f"{value / 1024 / 1024 / 1024:.1f}"


def _uptime(seconds: int) -> str:
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return strings.SYS_UPTIME_DMY.format(days=days, hours=hours, minutes=minutes)
    return strings.SYS_UPTIME_HM.format(hours=hours, minutes=minutes)


class SystemPage(Page):
    def build(self) -> None:
        self.values: dict[str, Row] = {}

        about = self.add_group(Group(strings.SYS_ABOUT_GROUP))
        for row_id, title in (
            ("model", strings.SYS_MODEL),
            ("hostname", strings.SYS_HOSTNAME),
            ("os", strings.SYS_OS),
            ("kernel", strings.SYS_KERNEL),
            ("hyprland", strings.SYS_HYPRLAND),
            ("cpu", strings.SYS_CPU),
            ("memory", strings.SYS_MEMORY),
            ("disk", strings.SYS_DISK),
            ("temperature", strings.SYS_TEMPERATURE),
            ("uptime", strings.SYS_UPTIME),
        ):
            row = about.add(Row(title, row_id=row_id))
            self.rows[row_id] = row
            self.values[row_id] = row

        state = self.add_group(Group(strings.SYS_STATE_GROUP))
        self.failed_row = state.add(Row(strings.SYS_FAILED, row_id="failed"))
        self.rows["failed"] = self.failed_row
        self.updates_row = state.add(Row(strings.SYS_UPDATES, row_id="updates"))
        self.rows["updates"] = self.updates_row

        refresh = self.add_group(Group())
        button = Gtk.Button(label=strings.SYS_REFRESH)
        button.connect("clicked", lambda *_: self.refresh())
        refresh.add(Row(strings.SYS_REFRESH, strings.SYS_REFRESH_HINT,
                        suffix=button, row_id="refresh"))

        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(WORKER, sysinfo.probe, self._show)

    def _show(self, info: sysinfo.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.SYS_READ_FAILED.format(error=error))
            return
        self._set("model", info.model or "—", "")
        self._set("hostname", info.hostname or "—", info.session or "")
        self._set("os", info.os_name or "—", "")
        self._set("kernel", info.kernel or "—", "")
        self._set("hyprland", info.hyprland or "—", "")
        if info.cpu:
            self._set("cpu", info.cpu,
                      strings.SYS_CORES.format(cores=info.cores))
        else:
            self._set("cpu", "—", "")
        memory = info.memory
        if memory.get("MemTotal"):
            used = memory["MemTotal"] - memory.get("MemAvailable", 0)
            percent = round(used / memory["MemTotal"] * 100)
            self._set("memory", strings.SYS_MEMORY_VALUE.format(
                used=_gib(used), total=_gib(memory["MemTotal"]), percent=percent),
                strings.SYS_SWAP.format(
                    used=_gib(memory["SwapTotal"] - memory.get("SwapFree", 0)),
                    total=_gib(memory.get("SwapTotal", 0))))
        else:
            self._set("memory", "—", "")
        disk = info.disk
        if disk.get("total"):
            percent = round(disk["used"] / disk["total"] * 100)
            self._set("disk", strings.SYS_DISK_VALUE.format(
                used=_gib_bytes(disk["used"]), total=_gib_bytes(disk["total"]),
                percent=percent),
                strings.SYS_DISK_FREE.format(free=_gib_bytes(disk["free"])))
        else:
            self._set("disk", "—", "")
        if info.temperature_c is not None:
            self._set("temperature", strings.SYS_TEMPERATURE_VALUE.format(
                celsius=info.temperature_c))
        else:
            self._set("temperature", "—", "")
        self._set("uptime", _uptime(info.uptime_s), "")

        if info.failed_units:
            self.failed_row.title_label.set_label(strings.SYS_FAILED_BAD.format(
                count=len(info.failed_units)))
            self.failed_row.subtitle_label.set_label(", ".join(info.failed_units[:4]))
            self.failed_row.subtitle_label.set_visible(True)
            self.failed_row.title_label.add_css_class("sh-warning")
        else:
            self.failed_row.title_label.set_label(strings.SYS_FAILED_OK)
            self.failed_row.subtitle_label.set_visible(False)
            self.failed_row.title_label.remove_css_class("sh-warning")

        if info.updates is None:
            self.updates_row.title_label.set_label(strings.SYS_UPDATES_UNKNOWN)
            self.updates_row.subtitle_label.set_visible(False)
        elif info.updates:
            self.updates_row.title_label.set_label(
                strings.SYS_UPDATES_N.format(count=info.updates))
            self.updates_row.title_label.add_css_class("sh-warning")
            self.updates_row.subtitle_label.set_label(strings.SYS_UPDATES_HINT)
            self.updates_row.subtitle_label.set_visible(True)
        else:
            self.updates_row.title_label.set_label(strings.SYS_UPDATES_OK)
            self.updates_row.title_label.remove_css_class("sh-warning")
            self.updates_row.subtitle_label.set_visible(False)

    def _set(self, row_id: str, value: str, hint: str = "") -> None:
        row = self.values.get(row_id)
        if row is None:
            return
        title = strings.SYS_TITLES[row_id]
        row.title_label.set_label(f"{title} · {hint}" if hint else title)
        row.subtitle_label.set_label(value)
        row.subtitle_label.set_visible(True)


PAGE = SystemPage
