"""The "Window minimize" block of the Animations page. No GTK.

A choice writes ~/.config/minimize/animation.json through the backend (one
History line per change). "Look" plays the chosen animation on this window
itself (`minimize preview`), so the window is not hidden for it.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import minimize_anim as ma


class View(Protocol):
    def show_minimize_setup(self, state: str, detail: str) -> None: ...

    def show_minimize(self, state: dict[str, Any], keys: set[str]) -> None:
        """Show these keys (others have a change queued)."""

    def set_minimize_busy(self, busy: bool) -> None: ...

    def status(self, text: str) -> None: ...


class Controller:
    def __init__(self, backend: ma.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.pending: set[str] = set()
        self.chosen: dict[str, str] = {}   # chosen, maybe not written yet
        self.previewing = False
        backend.on_external.append(lambda _keys: self.refresh())

    @staticmethod
    def label_for(key: str) -> str:
        return strings.MA_LABEL_STYLE if key == "style" else strings.MA_LABEL_SPEED

    def refresh(self) -> None:
        state, detail = self.backend.state()
        self.view.show_minimize_setup(state, detail)
        if state != "ok":
            return
        current = self.backend.read_all()
        self.view.show_minimize(current, set(current) - self.pending)

    def _submit(self, key: str, value: str, message: str) -> None:
        if key not in self.pending and self.backend.read([key])[key] == value:
            return  # the control echoed a value it was given
        self.pending.add(key)
        self.chosen[key] = value

        def done(result, error) -> None:
            self.pending.discard(key)
            if error is not None:
                self.view.status(strings.MA_FAILED.format(error=error))
            else:
                before, after = result
                if before.get(key) != after.get(key):
                    self.history.record([(ma.BACKEND, key, self.label_for(key),
                                          before.get(key), after.get(key))])
                self.view.status(message)
            self.refresh()

        self.backend.queue_write({key: value}, done)

    def choose_style(self, style: str) -> None:
        self._submit("style", style, strings.MA_APPLIED.format(name=self.backend.style_name(style)))

    def choose_speed(self, speed: str) -> None:
        self._submit("speed", speed, strings.MA_SPEED_APPLIED.format(
            speed=self.backend.speed_title(speed).lower()))

    def preview(self) -> None:
        if self.previewing:
            return
        # A fresh choice may still be queued for writing.
        state = dict(self.backend.read_all(),
                     **{k: v for k, v in self.chosen.items() if k in self.pending})
        if state["style"] == "none":
            self.view.status(strings.MA_PREVIEW_NONE)
            return
        self.previewing = True
        self.view.set_minimize_busy(True)
        self.view.status(strings.AN_PREVIEWING)

        def done(result, error) -> None:
            self.previewing = False
            self.view.set_minimize_busy(False)
            ok, message = (False, str(error)) if error is not None else result
            self.view.status("" if ok else strings.AN_PREVIEW_FAILED.format(error=message))

        self.backend.queue_preview(self.backend.preview_argv(state["style"], state["speed"]), done)
