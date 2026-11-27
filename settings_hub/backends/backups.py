"""Backups: how the backup-manager (BorgBackup) copies are doing, and "back up now".

Read without root, the way backup-manager's own panel module does:

    /var/lib/backup-manager/status.json   written by `bm` after every run (644)
    /var/lib/backup-manager/archives.txt  "name<TAB>start" per copy, newest first (644)
    systemctl show bm-*.service / bm-*.timer   running? failed? next run?

"Back up now" starts the same system unit the nightly timer starts
(`systemctl start --no-block bm-backup.service`, or bm-full for a full copy):
the unit's own waiting for the network, lock and failure notification all
apply. systemd asks for the password through the polkit agent; nothing here
runs as root, and nothing is restored or deleted.

No GTK.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

BACKEND = WORKER = "backups"
STATE_DIR = Path("/var/lib/backup-manager")
SYSTEMCTL = "/usr/bin/systemctl"  # not looked up in PATH: the click asks for a password
UNITS = {"backup": "bm-backup", "full": "bm-full", "check": "bm-check", "drill": "bm-drill"}
STARTABLE = ("backup", "full")
STALE = timedelta(hours=36)  # a nightly copy older than this: say so
CHECK_OLD = timedelta(days=21)  # as backup-manager's panel module
MAX_ARCHIVES = 50


@dataclass(frozen=True)
class Archive:
    name: str
    start: datetime | None  # local time
    full: bool  # a full copy (bm-full-…), else a nightly one


@dataclass(frozen=True)
class Info:
    configured: bool  # status.json is there, or the backup unit is installed
    status: str = "ok"  # status.json: "ok", "missing" (no copy yet) or "unreadable"
    last: datetime | None = None  # local start time of the newest copy
    size: str = ""  # as bm wrote it, "32,9 GB"
    added: str = ""
    repo: str = ""
    count: int = 0
    checked: datetime | None = None
    drilled: datetime | None = None
    next_backup: datetime | None = None
    next_full: datetime | None = None
    running: tuple[str, ...] = ()  # kinds whose unit is starting or running
    failed: tuple[str, ...] = ()  # kinds whose last run failed
    skipped: tuple[str, ...] = ()  # kinds whose last start was skipped by a unit condition
    skipped_at: dict = field(default_factory=dict)  # kind -> when it was skipped (local)
    archives: tuple[Archive, ...] = ()
    stale: bool = False  # the newest copy is older than STALE
    units: bool = True  # systemctl answered
    schedule_off: bool = False  # the nightly timer is not active
    check_old: bool = False  # the copies were last checked long ago, or never


def parse_time(text: object) -> datetime | None:
    """bm's times as local naive datetimes: "…Z" is UTC, a bare one is local already."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def _unix(value: str) -> datetime | None:
    """systemctl --timestamp=unix: "@1764296783" (or "" / "n/a")."""
    value = value.strip()
    if not value.startswith("@"):
        return None
    try:
        return datetime.fromtimestamp(int(value[1:].split(".")[0]))
    except (ValueError, OverflowError, OSError):
        return None


def parse_show(text: str) -> list[dict[str, str]]:
    """`systemctl show A B …` output: one dict per unit (blank line between)."""
    out: list[dict[str, str]] = [{}]
    for line in text.splitlines():
        if not line.strip():
            if out[-1]:
                out.append({})
            continue
        key, _, value = line.partition("=")
        out[-1][key] = value
    return [d for d in out if d]


def read_archives(text: str) -> tuple[Archive, ...]:
    out = []
    for line in text.splitlines()[:MAX_ARCHIVES]:
        name, _, start = line.partition("\t")
        name = name.strip()
        if name:
            out.append(Archive(name, parse_time(start), name.startswith("bm-full")))
    return tuple(out)


