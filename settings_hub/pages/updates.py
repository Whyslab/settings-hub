"""The "Updates" page: pending packages, reboot, and a little tidying.

Read-only in the window. Upgrading and cleaning the cache open a terminal
window that runs the command and waits for the password there; nothing is
logged to History (pacman has its own log and cannot be undone from here).

The package list needs the network, so it is fetched when the page is first
shown and then at most every RECHECK_S, or by the Check button; the local
facts (reboot, cache, orphans, .pacnew) are read on every show.
"""

from __future__ import annotations

import subprocess
import time
from datetime import date

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import updates as upd  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

RECHECK_S = 15 * 60
LIST_MAX = 30  # package rows shown; the rest is one "and N more" row
NAMES_MAX = 6  # names in an orphans or .pacnew summary


def _names(items: list[str]) -> str:
    shown = [i.rsplit("/", 1)[-1] if "/" in i else i for i in items[:NAMES_MAX]]
    more = len(items) - len(shown)
    return ", ".join(shown) + (f" …+{more}" if more > 0 else "")


def last_text(day: date | None, today: date | None = None) -> str:
    if day is None:
        return "—"
    today = today or date.today()
    shown = day.strftime("%d.%m.%Y")
    days = (today - day).days
    if days <= 0:
        return strings.UPD_LAST_TODAY.format(date=shown)
    if days == 1:
        return strings.UPD_LAST_YESTERDAY.format(date=shown)
    return strings.UPD_LAST_DAYS.format(date=shown, days=days)


