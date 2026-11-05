"""The "Network and Bluetooth" page logic. No GTK.

Radio switches and saved-network connections are History items; the lists
themselves are read anew on every show.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import network as net
from ..backends.network import BACKEND


class View(Protocol):
    def show_network(self, info: net.Network) -> None: ...

    def status(self, text: str) -> None: ...

    def refresh_later(self, seconds: int) -> None: ...


def label(key: str) -> str:
    return {
        net.WIFI_RADIO: strings.NET_LABEL_WIFI,
        net.BLUETOOTH_POWER: strings.NET_LABEL_BLUETOOTH,
        net.WIFI_CONNECTION: strings.NET_LABEL_CONNECTION,
    }.get(key, key)


class Controller:
    def __init__(self, backend: net.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.info: net.Network | None = None
        self.pending: set[str] = set()

    def refresh(self) -> None:
        self.backend.queue_probe(self._read)

    def _read(self, info: net.Network | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.view.status(strings.NET_READ_FAILED.format(error=error))
            return
        self.info = info
        self.view.show_network(info)

    # ---- changes ---------------------------------------------------------

    def set_wifi(self, enabled: bool) -> None:
        before = bool(self.info.wifi_on) if self.info else not enabled
        self._submit(net.WIFI_RADIO, before, enabled,
                     lambda: self.backend.set_wifi(enabled))

    def set_bluetooth(self, enabled: bool) -> None:
        before = bool(self.info.bluetooth_on) if self.info else not enabled
        self._submit(net.BLUETOOTH_POWER, before, enabled,
                     lambda: self.backend.set_bluetooth(enabled))

    def connect(self, name: str) -> None:
        before = ""
        if self.info is not None:
            before = next((s.name for s in self.info.saved if s.active), "")
        if before == name:
            return
        self._submit(net.WIFI_CONNECTION, before, name,
                     lambda: self.backend.connect(name))

    def _submit(self, key: str, before: Any, value: Any, action) -> None:
        self.pending.add(key)

        def job() -> tuple[str, Any, Any, bool, str]:
            ok, message = action()
            return key, before, value, ok, message

        self.backend.workers.submit(net.WORKER, job, self._done, key=key)

    def _done(self, result, error: BaseException | None) -> None:
        if error is not None or result is None:
            self.pending.clear()
            self.view.status(strings.NET_APPLY_FAILED.format(error=error))
            return
        key, before, value, ok, message = result
        self.pending.discard(key)
        if not ok:
            self.view.status(strings.NET_APPLY_FAILED.format(error=message))
        else:
            self.history.record([(BACKEND, key, label(key), before, value)])
            if message == net.STILL_CONNECTING:  # undo works; the page looks again later
                self.view.status(strings.NET_STILL_CONNECTING.format(name=value))
                self.view.refresh_later(net.SETTLE_S)
            else:
                self.view.status(strings.NET_APPLIED.format(name=label(key)))
        self.refresh()
