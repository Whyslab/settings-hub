"""The "System" page: what this computer is, what needs attention, and disk space.

The information comes from files, systemctl, pacman and du; the page re-reads
it every time it is shown and offers one "check again" button. The one change
it can make is emptying the Trash, after asking (backends.disk_space).
"""

from __future__ import annotations

import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import disk_space, sysinfo  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

WORKER = "system-info"
MOUNTS_WORKER = "disk-mounts"  # statvfs: quick, but a stuck disk must not hold the rest
TRASH_WORKER = "disk-trash"
COUNT_EVERY_S = 600  # du again on showing the page at most this often


def _gib(kib: int) -> str:
    return f"{kib / 1024 / 1024:.1f}"


def size_text(value: int) -> str:
    """Bytes in the unit people read (strings.SYS_GB, SYS_MB...)."""
    # by the rounded number: 1023.7 MiB is 1.0 GiB, not 1024 MiB
    if round(value / 1024 ** 3, 1) >= 1024:
        return strings.SYS_TB.format(n=value / 1024 ** 4)
    if round(value / 1024 ** 2) >= 1024:
        return strings.SYS_GB.format(n=value / 1024 ** 3)
    if round(value / 1024) >= 1024:
        return strings.SYS_MB.format(n=value / 1024 ** 2)
    return strings.SYS_KB.format(n=value / 1024)


def mount_name(mount: disk_space.Mount) -> str:
    return strings.SYS_MOUNT_NAMES.get(mount.path) or Path(mount.path).name or mount.path


def folder_name(path: Path) -> str:
    return strings.SYS_FOLDER_NAMES.get(path.name, path.name)