class UpdatesPage(Page):
    def build(self) -> None:
        self._checked_at: float | None = None  # None: never checked, check on show
        self._checking = False
        self._packages: list[upd.Package] | None = None

        state = self.add_group(Group(strings.UPD_STATE_GROUP))
        self.pending_row = state.add(Row(strings.UPD_PENDING, strings.UPD_CHECKING,
                                         row_id="pending"))
        self.rows["pending"] = self.pending_row
        self.upgrade_button = Gtk.Button(label=strings.UPD_UPGRADE_BUTTON)
        self.upgrade_button.add_css_class("suggested-action")
        self.upgrade_button.connect("clicked", lambda *_: self._terminal(upd.upgrade_command(),
                                                                       strings.UPD_TERMINAL_TITLE))
        self.rows["upgrade"] = state.add(Row(
            strings.UPD_UPGRADE,
            strings.UPD_UPGRADE_HINT.format(command=upd.upgrade_command()),
            suffix=self.upgrade_button, row_id="upgrade"))
        self.check_button = Gtk.Button(label=strings.UPD_CHECK_BUTTON)
        self.check_button.connect("clicked", lambda *_: self._check(force=True))
        self.rows["check"] = state.add(Row(strings.UPD_CHECK, strings.UPD_CHECK_HINT,
                                           suffix=self.check_button, row_id="check"))
        self.reboot_row = state.add(Row(strings.UPD_REBOOT, "—", row_id="reboot"))
        self.rows["reboot"] = self.reboot_row
        self.last_row = state.add(Row(strings.UPD_LAST, "—", row_id="last"))
        self.rows["last"] = self.last_row

        self.list_group = self.add_group(Group(strings.UPD_LIST_GROUP))
        self.list_group.set_visible(False)

        clean = self.add_group(Group(strings.UPD_CLEAN_GROUP))
        self.cache_label = Gtk.Label(label="—")
        self.cache_label.add_css_class("sh-dim")
        cache_button = Gtk.Button(label=strings.UPD_CACHE_BUTTON)
        cache_button.connect("clicked", lambda *_: self._terminal(upd.cache_command(),
                                                                  strings.UPD_CACHE_TITLE))
        box = Gtk.Box(spacing=12)
        box.append(self.cache_label)
        box.append(cache_button)
        self.rows["cache"] = clean.add(Row(strings.UPD_CACHE, strings.UPD_CACHE_HINT,
                                           suffix=box, row_id="cache"))
        self.orphans_row = clean.add(Row(strings.UPD_ORPHANS, strings.UPD_ORPHANS_HINT,
                                         row_id="orphans"))
        self.rows["orphans"] = self.orphans_row
        self.pacnew_row = clean.add(Row(strings.UPD_PACNEW, strings.UPD_PACNEW_HINT,
                                        row_id="pacnew"))
        self.rows["pacnew"] = self.pacnew_row

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        stale = (self._checked_at is None
                 or time.monotonic() - self._checked_at > RECHECK_S)
        self._check(force=stale)

    # ---- reading --------------------------------------------------------

    def _check(self, force: bool) -> None:
        if force and self._checking:
            return
        if force:
            self._checking = True
            self.check_button.set_sensitive(False)
            self.pending_row.subtitle_label.set_label(strings.UPD_CHECKING)
            self.pending_row.subtitle_label.set_visible(True)
        self.ctx.workers.submit(upd.WORKER, lambda: upd.probe(check=force),
                                lambda info, error: self._show(info, error, force),
                                key="check" if force else "local")

    def _show(self, info: upd.Info | None, error: BaseException | None, checked: bool) -> None:
        if checked:
            self._checking = False
            self.check_button.set_sensitive(True)
        if error is not None or info is None:
            if checked:
                self.pending_row.subtitle_label.set_label(strings.UPD_FAILED.format(error=error))
            else:
                self.ctx.status(strings.UPD_FAILED.format(error=error))
            return
        if checked:
            self._checked_at = time.monotonic()
            if info.checked:
                self._packages = info.packages
                self._show_packages(info.packages)
            else:
                self._packages = None
                self.list_group.set_visible(False)
                self.pending_row.subtitle_label.set_label(
                    strings.UPD_FAILED.format(error=info.error) if info.error
                    else strings.UPD_NO_TOOL)
        self._show_local(info)

    def _show_packages(self, packages: list[upd.Package]) -> None:
        sub = self.pending_row.subtitle_label
        if not packages:
            sub.set_label(strings.UPD_NONE)
            self.pending_row.title_label.remove_css_class("sh-warning")
        else:
            text = strings.UPD_N.format(count=len(packages))
            aur = sum(p.aur for p in packages)
            if aur:
                text += " · " + strings.UPD_AUR_N.format(count=aur)
            sub.set_label(text)
            self.pending_row.title_label.add_css_class("sh-warning")
        self.list_group.clear()
        self.list_group.set_visible(bool(packages))
        for package in packages[:LIST_MAX]:
            self.list_group.add(Row(package.name + (" · AUR" if package.aur else ""),
                                    strings.UPD_ITEM.format(old=package.old, new=package.new)))
        if len(packages) > LIST_MAX:
            self.list_group.add(Row(strings.UPD_MORE.format(count=len(packages) - LIST_MAX)))

    def _show_local(self, info: upd.Info) -> None:
        if info.reboot_needed:
            self.reboot_row.subtitle_label.set_label(
                strings.UPD_REBOOT_NEEDED.format(running=info.running_kernel))
            self.reboot_row.title_label.add_css_class("sh-warning")
        else:
            self.reboot_row.subtitle_label.set_label(strings.UPD_REBOOT_NO)
            self.reboot_row.title_label.remove_css_class("sh-warning")
        self.last_row.subtitle_label.set_label(last_text(info.last_upgrade))
        if info.cache_bytes is None:
            self.cache_label.set_label("—")
        else:
            self.cache_label.set_label(strings.UPD_CACHE_VALUE.format(
                size=f"{info.cache_bytes / 1024 ** 3:.1f}"))
        self._summary(self.orphans_row, strings.UPD_ORPHANS_HINT, info.orphans)
        self._summary(self.pacnew_row, strings.UPD_PACNEW_HINT, info.pacnew)

    def _summary(self, row: Row, hint: str, items: list[str]) -> None:
        value = (strings.UPD_SOME.format(count=len(items), names=_names(items))
                 if items else strings.UPD_NOTHING)
        row.subtitle_label.set_label(f"{value}\n{hint}")

    # ---- actions --------------------------------------------------------

    def _terminal(self, command: str, title: str) -> None:
        argv = upd.terminal_command(command, title, strings.UPD_TERMINAL_DONE)
        if argv is None:
            self.ctx.status(strings.UPD_TERMINAL_FAILED.format(error="kitty"))
            return
        try:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.ctx.status(strings.UPD_TERMINAL_FAILED.format(error=exc))
            return
        self.ctx.status(strings.UPD_TERMINAL_OPENED)
        self._checked_at = None  # the next show checks again: the list has changed


PAGE = UpdatesPage
