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

import json
import logging
import os
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import hypr, pages, registry, strings  # noqa: E402
from .history import History  # noqa: E402
from .settings import Settings  # noqa: E402
from .widgets import keycapture  # noqa: E402
from .widgets.sidebar import Sidebar  # noqa: E402
from .workers import Workers  # noqa: E402

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 920, 640
PREBUILD_AFTER_S = 20
STATUS_MS = 5000
TRANSITIONS = {
    "none": Gtk.StackTransitionType.NONE,
    "fade": Gtk.StackTransitionType.CROSSFADE,
    "slide": Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
}
CLASS_MATCH = r"class:^(settings-hub|io\.github\.whyslab\.SettingsHub)$"
FOCUS_COMMAND = hypr.dual_dispatch(
    f"hl.dsp.focus({{ window = {hypr.lua_str(CLASS_MATCH)} }})", "focuswindow", CLASS_MATCH)
CENTER_COMMAND = hypr.dual_dispatch(
    f"hl.dsp.window.center({{ window = {hypr.lua_str(CLASS_MATCH)} }})",
    "centerwindow")  # a .conf centers the active window only
# The window rule (float, center) is not enough: on the first open after login
# the window came up tiled or maximized (06.11.2026; the cause is not pinned
# down, the plugin manager was loading plugins at the time). So after every
# open the window puts itself back: floating, not maximized or fullscreen.
# Both are no-ops for a window that is already so.
FLOAT_COMMAND = hypr.dual_dispatch(
    f'hl.dsp.window.float({{ action = "set", window = {hypr.lua_str(CLASS_MATCH)} }})',
    "setfloating", CLASS_MATCH)
# Lua only: a .conf has no per-window "leave fullscreen", and its dispatcher
# would hit whatever window is active; there the dispatch just fails.
UNFULLSCREEN_COMMAND = ["hyprctl", "dispatch",
                        "hl.dsp.window.fullscreen_state({ internal = 0, client = 0, "
                        f"window = {hypr.lua_str(CLASS_MATCH)} }})"]
RESIZE_AFTER_MAP_MS = 60
NETWORK_SETTLE_S = 6


def resize_command(width: int, height: int) -> list[str]:
    """A floating window gets its size from Hyprland, not from GTK's default size."""
    lua = (f"hl.dsp.window.resize({{ x = {int(width)}, y = {int(height)}, relative = false, "
           f"window = {hypr.lua_str(CLASS_MATCH)} }})")
    return hypr.dual_dispatch(lua, "resizewindowpixel",
                              f"exact {int(width)} {int(height)},{CLASS_MATCH}")


