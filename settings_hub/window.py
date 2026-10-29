"""The settings window: sidebar + page stack, keys, show/hide.

The window is created once at startup and only ever hidden, never destroyed.
Keys (handled in the capture phase, before any child sees them):

    Ctrl+F      focus the search field
    Up/Down     move in the sidebar or between rows (Down leaves the search field)
    Enter       open the selected page or search result
    Tab         jump between the sidebar and the page
    Esc         swallowed on press, hides the window on release
    Ctrl+Z      undo the last change (one history group)

While the Binds page captures a key combination, all of these step aside.

Esc hides on *release*: hiding on press would hand the still-held key to the
window underneath (Wayland passes held keys to the new focus owner).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import pages, registry, strings  # noqa: E402
from .history import History  # noqa: E402
from .widgets import keycapture  # noqa: E402
from .widgets.sidebar import Sidebar  # noqa: E402
from .workers import Workers  # noqa: E402

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 920, 640
PREBUILD_AFTER_S = 20
STATUS_MS = 5000
CLASS_MATCH = r"class:^(settings-hub|io\.github\.whyslab\.SettingsHub)$"


class Window(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, history: History, workers: Workers,
                 state_dir: Path, backends: dict | None = None) -> None:
        super().__init__(application=app, title=strings.APP_TITLE)
        self.set_default_size(WIDTH, HEIGHT)
        self.set_hide_on_close(True)
        self.set_decorated(False)
        self.history = history
        self.state_dir = state_dir
        self.ctx = pages.Context(history, workers, self.show_status, self.undo_last,
                                 dict(backends or {}))
        self._pages: dict[str, pages.Page] = {}
        self.current: str | None = None
        self._esc_armed = False
        self._status_source = 0

        self.sidebar = Sidebar()
        self.sidebar.connect("open", self._on_sidebar_open)

        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("sh-title")
        self.stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.status = Gtk.Label(xalign=0, visible=False)
        self.status.add_css_class("sh-status")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        content.add_css_class("sh-content")
        content.append(self.title)
        content.append(self.stack)
        content.append(self.status)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(self.sidebar)
        body.append(content)
        handle = Gtk.WindowHandle()  # drag the window by any empty area
        handle.set_child(body)
        self.set_child(handle)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        keys.connect("key-released", self._on_key_released)
        self.add_controller(keys)
        self.connect("map", self._on_map)

        GLib.timeout_add_seconds(PREBUILD_AFTER_S, self._start_prebuild)

    # ---- pages ----------------------------------------------------------

    def _page(self, page_id: str) -> pages.Page:
        page = self._pages.get(page_id)
        if page is None:
            page = pages.create(page_id, self.ctx)
            self._pages[page_id] = page
            self.stack.add_named(page.widget, page_id)
        return page

    def show_page(self, page_id: str = "", row_id: str = "") -> None:
        started = time.perf_counter()
        if not page_id:
            page_id = self.current or registry.DEFAULT_PAGE
        if registry.get(page_id) is None:
            log.warning("unknown page %r, showing %s", page_id, registry.DEFAULT_PAGE)
            page_id, row_id = registry.DEFAULT_PAGE, ""
        page = self._page(page_id)
        changed = page_id != self.current
        self.current = page_id
        self.stack.set_visible_child_name(page_id)
        self.title.set_label(registry.title(page_id))
        self.sidebar.select_page(page_id)
        if changed and self.get_mapped():
            page.refresh()
        if row_id:
            GLib.idle_add(lambda: page.reveal(row_id) and False)
        if changed:
            log.info("page %s in %.1f ms", page_id, (time.perf_counter() - started) * 1000)

    def _on_sidebar_open(self, _sidebar, page_id: str, row_id: str) -> None:
        self.show_page(page_id, row_id)

    def _start_prebuild(self) -> bool:
        failed: set[str] = set()

        def step() -> bool:
            for info in registry.PAGES:
                if info.id in self._pages or info.id in failed:
                    continue
                try:
                    self._page(info.id)
                except Exception:
                    log.exception("prebuilding %s", info.id)
                    failed.add(info.id)  # opening it later shows the error again
                return True  # one page per idle slot
            return False

        GLib.idle_add(step, priority=GLib.PRIORITY_LOW)
        return False

    # ---- showing --------------------------------------------------------

    def open_page(self, page_id: str = "") -> None:
        """The `open` action: show the window on a page (empty = keep the page).

        "page#row" also scrolls to that row and tints it, like a search result.
        """
        page_id, _, row_id = page_id.partition("#")
        self.show_page(page_id, row_id)
        was_visible = self.get_visible()
        self.present()
        if was_visible and not self.is_active() and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            # With misc:focus_on_activate = 0, present() does not take focus
            # from another window; ask Hyprland directly.
            try:
                Gio.Subprocess.new(
                    ["hyprctl", "dispatch", "focuswindow", CLASS_MATCH],
                    Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
                )
            except GLib.Error as exc:
                log.warning("focuswindow: %s", exc.message)

    def _on_map(self, _win) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with (self.state_dir / "open.log").open("a", encoding="utf-8") as fh:
                fh.write(f"map {time.time_ns()} {self.current or ''}\n")
        except OSError as exc:
            log.warning("open.log: %s", exc)
        focus = self.get_focus()
        if focus is None or (self._in_search_field(focus) and not self.sidebar.entry.get_text()):
            self.sidebar.focus_list()  # like macOS: the search field is not focused on open
        page = self._pages.get(self.current or "")
        if page is not None:
            page.refresh()

    # ---- status and undo ------------------------------------------------

    def show_status(self, text: str) -> None:
        self.status.set_label(text)
        self.status.set_visible(True)
        if self._status_source:
            GLib.source_remove(self._status_source)

        def clear() -> bool:
            self.status.set_visible(False)
            self._status_source = 0
            return False

        self._status_source = GLib.timeout_add(STATUS_MS, clear)

    def undo_last(self) -> None:
        try:
            plan = self.history.plan_undo_last(strings.HISTORY_UNDO_PREFIX)
        except Exception as exc:
            log.exception("planning undo")
            self.show_status(strings.HISTORY_APPLY_FAILED.format(error=exc))
            return
        if plan is None:
            self.show_status(strings.HISTORY_NOTHING_TO_UNDO)
            return
        if plan.missing:
            names = ", ".join(strings.BACKENDS.get(b, b) for b in plan.missing)
            self.show_status(strings.HISTORY_NO_APPLIER.format(backends=names))
            return
        if not plan.flagged:
            self._execute(plan, ())
            return
        listed = [f"• {g.label}" for g in plan.flagged[:5]]
        if len(plan.flagged) > 5:
            listed.append(strings.HISTORY_MORE.format(n=len(plan.flagged) - 5))
        dialog = Gtk.AlertDialog(
            message=strings.HISTORY_CONFLICT_TITLE,
            detail=strings.HISTORY_CONFLICT_BODY.format(groups="\n".join(listed)),
            buttons=[strings.HISTORY_CONFLICT_REVERT_ALL, strings.HISTORY_CONFLICT_SKIP,
                     strings.HISTORY_CONFLICT_CANCEL],
            cancel_button=2, default_button=0, modal=True,
        )

        def answered(dlg, result) -> None:
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                return
            if choice == 0:
                self._execute(plan, ())
            elif choice == 1:
                self._execute(plan, [g.id for g in plan.flagged])

        dialog.choose(self, None, answered)

    def _execute(self, plan, skip) -> None:
        result = self.history.execute(plan, skip)
        if result.errors:
            detail = "; ".join(f"{strings.BACKENDS.get(b, b)}: {m}"
                               for b, m in result.errors.items())
            self.show_status(strings.HISTORY_APPLY_FAILED.format(error=detail))
        elif result.applied:
            label = ", ".join(g.label for g in plan.groups if g.id not in result.skipped)
            self.show_status(strings.HISTORY_UNDONE.format(label=label))
        page = self._pages.get(self.current or "")
        if page is not None:
            page.refresh()

    # ---- keys -----------------------------------------------------------

    def _on_key_pressed(self, _ctl, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        if keycapture.is_capturing(self):
            self._esc_armed = False
            return False  # a key capture (Binds page) takes every key, Esc included
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        focus = self.get_focus()
        if keyval == Gdk.KEY_Escape:
            if self.sidebar.contains_focus(focus) and self.sidebar.clear_search():
                self._esc_armed = False
                return True
            self._esc_armed = True
            return True  # swallowed; the window hides on release
        if ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.sidebar.focus_search()
            return True
        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            self.undo_last()
            return True
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_KP_Tab):
            if self.sidebar.contains_focus(focus):
                page = self._pages.get(self.current or "")
                if page is not None:
                    page.focus_first()
            else:
                self.sidebar.focus_list()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down) and self._in_search_field(focus):
            self.sidebar.focus_list()
            return True
        return False

    def _on_key_released(self, _ctl, keyval: int, _code: int, _state) -> None:
        if keyval == Gdk.KEY_Escape and self._esc_armed:
            self._esc_armed = False
            self.set_visible(False)

    def _in_search_field(self, widget: Gtk.Widget | None) -> bool:
        while widget is not None:
            if widget is self.sidebar.entry:
                return True
            widget = widget.get_parent()
        return False