def short_path(path: Path, home: Path) -> str:
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


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
            ("temperature", strings.SYS_TEMPERATURE),
            ("uptime", strings.SYS_UPTIME),
        ):
            value = Gtk.Label(label="—", xalign=1, selectable=True,
                              ellipsize=Pango.EllipsizeMode.END, max_width_chars=44)
            value.add_css_class("sh-dim")
            row = about.add(Row(title, suffix=value, row_id=row_id))
            row.value_label = value
            self.rows[row_id] = row
            self.values[row_id] = row

        state = self.add_group(Group(strings.SYS_STATE_GROUP))
        self.failed_row = state.add(Row(strings.SYS_FAILED, row_id="failed"))
        self.rows["failed"] = self.failed_row
        open_updates = Gtk.Button(label=strings.SYS_UPDATES_OPEN)
        open_updates.connect("clicked", lambda *_: self._open("updates"))
        self.updates_row = state.add(Row(strings.SYS_UPDATES, strings.SYS_UPDATES_OK,
                                         suffix=open_updates, row_id="updates"))
        self.rows["updates"] = self.updates_row

        space = self.ctx.backends.get(disk_space.BACKEND)
        if space is None:
            space = disk_space.Backend()
            self.ctx.backends[disk_space.BACKEND] = space
        self.space = space
        self._mounts: tuple[str, ...] | None = None  # the paths the rows show
        self._mount_rows: list[Row] = []  # the first one stays: search leads to it
        self._counting = False
        self._counted_at: float | None = None  # monotonic
        self._trash_gen = 0  # bumped by every fresh look at the trash...
        self._count_gen = 0  # ...and what it was when the running count started
        self._asking = False  # counting the trash for the dialog, or the dialog is open
        self._emptying = False
        self._revealed: tuple[str, float] | None = None  # row id, when (search)
        self.mounts_group = self.add_group(Group(strings.SYS_SPACE_GROUP))
        self._mount_rows.append(self.mounts_group.add(self._mount_row("disk")))
        self.rows["disk"] = self._mount_rows[0]

        free = self.add_group(Group(strings.SYS_FREE_GROUP))
        self.trash_button = Gtk.Button(label=strings.SYS_TRASH_BUTTON, sensitive=False)
        self.trash_button.update_property([Gtk.AccessibleProperty.LABEL],
                                          [strings.SYS_TRASH_A11Y])
        self.trash_button.add_css_class("destructive-action")
        self.trash_button.connect("clicked", lambda *_: self._ask_empty())
        self.trash_row = free.add(Row(strings.SYS_TRASH, strings.SYS_USAGE_COUNTING,
                                      suffix=self.trash_button, row_id="trash"))
        self.rows["trash"] = self.trash_row
        self.cache_row = free.add(self._sized_row(strings.SYS_CACHE, strings.SYS_CACHE_HINT,
                                                  "cache", openable=True))
        self.packages_row = free.add(self._sized_row(strings.SYS_PACKAGES, "", "packages",
                                                     openable=True))
        self.games_row = free.add(self._sized_row(strings.SYS_GAMES, "", "games"))
        for row_id, row in (("cache", self.cache_row), ("packages", self.packages_row),
                            ("games", self.games_row)):
            self.rows[row_id] = row

        self.usage_group = self.add_group(Group(strings.SYS_USAGE_GROUP,
                                                strings.SYS_USAGE_NOTE))
        self.recount = Gtk.Button(label=strings.SYS_USAGE_RECOUNT)
        self.recount.connect("clicked", lambda *_: self._count())
        self.usage_row = Row(strings.SYS_USAGE_TITLE.format(size="…"), suffix=self.recount,
                             row_id="space")
        self.rows["space"] = self.usage_group.add(self.usage_row)
        self._folder_rows: list[Row] = []

        refresh = self.add_group(Group())
        button = Gtk.Button(label=strings.SYS_REFRESH)
        button.connect("clicked", lambda *_: self.refresh())
        refresh.add(Row(strings.SYS_REFRESH, strings.SYS_REFRESH_HINT,
                        suffix=button, row_id="refresh"))

        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(WORKER, sysinfo.probe, self._show)
        self.ctx.workers.submit(MOUNTS_WORKER, disk_space.mounts, self._show_mounts,
                                key="mounts")
        if self._counted_at is None or time.monotonic() - self._counted_at > COUNT_EVERY_S:
            self._count()
        elif not (self._asking or self._emptying):
            self._look_at_trash()  # quick, and it may have changed since

    def _show(self, info: sysinfo.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.ctx.status(strings.SYS_READ_FAILED.format(error=error))
            return
        self._set("model", info.model or "—", "")
        self._set("hostname", info.hostname or "—", "")
        self._set("os", info.os_name or "—", "")
        self._set("kernel", info.kernel or "—", "")
        self._set("hyprland", info.hyprland or info.session or "—", "")
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

        # pacman -Qu only knows the last database sync: the title stays "Updates",
        # the number (if any) is a hint, and the button leads to the fresh check.
        self.updates_row.title_label.set_label(strings.SYS_UPDATES)
        self.updates_row.subtitle_label.set_label(
            strings.SYS_UPDATES_N.format(count=info.updates) if info.updates
            else strings.SYS_UPDATES_OK)
        self.updates_row.subtitle_label.set_visible(True)

    # ---- disk space ----------------------------------------------------

    def _sized_row(self, title: str, hint: str, row_id: str, openable: bool = False) -> Row:
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        value = Gtk.Label(label="…", xalign=1)
        value.add_css_class("sh-value")
        box.append(value)
        row = Row(title, hint or None, suffix=box, row_id=row_id)
        row.value_label = value
        row.hint = hint
        row.open_button = None
        if openable:
            button = Gtk.Button(icon_name="folder-open-symbolic", sensitive=False,
                                tooltip_text=strings.SYS_OPEN)
            button.update_property([Gtk.AccessibleProperty.LABEL],
                                   [strings.SYS_OPEN_A11Y.format(name=title)])
            button.add_css_class("flat")
            button.connect("clicked", lambda *_: row.path and self.open_folder(row.path))
            box.append(button)
            row.open_button = button
        row.path = None
        return row

    def _mount_row(self, row_id: str | None) -> Row:
        bar = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER)
        bar.add_css_class("sh-fill")
        for name in ("low", "high", "full"):  # no colour steps: one class, below
            bar.remove_offset_value(name)
        value = Gtk.Label(xalign=1, width_chars=4)
        value.add_css_class("sh-value")
        box = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
        box.append(bar)
        box.append(value)
        row = Row("…", "", suffix=box, row_id=row_id)
        row.bar, row.value_label = bar, value
        return row

    def reveal(self, row_id: str) -> None:
        self._revealed = (row_id, time.monotonic())
        super().reveal(row_id)

    def _rescroll(self) -> None:
        """Rows came in above a row search just led to: put it back in view."""
        if self._revealed is None or time.monotonic() - self._revealed[1] > 3:
            return
        row = self.rows.get(self._revealed[0])
        if row is not None:
            GLib.idle_add(self._scroll_to, row)

    def _show_mounts(self, mounts, error: BaseException | None) -> None:
        if error is not None or not mounts:
            if self._mounts is None:
                self._mount_rows[0].title_label.set_label(strings.SYS_MOUNT_NONE)
            return
        self._mounts = tuple(m.path for m in mounts)
        changed = len(self._mount_rows) != len(mounts)
        while len(self._mount_rows) < len(mounts):  # updated in place, never rebuilt
            self._mount_rows.append(self.mounts_group.add(self._mount_row(None)))
        while len(self._mount_rows) > len(mounts):
            self.mounts_group.list.remove(self._mount_rows.pop())
        for row, mount in zip(self._mount_rows, mounts, strict=True):
            percent = round(mount.share * 100)
            name = mount_name(mount)
            row.title_label.set_label(name)
            row.set_tooltip_text(f"{mount.path} · {mount.device} · {mount.fstype}")
            row.bar.set_value(mount.share)
            row.value_label.set_label(strings.SYS_MOUNT_VALUE.format(percent=percent))
            row.bar.update_property([Gtk.AccessibleProperty.LABEL],
                                    [strings.SYS_MOUNT_A11Y.format(name=name,
                                                                   percent=percent)])
            hint = strings.SYS_MOUNT_LOW if mount.low else strings.SYS_MOUNT_HINT
            self._subtitle(row, hint.format(free=size_text(mount.free),
                                            total=size_text(mount.total)))
            if mount.low:
                row.bar.add_css_class("sh-full")
                row.subtitle_label.add_css_class("sh-warning")
            else:
                row.bar.remove_css_class("sh-full")
                row.subtitle_label.remove_css_class("sh-warning")
        if changed:
            self._rescroll()

    def _count(self) -> None:
        if self._counting:
            return
        self._counting = True
        self._count_gen = self._trash_gen
        self.recount.set_sensitive(False)
        self.usage_row.subtitle_label.set_label(strings.SYS_USAGE_COUNTING)
        self.usage_row.subtitle_label.set_visible(True)
        self.ctx.workers.submit(disk_space.WORKER, self.space.count, self._show_space,
                                key="count")

    def _show_space(self, space: disk_space.Space | None,
                    error: BaseException | None) -> None:
        self._counting = False
        self.recount.set_sensitive(True)
        if error is not None or space is None:
            self._counted_at = None  # the next showing tries again
            self._subtitle(self.usage_row, strings.SYS_USAGE_FAILED.format(error=error))
            for row in (self.cache_row, self.packages_row, self.games_row):
                self._fill(row, None, None, "")
            self._look_at_trash()
            return
        self._counted_at = time.monotonic()
        self.usage_row.title_label.set_label(strings.SYS_USAGE_TITLE.format(
            size=size_text(space.home_size) if space.complete else "—"))
        self._subtitle(self.usage_row, strings.SYS_USAGE_AT.format(
            time=space.counted_at.strftime("%H:%M")) if space.complete
            else strings.SYS_USAGE_PARTIAL)
        for row in self._folder_rows:
            self.usage_group.list.remove(row)
        self._folder_rows = []
        for folder in space.folders:
            row = self._sized_row(folder_name(folder.path), short_path(folder.path, space.home),
                                  "", openable=True)
            row.row_id = None
            row.value_label.set_label(size_text(folder.size))
            row.path = folder.path
            row.open_button.set_sensitive(True)
            self.usage_group.add(row)
            self._folder_rows.append(row)

        # the trash was looked at again since this count started: that is newer
        if self._count_gen == self._trash_gen and not (self._asking or self._emptying):
            self._show_trash(space.trash)
        self._fill(self.cache_row, space.cache_size if space.cache_dir else None,
                   space.cache_dir, strings.SYS_CACHE_HINT)
        self._fill(self.packages_row, space.pkg_size if space.pkg_dir else None, space.pkg_dir,
                   {True: strings.SYS_PACKAGES_AUTO, False: strings.SYS_PACKAGES_MANUAL,
                    None: strings.SYS_PACKAGES_UNKNOWN}[space.pkg_auto])
        top = ", ".join(strings.SYS_GAMES_ITEM.format(name=g.name, size=size_text(g.size))
                        for g in space.games[:3])
        self._fill(self.games_row, sum(g.size for g in space.games) if space.games else None,
                   None, strings.SYS_GAMES_HINT.format(top=top) if top
                   else strings.SYS_GAMES_NONE)

    def _fill(self, row: Row, size: int | None, path: Path | None, hint: str) -> None:
        """None: not there, or not known (the row stays, so search can lead to it)."""
        row.value_label.set_label(size_text(size) if size is not None else "—")
        row.path = path
        if row.open_button is not None:
            row.open_button.set_sensitive(path is not None)
        self._subtitle(row, hint)

    def _show_trash(self, trash: disk_space.Trash) -> None:
        empty = trash.items == 0
        size = size_text(trash.size) if trash.size is not None else "—"
        self._subtitle(self.trash_row, strings.SYS_TRASH_NONE if empty else
                       strings.SYS_TRASH_HINT.format(size=size, count=trash.items))
        self.trash_button.set_sensitive(not empty and not self._emptying and not self._asking)

    def _look_at_trash(self) -> None:
        def seen(result, error: BaseException | None) -> None:
            self._trash_gen += 1
            if error is None and result is not None:
                self._show_trash(result)
            else:
                self._subtitle(self.trash_row, "—")
                self.trash_button.set_sensitive(not self._emptying and not self._asking)

        self.ctx.workers.submit(TRASH_WORKER, self.space.trash_all, seen, key="look")

    def _ask_empty(self) -> None:
        """Count every trash again, then ask with those numbers: never from old ones."""
        if self._asking or self._emptying:
            return
        self._asking = True
        self.trash_button.set_sensitive(False)
        self._subtitle(self.trash_row, strings.SYS_USAGE_COUNTING)

        def counted(result: disk_space.Trash | None, error: BaseException | None) -> None:
            self._trash_gen += 1
            if error is not None or result is None:
                self._asking = False
                self.trash_button.set_sensitive(True)
                self._subtitle(self.trash_row, "—")
                self.ctx.status(strings.SYS_TRASH_FAILED.format(error=error))
                return
            if not result.items and not result.network:
                self._asking = False
                self._show_trash(result)
                self.ctx.status(strings.SYS_TRASH_NONE_NOW)
                return
            if not self.widget.get_mapped():  # the window was closed meanwhile: no dialog
                self._asking = False
                self._show_trash(result)
                return
            size = size_text(result.size) if result.size is not None else "—"
            detail = strings.SYS_TRASH_ASK_DETAIL.format(count=result.items, size=size)
            if result.other:
                detail += " " + strings.SYS_TRASH_ASK_OTHER.format(count=result.other)
            if result.network:
                detail += " " + strings.SYS_TRASH_ASK_NETWORK.format(
                    disks=", ".join(result.network[:3]))

            def yes() -> None:
                self._asking = False
                self._empty()

            def no() -> None:
                self._asking = False
                self._show_trash(result)

            self.confirm(strings.SYS_TRASH_ASK, detail, strings.SYS_TRASH_OK, yes, no)

        self.ctx.workers.submit(TRASH_WORKER, self.space.trash_all, counted, key="ask")

    def _empty(self) -> None:
        if self._emptying:
            return
        self._emptying = True
        self._trash_gen += 1  # any count from before this is old now
        self.trash_button.set_sensitive(False)

        def emptied(_result, error: BaseException | None) -> None:
            self._emptying = False
            if isinstance(error, TimeoutError):
                self.ctx.status(strings.SYS_TRASH_TIMEOUT)
            elif error is not None:
                self.ctx.status(strings.SYS_TRASH_FAILED.format(error=error))
            else:
                self.ctx.status(strings.SYS_TRASH_DONE)
            self._look_at_trash()
            self.ctx.workers.submit(MOUNTS_WORKER, disk_space.mounts, self._show_mounts,
                                    key="mounts")

        self.ctx.workers.submit(TRASH_WORKER, self.space.empty_trash, emptied, key="empty")

    def open_folder(self, path: Path) -> None:
        """The folder in the file manager (only on a click)."""
        if not path.is_dir():  # gone, or a file now: not opened with some program
            self.ctx.status(strings.SYS_OPEN_FAILED.format(error=path))
            return
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(path)))

        def done(source, result) -> None:
            try:
                source.launch_finish(result)
            except GLib.Error as exc:
                if not exc.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                    self.ctx.status(strings.SYS_OPEN_FAILED.format(error=exc.message))

        launcher.launch(self.widget.get_root(), None, done)

    @staticmethod
    def _subtitle(row: Row, text: str) -> None:
        row.subtitle_label.set_label(text)
        row.subtitle_label.set_visible(bool(text))

    def _open(self, page_id: str) -> None:
        if self.ctx.open_page is not None:
            self.ctx.open_page(page_id)

    def _set(self, row_id: str, value: str, hint: str = "") -> None:
        """The value on the right, as on the Power page; a detail under the title."""
        row = self.values.get(row_id)
        if row is None:
            return
        row.value_label.set_label(value)
        row.value_label.set_tooltip_text(value)
        row.subtitle_label.set_label(hint)
        row.subtitle_label.set_visible(bool(hint))


PAGE = SystemPage
