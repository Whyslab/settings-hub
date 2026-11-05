"""The "Screen and sleep" page logic. No GTK.

Fields (the page's unit of editing; History keys are config paths):

    idle.<ac|battery>.<step>   {"enabled": bool, "minutes": 1..600}
    night.target_temp          2000..6500, step 100
    night.on, night.off        [hour, minute] (on_hour/on_minute in config.json)
    night.manual_override      bool; the "On schedule" switch shows its negation
    night.current_temp         the temperature on screen (not in config.json)
    caffeine                   "stay awake"

Rules:

* Changes apply at once, like macOS: a timing or a night setting is written
  1.5 s after the last change (one write = one History group). A preset is
  written immediately as one group of the four steps.
* The slider applies the temperature live 120 ms after each change. A series
  of moves ends when the value has been still for 600 ms, the mouse button is
  released, or the slider loses focus, whichever is first; then
  manual_override is saved and the series is logged as ONE group
  (temperature + manual_override). Moving the slider turns "On schedule" off.
* Turning "On schedule" on clears manual_override (like the old window's Save)
  and sets the scheduled temperature right away.
* The page re-reads its sources when shown and every 5 s while visible, but a
  re-read never overwrites a field that has a queued write, has focus, or was
  changed in the last 10 s (the old window's rule for its slider).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from .. import strings
from ..backends import screen_sleep as ss_backend
from ..backends.screen_sleep import (
    BACKEND,
    CAFFEINE,
    CAFFEINE_KEY,
    NIGHT,
    TEMP_KEY,
    ApplyResult,
    Probe,
    WriteResult,
    idle_profiles,
    out_of_order,
)

DEBOUNCE_MS = 1500
TEMP_LIVE_MS = 120
SERIES_STILL_MS = 600
REFRESH_MS = 5000
GUARD_S = 10.0

# Limits of screen-sleep (common.py); a test checks they match the live module.
MIN_TEMP, MAX_TEMP, SLEEP_MARK_TEMP = 2000, 6500, 2700
TARGET_STEP = 100
SLIDER_STEP = 50
MIN_MINUTES, MAX_MINUTES = 1, 600
RAMP_STEP, RAMP_INTERVAL_MIN = 500, 15
PROFILES = ("ac", "battery")
STEPS = ("dim", "lock", "dpms", "suspend")
TIMES = ("on", "off")
OVERRIDE = "night.manual_override"
TARGET = "night.target_temp"

# Widget ids of the page. pages/screen_sleep.py registers a widget under each
# of them; the README table maps the old window's abilities onto them.
WIDGETS: tuple[str, ...] = (
    "status.power", "status.hyprsunset", "status.hypridle", "status.daemon",
    "caffeine.switch",
    *(f"idle.{p}.{s}.{w}" for p in PROFILES for s in STEPS for w in ("enabled", "minutes")),
    *(f"idle.{p}.preset.{name}" for p in PROFILES for name in strings.SS_PRESETS),
    *(f"idle.{p}.order-warning" for p in PROFILES),
    "night.slider", "night.value", "night.schedule", "night.target",
    "night.on.hour", "night.on.minute", "night.off.hour", "night.off.minute", "night.off-now",
    "setup.notice", "setup.open-old",
)

# What the old window (screen-sleep gui.py) could do -> where it is now.
OLD_WINDOW: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "two sets of idle timings, AC and battery, four steps each: on/off + minutes 1-600",
     tuple(f"idle.{p}.{s}.{w}" for p in PROFILES for s in STEPS for w in ("enabled", "minutes"))),
    (2, "presets Normal / Movie / Saver",
     tuple(f"idle.{p}.preset.{name}" for p in PROFILES for name in strings.SS_PRESETS)),
    (3, "stay awake", ("caffeine.switch",)),
    (4, "night filter: 'now' slider 2000-6500 K with marks, target at night, warm-up "
        "start and off times, turn off now, save returns to the schedule",
     ("night.slider", "night.value", "night.target", "night.on.hour", "night.on.minute",
      "night.off.hour", "night.off.minute", "night.off-now", "night.schedule")),
    (5, "moving the slider switches to manual mode", ("night.slider", "night.schedule")),
    (6, "hyprsunset / hypridle / daemon checks; warning when steps are not in ascending order",
     ("status.hyprsunset", "status.hypridle", "status.daemon", "status.power",
      "idle.ac.order-warning", "idle.battery.order-warning")),
)


class View(Protocol):
    def show(self, key: str, value: Any) -> None:
        """Set the widgets of a field without firing their handlers."""

    def focused(self, key: str) -> bool:
        """True while a widget of this field has keyboard focus."""

    def show_order(self, profile: str, bad: bool) -> None: ...

    def show_probe(self, probe: Probe) -> None: ...

    def show_setup(self, state: str, detail: str) -> None:
        """state: "ok", "missing" (no config.json) or "error" (modules)."""

    def status(self, text: str) -> None: ...


class Timers(Protocol):
    def now(self) -> float: ...

    def after(self, ms: int, fn: Callable[[], None]) -> Any: ...

    def cancel(self, handle: Any) -> None: ...


class GLibTimers:
    """Timers on the GTK main loop (the default outside tests)."""

    class _Handle:
        source = 0

    def now(self) -> float:
        return time.monotonic()

    def after(self, ms: int, fn: Callable[[], None]) -> _Handle:
        from gi.repository import GLib

        handle = self._Handle()

        def run() -> bool:
            handle.source = 0
            fn()
            return False

        handle.source = GLib.timeout_add(ms, run)
        return handle

    def cancel(self, handle: _Handle | None) -> None:
        if handle is not None and handle.source:
            from gi.repository import GLib

            GLib.source_remove(handle.source)
            handle.source = 0


# ---- fields <-> config paths ---------------------------------------------------

def to_paths(key: str, value: Any) -> dict[str, Any]:
    if key in ("night.on", "night.off"):
        name = key.split(".")[1]
        return {f"night.{name}_hour": int(value[0]), f"night.{name}_minute": int(value[1])}
    return {key: value}


def field_of(path: str) -> str:
    for name in TIMES:
        if path in (f"night.{name}_hour", f"night.{name}_minute"):
            return f"night.{name}"
    return path


def fields_from_config(cfg: dict) -> dict[str, Any]:
    night = cfg["night"]
    out: dict[str, Any] = {
        f"idle.{p}.{s}": dict(cfg["idle"][p][s]) for p in PROFILES for s in STEPS
    }
    out[TARGET] = night["target_temp"]
    out["night.on"] = [night["on_hour"], night["on_minute"]]
    out["night.off"] = [night["off_hour"], night["off_minute"]]
    out[OVERRIDE] = night["manual_override"]
    return out


def label_for(path: str) -> str:
    if path.startswith("idle."):
        _, profile, step = path.split(".")
        return strings.SS_LABEL_STEP.format(profile=strings.SS_PROFILES[profile],
                                            step=strings.SS_STEPS[step])
    return {
        TARGET: strings.SS_LABEL_TARGET,
        "night.on_hour": strings.SS_LABEL_ON, "night.on_minute": strings.SS_LABEL_ON,
        "night.off_hour": strings.SS_LABEL_OFF, "night.off_minute": strings.SS_LABEL_OFF,
        OVERRIDE: strings.SS_LABEL_SCHEDULE,
    }.get(path, path)


class Controller:
    def __init__(self, backend: ss_backend.Backend, history, view: View,
                 timers: Timers | None = None, settings=None) -> None:
        self.settings = settings  # the General page's delays; None = the defaults
        self.backend = backend
        self.history = history
        self.view = view
        self.timers = timers or GLibTimers()
        self.pending: dict[str, int] = {}  # field -> generation of its queued change
        self.touched: dict[str, float] = {}  # field -> when the user last changed it
        self.shown: dict[str, Any] = {}  # field -> value the widgets show
        self._gen = 0
        self._dirty: dict[str, Any] = {}
        self._debounce = None
        self._series: dict | None = None
        self._temp_timer = None
        self._still_timer = None
        self._refresh_timer = None
        self._visible = False
        backend.on_applied.append(self._on_applied)
        backend.on_external.append(self._on_external)

    def _delay(self, key: str, default: float) -> float:
        """A delay from the General page, read at each use so a change applies at once."""
        return default if self.settings is None else self.settings.get(key)

    def _refresh_ms(self) -> int:
        if self.settings is None:
            return REFRESH_MS
        return self.settings.get("behavior.refresh_s") * 1000

    # ---- re-reading -------------------------------------------------------

    def may_overwrite(self, key: str) -> bool:
        if key in self.pending or self.view.focused(key):
            return False
        last = self.touched.get(key)
        return last is None or self.timers.now() - last >= self._delay("behavior.guard_s", GUARD_S)

    def refresh(self) -> None:
        """Re-read config.json (now) and the running state (on a worker)."""
        state, detail = self.backend.state()
        if state == "ok":
            try:
                cfg = self.backend.read_config()
            except ss_backend.NotConfigured:
                state, cfg = "missing", None
            except Exception as exc:  # unreadable for a reason load_config does not hide
                state, detail, cfg = "error", str(exc), None
        self.view.show_setup(state, detail)
        if state != "ok":
            return
        for key, value in fields_from_config(cfg).items():
            self._offer(key, value)
        self._show_order()
        self.backend.probe(self._on_probe)

    def _offer(self, key: str, value: Any) -> None:
        if value is None or not self.may_overwrite(key):
            return
        if self.shown.get(key) != value:
            self.shown[key] = value
            self.view.show(key, value)

    def _on_probe(self, probe: Probe) -> None:
        self._offer(TEMP_KEY, probe.temperature)
        self._offer(CAFFEINE_KEY, probe.caffeine)
        self.view.show_probe(probe)

    def set_visible(self, visible: bool) -> None:
        """While visible, re-read every 5 s (the daemon changes things too)."""
        self._visible = visible
        self.timers.cancel(self._refresh_timer)
        self._refresh_timer = None
        if visible:
            self._refresh_timer = self.timers.after(self._refresh_ms(), self._tick)

    def _tick(self) -> None:
        self._refresh_timer = None
        if not self._visible:
            return
        self.refresh()
        self._refresh_timer = self.timers.after(self._refresh_ms(), self._tick)

    def _on_external(self, keys: set[str]) -> None:
        """History changed these keys: show them even if touched a moment ago."""
        for key in {field_of(k) for k in keys}:
            if key not in self.pending:
                self.touched.pop(key, None)
        self.refresh()

    # ---- editing ----------------------------------------------------------

    def _mark(self, key: str, value: Any) -> None:
        self._gen += 1
        self.pending[key] = self._gen
        self.touched[key] = self.timers.now()
        self.shown[key] = value

    def _release(self, gens: dict[str, int | None]) -> None:
        for key, gen in gens.items():
            if gen is not None and self.pending.get(key) == gen:
                del self.pending[key]

    def edit(self, key: str, value: Any) -> None:
        """A timing or night field changed; written 1.5 s after the last change."""
        if key.startswith("idle."):
            value = {"enabled": bool(value["enabled"]),
                     "minutes": max(MIN_MINUTES, min(MAX_MINUTES, int(value["minutes"])))}
        elif key == TARGET:
            value = max(MIN_TEMP, min(MAX_TEMP, int(value)))
        elif key in ("night.on", "night.off"):
            value = [int(value[0]) % 24, int(value[1]) % 60]
        else:
            raise KeyError(key)
        if self.shown.get(key) == value and key not in self._dirty:
            return  # a widget echoed a value it was given
        self._mark(key, value)
        self._dirty[key] = value
        if key.startswith("idle."):
            self._show_order()
        self.timers.cancel(self._debounce)
        self._debounce = self.timers.after(self._delay("behavior.apply_delay_ms", DEBOUNCE_MS),
                                           self.flush)

    def flush(self) -> None:
        """Write the debounced changes now (as one group)."""
        self.timers.cancel(self._debounce)
        self._debounce = None
        if not self._dirty:
            return
        fields, self._dirty = self._dirty, {}
        self._commit(fields)

    def preset(self, profile: str, preset_id: str) -> None:
        self.flush()
        minutes = self.backend.ss.common.PRESETS[strings.SS_PRESETS[preset_id]]
        label = strings.SS_PRESET_LABEL.format(preset=strings.SS_PRESETS[preset_id],
                                               profile=strings.SS_PROFILES[profile])
        fields = {}
        for step in STEPS:
            key = f"idle.{profile}.{step}"
            current = self.shown.get(key) or {"enabled": False, "minutes": MIN_MINUTES}
            value = {"enabled": minutes[step] is not None,
                     "minutes": current["minutes"] if minutes[step] is None
                     else int(minutes[step])}
            self._mark(key, value)
            self.view.show(key, value)
            fields[key] = value
        self._show_order()
        self._commit(fields, labels=dict.fromkeys(fields, label))

    def _commit(self, fields: dict[str, Any], labels: dict[str, str] | None = None,
                extra: list | None = None,
                after: Callable[[WriteResult], list] | None = None) -> None:
        paths: dict[str, Any] = {}
        for key, value in fields.items():
            paths.update(to_paths(key, value))
        gens = {key: self.pending.get(key) for key in fields}
        items = list(extra or [])

        def done(result: WriteResult | None, error: BaseException | None) -> None:
            self._release(gens)
            if error is not None:
                if items:
                    self.history.record(items)
                self.view.status(strings.SS_WRITE_FAILED.format(error=error))
                for key in fields:
                    self.touched.pop(key, None)
                self.refresh()  # show what the file really says
                return
            more = after(result) if after else []
            self.history.record(
                [(BACKEND, p, (labels or {}).get(p) or label_for(p), result.before[p], v)
                 for p, v in result.values.items()] + items + more)
            if not idle_profiles(paths):
                self.view.status(strings.SS_SAVED)

        self.backend.queue_write(paths, done)
        if idle_profiles(paths):
            self.view.status(strings.SS_APPLYING)

    def _on_applied(self, result: ApplyResult) -> None:
        if not result.ok:
            self.view.status(strings.SS_APPLY_FAILED.format(error=result.message))
        elif result.applied:
            self.view.status(strings.SS_APPLIED.format(
                profile=strings.SS_PROFILES.get(result.power, result.power)))
        else:
            self.view.status(strings.SS_APPLIED_LATER)

    def _show_order(self) -> None:
        for profile in PROFILES:
            steps = {s: self.shown.get(f"idle.{profile}.{s}") for s in STEPS}
            if all(steps.values()):
                self.view.show_order(profile, out_of_order(steps, STEPS))

    # ---- switches ---------------------------------------------------------

    def caffeine_toggled(self, enabled: bool) -> None:
        before = self.shown.get(CAFFEINE_KEY)
        if before is None:
            before = not enabled
        if before == enabled and CAFFEINE_KEY not in self.pending:
            return
        self._mark(CAFFEINE_KEY, enabled)
        gens = {CAFFEINE_KEY: self.pending[CAFFEINE_KEY]}

        def done(result, error) -> None:
            self._release(gens)
            if error is not None:
                ok, message, active = False, str(error), before
            else:
                ok, message, active = result
            if not ok:
                self.view.status(strings.SS_CAFFEINE_FAILED.format(error=message))
            if CAFFEINE_KEY not in self.pending:
                self.shown[CAFFEINE_KEY] = active
                self.view.show(CAFFEINE_KEY, active)
            self.history.record([(CAFFEINE, CAFFEINE_KEY, strings.SS_LABEL_CAFFEINE,
                                  before, active)])

        self.backend.queue_caffeine(enabled, done)

    def schedule_toggled(self, on_schedule: bool) -> None:
        if self._series is not None:
            self.slider_done()
        if self.shown.get(OVERRIDE) == (not on_schedule) and OVERRIDE not in self.pending:
            return
        self._mark(OVERRIDE, not on_schedule)
        if not on_schedule:
            self._commit({OVERRIDE: True})
            return
        temp_before = self.shown.get(TEMP_KEY)

        def back_to_schedule(result: WriteResult) -> list:
            target = self.backend.scheduled_temperature(result.config["night"])
            self.touched[TEMP_KEY] = self.timers.now()
            self.shown[TEMP_KEY] = target
            self.view.show(TEMP_KEY, target)
            self.backend.queue_temperature(target, self._temp_done)
            if temp_before is None:
                return []
            return [(NIGHT, TEMP_KEY, strings.SS_LABEL_SCHEDULE, temp_before, target)]

        self._commit({OVERRIDE: False}, after=back_to_schedule)

    # ---- the "now" slider -------------------------------------------------

    def slider_moved(self, value: float) -> None:
        value = int(round(value))
        if self._series is None:
            self._series = {"before": self.shown.get(TEMP_KEY)}
            if self.shown.get(OVERRIDE) is not True:
                self.view.show(OVERRIDE, True)  # "On schedule" goes off at once
            self._mark(OVERRIDE, True)
        if self.shown.get(TEMP_KEY) == value and TEMP_KEY in self.pending:
            return
        self._mark(TEMP_KEY, value)
        self.view.show(TEMP_KEY, value)  # the slider is there already; the label follows
        self.timers.cancel(self._temp_timer)
        self._temp_timer = self.timers.after(self._delay("behavior.night_slider_ms", TEMP_LIVE_MS),
                                             self._apply_live)
        self.timers.cancel(self._still_timer)
        self._still_timer = self.timers.after(
            self._delay("behavior.series_still_ms", SERIES_STILL_MS), self.slider_done)

    def _apply_live(self) -> None:
        self._temp_timer = None
        self.backend.queue_temperature(self.shown[TEMP_KEY], self._temp_done)

    def _temp_done(self, result, error) -> None:
        ok, message = (False, str(error)) if error is not None else result
        if not ok:
            self.view.status(strings.SS_TEMP_FAILED.format(error=message))

    def slider_done(self) -> None:
        """The series ended: still for 600 ms, button released or focus lost."""
        if self._series is None:
            return
        self.timers.cancel(self._still_timer)
        self._still_timer = None
        if self._temp_timer is not None:
            self.timers.cancel(self._temp_timer)
            self._apply_live()  # the final value is applied, not dropped
        series, self._series = self._series, None
        final = self.shown[TEMP_KEY]
        self.pending.pop(TEMP_KEY, None)  # the 10 s guard keeps protecting it
        extra = []
        if series["before"] is not None:
            extra.append((NIGHT, TEMP_KEY, strings.SS_LABEL_SLIDER, series["before"], final))
        self._commit({OVERRIDE: True}, labels={OVERRIDE: strings.SS_LABEL_SLIDER},
                     extra=extra)

    def off_now(self) -> None:
        """The "Turn off now" button: the slider to neutral, as one series."""
        self.view.show(TEMP_KEY, MAX_TEMP)
        self.slider_moved(MAX_TEMP)
        self.slider_done()
