"""Battery, power profile and screen brightness. No GTK.

Values come from /sys (capacity, status, charge, current, voltage, cycles),
`powerprofilesctl get|set|list` and `brightnessctl get|max|set`. A missing
battery or program leaves the field empty instead of failing the page.

History: "power.profile" (a profile id) and "power.brightness" (percent).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workers import Workers

log = logging.getLogger(__name__)

BACKEND = "power"
WORKER = "power"
READ_WORKER = "power-read"
PROFILE_KEY = "power.profile"
BRIGHTNESS_KEY = "power.brightness"
PROFILES = ("performance", "balanced", "power-saver")
TIMEOUT_S = 5

Result = tuple[int, str, str]
Runner = Callable[[list[str]], Result]


def _run(argv: list[str]) -> Result:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass
class Power:
    battery: str = ""  # the /sys directory used, empty when there is no battery
    charge: int | None = None  # percent
    status: str = ""  # "Full", "Discharging", ...
    energy_wh: float | None = None
    full_wh: float | None = None
    design_wh: float | None = None
    cycles: int | None = None
    ac_online: bool | None = None
    profile: str = ""
    profiles: list[str] = field(default_factory=list)
    brightness: int | None = None  # percent
    brightness_max: int | None = None


def _battery_dir() -> Path | None:
    base = Path("/sys/class/power_supply")
    try:
        for entry in sorted(base.iterdir()):
            if entry.name.startswith("BAT") and (entry / "capacity").exists():
                return entry
    except OSError:
        return None
    return None


def _ac_online() -> bool | None:
    base = Path("/sys/class/power_supply")
    try:
        for entry in sorted(base.iterdir()):
            if entry.name.startswith(("AC", "ADP")) and (entry / "online").exists():
                return (entry / "online").read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return None
    return None


def _number(path: Path) -> float | None:
    text = _read(str(path))
    try:
        return float(text)
    except ValueError:
        return None


def _profiles(run: Runner) -> list[str]:
    code, out, _err = run(["powerprofilesctl", "list"])
    found: list[str] = []
    if code == 0:
        for line in out.splitlines():
            name = line.strip().lstrip("* ").split(":", 1)[0].strip()
            if name in PROFILES:
                found.append(name)
    return found or list(PROFILES)


def probe(run: Runner | None = None) -> Power:
    run = run or _run
    info = Power()
    battery = _battery_dir()
    if battery is not None:
        info.battery = battery.name
        capacity = _number(battery / "capacity")
        info.charge = int(capacity) if capacity is not None else None
        info.status = _read(battery / "status")
        cycles = _number(battery / "cycle_count")
        info.cycles = int(cycles) if cycles else None
        # Energy is in µWh on some machines, charge (µAh) and voltage (µV) on
        # others; both are shown as Wh so the numbers can be compared.
        energy = _number(battery / "energy_now")
        full = _number(battery / "energy_full")
        design = _number(battery / "energy_full_design")
        if energy is None:
            charge_now = _number(battery / "charge_now")
            charge_full = _number(battery / "charge_full")
            charge_design = _number(battery / "charge_full_design")
            voltage = _number(battery / "voltage_now")
            if charge_now is not None and voltage:
                energy = charge_now * voltage / 1e6
            if charge_full is not None and voltage:
                full = charge_full * voltage / 1e6
            if charge_design is not None and voltage:
                design = charge_design * voltage / 1e6
            if info.charge is None and charge_full and charge_now is not None:
                info.charge = int(round(charge_now / charge_full * 100))
        def wh(value: float | None) -> float | None:
            return round(value / 1e6, 2) if value and value > 1e4 else (
                round(value, 2) if value else None)
        info.energy_wh = wh(energy)
        info.full_wh = wh(full)
        info.design_wh = wh(design)
    info.ac_online = _ac_online()
    code, out, _err = run(["powerprofilesctl", "get"])
    if code == 0:
        info.profile = out.strip()
    info.profiles = _profiles(run)
    code, out, _err = run(["brightnessctl", "get"])
    code_max, out_max, _err_max = run(["brightnessctl", "max"])
    try:
        current = int(out.strip()) if code == 0 else None
        maximum = int(out_max.strip()) if code_max == 0 else None
    except ValueError:
        current = maximum = None
    if current is not None and maximum:
        info.brightness = int(round(current / maximum * 100))
        info.brightness_max = maximum
    return info


class Backend:
    def __init__(self, workers: Workers, runner: Runner | None = None) -> None:
        self.workers = workers
        self.run = runner or _run

    def queue_probe(self, on_done: Callable[[Power, BaseException | None], None]) -> None:
        self.workers.submit(READ_WORKER, lambda: probe(self.run), on_done)

    # ---- changes ---------------------------------------------------------

    def set_profile(self, profile: str) -> tuple[bool, str]:
        if profile not in PROFILES:
            return False, f"unknown profile {profile}"
        return self._ok(["powerprofilesctl", "set", profile])

    def set_brightness(self, percent: int) -> tuple[bool, str]:
        percent = max(1, min(100, int(percent)))
        return self._ok(["brightnessctl", "set", f"{percent}%"])

    def _ok(self, argv: list[str]) -> tuple[bool, str]:
        code, out, err = self.run(argv)
        text = (out + err).strip()
        return code == 0, "" if code == 0 else (text or f"exit {code}")

    # ---- History's view --------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        info = probe(self.run)
        out: dict[str, Any] = {}
        for key in keys:
            value = {PROFILE_KEY: info.profile,
                     BRIGHTNESS_KEY: info.brightness}.get(key)
            if value not in (None, ""):
                out[key] = value
        return out

    def apply(self, values: dict[str, Any]) -> None:
        errors: list[str] = []
        for key, value in values.items():
            if key == PROFILE_KEY:
                ok, message = self.set_profile(str(value))
            elif key == BRIGHTNESS_KEY:
                ok, message = self.set_brightness(int(value))
            else:
                continue
            if not ok:
                errors.append(f"{key}: {message}")
        if errors:
            raise RuntimeError("; ".join(errors))


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend


def _env() -> dict[str, str]:
    return dict(os.environ)


def available() -> bool:
    return shutil.which("brightnessctl") is not None or shutil.which("powerprofilesctl") is not None
