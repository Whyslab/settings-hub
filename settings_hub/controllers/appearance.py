"""The "Appearance" page logic: fonts, text scale, icons. No GTK.

Each change is one History item. The text scale applies while the slider moves
and is logged once when it rests. The cursor rows on the same page are the
variable table's (controllers.variables), not this controller.
"""

from __future__ import annotations

import itertools
from typing import Any, Protocol

from .. import strings
from ..backends import appearance as ap
from ..backends.appearance import BACKEND


class View(Protocol):
    def show_look(self, look: ap.Look, pending: set[str]) -> None: ...

    def status(self, text: str) -> None: ...


def label(key: str) -> str:
    return strings.LOOK_LABELS.get(key, key)


class Controller:
    def __init__(self, backend: ap.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.look: ap.Look | None = None
        self.pending: set[str] = set()  # keys with a change under way (not redrawn)
        self._inflight: dict[str, int] = {}
        self._jobs = itertools.count()  # each change its own job: none is coalesced away
        self._drag: dict[str, Any] | None = None  # the text scale drag under way

    def refresh(self) -> None:
        self.backend.queue_probe(self._read)

    def _read(self, look: ap.Look | None, error: BaseException | None) -> None:
        if error is not None or look is None:
            self.view.status(strings.LOOK_READ_FAILED.format(error=error))
            return
        self.look = look
        self.view.show_look(look, set(self.pending))

    def value(self, key: str) -> Any:
        return self.look.values.get(key) if self.look else None

    # ---- changes ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        try:
            value = ap.clean(key, value)
        except (KeyError, ValueError):
            self.view.status(strings.LOOK_BAD_VALUE)
            return
        self.pending.add(key)
        self._inflight[key] = self._inflight.get(key, 0) + 1

        def job() -> tuple[Any, Any]:
            # "Before" is read here, on the serial worker, not taken from the last
            # picture: two quick changes then log A->B and B->C, not A->B, A->C.
            before = self.backend.read([key]).get(key)
            if before != value:
                self.backend.set(key, value)
            return before, self.backend.read([key]).get(key, value)

        try:
            self.backend.workers.submit(ap.WORKER, job, lambda r, e: self._done(key, r, e),
                                        key=("set", next(self._jobs)))
        except RuntimeError:  # the worker is stopped (the app is closing)
            self._done(key, None, RuntimeError("stopped"))

    def _done(self, key: str, result, error: BaseException | None) -> None:
        self._inflight[key] -= 1
        if self._inflight[key] <= 0 and not (key == ap.SCALE and self._drag is not None):
            self._inflight.pop(key)
            self.pending.discard(key)
        if error is not None:
            self.view.status(strings.LOOK_APPLY_FAILED.format(name=label(key), error=error))
        else:
            before, actual = result
            self._log(key, before, actual)
        self.refresh()

    def _log(self, key: str, before: Any, actual: Any) -> None:
        if before == actual:
            return
        try:
            undoable = before is not None and ap.clean(key, before) == before
        except (KeyError, ValueError):
            undoable = False
        if undoable:
            self.history.record([(BACKEND, key, label(key), before, actual)])
            self.view.status(strings.LOOK_APPLIED.format(name=label(key)))
        else:  # nothing to go back to: say so rather than let Ctrl+Z skip it
            self.view.status(strings.LOOK_APPLIED_NO_UNDO.format(name=label(key)))

    def same_as(self, target: str, family: str | None = None) -> None:
        """"The same font there": the panel takes the interface family, kitty the
        monospace one. `family` is the view's reading of that font (Pango knows
        that "Sans Bold 11" is the family "Sans"); without it the size is cut off."""
        source = ap.FONT if target == ap.PANEL_FONT else ap.MONO
        if family is None:
            family, _size = ap.split_font(self.value(source) or "")
        if not family:
            return
        if target == ap.PANEL_FONT:
            self.set(ap.PANEL_FONT, family)
        elif target == ap.KITTY_FONT:
            _old, size = ap.split_font(self.value(ap.KITTY_FONT) or "")
            # the terminal keeps its own size: 11 pt of GTK is small there
            self.set(ap.KITTY_FONT, ap.font_text(family, size))

    # ---- the text scale --------------------------------------------------------

    def scale_moved(self, value: float) -> None:
        value = ap.clean(ap.SCALE, value)
        if self._drag is None:
            # A new drag: its "before" is read on the worker, ahead of its first move.
            drag: dict[str, Any] = {}
            try:
                self.backend.workers.submit(
                    ap.WORKER, lambda: drag.__setitem__("before", self.backend.read(
                        [ap.SCALE]).get(ap.SCALE)), None, key=("before", id(drag)))
            except RuntimeError:  # the worker is stopped (the app is closing)
                return
            self._drag = drag
        self.pending.add(ap.SCALE)
        if self.look is not None:
            self.look.values[ap.SCALE] = value
        self.backend.workers.submit(ap.WORKER, lambda: self.backend.set(ap.SCALE, value),
                                    self._scale_applied, key=ap.SCALE)

    def _scale_applied(self, _result, error: BaseException | None) -> None:
        if error is not None:
            self.view.status(strings.LOOK_APPLY_FAILED.format(name=label(ap.SCALE),
                                                               error=error))

    def commit_scale(self) -> None:
        drag, self._drag = self._drag, None
        if drag is None:
            return

        def job() -> tuple[Any, Any]:
            # Queued after this drag's last move (moves share one key and are
            # re-queued at the end), so it reads what the drag left.
            return drag.get("before"), self.backend.read([ap.SCALE]).get(ap.SCALE)

        def done(result, error: BaseException | None) -> None:
            if self._drag is None:  # no new drag started meanwhile
                self.pending.discard(ap.SCALE)
            if error is None and result[1] is not None:
                self._log(ap.SCALE, *result)
            if self._drag is None:
                self.refresh()  # the slider shows what was applied, not what was dragged

        self.backend.workers.submit(ap.WORKER, job, done, key=("commit", id(drag)))
