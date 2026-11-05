"""screen-sleep: idle timings, the night filter and "stay awake". No GTK.

Everything goes through the live screen-sleep modules (common, idle, night),
loaded by file path (see loader.py). Nothing is kept in memory: every read is a
fresh load_config(), every write is

    fresh load_config() -> set the changed fields -> save_config()

and, if an idle field of the profile for the current power source changed,
idle.apply_profile() for that profile (re-checking current_power() right
before, since the power source may change while the job waits).

All writes of config.json and all hypridle restarts run on ONE worker thread
("screen-sleep"), in submission order, so two writers never race for the file
and two apply_profile() calls never overlap. The apply job is coalesced: N
writes queued in a row are followed by one restart.

load_config() creates config.json when it is missing, through a lazy import
that does not work for modules loaded under private names; so nothing here
calls it unless config.json exists. The page then offers the old window, which
creates the file the way it always did.

"Stay awake" (caffeine) never runs in this process: idle.caffeine_set() starts
systemd-inhibit as a child of the caller, and a resident process would collect
zombies. A short helper process does it instead (helpers/caffeine.py).

Keys used in History are config paths: "idle.battery.dim" (value
{"enabled", "minutes"}), "night.target_temp", "night.on_hour", ... plus
"night.current_temp" (backend "night", the temperature on screen right now)
and "caffeine" (backend "caffeine").
"""

from __future__ import annotations

import itertools
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import loader
from ..workers import Dispatch, Workers, glib_dispatch

log = logging.getLogger(__name__)

BACKEND = "screen-sleep"  # config.json fields
NIGHT = "night"  # the temperature on screen
CAFFEINE = "caffeine"
TEMP_KEY = "night.current_temp"
CAFFEINE_KEY = "caffeine"

CONFIG_WORKER = "screen-sleep"  # every config write and every hypridle restart
NIGHT_WORKER = "night"
CAFFEINE_WORKER = "caffeine"
PROBE_WORKER = "screen-sleep-probe"

HELPER = Path(__file__).resolve().parent.parent / "helpers" / "caffeine.py"
HELPER_TIMEOUT_S = 10


class NotConfigured(Exception):
    """config.json does not exist (and must not be created by us)."""


def get_path(cfg: dict, path: str) -> Any:
    node: Any = cfg
    for part in path.split("."):
        node = node[part]
    return node


