"""Bluetooth devices through BlueZ on the system D-Bus (Gio). No GTK.

    devices()            paired devices and, while searching, the new ones nearby
    connect(path)        connect a paired device
    disconnect(path)
    forget(path)         unpair (Adapter1.RemoveDevice)
    pair(path)           pair a new device, trust it, connect it
    start_search() / stop_search()

Pairing works for devices that need no code ("Just Works": headphones,
speakers, most mice). A device that asks for a PIN or a code on screen (most
keyboards) needs an agent this window does not have; BlueZ then refuses and the
reason says so. A name is whatever the device announces, so the page asks before
pairing and shows the type BlueZ sees (an "AirPods" that is really a keyboard
could type for you); names are stripped of invisible and direction characters.

A search is BlueZ discovery, which belongs to this process's bus connection:
it stops when stop_search() is called, after SEARCH_S at the latest, or when the
process exits. Connections are not History items: they are a device's state,
not a setting.

Blocking calls with timeouts: run on a worker thread.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import strings

log = logging.getLogger(__name__)

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
OBJECTS = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
WORKER = "bluetooth"
SEARCH_S = 30
CALL_TIMEOUT_MS = 10_000
CONNECT_TIMEOUT_MS = 30_000  # headphones can take a while to agree on a profile
PAIR_TIMEOUT_MS = 60_000

# BlueZ error names -> plain words.
ERRORS = {
    "org.bluez.Error.AuthenticationFailed": strings.BT_ERR_AUTH,
    "org.bluez.Error.AuthenticationRejected": strings.BT_ERR_AUTH,
    "org.bluez.Error.AuthenticationCanceled": strings.BT_ERR_AUTH,
    "org.bluez.Error.AuthenticationTimeout": strings.BT_ERR_TIMEOUT,
    "org.bluez.Error.ConnectionAttemptFailed": strings.BT_ERR_UNREACHABLE,
    "org.bluez.Error.Failed": strings.BT_ERR_FAILED,
    "org.bluez.Error.InProgress": strings.BT_ERR_BUSY,
    "org.bluez.Error.AlreadyExists": strings.BT_ERR_ALREADY,
    "org.bluez.Error.NotReady": strings.BT_ERR_OFF,
    "org.bluez.Error.DoesNotExist": strings.BT_ERR_GONE,
    "org.freedesktop.DBus.Error.NoReply": strings.BT_ERR_TIMEOUT,
    "org.freedesktop.DBus.Error.ServiceUnknown": strings.BT_ERR_NO_BLUEZ,
}


# Keyboard services: classic HID and HID over GATT (Bluetooth LE).
HID_UUIDS = frozenset({"00001124-0000-1000-8000-00805f9b34fb",
                       "00001812-0000-1000-8000-00805f9b34fb"})


def clean_name(text: str) -> str:
    """Drop control, format (direction overrides, zero-width) and surrogate characters."""
    kept = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    return " ".join(kept.split())[:64]


def risky(device: Device) -> bool:
    """Anything but plain audio could type for you: input devices, phones and computers
    (keyboard apps), unknown types. The type is what the device says about itself, so
    pair() checks the services again once they are known."""
    return not device.icon.startswith("audio-") or bool(device.uuids & HID_UUIDS)


class BluetoothError(Exception):
    """A reason for the person (strings.py)."""


@dataclass(frozen=True)
class Device:
    path: str
    address: str
    name: str
    icon: str  # BlueZ's guess: "audio-headphones", "input-mouse", ...
    paired: bool
    connected: bool
    battery: int | None = None  # percent, if the device reports it
    named: bool = True  # False: BlueZ only knows its address ("AA-BB-...")
    uuids: frozenset[str] = frozenset()  # services it announced (may be incomplete)


@dataclass(frozen=True)
class State:
    adapter: str  # "" when there is no adapter
    powered: bool
    searching: bool
    devices: tuple[Device, ...] = ()
    error: str = ""  # why there is no list (BlueZ did not answer)

    @property
    def paired(self) -> list[Device]:
        return [d for d in self.devices if d.paired]

    @property
    def found(self) -> list[Device]:
        """New devices nearby that have a name (nameless ones cannot be told apart)."""
        return [d for d in self.devices if not d.paired and d.named]


Call = Callable[[str, str, str, Any, str | None, int], tuple]


def _gio_call() -> Call:
    from gi.repository import Gio, GLib

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as exc:  # no system bus at all
        raise BluetoothError(strings.BT_ERR_NO_BLUEZ) from exc

    def call(path: str, iface: str, method: str, args: Any, reply: str | None,
             timeout_ms: int) -> tuple:
        try:
            out = bus.call_sync(BLUEZ, path, iface, method, args,
                                GLib.VariantType(reply) if reply else None,
                                Gio.DBusCallFlags.NONE, timeout_ms, None)
        except GLib.Error as exc:
            name = Gio.DBusError.get_remote_error(exc) or ""
            text = Gio.DBusError.strip_remote_error(exc) or exc.message
            raise BluetoothError(ERRORS.get(name, strings.BT_ERR_OTHER.format(error=text))) \
                from exc
        return out.unpack() if out is not None else ()

    return call


def _variant(kind: str, value: Any):
    from gi.repository import GLib

    return GLib.Variant(kind, value)


def parse(objects: dict) -> State:
    """GetManagedObjects' answer -> the first adapter and its devices."""
    adapter, powered, searching = "", False, False
    for path in sorted(objects):
        props = objects[path].get(ADAPTER)
        if props is not None:
            adapter = path
            powered = bool(props.get("Powered"))
            searching = bool(props.get("Discovering"))
            break
    devices = []
    for path, interfaces in objects.items():
        props = interfaces.get(DEVICE)
        if props is None or (adapter and props.get("Adapter") not in (None, adapter)):
            continue
        address = str(props.get("Address") or "")
        battery = interfaces.get(BATTERY, {}).get("Percentage")
        alias = clean_name(str(props.get("Alias") or ""))
        # Without a Name, BlueZ makes the alias from the address ("AA-BB-CC-...").
        named = bool(props.get("Name")) or bool(alias and alias.replace("-", ":") != address)
        devices.append(Device(
            path=path, address=address, named=named,
            name=alias or clean_name(str(props.get("Name") or "")) or address,
            icon=str(props.get("Icon") or ""),
            paired=bool(props.get("Paired")), connected=bool(props.get("Connected")),
            uuids=frozenset(str(u).lower() for u in props.get("UUIDs") or ()),
            battery=int(battery) if battery is not None else None))
    devices.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
    return State(adapter, powered, searching, tuple(devices))


