"""The "Backups" page: how the copies are doing, and a copy right now.

Everything is read without root (backends.backups). The two buttons start the
backup units through systemd, which asks for the password; while a copy runs
the page looks again every few seconds, only while it is on screen.
"""

from __future__ import annotations

import time
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import backups as bk  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

POLL_S = 5  # while a copy runs
EXPECT_S = 20  # after a start: the unit may show as running a moment later


def when(value: datetime | None, now: datetime) -> str:
    if value is None:
        return strings.BK_NEVER
    return strings.BK_WHEN.format(date=value.strftime(strings.BK_DATE), ago=ago(value, now))


def ago(value: datetime, now: datetime) -> str:
    seconds = max(0, int((now - value).total_seconds()))
    if seconds < 3600:
        return strings.BK_AGO_MIN.format(n=seconds // 60)
    if seconds < 86400:
        return strings.BK_AGO_HOURS.format(n=seconds // 3600)
    return strings.BK_AGO_DAYS.format(n=seconds // 86400)


def date_only(value: datetime | None) -> str:
    return value.strftime(strings.BK_DATE) if value is not None else "—"


class BackupsPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(bk.BACKEND)
        if backend is None:
            backend = bk.Backend(self.ctx.workers)
            self.ctx.backends[bk.BACKEND] = backend
        self.backend = backend
        self._poll = 0
        self._starting = False
        self._expect_until = 0.0  # monotonic time until which a just-started copy is awaited
        self._expect_kind = ""
        self._clicked_at = datetime.max  # wall time of the last start, to the second
        self._archives: tuple | None = None  # what the list shows, to rebuild only on change
        titles = {k: v[0] for k, v in strings.PAGES["backups"]["rows"].items()}

        state = self.add_group(Group(strings.BK_STATE_GROUP))
        self.rows["state"] = state.add(Row("…", row_id="state"))
        for key in ("last", "size", "count", "next", "checked", "drilled"):
            value = Gtk.Label(xalign=1, selectable=True, wrap=True, max_width_chars=34,
                              valign=Gtk.Align.CENTER)
            value.add_css_class("sh-dim")
            row = state.add(Row(titles[key], suffix=value, row_id=key))
            row.value_label = value
            self.rows[key] = row

        self.actions = self.add_group(Group(strings.BK_ACTIONS_GROUP, strings.BK_ACTIONS_NOTE))
        self.buttons: dict[str, Gtk.Button] = {}
        for kind, row_id, label, hint in (("backup", "now", strings.BK_NOW, strings.BK_NOW_HINT),
                                          ("full", "full", strings.BK_FULL, strings.BK_FULL_HINT)):
            button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            button.update_property([Gtk.AccessibleProperty.LABEL],
                                   [strings.BK_NOW_A11Y if kind == "backup"
                                    else strings.BK_FULL_A11Y])
            if kind == "backup":
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda *_a, k=kind: self._start(k))
            self.buttons[kind] = button
            self.rows[row_id] = self.actions.add(Row(titles[row_id], hint, suffix=button,
                                                     row_id=row_id))

        self.list_group = self.add_group(Group(strings.BK_LIST_GROUP, strings.BK_LIST_NOTE))
        self.rows["archives"] = self.list_group.add(Row(strings.BK_EMPTY, row_id="archives"))

        self.widget.connect("unmap", lambda *_: self._left())

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(bk.WORKER, self.backend.probe, self._show, key="probe")

    def _show(self, info: bk.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self._stop_poll()
            self.ctx.status(strings.BK_READ_FAILED.format(error=error))
            return
        state = self.rows["state"]
        details = ("last", "size", "count", "next", "checked", "drilled")
        if not info.configured:
            state.title_label.set_label(strings.BK_NOT_SET)
            self._subtitle(state, strings.BK_NOT_SET_HINT)
            for key in details:
                self.rows[key].set_visible(False)
            self.actions.set_visible(False)
            self.list_group.set_visible(False)
            return
        for key in details:
            self.rows[key].set_visible(True)
        self.actions.set_visible(True)
        self.list_group.set_visible(True)

        skipped_now = info.skipped_at.get(self._expect_kind)
        if info.running or (skipped_now is not None and skipped_now >= self._clicked_at):
            self._expect_until = 0.0  # it showed up, or systemd skipped it just now
        expecting = self._expect_kind if time.monotonic() < self._expect_until else ""
        waiting = bool(info.running) or bool(expecting)
        title, hint, level = self.verdict(info, expecting)
        state.title_label.set_label(title)
        self._subtitle(state, hint)
        if level:
            state.title_label.add_css_class(level)
        else:
            state.title_label.remove_css_class("sh-warning")

        now = self.backend.now()
        values = {
            "last": when(info.last, now),
            "size": strings.BK_SIZE.format(size=info.size, added=info.added)
            if info.size else "—",
            "count": strings.BK_COUNT.format(count=info.count, repo=info.repo or "—"),
            "next": self.next_text(info),
            "checked": when(info.checked, now),
            "drilled": when(info.drilled, now),
        }
        for key, text in values.items():
            self.rows[key].value_label.set_label(text)

        busy = waiting or self._starting
        for button in self.buttons.values():
            button.set_sensitive(not busy and info.units)

        shown = tuple(when(a.start, now) for a in info.archives)  # the texts, "N min ago" too
        shown = (info.archives, shown)
        if shown != self._archives:
            self._archives = shown
            self._fill_list(info.archives, now)

        if waiting:
            self._start_poll()
        else:
            self._stop_poll()

    @staticmethod
    def verdict(info: bk.Info, expecting: str) -> tuple[str, str, str]:
        """The state row: title, hint and a CSS class ("" for fine)."""
        if not info.units:
            return strings.BK_UNKNOWN, strings.BK_NO_UNITS, "sh-warning"
        # a new run of the same kind clears its old failure; another kind's stays first
        starting = (*info.running, expecting) if expecting else info.running
        failed = [k for k in info.failed if k not in starting]
        if failed:
            return (strings.BK_FAILED.format(kinds=", ".join(strings.BK_KIND[k] for k in failed)),
                    strings.BK_FAILED_HINT.format(
                        units=" -u ".join(bk.UNITS[k] for k in failed)), "sh-warning")
        if info.running:
            return strings.BK_RUNNING[info.running[0]], strings.BK_RUNNING_HINT, ""
        if expecting:
            return strings.BK_RUNNING[expecting], strings.BK_RUNNING_HINT, ""
        skipped = [k for k in info.skipped if k in bk.STARTABLE]
        if skipped:
            dates = [info.skipped_at[k] for k in skipped if k in info.skipped_at]
            hint = strings.BK_SKIPPED_HINT.format(date=date_only(max(dates))) if dates else \
                strings.BK_SKIPPED_HINT.format(date="—")
            return (strings.BK_SKIPPED.format(kinds=", ".join(strings.BK_KIND[k]
                                                              for k in skipped)),
                    hint, "sh-warning")
        if info.status == "unreadable":
            return strings.BK_UNREADABLE, strings.BK_UNREADABLE_HINT, "sh-warning"
        if info.schedule_off:
            return strings.BK_SCHEDULE_OFF, strings.BK_SCHEDULE_OFF_HINT, "sh-warning"
        if info.status == "missing":
            return strings.BK_FIRST, strings.BK_FIRST_HINT, ""
        if info.stale:
            return strings.BK_STALE, strings.BK_STALE_HINT, "sh-warning"
        if info.check_old:
            return strings.BK_CHECK_OLD, strings.BK_CHECK_OLD_HINT, "sh-warning"
        return strings.BK_OK, strings.BK_OK_HINT, ""

    @staticmethod
    def next_text(info: bk.Info) -> str:
        if info.next_backup and info.next_full:
            return strings.BK_NEXT.format(backup=date_only(info.next_backup),
                                          full=date_only(info.next_full))
        if info.next_full:
            return strings.BK_NEXT_FULL.format(full=date_only(info.next_full))
        return date_only(info.next_backup)

    def _fill_list(self, archives: tuple[bk.Archive, ...], now: datetime) -> None:
        self.list_group.clear()
        if not archives:
            self.rows["archives"] = self.list_group.add(Row(strings.BK_EMPTY, row_id="archives"))
        for index, archive in enumerate(archives):
            row = Row(strings.BK_ARCHIVE_FULL if archive.full else strings.BK_ARCHIVE_NIGHTLY,
                      when(archive.start, now) if archive.start else archive.name)
            row.set_tooltip_text(archive.name)
            self.list_group.add(row)
            if index == 0:
                self.rows["archives"] = row

    @staticmethod
    def _subtitle(row: Row, text: str) -> None:
        row.subtitle_label.set_label(text)
        row.subtitle_label.set_visible(bool(text))

    # ---- polling while a copy runs -------------------------------------

    def _start_poll(self) -> None:
        if not self._poll and self.widget.get_mapped():
            self._poll = GLib.timeout_add_seconds(POLL_S, self._tick)

    def _left(self) -> None:
        self._stop_poll()
        self._expect_until = 0.0  # back on the page: what systemd says, nothing awaited

    def _stop_poll(self) -> None:
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = 0

    def _tick(self) -> bool:
        if not self.widget.get_mapped():
            self._poll = 0
            return False
        self.refresh()
        return True

    # ---- actions --------------------------------------------------------

    def _start(self, kind: str) -> None:
        if self._starting:
            return
        self._starting = True
        self._clicked_at = self.backend.now().replace(microsecond=0)
        for button in self.buttons.values():
            button.set_sensitive(False)

        def done(_result, error: BaseException | None) -> None:
            self._starting = False
            if isinstance(error, bk.NoAgent):
                self.ctx.status(strings.BK_NO_AGENT)
            elif isinstance(error, PermissionError):
                self.ctx.status(strings.BK_DENIED)
            elif isinstance(error, TimeoutError):
                self.ctx.status(strings.BK_TIMEOUT)
            elif isinstance(error, FileNotFoundError):
                self.ctx.status(strings.BK_NO_SYSTEMCTL)
            elif error is not None:
                self.ctx.status(strings.BK_START_FAILED.format(error=error))
            else:
                self._expect_until = time.monotonic() + EXPECT_S
                self._expect_kind = kind
                self.ctx.status(strings.BK_STARTED)
            self.refresh()

        # its own worker: the password dialog may stay open while the page reads
        self.ctx.workers.submit("backups-start", lambda: self.backend.start(kind), done,
                                key="start")


PAGE = BackupsPage
