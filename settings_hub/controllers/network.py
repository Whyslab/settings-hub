"""The "Network and Bluetooth" page logic. No GTK.

Radio switches and saved-network connections are History items; the lists
themselves are read anew on every show.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .. import strings
from ..backends import network as net
from ..backends import nm_wifi
from ..backends.network import BACKEND

log = logging.getLogger(__name__)


class View(Protocol):
    def show_network(self, info: net.Network) -> None: ...

    def join_finished(self, ssid: str, error: str) -> None:
        """A join ended; error is "" when it worked."""

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

    def join(self, ssid: str, password: str = "", hidden: bool = False,
             expect: str = "") -> None:
        """A network that has no saved connection yet (the password goes over D-Bus).

        expect: the security the person saw in the list (nm_wifi.OPEN / PERSONAL).
        """
        if net.WIFI_CONNECTION in self.pending:  # one connection attempt at a time
            self.view.status(strings.NET_JOIN_FAILED_STATUS.format(error=strings.NET_JOIN_BUSY))
            self.view.join_finished(ssid, strings.NET_JOIN_BUSY)
            return
        before = ""
        if self.info is not None:
            before = next((s.name for s in self.info.saved if s.active), "")
        self.pending.add(net.WIFI_CONNECTION)
        self.view.status(strings.NET_JOIN_STARTED.format(ssid=ssid))

        def job() -> nm_wifi.Joined:
            return self.backend.join(ssid, password, hidden, expect)

        def done(joined: nm_wifi.Joined | None, error: BaseException | None) -> None:
            self.pending.discard(net.WIFI_CONNECTION)
            if error is not None or joined is None:
                if isinstance(error, nm_wifi.JoinError):
                    text = str(error)
                else:  # never repr(): an exception's arguments could hold the password
                    log.error("joining %s failed", ssid, exc_info=error)
                    text = strings.NET_JOIN_UNEXPECTED.format(kind=type(error).__name__)
                self.view.status(strings.NET_JOIN_FAILED_STATUS.format(error=text))
                self.view.join_finished(ssid, text)
            else:
                self.history.record([(BACKEND, net.WIFI_CONNECTION,
                                      label(net.WIFI_CONNECTION), before, joined.name)])
                self.view.status((strings.NET_JOIN_DONE if joined.saved
                                  else strings.NET_JOIN_DONE_UNSAVED).format(name=joined.name))
                self.view.join_finished(ssid, "")
            self.refresh()

        self.backend.workers.submit(net.WORKER, job, done, key=("join", ssid))

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
