"""Run the window inside the user's systemd manager, not in a bare cgroup.

Hyprland, started by SDDM here, sits in the root cgroup, and so does everything
it starts (exec-once, binds). logind and polkit cannot tell which login such a
process belongs to, so they refuse it: brightnessctl fails ("Invalid request
descriptor") and NetworkManager will not let it switch Wi-Fi. The user manager
is asked to put this very process (same PID, nothing re-executed) into a
transient scope under user@.service, where both work, the way a terminal's
programs do. Whatever goes wrong there, the window starts as before.

No GTK here.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Mapping

log = logging.getLogger(__name__)

TIMEOUT_S = 3  # a hung user manager must not hold up the window


def cgroup_path(text: str) -> str:
    """The unified (cgroup v2) path from /proc/self/cgroup."""
    for line in text.splitlines():
        if line.startswith("0::"):
            return line[3:].strip()
    return ""


def needs_scope(environ: Mapping[str, str], cgroup: str) -> bool:
    """Only in a Hyprland session, only from outside a login or the user manager."""
    if not environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return False
    return "/user@" not in cgroup and "/session-" not in cgroup


def scope_call(pid: int) -> list[str]:
    """StartTransientUnit for one PID, the call systemd-run --scope makes."""
    return ["busctl", "--user", f"--timeout={TIMEOUT_S - 1}", "call",
            "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
            f"settings-hub-{pid}.scope", "fail", "3",
            "PIDs", "au", "1", str(pid),
            "Description", "s", "Settings (settings-hub)",
            "CollectMode", "s", "inactive-or-failed",
            "0"]


def _read_cgroup() -> str:
    try:
        with open("/proc/self/cgroup", encoding="utf-8") as f:
            return cgroup_path(f.read())
    except OSError:
        return ""


def move_into_scope() -> bool:
    """Ask for the scope; True if this process ended up in the user manager."""
    if not needs_scope(os.environ, _read_cgroup()) or not shutil.which("busctl"):
        return False
    try:
        done = subprocess.run(scope_call(os.getpid()), capture_output=True, text=True,
                              timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("no scope for the window: %s", exc)
        return False
    if done.returncode != 0:
        log.warning("no scope for the window: %s", (done.stderr or done.stdout).strip())
        return False
    return "/user@" in _read_cgroup()