class Backend:
    def __init__(self, workers, call: Call | None = None,
                 variant: Callable[[str, Any], Any] = _variant) -> None:
        self.workers = workers
        self._call = call
        self._variant = variant

    @property
    def call(self) -> Call:
        if self._call is None:
            self._call = _gio_call()
        return self._call

    def state(self) -> State:
        (objects,) = self.call("/", OBJECTS, "GetManagedObjects", None,
                               "(a{oa{sa{sv}}})", CALL_TIMEOUT_MS)
        return parse(objects)

    def queue_state(self, on_done) -> None:
        self.workers.submit(WORKER + "-read", self.state, on_done)

    # ---- devices ------------------------------------------------------------

    def connect(self, path: str) -> None:
        self.call(path, DEVICE, "Connect", None, None, CONNECT_TIMEOUT_MS)

    def disconnect(self, path: str) -> None:
        self.call(path, DEVICE, "Disconnect", None, None, CALL_TIMEOUT_MS)

    def forget(self, path: str) -> None:
        adapter = path.rsplit("/", 1)[0]  # /org/bluez/hci0/dev_XX -> /org/bluez/hci0
        self.call(adapter, ADAPTER, "RemoveDevice", self._variant("(o)", (path,)), None,
                  CALL_TIMEOUT_MS)

    def pair(self, path: str, input_ok: bool = False) -> None:
        """Pair, check what it really offers, trust (so it may reconnect), connect.

        input_ok: the person was warned that it may type for them. Without that, a
        device that turns out to offer a keyboard service is forgotten again before
        it is trusted or connected (a fake "headphones").
        """
        try:
            self.call(path, DEVICE, "Pair", None, None, PAIR_TIMEOUT_MS)
        except BluetoothError as exc:
            if str(exc) != strings.BT_ERR_ALREADY:
                raise
        if not input_ok:
            (uuids,) = self.call(path, PROPS, "Get", self._variant("(ss)", (DEVICE, "UUIDs")),
                                 "(v)", CALL_TIMEOUT_MS)
            if {str(u).lower() for u in uuids or ()} & HID_UUIDS:
                self.forget(path)
                raise BluetoothError(strings.BT_ERR_IS_INPUT)
        self.call(path, PROPS, "Set",
                  self._variant("(ssv)", (DEVICE, "Trusted", self._variant("b", True))),
                  None, CALL_TIMEOUT_MS)
        self.connect(path)

    # ---- searching ------------------------------------------------------------

    def start_search(self, adapter: str) -> None:
        try:
            self.call(adapter, ADAPTER, "StartDiscovery", None, None, CALL_TIMEOUT_MS)
        except BluetoothError as exc:
            if str(exc) != strings.BT_ERR_BUSY:  # already searching: fine
                raise

    def stop_search(self, adapter: str) -> None:
        try:
            self.call(adapter, ADAPTER, "StopDiscovery", None, None, CALL_TIMEOUT_MS)
        except BluetoothError as exc:
            log.info("stop discovery: %s", exc)  # not ours, or already stopped
