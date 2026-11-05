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

from ..workers import Workers

log = logging.getLogger(__name__)

BACKEND = "network"
WORKER = "network"
READ_WORKER = "network-read"
WIFI_RADIO = "wifi.radio"
BLUETOOTH_POWER = "bluetooth.power"
WIFI_CONNECTION = "wifi.connection"
TIMEOUT_S = 10

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

    def connect(self, name: str) -> tuple[bool, str]:
        return self._ok(["nmcli", "connection", "up", name])

    def _ok(self, argv: list[str]) -> tuple[bool, str]:
        if not shutil.which(argv[0]):
            return False, f"{argv[0]} not found"
        code, out, err = self.run(argv)
        text = (out + err).strip()
        return code == 0, "" if code == 0 else (text or f"exit {code}")

    # ---- History's view --------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        info = probe(self.run)
        out: dict[str, Any] = {}
        for key in keys:
            if key == WIFI_RADIO and info.wifi_on is not None:
                out[key] = info.wifi_on
            elif key == BLUETOOTH_POWER and info.bluetooth_on is not None:
                out[key] = info.bluetooth_on
            elif key == WIFI_CONNECTION:
                active = next((s.name for s in info.saved if s.active), "")
                if active:
                    out[key] = active
        return out

    def apply(self, values: dict[str, Any]) -> None:
        errors: list[str] = []
        for key, value in values.items():
            if key == WIFI_RADIO:
                ok, message = self.set_wifi(bool(value))
            elif key == BLUETOOTH_POWER:
                ok, message = self.set_bluetooth(bool(value))
            elif key == WIFI_CONNECTION:
                ok, message = self.connect(str(value))
            else:
                continue
            if not ok:
                errors.append(f"{key}: {message}")
        if errors:
            raise RuntimeError("; ".join(errors))


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
