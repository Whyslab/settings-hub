"""Bluetooth devices on the "Network and Bluetooth" page. No GTK.

One action per device at a time; the list is read again after each one. A
search re-reads the list every TICK_S seconds and stops after bluez.SEARCH_S,
when the page is hidden (stop_search), or when the person stops it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from .. import strings
from ..backends import bluez as bz

TICK_S = 3
log = logging.getLogger(__name__)


class View(Protocol):
    def show_bluetooth(self, state: bz.State, busy: set[str], searching: bool) -> None: ...

    def status(self, text: str) -> None: ...


Later = Callable[[int, Callable[[], None]], Any]  # (seconds, fn) -> a handle


class Controller:
    def __init__(self, backend: bz.Backend, view: View, later: Later,
                 cancel: Callable[[Any], None]) -> None:
        self.backend = backend
        self.view = view
        self.later = later
        self.cancel = cancel
        self.state: bz.State | None = None
        self.busy: set[str] = set()  # device paths with an action running
        self.searching = False
        self._ticks = 0
        self._tick: Any = None
        self._search_adapter = ""  # where discovery was started (to stop it there)

    # ---- reading -------------------------------------------------------------

    def refresh(self) -> None:
        self.backend.queue_state(self._read)

    def _read(self, state: bz.State | None, error: BaseException | None) -> None:
        if error is not None or state is None:
            # The page says why in the device list; no adapter = no search. A search
            # in progress is still stopped: discovery must not run for the session.
            self.stop_search(redraw=False)
            self.state = None
            text = _reason(error)
            self.view.show_bluetooth(bz.State("", False, False, error=text), set(), False)
            return
        self.state = state
        self.view.show_bluetooth(state, set(self.busy), self.searching)

    def device(self, path: str) -> bz.Device | None:
        if self.state is None:
            return None
        return next((d for d in self.state.devices if d.path == path), None)

    # ---- device actions --------------------------------------------------------

    def connect(self, path: str) -> None:
        self._act(path, self.backend.connect, strings.BT_DONE_CONNECT)

    def disconnect(self, path: str) -> None:
        self._act(path, self.backend.disconnect, strings.BT_DONE_DISCONNECT)

    def forget(self, path: str) -> None:
        self._act(path, self.backend.forget, strings.BT_DONE_FORGET)

    def pair(self, path: str, input_ok: bool = False) -> None:
        """Called after the page asked (input_ok: with the "may type for you" warning).
        The search stops first: BlueZ pairs badly during it."""
        self.stop_search(redraw=False)
        self._act(path, lambda p: self.backend.pair(p, input_ok), strings.BT_DONE_PAIR)

    def _act(self, path: str, action: Callable[[str], None], done_text: str) -> None:
        if path in self.busy:
            return
        device = self.device(path)
        name = device.name if device else path.rsplit("/", 1)[-1]
        self.busy.add(path)
        if self.state is not None:
            self.view.show_bluetooth(self.state, set(self.busy), self.searching)

        def done(_result, error: BaseException | None) -> None:
            self.busy.discard(path)
            if error is None:
                self.view.status(done_text.format(name=name))
            else:
                self.view.status(strings.BT_FAILED.format(name=name, error=_reason(error)))
            self.refresh()

        # One worker: actions run in order; `busy` keeps a device to one at a time.
        self.backend.workers.submit(bz.WORKER, lambda: action(path), done, key=path)

    # ---- searching -------------------------------------------------------------

    def start_search(self) -> None:
        state = self.state
        if self.searching or state is None or not state.adapter:
            return
        if not state.powered:
            self.view.status(strings.BT_ERR_OFF)
            return
        self.searching = True
        self._ticks = 0
        self._search_adapter = state.adapter
        self.view.show_bluetooth(state, set(self.busy), True)

        def started(_result, error: BaseException | None) -> None:
            if error is not None:
                self.searching = False
                self.view.status(strings.BT_FAILED.format(name=strings.BT_SEARCH,
                                                          error=_reason(error)))
                self.refresh()
                return
            if not self.searching:  # stopped while starting: the stop is queued after
                return
            if self._tick is not None:  # a quick stop + start: one chain of ticks only
                self.cancel(self._tick)
            self._schedule()

        self.backend.workers.submit(bz.WORKER, lambda: self.backend.start_search(
            state.adapter), started, key="search")

    def _schedule(self) -> None:
        self._tick = self.later(TICK_S, self._on_tick)

    def _on_tick(self) -> None:
        self._tick = None
        if not self.searching:
            return
        self._ticks += 1
        if self._ticks * TICK_S >= bz.SEARCH_S:
            self.stop_search()
            return
        self.refresh()
        self._schedule()

    def stop_search(self, redraw: bool = True) -> None:
        if not self.searching:
            return
        self.searching = False
        if self._tick is not None:
            self.cancel(self._tick)
            self._tick = None
        adapter, self._search_adapter = self._search_adapter, ""
        after = (lambda *_: self.refresh()) if redraw else None
        if adapter:
            self.backend.workers.submit(bz.WORKER, lambda: self.backend.stop_search(adapter),
                                        after, key="search")
        elif redraw:
            self.refresh()


def _reason(error: BaseException) -> str:
    """A BlueZ reason as is; anything else by its type only (never its arguments)."""
    if isinstance(error, bz.BluetoothError):
        return str(error)
    log.error("bluetooth action failed", exc_info=error)
    return strings.BT_ERR_OTHER.format(error=type(error).__name__)
