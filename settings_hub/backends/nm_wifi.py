"""Join a Wi-Fi network that has no saved connection yet. No GTK.

NetworkManager is asked over the system D-Bus (Gio), not through nmcli: a
password on a command line can be read by any program of the session (ps,
/proc/PID/cmdline) while the command runs. Here it goes straight into the
AddAndActivateConnection call.

    join(ssid, password)               a network in the visible list
    join(ssid, password, hidden=True)  a network that does not announce itself

Only what the visible list shows is sent: the password ("psk"), and NetworkManager
completes the rest from the access point (WPA2, WPA3, open). A network with a
login (802.1X, "enterprise") or the old WEP is refused before anything is sent.

`expect` is the kind of security the person saw in the list. Only access points
of that kind are used: a stranger's open point with the same name ("evil twin")
cannot take a join meant for a protected network, and a password is never
dropped to join something open.

The new connection lives in memory only (AddAndActivateConnection2, persist
"memory") until the network is up; then it is written to disk (Update2,
to-disk). Any failure deletes it, and a crash or a restart of NetworkManager
drops it by itself: a wrong password is never kept and never retried.

Blocking calls with timeouts: run on a worker thread.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import strings

log = logging.getLogger(__name__)

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
DEVICE = NM + ".Device"
WIRELESS = NM + ".Device.Wireless"
AP = NM + ".AccessPoint"
ACTIVE = NM + ".Connection.Active"
SETTINGS_CONN = NM + ".Settings.Connection"
PROPS = "org.freedesktop.DBus.Properties"

DEVICE_TYPE_WIFI = 2
ACTIVE_ACTIVATED = 2
ACTIVE_DEACTIVATED = 4
CALL_TIMEOUT_MS = 10_000
JOIN_TIMEOUT_S = 30.0  # DHCP after a slow handshake can take a while
POLL_S = 0.4

# NM_DEVICE_STATE_REASON_*: the ones that mean "the password did not work".
REASONS_BAD_PASSWORD = {7, 8, 9, 10, 11}  # no secrets, supplicant disconnect/failed/timeout
REASON_SSID_NOT_FOUND = 53
UPDATE_TO_DISK = 0x1
HEX = set("0123456789abcdefABCDEF")

AP_FLAG_PRIVACY = 0x1
KEY_MGMT_PSK = 0x100
KEY_MGMT_8021X = 0x200
KEY_MGMT_SAE = 0x400
KEY_MGMT_OWE = 0x800

OPEN, PERSONAL, ENTERPRISE, WEP = "open", "personal", "enterprise", "wep"
OWE = "owe"  # "enhanced open": no password, but encrypted -- never mixed up with OPEN
NO_PASSWORD = (OPEN, OWE)


class JoinError(Exception):
    """A reason for the person, already in plain words (strings.py)."""


def security_kind(security: str) -> str:
    """nmcli's SECURITY column ("WPA2", "WPA1 WPA2 802.1X", "", "--") -> a kind."""
    text = security.upper()
    if "802.1X" in text:
        return ENTERPRISE
    if "WPA" in text or "SAE" in text:
        return PERSONAL
    if "WEP" in text:
        return WEP
    if "OWE" in text:
        return OWE
    return OPEN  # "" or "--"


def ap_kind(flags: int, wpa: int, rsn: int) -> str:
    """The same answer from an access point's own flags."""
    mgmt = wpa | rsn
    if mgmt & (KEY_MGMT_PSK | KEY_MGMT_SAE):
        return PERSONAL
    if mgmt & KEY_MGMT_8021X:
        return ENTERPRISE
    if mgmt & KEY_MGMT_OWE:
        return OWE
    if not flags & AP_FLAG_PRIVACY:
        return OPEN
    return WEP


@dataclass(frozen=True)
class Joined:
    name: str  # the new connection's name (what History records)
    saved: bool = True  # False: works now, but could not be written to disk


def password_ok(password: str) -> bool:
    """WPA: a passphrase of 8-63 printable ASCII characters, or the raw key as 64 hex
    digits (WPA3-only networks allow more, but such passwords are rare: refused here)."""
    if len(password) == 64:
        return set(password) <= HEX
    return 8 <= len(password) <= 63 and all(" " <= ch <= "~" for ch in password)


