"""Capture one key combination from the keyboard.

Hyprland handles its own binds before any window sees the keys, so while a
capture runs:

* primary path: the window asks the compositor to inhibit its shortcuts
  (Gdk.Toplevel.inhibit_system_shortcuts, the keyboard-shortcuts-inhibit
  protocol) and waits up to 300 ms for `shortcuts-inhibited`;
* fallback, when that is not granted: binds/capture.SubmapFallback (an empty
  Hyprland submap, a token file and a watchdog started through Hyprland).

The capture ends on the first non-modifier key (the result), on Esc without
modifiers (cancelled) or when the window loses focus (cancelled); the shortcuts
are restored and the fallback undone in every case.

A key controller on the toplevel, capture phase, receives the keys; tests drive
it in-process by emitting its "key-pressed" signal with a keyval, keycode and
modifier state, which runs exactly the handler a real key press runs.
The window's own key handling steps aside while is_capturing(window) is true.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from ..binds import names  # noqa: E402
from ..binds.capture import SubmapFallback  # noqa: E402
from ..binds.writer import Runner  # noqa: E402

log = logging.getLogger(__name__)

INHIBIT_WAIT_MS = 300
_ACTIVE: weakref.WeakSet = weakref.WeakSet()

MODIFIER_KEYS = frozenset((
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
    Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift, Gdk.KEY_ISO_Level5_Shift, Gdk.KEY_Caps_Lock,
    Gdk.KEY_Num_Lock, Gdk.KEY_ISO_Next_Group, Gdk.KEY_ISO_Prev_Group,
))
# GDK modifier -> Hyprland modmask bit (SHIFT 1, CTRL 4, ALT 8, SUPER 64).
MASKS = (
    (Gdk.ModifierType.SHIFT_MASK, 1),
    (Gdk.ModifierType.CONTROL_MASK, 4),
    (Gdk.ModifierType.ALT_MASK, 8),
    (Gdk.ModifierType.SUPER_MASK, 64),
    (Gdk.ModifierType.META_MASK, 64),
)


def is_capturing(window: Gtk.Widget | None) -> bool:
    return window is not None and window in _ACTIVE


def hypr_mask(state: Gdk.ModifierType) -> int:
    mask = 0
    for gdk_mask, bit in MASKS:
        if state & gdk_mask:
            mask |= bit
    return mask


def hypr_key(keyval: int, keycode: int, display: Gdk.Display | None = None) -> str:
    """Hyprland's name for the key: the first layout's unshifted keysym ("K", "grave")."""
    base = 0
    if display is not None and keycode:
        ok, kv, *_ = display.translate_key(keycode, 0, 0)
        if ok:
            base = kv
    if not base:
        base = Gdk.keyval_to_lower(keyval)
    name = Gdk.keyval_name(base) or ""
    return name.upper() if len(name) == 1 else name


@dataclass(frozen=True)
class Captured:
    mask: int
    key: str

    @property
    def label(self) -> str:
        return names.combo_label(self.mask, self.key)


class KeyCapture:
    def __init__(self, widget: Gtk.Widget, on_done: Callable[[Captured | None], None],
                 hyprctl: Runner, runtime_dir: Path | str | None = None,
                 inhibit: bool = True, wait_ms: int = INHIBIT_WAIT_MS) -> None:
        """inhibit=False skips the inhibitor (a compositor that never grants it)."""
        self.widget = widget
        self.on_done = on_done
        self.fallback = SubmapFallback(hyprctl, runtime_dir)
        self.use_inhibit = inhibit
        self.wait_ms = wait_ms
        self.mode = ""  # "inhibit", "submap" or "plain" once known
        self.done = False
        self.window: Gtk.Window | None = None
        self.controller: Gtk.EventControllerKey | None = None
        self._surface: Gdk.Toplevel | None = None
        self._handlers: list[tuple[object, int]] = []
        self._timer = 0
        self._was_active = False

    def start(self) -> None:
        root = self.widget.get_root()
        if not isinstance(root, Gtk.Window):
            raise RuntimeError("the widget is not in a window")
        self.window = root
        self.controller = Gtk.EventControllerKey()
        self.controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.controller.connect("key-pressed", self._on_key)
        root.add_controller(self.controller)
        _ACTIVE.add(root)
        self._was_active = root.is_active()
        self._handlers.append((root, root.connect("notify::is-active", self._on_active)))
        surface = root.get_surface()
        if self.use_inhibit and isinstance(surface, Gdk.Toplevel):
            self._surface = surface
            self._handlers.append((surface, surface.connect("notify::shortcuts-inhibited",
                                                            self._on_inhibited)))
            surface.inhibit_system_shortcuts(None)
            if surface.get_property("shortcuts-inhibited"):
                self._granted()
                return
            self._timer = GLib.timeout_add(self.wait_ms, self._timeout)
        else:
            self._start_fallback()

    # ---- the two paths ------------------------------------------------------

    def _granted(self) -> None:
        if self.mode == "":
            self.mode = "inhibit"
            log.info("inhibit granted")

    def _on_inhibited(self, surface, _pspec) -> None:
        if not self.done and surface.get_property("shortcuts-inhibited"):
            self._granted()

    def _timeout(self) -> bool:
        self._timer = 0
        if not self.done and self.mode == "":
            log.info("inhibit not granted in %d ms, using the submap", self.wait_ms)
            self._start_fallback()
        return False

    def _start_fallback(self) -> None:
        try:
            entered = self.fallback.start()
        except OSError as exc:
            log.warning("capture fallback: %s", exc)
            entered = False
        if entered:
            self.mode = "submap"
        else:  # keys still reach the window, except combinations Hyprland binds
            self.mode = "plain"
            log.warning("capture without inhibitor or submap: %s is not loaded",
                        "settings-hub-capture")

    # ---- events -------------------------------------------------------------

    def _on_key(self, _controller, keyval: int, keycode: int, state) -> bool:
        return self.handle_key(keyval, keycode, Gdk.ModifierType(state))

    def handle_key(self, keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if self.done:
            return False
        if keyval in MODIFIER_KEYS:
            return True  # wait for the key itself
        mask = hypr_mask(state)
        if keyval == Gdk.KEY_Escape and mask == 0:
            self.finish(None)
            return True
        display = self.window.get_display() if self.window is not None else None
        key = hypr_key(keyval, keycode, display)
        if key:
            self.finish(Captured(mask, key))
        return True

    def _on_active(self, window, _pspec) -> None:
        active = window.is_active()
        if self._was_active and not active:
            self.finish(None)  # focus went elsewhere: stop, give the keys back
        self._was_active = active

    def cancel(self) -> None:
        self.finish(None)

    def finish(self, result: Captured | None) -> None:
        if self.done:
            return
        self.done = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        for obj, handler in self._handlers:
            obj.disconnect(handler)
        self._handlers.clear()
        if self.window is not None:
            if self.controller is not None:
                self.window.remove_controller(self.controller)
            _ACTIVE.discard(self.window)
        if self._surface is not None:
            self._surface.restore_system_shortcuts()
        try:
            self.fallback.stop()
        except OSError as exc:
            log.warning("capture fallback: %s", exc)
        self.on_done(result)
