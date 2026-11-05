"""Read-only information about this machine. No GTK, no History, no changes.

Every value comes from a file or a short command that is already on the
system; a missing program or file is not an error, it just leaves the field
out. The page shows the numbers, strings.py spells them out in Russian.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT_S = 5


def _run(argv: list[str], timeout: float = TIMEOUT_S) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _read(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _os_name() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _model() -> str:
    vendor = _read("/sys/devices/virtual/dmi/id/sys_vendor")
    product = _read("/sys/devices/virtual/dmi/id/product_name")
    parts = [p for p in (vendor, product) if p and p.lower() != "system product name"]
    return " ".join(parts)


def _cpu() -> tuple[str, int]:
    for line in _read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip(), os.cpu_count() or 0
    return "", os.cpu_count() or 0


def _memory() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree") and parts:
            values[key] = int(parts[0])  # kB
    return values


def _disk() -> dict[str, int]:
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return {}
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def _uptime() -> int:
    try:
        return int(float(_read("/proc/uptime").split()[0]))
    except (OSError, ValueError, IndexError):
        return 0


def _temperature() -> float | None:
    best: float | None = None
    base = Path("/sys/class/thermal")
    try:
        zones = sorted(base.glob("thermal_zone*"))
    except OSError:
        return None
    for zone in zones:
        try:
            raw = int((zone / "temp").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        celsius = raw / 1000 if raw > 1000 else raw / 10 if raw > 200 else raw
        if best is None or celsius > best:
            best = celsius
    return best


def _hyprland() -> str:
    version = _run(["hyprctl", "version"], timeout=2)
    first = version.splitlines()[0] if version else ""
    if first.startswith("Hyprland "):
        return first.split(" built", 1)[0].strip()
    return ""


def _failed_units() -> list[str]:
    out: list[str] = []
    for scope in ([], ["--user"]):
        text = _run(["systemctl", *scope, "--failed", "--no-legend", "--plain"])
        for line in text.splitlines():
            parts = line.split()
            if parts:
                out.append(parts[0])
    return out


def _updates() -> int | None:
    """Pending package updates (pacman's local database, a fast command)."""
    if not shutil.which("pacman"):
        return None
    try:
        done = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True,
                              timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode not in (0, 1):  # 1 = nothing to do is normal
        return None
    return len([line for line in done.stdout.splitlines() if line.strip()])


@dataclass
class Info:
    """What the System page shows; empty values mean "unknown"."""

    model: str = ""
    os_name: str = ""
    kernel: str = ""
    hyprland: str = ""
    cpu: str = ""
    cores: int = 0
    hostname: str = ""
    session: str = ""
    uptime_s: int = 0
    memory: dict[str, int] = field(default_factory=dict)
    disk: dict[str, int] = field(default_factory=dict)
    temperature_c: float | None = None
    failed_units: list[str] = field(default_factory=list)
    updates: int | None = None


def probe() -> Info:
    cpu, cores = _cpu()
    return Info(
        model=_model(),
        os_name=_os_name(),
        kernel=os.uname().release,
        hyprland=_hyprland(),
        cpu=cpu,
        cores=cores,
        hostname=socket.gethostname(),
        session=os.environ.get("XDG_CURRENT_DESKTOP", "") or os.environ.get(
            "XDG_SESSION_DESKTOP", ""),
        uptime_s=_uptime(),
        memory=_memory(),
        disk=_disk(),
        temperature_c=_temperature(),
        failed_units=_failed_units(),
        updates=_updates(),
    )