Call = Callable[[str, str, str, Any, str | None], tuple]


def _gio_call() -> Call:
    from gi.repository import Gio, GLib  # Gio only: no GTK in a backend

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as exc:  # no system bus at all
        raise JoinError(strings.NET_JOIN_NO_NM) from exc

    def call(path: str, iface: str, method: str, args: Any, reply: str | None) -> tuple:
        try:
            out = bus.call_sync(NM, path, iface, method, args,
                                GLib.VariantType(reply) if reply else None,
                                Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None)
        except GLib.Error as exc:
            raise RuntimeError(Gio.DBusError.strip_remote_error(exc) or exc.message) from exc
        return out.unpack() if out is not None else ()

    return call


def _variant(kind: str, value: Any):
    from gi.repository import GLib

    return GLib.Variant(kind, value)


class Joiner:
    """One attempt at a time; `call` and `sleep` are replaceable for tests."""

    def __init__(self, call: Call | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 variant: Callable[[str, Any], Any] = _variant) -> None:
        self._call = call
        self._sleep = sleep
        self._clock = clock
        self._variant = variant

    @property
    def call(self) -> Call:
        if self._call is None:
            self._call = _gio_call()
        return self._call

    def prop(self, path: str, iface: str, name: str) -> Any:
        return self.call(path, PROPS, "Get", self._variant("(ss)", (iface, name)), "(v)")[0]

    # ---- finding things ---------------------------------------------------

    def wifi_device(self) -> str:
        (devices,) = self.call(NM_PATH, NM, "GetDevices", None, "(ao)")
        for path in devices:
            if self.prop(path, DEVICE, "DeviceType") == DEVICE_TYPE_WIFI:
                return path
        raise JoinError(strings.NET_JOIN_NO_DEVICE)

    def access_point(self, device: str, ssid: str, want: str = "") -> tuple[str, str]:
        """(path, kind) of the strongest access point with this name (and kind, if given)."""
        (points,) = self.call(device, WIRELESS, "GetAllAccessPoints", None, "(ao)")
        best: tuple[int, str, str] | None = None
        other_kind = False
        wanted = ssid.encode()
        for path in points:
            try:
                if bytes(self.prop(path, AP, "Ssid")) != wanted:
                    continue
                strength = int(self.prop(path, AP, "Strength"))
                kind = ap_kind(int(self.prop(path, AP, "Flags")),
                               int(self.prop(path, AP, "WpaFlags")),
                               int(self.prop(path, AP, "RsnFlags")))
            except RuntimeError:
                continue  # it went away while we were looking
            if want and kind != want:
                other_kind = True
                continue
            if best is None or strength > best[0]:
                best = (strength, path, kind)
        if best is None:
            if other_kind:
                raise JoinError(strings.NET_JOIN_SECURITY_CHANGED.format(ssid=ssid))
            raise JoinError(strings.NET_JOIN_NOT_VISIBLE.format(ssid=ssid))
        return best[1], best[2]

    # ---- joining ------------------------------------------------------------

    def settings(self, ssid: str, password: str, kind: str, hidden: bool) -> dict:
        v = self._variant
        out: dict[str, dict[str, Any]] = {}
        if hidden:  # nothing to complete it from: say everything
            out["connection"] = {"id": v("s", ssid), "type": v("s", "802-11-wireless")}
            out["802-11-wireless"] = {"ssid": v("ay", ssid.encode()), "hidden": v("b", True),
                                      "mode": v("s", "infrastructure")}
            if password:
                out["802-11-wireless-security"] = {"key-mgmt": v("s", "wpa-psk"),
                                                   "psk": v("s", password)}
        elif kind == PERSONAL:
            out["802-11-wireless-security"] = {"psk": v("s", password)}
        return out

    def join(self, ssid: str, password: str = "", hidden: bool = False,
             expect: str = "") -> Joined:
        ssid = ssid.strip()
        if not ssid:
            raise JoinError(strings.NET_JOIN_NO_NAME)
        if len(ssid.encode()) > 32:
            raise JoinError(strings.NET_JOIN_LONG_NAME)
        if not hidden and expect not in (OPEN, OWE, PERSONAL):
            # Without the kind the person saw, an evil twin could not be told apart.
            raise JoinError(strings.NET_JOIN_NO_KIND)
        if hidden and not password:
            # An open hidden profile would join any open network of that name, anywhere.
            raise JoinError(strings.NET_JOIN_HIDDEN_NEEDS_PASSWORD)
        try:
            device = self.wifi_device()
            if hidden:
                point, kind = "/", PERSONAL
            else:
                point, kind = self.access_point(device, ssid, expect)
        except RuntimeError as exc:  # NetworkManager is not there or broke off
            raise JoinError(strings.NET_JOIN_REFUSED.format(error=exc)) from exc
        if kind in (ENTERPRISE, WEP):
            raise JoinError(strings.NET_JOIN_UNSUPPORTED)
        if kind in NO_PASSWORD and password:
            raise JoinError(strings.NET_JOIN_SECURITY_CHANGED.format(ssid=ssid))
        if kind == PERSONAL and not password_ok(password):
            raise JoinError(strings.NET_JOIN_PASSWORD_LENGTH)
        v = self._variant
        args = v("(a{sa{sv}}ooa{sv})", (self.settings(ssid, password, kind, hidden),
                                        device, point, {"persist": v("s", "memory")}))
        try:
            conn, active, _result = self.call(NM_PATH, NM, "AddAndActivateConnection2", args,
                                              "(ooa{sv})")
        except RuntimeError as exc:
            raise JoinError(strings.NET_JOIN_REFUSED.format(error=exc)) from exc
        ok, reason = False, None
        try:
            ok, reason = self._wait(active, device)
        finally:
            if not ok:  # also on an unexpected error: nothing half-made stays behind
                self._forget(conn)
        if ok:
            return Joined(self._name(conn, ssid), saved=self._save(conn))
        if reason in REASONS_BAD_PASSWORD:
            raise JoinError(strings.NET_JOIN_BAD_PASSWORD)
        if reason == REASON_SSID_NOT_FOUND:
            raise JoinError(strings.NET_JOIN_NOT_VISIBLE.format(ssid=ssid))
        if reason is None:
            raise JoinError(strings.NET_JOIN_TIMEOUT)
        raise JoinError(strings.NET_JOIN_FAILED.format(code=reason))

    def _wait(self, active: str, device: str) -> tuple[bool, int | None]:
        """(activated?, the device's reason code when it failed; None: timed out)."""
        deadline = self._clock() + JOIN_TIMEOUT_S
        while self._clock() < deadline:
            try:
                state = int(self.prop(active, ACTIVE, "State"))
            except RuntimeError:
                state = ACTIVE_DEACTIVATED  # the object is gone: it gave up
            if state == ACTIVE_ACTIVATED:
                return True, None
            if state == ACTIVE_DEACTIVATED:
                return False, self._reason(device)
            self._sleep(POLL_S)
        return False, None

    def _reason(self, device: str) -> int:
        try:
            _state, reason = self.prop(device, DEVICE, "StateReason")
            return int(reason)
        except (RuntimeError, TypeError, ValueError):
            return -1

    def _name(self, conn: str, fallback: str) -> str:
        try:
            (settings,) = self.call(conn, SETTINGS_CONN, "GetSettings", None, "(a{sa{sv}})")
            return str(settings.get("connection", {}).get("id") or fallback)
        except RuntimeError:
            return fallback

    def _save(self, conn: str) -> bool:
        """The network works: keep it for the next start too."""
        try:
            self.call(conn, SETTINGS_CONN, "Update2",
                      self._variant("(a{sa{sv}}ua{sv})", ({}, UPDATE_TO_DISK, {})), "(a{sv})")
            return True
        except RuntimeError as exc:
            log.warning("connected, but could not save %s: %s", conn, exc)
            return False

    def _forget(self, conn: str) -> None:
        try:
            self.call(conn, SETTINGS_CONN, "Delete", None, None)
        except RuntimeError as exc:
            log.warning("could not delete the failed connection %s: %s", conn, exc)