@dataclass
class Backend:
    workers: object
    state_dir: Path = STATE_DIR
    run: Callable[..., subprocess.CompletedProcess] = field(default=subprocess.run)
    now: Callable[[], datetime] = field(default=datetime.now)
    systemctl: str = SYSTEMCTL

    def _systemctl_show(self) -> list[dict[str, str]] | None:
        names = [f"{u}.service" for u in UNITS.values()] + \
                [f"{UNITS[k]}.timer" for k in STARTABLE]
        try:
            done = self.run([self.systemctl, "show", "--timestamp=unix", "-p",
                             "Id,LoadState,ActiveState,Result,Job,ConditionResult,"
                             "ConditionTimestamp,NextElapseUSecRealtime", *names],
                            capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("systemctl show failed: %s", exc)
            return None
        if done.returncode != 0:
            return None
        return parse_show(done.stdout)

    def probe(self) -> Info:
        status: dict = {}
        state = "ok"
        try:
            status = json.loads((self.state_dir / "status.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            state = "missing"
        except (OSError, ValueError) as exc:
            log.warning("status.json: %s", exc)
            state = "unreadable"
        if not isinstance(status, dict):
            status, state = {}, "unreadable"
        try:
            archives = read_archives((self.state_dir / "archives.txt").read_text(
                encoding="utf-8", errors="replace"))
        except OSError:
            archives = ()
        units = self._systemctl_show()
        by_id = {u.get("Id", ""): u for u in units or []}
        installed = by_id.get("bm-backup.service", {}).get("LoadState") == "loaded"
        if state == "missing" and not installed and units is not None:
            return Info(configured=False, status=state, units=units is not None)
        running, failed, skipped, skipped_at = [], [], [], {}
        for kind, unit in UNITS.items():
            unit_state = by_id.get(f"{unit}.service", {})
            # "no" with no time: never started since boot; with a time: started and skipped
            when = _unix(unit_state.get("ConditionTimestamp", ""))
            if unit_state.get("ConditionResult") == "no" and when is not None:
                skipped.append(kind)
                skipped_at[kind] = when
            active = unit_state.get("ActiveState") in ("activating", "active", "reloading",
                                                       "deactivating")
            if active or unit_state.get("Job", "") not in ("", "0"):  # queued counts too
                running.append(kind)
            elif unit_state.get("ActiveState") == "failed" or \
                    unit_state.get("Result", "success") not in ("success", ""):
                failed.append(kind)
        timers = [by_id.get(f"{UNITS[k]}.timer", {}) for k in STARTABLE]
        last = parse_time(status.get("start"))
        checked = parse_time(status.get("checked"))
        count = status.get("count")
        return Info(
            configured=True, status=state, last=last,
            size=_text(status.get("size")), added=_text(status.get("added")),
            repo=_text(status.get("repo")),
            count=count if isinstance(count, int) and not isinstance(count, bool) else 0,
            checked=checked, drilled=parse_time(status.get("drilled")),
            next_backup=_unix(by_id.get("bm-backup.timer", {}).get("NextElapseUSecRealtime", "")),
            next_full=_unix(by_id.get("bm-full.timer", {}).get("NextElapseUSecRealtime", "")),
            running=tuple(running), failed=tuple(failed), skipped=tuple(skipped),
            skipped_at=skipped_at,
            archives=archives,
            check_old=state == "ok" and (checked is None or self.now() - checked > CHECK_OLD),
            stale=state == "ok" and (last is None or self.now() - last > STALE),
            units=units is not None,
            schedule_off=units is not None and any(t.get("ActiveState") != "active"
                                                   for t in timers))

    def start(self, kind: str) -> None:
        """Start a copy now; PermissionError when the password was not given."""
        if kind not in STARTABLE:
            raise ValueError(f"cannot start {kind!r}")
        unit = f"{UNITS[kind]}.service"
        # --no-block: only the start is waited for (and the password asked);
        # the copy itself runs as the unit, minutes long.
        try:
            done = self.run([self.systemctl, "start", "--no-block", unit],
                            capture_output=True, text=True, timeout=180, check=False)
        except subprocess.TimeoutExpired as exc:  # the password dialog left unanswered
            raise TimeoutError(str(exc)) from exc
        if done.returncode == 0:
            log.info("started %s", unit)
            return
        said = (done.stderr or "").strip().splitlines()
        reason = said[-1] if said else f"exit {done.returncode}"
        if "interactive authentication" in reason.lower():
            raise NoAgent(reason)  # nothing on screen could ask for the password
        if "access denied" in reason.lower():
            raise PermissionError(reason)
        raise RuntimeError(reason)


class NoAgent(PermissionError):
    """No polkit agent is running to ask for the password."""


def _text(value: object) -> str:
    return value.strip()[:40] if isinstance(value, str) else ""
