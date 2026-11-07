"""Charge of a mouse, headphones and other devices with their own battery. No GTK.

Three sources, read only:
  * /sys/class/power_supply entries with scope "Device" -- what the kernel
    knows itself, e.g. a Logitech mouse on its USB receiver (hidpp_battery_N);
  * BlueZ, org.bluez.Battery1 on a device (through `busctl`) -- Bluetooth
    headphones; for AirPods and most headsets PipeWire fills it in while they
    are connected;
  * a short list of devices that are plugged in but whose charge nobody can
    read on Linux, so the page can say so instead of keeping quiet.

A device the kernel and BlueZ both report (a Bluetooth mouse) is shown once.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SYS_POWER = Path("/sys/class/power_supply")
SYS_HID = Path("/sys/bus/hid/devices")
TIMEOUT_S = 5

# USB vendor:product (upper case, as in HID_ID) -> name. Plugged in, but the
# charge cannot be read: HeadsetControl has no support for it (issue #402).
UNREADABLE = {
    ("046D", "0ACB"): "Logitech G435",
}

Result = tuple[int, str, str]
Runner = Callable[[list[str]], Result]


def _run(argv: list[str]) -> Result:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


@dataclass
class Device:
    key: str  # stable id: "sys:<name>", "bt:<address>" or "usb:<vid>:<pid>"
    name: str
    kind: str = ""  # "mouse", "headphones", "keyboard", "" when not known
    percent: int | None = None  # None: the charge cannot be read
    charging: bool = False
    asleep: bool = False  # the value is the last one the device sent


def _uevent(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            out[name] = value
    return out


def _kind_from_name(name: str) -> str:
    low = name.lower()
    if any(word in low for word in ("mouse", "мыш")):
        return "mouse"
    if any(word in low for word in ("keyboard", "клавиат")):
        return "keyboard"
    if any(word in low for word in ("headset", "headphone", "airpods", "buds")):
        return "headphones"
    return ""


def from_sysfs(base: Path = SYS_POWER) -> list[Device]:
    found: list[Device] = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return found
    for entry in entries:
        info = _uevent(entry / "uevent")
        if info.get("POWER_SUPPLY_SCOPE") != "Device":
            continue  # the laptop's own battery and the charger
        if info.get("POWER_SUPPLY_TYPE", "Battery") != "Battery":
            continue  # USB-C ports (ucsi-source-psy-*) also say "Device"
        if info.get("POWER_SUPPLY_PRESENT") == "0":
            continue
        try:
            percent: int | None = int(info["POWER_SUPPLY_CAPACITY"])
        except (KeyError, ValueError):
            percent = None
        name = (info.get("POWER_SUPPLY_MODEL_NAME") or info.get("POWER_SUPPLY_NAME")
                or entry.name).strip()
        status = info.get("POWER_SUPPLY_STATUS", "")
        kind = _kind_from_name(name)
        if not kind and entry.name.startswith("hidpp_battery"):
            # Logitech's receivers carry mice and keyboards; the name tells which
            # only sometimes ("PRO X 2" is a mouse).
            kind = "mouse"
        # hidpp_battery_N is renumbered when the receiver comes back (resume,
        # re-plug); the serial number stays, so warnings are not repeated.
        ident = (info.get("POWER_SUPPLY_SERIAL_NUMBER") or "").strip() or entry.name
        found.append(Device(
            key=f"sys:{ident}", name=name, kind=kind, percent=percent,
            charging=status == "Charging",
            # A Logitech device that went off or to sleep: the driver keeps the
            # last capacity and sets online=0, status=Unknown.
            asleep=info.get("POWER_SUPPLY_ONLINE") == "0" and status in ("", "Unknown")))
    return found


def _value(prop: object) -> object:
    return prop.get("data") if isinstance(prop, dict) else None


def from_bluez(run: Runner) -> list[Device]:
    # --auto-start=no: a Bluetooth service the person stopped stays stopped.
    code, out, _err = run(["busctl", "--system", "--auto-start=no", "--json=short",
                           "call", "org.bluez", "/",
                           "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"])
    if code != 0:
        return []
    try:
        objects = json.loads(out)["data"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return []
    if not isinstance(objects, dict):
        return []
    found: list[Device] = []
    for _path, interfaces in sorted(objects.items()):
        if not isinstance(interfaces, dict):
            continue
        battery = interfaces.get("org.bluez.Battery1")
        device = interfaces.get("org.bluez.Device1")
        if not isinstance(battery, dict) or not isinstance(device, dict):
            continue
        percent = _value(battery.get("Percentage"))
        if isinstance(percent, bool) or not isinstance(percent, int):
            continue
        name = str(_value(device.get("Alias")) or _value(device.get("Name")) or "Bluetooth")
        icon = str(_value(device.get("Icon")) or "")
        kind = {"input-mouse": "mouse", "input-keyboard": "keyboard",
                "audio-headphones": "headphones", "audio-headset": "headphones",
                }.get(icon) or _kind_from_name(name)
        address = str(_value(device.get("Address")) or name)
        found.append(Device(key=f"bt:{address}", name=name, kind=kind,
                            percent=max(0, min(100, percent))))
    return found


def unreadable(base: Path = SYS_HID) -> list[Device]:
    found: dict[tuple[str, str], Device] = {}
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        # HID_ID=0003:0000046D:00000ACB -> bus 3 is USB.
        parts = _uevent(entry / "uevent").get("HID_ID", "").split(":")
        if len(parts) != 3 or parts[0] != "0003":
            continue
        ids = (parts[1][-4:].upper(), parts[2][-4:].upper())
        if ids in UNREADABLE and ids not in found:
            found[ids] = Device(key=f"usb:{ids[0]}:{ids[1]}".lower(),
                                name=UNREADABLE[ids], kind="headphones")
    return list(found.values())


def probe(run: Runner | None = None, power_base: Path = SYS_POWER,
          hid_base: Path = SYS_HID) -> list[Device]:
    devices = from_sysfs(power_base)
    known = {d.name.casefold() for d in devices}
    for device in from_bluez(run or _run):
        if device.name.casefold() not in known:
            devices.append(device)
            known.add(device.name.casefold())
    for device in unreadable(hid_base):
        if device.name.casefold() not in known:
            devices.append(device)
    return devices


# ---- low charge warnings ------------------------------------------------------

LEVELS = (20, 5)  # warn when the charge first drops to these
RESET_ABOVE = 25  # charged back above this -> warn again next time


class Alerts:
    """Which warnings to send; remembers per device what was already said."""

    def __init__(self, levels: tuple[int, ...] = LEVELS) -> None:
        self.levels = tuple(sorted(levels, reverse=True))
        self.said: dict[str, int] = {}  # device key -> lowest level warned about

    def check(self, devices: list[Device]) -> list[tuple[Device, int]]:
        due: list[tuple[Device, int]] = []
        for device in devices:
            if device.percent is None or device.asleep:
                continue  # asleep: the number may be old (charged meanwhile)
            if device.charging or device.percent > RESET_ABOVE:
                self.said.pop(device.key, None)
                continue
            reached = [lvl for lvl in self.levels if device.percent <= lvl]
            if not reached:
                continue
            level = reached[-1]  # the lowest one reached: one message, not two
            if level < self.said.get(device.key, 101):
                self.said[device.key] = level
                due.append((device, level))
        return due

    def forget(self, device: Device) -> None:
        """The warning could not be shown: try again on the next check."""
        self.said.pop(device.key, None)
