"""Wi-Fi, Bluetooth and Tailscale: state and a few safe switches. No GTK.

Commands only, all already on the system: `nmcli` (NetworkManager),
`bluetoothctl` and `tailscale`. Nothing is invented: a missing program leaves
its section empty.

History: "wifi.radio" (on/off), "bluetooth.power" (on/off) and
"wifi.connection" (a saved connection's name) -- undoing that one brings the
previous saved connection up again.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import strings
from ..workers import Workers

log = logging.getLogger(__name__)

BACKEND = "network"
WORKER = "network"
READ_WORKER = "network-read"
WIFI_RADIO = "wifi.radio"
BLUETOOTH_POWER = "bluetooth.power"
WIFI_CONNECTION = "wifi.connection"
TIMEOUT_S = 10
CONNECT_WAIT_S = 8  # shorter than TIMEOUT_S, so nmcli itself says it timed out
NMCLI_TIMED_OUT = 3  # man nmcli: "Timeout expired"
STILL_CONNECTING = "still connecting"  # connect(): started, the result comes later
SETTLE_S = 10  # when the page looks again after a slow connection

Result = tuple[int, str, str]
Runner = Callable[[list[str]], Result]


def _run(argv: list[str]) -> Result:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


@dataclass(frozen=True)
class Wifi:
    ssid: str
    signal: int
    security: str
    in_use: bool


@dataclass(frozen=True)
class Saved:
    name: str
    active: bool


@dataclass(frozen=True)
class BluetoothDevice:
    name: str
    connected: bool


@dataclass
class Network:
    wifi_on: bool | None = None
    wifi: list[Wifi] = field(default_factory=list)  # strongest first
    saved: list[Saved] = field(default_factory=list)  # saved Wi-Fi connections
    bluetooth_on: bool | None = None
    bluetooth: list[BluetoothDevice] = field(default_factory=list)
    tailscale_state: str = ""
    tailscale_names: list[str] = field(default_factory=list)


def split_escaped(line: str, count: int) -> list[str]:
    """Split nmcli -t output on ':' that is not escaped as '\\:'."""
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":" and len(parts) < count - 1:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_wifi(text: str) -> list[Wifi]:
    out: list[Wifi] = []
    for line in text.splitlines():
        fields = split_escaped(line, 4)
        if len(fields) < 4:
            continue
        in_use, ssid, signal, security = fields
        if not ssid:
            continue
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        out.append(Wifi(ssid, strength, security.strip(), in_use.strip() == "*"))
    return sorted(out, key=lambda w: (not w.in_use, -w.signal))


def parse_saved(text: str) -> list[Saved]:
    out: list[Saved] = []
    for line in text.splitlines():
        fields = split_escaped(line, 3)
        if len(fields) < 3:
            continue
        name, kind, active = fields
        if kind != "802-11-wireless":
            continue
        out.append(Saved(name, active == "yes"))
    return out


def parse_bluetooth_devices(text: str) -> list[BluetoothDevice]:
    out: list[BluetoothDevice] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "Device":
            out.append(BluetoothDevice(parts[2].strip(), True))
    return out


def parse_tailscale(text: str) -> tuple[str, list[str]]:
    try:
        raw = json.loads(text)
    except ValueError:
        return "", []
    if not isinstance(raw, dict):
        return "", []
    names: list[str] = []
    for key in ("TailscaleIPs",):
        for value in raw.get(key) or []:
            names.append(str(value))
    return str(raw.get("BackendState") or ""), names


def probe(run: Runner | None = None) -> Network:
    run = run or _run
    info = Network()
    if shutil.which("nmcli"):
        code, out, _err = run(["nmcli", "radio", "wifi"])
        if code == 0:
            info.wifi_on = out.strip() == "enabled"
        code, out, _err = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                               "device", "wifi", "list"])
        if code == 0:
            info.wifi = parse_wifi(out)[:20]
        code, out, _err = run(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE",
                               "connection", "show"])
        if code == 0:
            info.saved = parse_saved(out)
    if shutil.which("bluetoothctl"):
        code, out, _err = run(["bluetoothctl", "show"])
        if code == 0:
            for line in out.splitlines():
                if line.strip().lower().startswith("powered:"):
                    info.bluetooth_on = line.split(":", 1)[1].strip().lower() == "yes"
        code, out, _err = run(["bluetoothctl", "devices", "Connected"])
        if code == 0:
            info.bluetooth = parse_bluetooth_devices(out)
    if shutil.which("tailscale"):
        code, out, _ = run(["tailscale", "status", "--json"])
        if code == 0:
            info.tailscale_state, info.tailscale_names = parse_tailscale(out)
    return info


class Backend:
    def __init__(self, workers: Workers, runner: Runner | None = None) -> None:
        self.workers = workers
        self.run = runner or _run

    def queue_probe(self, on_done: Callable[[Network, BaseException | None], None]) -> None:
        self.workers.submit(READ_WORKER, lambda: probe(self.run), on_done)

    # ---- changes ---------------------------------------------------------

    def set_wifi(self, enabled: bool) -> tuple[bool, str]:
        return self._ok(["nmcli", "radio", "wifi", "on" if enabled else "off"])

    def set_bluetooth(self, enabled: bool) -> tuple[bool, str]:
        return self._ok(["bluetoothctl", "power", "on" if enabled else "off"])

    def connect(self, name: str, wait: bool = True) -> tuple[bool, str]:
        """wait=False: History runs on the GTK thread and must not stop the window.

        It only starts the connection: a wrong password shows on the page later.
        """
        if not wait:
            return self._ok(["nmcli", "-w", "0", "connection", "up", name])
        if not shutil.which("nmcli"):
            return False, "nmcli not found"
        code, out, err = self.run(["nmcli", "-w", str(CONNECT_WAIT_S), "connection", "up", name])
        if code == NMCLI_TIMED_OUT:  # it carries on connecting without us
            return True, STILL_CONNECTING
        text = (out + err).strip()
        return code == 0, "" if code == 0 else (text or f"exit {code}")

    def disconnect_active(self) -> tuple[bool, str]:
        """Undo a connection made from no connection at all."""
        active = self.read([WIFI_CONNECTION]).get(WIFI_CONNECTION)
        if active is None:
            return False, strings.NET_NOT_READ
        if not active:
            return True, ""
        return self._ok(["nmcli", "-w", "0", "connection", "down", active])

    def _ok(self, argv: list[str]) -> tuple[bool, str]:
        if not shutil.which(argv[0]):
            return False, f"{argv[0]} not found"
        code, out, err = self.run(argv)
        text = (out + err).strip()
        return code == 0, "" if code == 0 else (text or f"exit {code}")

    # ---- History's view --------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        """Only what is asked: listing the visible networks takes seconds."""
        out: dict[str, Any] = {}
        if WIFI_RADIO in keys and shutil.which("nmcli"):
            code, text, _err = self.run(["nmcli", "radio", "wifi"])
            if code == 0:
                out[WIFI_RADIO] = text.strip() == "enabled"
        if WIFI_CONNECTION in keys and shutil.which("nmcli"):
            code, text, _err = self.run(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE",
                                         "connection", "show"])
            if code == 0:  # "" is a real answer: connected to nothing
                out[WIFI_CONNECTION] = next((s.name for s in parse_saved(text) if s.active), "")
        if BLUETOOTH_POWER in keys and shutil.which("bluetoothctl"):
            code, text, _err = self.run(["bluetoothctl", "show"])
            if code == 0:
                for line in text.splitlines():
                    if line.strip().lower().startswith("powered:"):
                        out[BLUETOOTH_POWER] = line.split(":", 1)[1].strip().lower() == "yes"
        return out

    def apply(self, values: dict[str, Any]) -> None:
        errors: list[str] = []
        for key, value in values.items():
            if key == WIFI_RADIO:
                ok, message = self.set_wifi(bool(value))
            elif key == BLUETOOTH_POWER:
                ok, message = self.set_bluetooth(bool(value))
            elif key == WIFI_CONNECTION:
                if value:
                    ok, message = self.connect(str(value), wait=False)
                else:
                    ok, message = self.disconnect_active()
            else:
                continue
            if not ok:
                errors.append(f"{key}: {message}")
        if errors:
            raise RuntimeError("; ".join(errors))


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