class Window(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, history: History, workers: Workers,
                 state_dir: Path, backends: dict | None = None,
                 settings: Settings | None = None) -> None:
        super().__init__(application=app, title=strings.APP_TITLE)
        self.settings = settings if settings is not None else Settings()
        self.set_default_size(*self._initial_size())
        self.set_hide_on_close(True)
        self.set_decorated(False)
        self.history = history
        self.state_dir = state_dir
        self.ctx = pages.Context(history, workers, self.show_status, self.undo_last,
                                 dict(backends or {}), self.settings, self.return_to,
                                 self.undo_group)
        self._pages: dict[str, pages.Page] = {}
        self.current: str | None = None
        self._esc_armed = False
        self._status_source = 0

        self.sidebar = Sidebar(
            width=int(self.settings.get("appearance.sidebar_width")),
            search_limit=int(self.settings.get("behavior.search_limit")),
        )
        self.sidebar.connect("open", self._on_sidebar_open)

        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("sh-title")
        self.stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.stack.set_transition_type(self.transition())
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
        self.connect("unmap", self._on_unmap)

        self._prebuild_source = 0
        self.set_preload(int(self.settings.get("behavior.preload_s")))

    def set_preload(self, seconds: int) -> None:
        """Build the pages lazily, after this many seconds of an idle window."""
        if self._prebuild_source:
            GLib.source_remove(self._prebuild_source)
            self._prebuild_source = 0
        if int(seconds) > 0:
            self._prebuild_source = GLib.timeout_add_seconds(
                int(seconds), self._start_prebuild)

    # ---- settings helpers -----------------------------------------------

    def transition(self) -> Gtk.StackTransitionType:
        return TRANSITIONS.get(str(self.settings.get("appearance.transition")),
                               Gtk.StackTransitionType.NONE)

    def _state_file(self, name: str) -> Path:
        return self.state_dir / name

    def _initial_size(self) -> tuple[int, int]:
        """The remembered size, or the default one from the General page."""
        width = int(self.settings.get("appearance.window_width"))
        height = int(self.settings.get("appearance.window_height"))
        if not self.settings.get("appearance.remember_size"):
            return width, height
        try:
            raw = json.loads(self._state_file("window.json").read_text(encoding="utf-8"))
            return max(600, int(raw["width"])), max(400, int(raw["height"]))
        except (OSError, ValueError, KeyError, TypeError):
            return width, height

    def _on_unmap(self, _win) -> None:
        """Keep the last size and page (both only when the settings ask for it)."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            if self.settings.get("appearance.remember_size"):
                width, height = self.get_width(), self.get_height()
                self._state_file("window.json").write_text(
                    json.dumps({"width": width, "height": height}) + "\n",
                    encoding="utf-8")
            if self.settings.get("behavior.start_page") == "last" and self.current:
                self._state_file("last-page").write_text(self.current + "\n",
                                                         encoding="utf-8")
        except OSError as exc:
            log.warning("state files: %s", exc)

    def last_page(self) -> str:
        """The page to open when the start page is "as last time"."""
        try:
            page_id = self._state_file("last-page").read_text(encoding="utf-8").strip()
        except OSError:
            return registry.DEFAULT_PAGE
        return page_id if registry.get(page_id) is not None else registry.DEFAULT_PAGE

    def start_page(self) -> str:
        chosen = str(self.settings.get("behavior.start_page"))
        if chosen == "last":
            return self.last_page()
        return chosen if registry.get(chosen) is not None else registry.DEFAULT_PAGE

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
            page_id = self.current or self.start_page()
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
        self._prebuild_source = 0
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
        """The `open` action: show the window on a page.

        Empty: the start page, but a window already on screen stays where it is.

        "page#row" also scrolls to that row and tints it, like a search result.
        """
        page_id, _, row_id = page_id.partition("#")
        was_visible = self.get_visible()
        if not page_id:
            page_id = (self.current if was_visible else "") or self.start_page()
        self.show_page(page_id, row_id)
        self.present()
        if was_visible and not self.is_active() and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            # With misc:focus_on_activate = 0, present() does not take focus
            # from another window; ask Hyprland directly.
            try:
                Gio.Subprocess.new(
                    FOCUS_COMMAND,
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
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            GLib.timeout_add(RESIZE_AFTER_MAP_MS, self._apply_size)

    def _apply_size(self) -> bool:
        """Floating, not maximized, the size the General page names, centered.

        Always all four: GTK may not know yet that Hyprland tiled or maximized
        the window, and a window floated back gets a size of Hyprland's choosing.
        """
        width, height = self._initial_size()
        self._run_in_order([FLOAT_COMMAND, UNFULLSCREEN_COMMAND,
                            resize_command(width, height), CENTER_COMMAND])
        return False

    def _run_in_order(self, commands: list[list[str]]) -> None:
        """One after the other: centering before the resize would leave it off center."""
        if not commands:
            return
        try:
            process = Gio.Subprocess.new(
                commands[0],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error as exc:
            log.warning("window size: %s", exc.message)
            return
        process.wait_async(None, lambda *_: self._run_in_order(commands[1:]))

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

        self._status_source = GLib.timeout_add(
            int(self.settings.get("appearance.status_ms")), clear)

    def return_to(self, group_id: str) -> None:
        """The History page's "return to this moment": undo everything after it."""
        try:
            plan = self.history.plan_return_to(group_id, strings.HISTORY_UNDO_PREFIX)
        except Exception as exc:
            log.exception("planning a return")
            self.show_status(strings.HISTORY_APPLY_FAILED.format(error=exc))
            return
        if plan is None:
            self.show_status(strings.HISTORY_NOTHING_LATER)
            return
        self._revert(plan)

    def undo_group(self, group_ids: list[str]) -> None:
        """Undo these groups, such as the ones a mode wrote ("Turn off")."""
        try:
            plan = self.history.plan_undo(group_ids, strings.HISTORY_UNDO_PREFIX)
        except Exception as exc:
            log.exception("planning a group undo")
            self.show_status(strings.HISTORY_APPLY_FAILED.format(error=exc))
            return
        self._revert(plan)

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
        self._revert(plan)

    def _revert(self, plan) -> None:
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
        self._refresh_page()
        if "network" in result.applied:  # undo only starts the connection
            GLib.timeout_add_seconds(NETWORK_SETTLE_S, self._refresh_page)

    def _refresh_page(self) -> bool:
        page = self._pages.get(self.current or "")
        if page is not None:
            page.refresh()
        return False

    # ---- keys -----------------------------------------------------------

    def _on_key_pressed(self, _ctl, keyval: int, code: int, state: Gdk.ModifierType) -> bool:
        if keycapture.is_capturing(self):
            self._esc_armed = False
            return False  # a key capture (Binds page) takes every key, Esc included
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        # Letters by the key's place on the first layout: in the Russian
        # layout Ctrl+F arrives as Ctrl+Cyrillic_a.
        letter = keycapture.hypr_key(keyval, code, self.get_display()) if ctrl else ""
        focus = self.get_focus()
        if keyval == Gdk.KEY_Escape:
            if self.sidebar.contains_focus(focus) and self.sidebar.clear_search():
                self._esc_armed = False
                return True
            self._esc_armed = True
            return True  # swallowed; the window hides on release
        if letter == "F":
            self.sidebar.focus_search()
            return True
        if letter == "Z":
            if focus is not None and isinstance(focus.get_parent(), (Gtk.Entry, Gtk.SearchEntry)):
                return False  # a text field undoes its own typing
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
