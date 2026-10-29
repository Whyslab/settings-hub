"""One worker thread per backend, with coalescing. No GTK at import time.

Applying a change can be slow (restarting hypridle takes ~2 s), so it never
runs on the GTK thread. Each backend gets one thread, so two applies of the
same backend never run at the same time. Jobs are coalesced by key: if three
jobs with the same key arrive while one is running, only the last of them runs.
Jobs with different keys all run, in the order their latest version arrived.

Results go back through a dispatcher, by default GLib.idle_add, so callbacks
run on the GTK thread. Tests inject a plain function instead.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

Done = Callable[[Any, BaseException | None], None]
Dispatch = Callable[[Callable[[], None]], None]


def glib_dispatch(fn: Callable[[], None]) -> None:
    from gi.repository import GLib

    def once() -> bool:
        fn()
        return False

    GLib.idle_add(once)


class Worker:
    def __init__(self, name: str, dispatch: Dispatch | None = None) -> None:
        self.name = name
        self._dispatch = dispatch or glib_dispatch
        self._cond = threading.Condition()
        self._pending: OrderedDict[Any, tuple[Callable[[], Any], Done | None]] = OrderedDict()
        self._busy = False
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, name=f"apply-{name}", daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[[], Any], on_done: Done | None = None, key: Any = None) -> None:
        """Queue fn(); a pending job with the same key is replaced."""
        with self._cond:
            if self._stopped:
                raise RuntimeError(f"worker {self.name} is stopped")
            self._pending.pop(key, None)
            self._pending[key] = (fn, on_done)
            self._cond.notify_all()

    def pending(self) -> int:
        with self._cond:
            return len(self._pending)

    def busy(self) -> bool:
        """True while a job is queued or running (the page must not overwrite the field)."""
        with self._cond:
            return self._busy or bool(self._pending)

    def wait_idle(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not self._busy and not self._pending, timeout)

    def stop(self, timeout: float | None = None) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending or self._stopped)
                if not self._pending:  # stopped and drained
                    return
                _key, (fn, on_done) = self._pending.popitem(last=False)
                self._busy = True
            result: Any = None
            error: BaseException | None = None
            try:
                result = fn()
            except Exception as exc:  # handed to the callback, never kills the thread
                error = exc
            if on_done is not None:
                self._dispatch(lambda r=result, e=error, cb=on_done: cb(r, e))
            with self._cond:
                self._busy = False
                self._cond.notify_all()


class Workers:
    """Workers by backend name, created on first use."""

    def __init__(self, dispatch: Dispatch | None = None) -> None:
        self._dispatch = dispatch
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()

    def get(self, backend: str) -> Worker:
        with self._lock:
            if backend not in self._workers:
                self._workers[backend] = Worker(backend, self._dispatch)
            return self._workers[backend]

    def submit(self, backend: str, fn: Callable[[], Any], on_done: Done | None = None,
               key: Any = None) -> None:
        self.get(backend).submit(fn, on_done, key)

    def stop_all(self, timeout: float | None = None) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            w.stop(timeout)