def set_path(cfg: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node[part]
    if parts[-1] not in node:
        raise KeyError(path)
    node[parts[-1]] = value


def idle_profiles(paths) -> set[str]:
    """Profiles ("ac", "battery") touched by these config paths."""
    return {p.split(".")[1] for p in paths if p.startswith("idle.")}


def out_of_order(profile: dict, steps) -> bool:
    """True if the enabled steps do not go up in time (dim before lock ...)."""
    enabled = [profile[s]["minutes"] for s in steps if profile[s]["enabled"]]
    return any(a > b for a, b in zip(enabled, enabled[1:], strict=False))


@dataclass
class WriteResult:
    values: dict[str, Any]  # path -> value written
    before: dict[str, Any]  # path -> value found by the fresh read
    config: dict  # the config as saved
    origin: str


@dataclass
class ApplyResult:
    power: str  # the power source at apply time
    applied: bool  # False: the changed profile is not the active one
    ok: bool
    message: str
    out_of_order: bool = False


@dataclass
class Probe:
    """What is running right now (read off the GTK thread)."""

    power: str = ""
    temperature: int | None = None
    hyprsunset: tuple[bool, str] = (False, "")
    hypridle: bool = False
    daemon: tuple[bool, str] = (False, "")
    caffeine: bool = False
    errors: list[str] = field(default_factory=list)


class Backend:
    def __init__(self, workers: Workers, directory: Path | str | None = None,
                 dispatch: Dispatch | None = None, python: str | None = None) -> None:
        self.workers = workers
        self.directory = Path(directory) if directory else loader.screen_sleep_dir()
        self._dispatch = dispatch or glib_dispatch
        self.python = python or sys.executable or "python3"
        self._modules: loader.ScreenSleep | None = None
        self._lock = threading.Lock()
        self._apply_profiles: set[str] = set()
        self._write_ids = itertools.count()
        # Called on the GTK thread: on_applied(ApplyResult) after a hypridle
        # apply; on_external(keys) after History changed values.
        self.on_applied: list[Callable[[ApplyResult], None]] = []
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- modules and state ------------------------------------------------

    @property
    def ss(self) -> loader.ScreenSleep:
        with self._lock:
            if self._modules is None:
                self._modules = loader.load_screen_sleep(self.directory)
            return self._modules

    def state(self) -> tuple[str, str]:
        """("ok", ""), ("missing", "") without config.json, ("error", why)."""
        try:
            ss = self.ss
        except loader.LoadError as exc:
            return "error", str(exc)
        return ("ok", "") if ss.config_exists() else ("missing", "")

    def old_window(self) -> Path | None:
        gui = self.directory / "gui.py"
        return gui if gui.is_file() else None

    # ---- reading ----------------------------------------------------------

    def read_config(self) -> dict:
        ss = self.ss
        if not ss.config_exists():
            raise NotConfigured(str(ss.common.CONFIG_FILE))
        return ss.common.load_config()

    def read(self, paths) -> dict[str, Any]:
        cfg = self.read_config()
        return {p: get_path(cfg, p) for p in paths}

    def probe(self, on_done: Callable[[Probe], None]) -> None:
        """Gather the status lines on a worker; on_done runs on the GTK thread."""

        def job() -> Probe:
            ss = self.ss
            out = Probe()
            for name, fn in (
                ("power", ss.idle.current_power),
                ("temperature", ss.night.read_temperature),
                ("hyprsunset", ss.night.check_hyprsunset_alive),
                ("hypridle", ss.idle.hypridle_running),
                ("daemon", ss.night.check_daemon_alive),
                ("caffeine", ss.idle.caffeine_active),
            ):
                try:
                    setattr(out, name, fn())
                except Exception as exc:  # one broken check must not hide the rest
                    out.errors.append(f"{name}: {exc}")
            return out

        def done(result, error) -> None:
            if error is None:
                on_done(result)
            else:
                log.warning("probe: %s", error)

        self.workers.submit(PROBE_WORKER, job, done, key="probe")

    def scheduled_temperature(self, night: dict, now: datetime | None = None) -> int:
        now = now or datetime.now()
        minutes = now.hour * 60 + now.minute + now.second / 60
        return int(self.ss.night.compute_target_temperature(minutes, night))

    # ---- writing ----------------------------------------------------------

    def write(self, values: dict[str, Any], origin: str = "page") -> WriteResult:
        """Fresh read -> set these fields -> save. Runs on the config worker."""
        ss = self.ss
        if not ss.config_exists():
            raise NotConfigured(str(ss.common.CONFIG_FILE))
        cfg = ss.common.load_config()
        before = {p: get_path(cfg, p) for p in values}
        for path, value in values.items():
            set_path(cfg, path, value)
        ss.common.save_config(cfg)
        return WriteResult(dict(values), before, cfg, origin)

    def queue_write(self, values: dict[str, Any],
                    on_done: Callable[[WriteResult | None, BaseException | None], None]
                    | None = None, origin: str = "page") -> None:
        """Write on the config worker; then apply hypridle if an idle field changed."""
        values = dict(values)
        key = ("write", next(self._write_ids))  # writes are never coalesced
        self.workers.submit(CONFIG_WORKER, lambda: self.write(values, origin), on_done, key=key)
        profiles = idle_profiles(values)
        if profiles:
            self.schedule_apply(profiles)

    def schedule_apply(self, profiles) -> None:
        with self._lock:
            self._apply_profiles |= set(profiles)
        # Same key: re-submitting moves the one apply job behind the newest write.
        self.workers.submit(CONFIG_WORKER, self._apply_job, self._applied, key="apply")

    def _apply_job(self) -> ApplyResult:
        with self._lock:
            profiles, self._apply_profiles = self._apply_profiles, set()
        ss = self.ss
        power = ss.idle.current_power()  # asked again: it may have changed meanwhile
        if power not in profiles:
            return ApplyResult(power, applied=False, ok=True, message="")
        cfg = self.read_config()
        ok, message = ss.idle.apply_profile(cfg, power)
        return ApplyResult(power, True, ok, message,
                           out_of_order(cfg["idle"][power], ss.common.STEPS))

    def _applied(self, result: ApplyResult | None, error: BaseException | None) -> None:
        if error is not None:
            result = ApplyResult("", True, False, str(error) or type(error).__name__)
        for fn in list(self.on_applied):
            fn(result)

    # ---- night filter -----------------------------------------------------

    def apply_temperature(self, kelvin: int) -> tuple[bool, str]:
        return self.ss.night.apply_temperature(int(kelvin))

    def queue_temperature(self, kelvin: int,
                          on_done: Callable[[Any, BaseException | None], None] | None = None
                          ) -> None:
        """Live preview while the slider moves: only the newest value matters."""
        self.workers.submit(NIGHT_WORKER, lambda: self.apply_temperature(kelvin), on_done,
                            key="temp")

    # ---- stay awake -------------------------------------------------------

    def caffeine_argv(self, enabled: bool) -> list[str]:
        return [self.python, "-I", str(HELPER), "on" if enabled else "off",
                "--dir", str(self.directory)]

    def set_caffeine(self, enabled: bool) -> tuple[bool, str]:
        """Run the helper (blocking: call it on a worker)."""
        try:
            run = subprocess.run(self.caffeine_argv(enabled), capture_output=True, text=True,
                                 timeout=HELPER_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if run.returncode != 0:
            return False, (run.stderr.strip().splitlines() or [f"exit {run.returncode}"])[-1]
        return True, ""

    def queue_caffeine(self, enabled: bool,
                       on_done: Callable[[Any, BaseException | None], None] | None = None
                       ) -> None:
        def job() -> tuple[bool, str, bool]:
            ok, message = self.set_caffeine(enabled)
            return ok, message, bool(self.ss.idle.caffeine_active())

        self.workers.submit(CAFFEINE_WORKER, job, on_done, key="caffeine")

    # ---- notifications ----------------------------------------------------

    def notify_external(self, keys: set[str]) -> None:
        def call() -> None:
            for fn in list(self.on_external):
                fn(set(keys))

        self._dispatch(call)


# ---- History appliers -------------------------------------------------------

class ConfigApplier:
    """History backend "screen-sleep": fields of config.json."""

    queued = True  # apply() only queues the write; a read right after sees the old file

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        # One write and (if needed) one hypridle restart for the whole batch.
        self.backend.read_config()  # fails now, not later, when not configured
        keys = set(values)

        def done(_result, error) -> None:
            if error is not None:
                log.warning("history write: %s", error)
            self.backend.notify_external(keys)

        self.backend.queue_write(values, done, origin="history")


class NightApplier:
    """History backend "night": the temperature on screen."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return {k: self.backend.ss.night.read_temperature() for k in keys}

    def apply(self, values: dict[str, Any]) -> None:
        kelvin = values.get(TEMP_KEY)
        if kelvin is None:
            return
        ok, message = self.backend.apply_temperature(kelvin)
        if not ok:
            raise RuntimeError(message)
        self.backend.notify_external({TEMP_KEY})


class CaffeineApplier:
    """History backend "caffeine": the stay-awake switch."""

    queued = True  # like ConfigApplier: a read right after apply() is too early

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return {k: bool(self.backend.ss.idle.caffeine_active()) for k in keys}

    def apply(self, values: dict[str, Any]) -> None:
        if CAFFEINE_KEY not in values:
            return
        self.backend.queue_caffeine(
            bool(values[CAFFEINE_KEY]),
            lambda *_: self.backend.notify_external({CAFFEINE_KEY}))


def register(history, backend: Backend) -> None:
    history.register(BACKEND, ConfigApplier(backend))
    history.register(NIGHT, NightApplier(backend))
    history.register(CAFFEINE, CaffeineApplier(backend))
