"""The "Screen and sleep" page: idle timings, stay awake, the night filter.

Only widgets live here; what to write and when is decided by
controllers.screen_sleep.Controller, which this page serves as the view.
Every widget the old window's abilities map to is registered in
self.widgets under an id from controllers.screen_sleep.WIDGETS.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import screen_sleep as ss_backend  # noqa: E402
from ..controllers import screen_sleep as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


def _spin(lo: int, hi: int, step: int, width: int, pad: bool = False) -> Gtk.SpinButton:
    spin = Gtk.SpinButton.new_with_range(lo, hi, step)
    spin.set_numeric(True)
    spin.set_width_chars(width)
    spin.set_digits(0)
    spin.set_alignment(1.0)  # numbers line up on the right, as in macOS fields
    spin.set_valign(Gtk.Align.CENTER)
    if pad:
        def two_digits(s: Gtk.SpinButton) -> bool:
            s.set_text(f"{int(s.get_adjustment().get_value()):02d}")
            return True

        spin.connect("output", two_digits)
    return spin


def _dim(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("sh-dim")
    return label


class StatusBadge(Gtk.Box):
    """A coloured dot and a word: running / not running / checking."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.dot.add_css_class("sh-dot")
        self.label = _dim(strings.SS_UNKNOWN)
        self.append(self.dot)
        self.append(self.label)
        self.show_state(None)

    def show_state(self, ok: bool | None, text: str | None = None) -> None:
        for name in ("ok", "bad"):
            self.dot.remove_css_class(name)
        if ok is not None:
            self.dot.add_css_class("ok" if ok else "bad")
        self.label.set_label(text or (strings.SS_UNKNOWN if ok is None
                                      else strings.SS_RUNNING if ok else strings.SS_STOPPED))


class ScreenSleepPage(Page):
    def build(self) -> None:
        self.widgets: dict[str, Gtk.Widget] = {}
        self._quiet_depth = 0
        self._steps: dict[str, tuple[Gtk.Switch, Gtk.SpinButton]] = {}
        self._times: dict[str, tuple[Gtk.SpinButton, Gtk.SpinButton]] = {}
        self._main: list[Gtk.Widget] = []
        self.profile_groups: dict[str, Group] = {}
        self.order_labels: dict[str, Gtk.Label] = {}
        backend = self.ctx.backends.get(ss_backend.BACKEND)
        if backend is None:  # normally created by the app, with History appliers
            backend = ss_backend.Backend(self.ctx.workers)
            ss_backend.register(self.ctx.history, backend)
            self.ctx.backends[ss_backend.BACKEND] = backend
        self.backend = backend

        self._build_setup()
        self._build_now()
        self._build_caffeine()
        for profile in ctl.PROFILES:
            self._build_profile(profile)
        self._build_night()

        self.controller = ctl.Controller(backend, self.ctx.history, self,
                                         settings=self.ctx.settings)
        self.widget.connect("map", lambda *_: self.controller.set_visible(True))
        self.widget.connect("unmap", lambda *_: self._hidden())
        self.refresh()

    # ---- building -------------------------------------------------------

    def _add(self, group: Group, main: bool = True) -> Group:
        self.add_group(group)
        if main:
            self._main.append(group)
        return group

    def _build_setup(self) -> None:
        self.setup_group = self._add(Group(strings.SS_SETUP_GROUP), main=False)
        button = Gtk.Button(label=strings.SS_OPEN_OLD)
        button.connect("clicked", lambda *_: self._open_old_window())
        self.setup_row = self.setup_group.add(Row(
            strings.SS_SETUP_MISSING, strings.SS_SETUP_MISSING_HINT, suffix=button))
        self.widgets["setup.notice"] = self.setup_row
        self.widgets["setup.open-old"] = button
        self.setup_group.set_visible(False)

    def _build_now(self) -> None:
        group = self._add(Group(strings.SS_NOW_GROUP))
        self.power_label = _dim("")
        self.power_row = group.add(Row(strings.SS_POWER, suffix=self.power_label,
                                       row_id="now"))
        self.rows["now"] = self.power_row
        self.widgets["status.power"] = self.power_label
        self.checks: dict[str, tuple[Row, StatusBadge]] = {}
        for name, title in (("hyprsunset", strings.SS_CHECK_HYPRSUNSET),
                            ("hypridle", strings.SS_CHECK_HYPRIDLE),
                            ("daemon", strings.SS_CHECK_DAEMON)):
            badge = StatusBadge()
            row = group.add(Row(title, suffix=badge))
            self.checks[name] = (row, badge)
            self.widgets[f"status.{name}"] = badge

    def _build_caffeine(self) -> None:
        group = self._add(Group())
        self.caffeine = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.caffeine.connect("notify::active", self._on_caffeine)
        self.caffeine_row = group.add(Row(strings.SS_CAFFEINE, strings.SS_CAFFEINE_OFF,
                                          suffix=self.caffeine, row_id="caffeine"))
        self.rows["caffeine"] = self.caffeine_row
        self.widgets["caffeine.switch"] = self.caffeine

    def _build_profile(self, profile: str) -> None:
        group = self._add(Group(strings.SS_PROFILES[profile]))
        self.profile_groups[profile] = group
        first = None
        for step in ctl.STEPS:
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            spin = _spin(ctl.MIN_MINUTES, ctl.MAX_MINUTES, 1, 3)
            suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            suffix.append(_dim(strings.SS_AFTER))
            suffix.append(spin)
            suffix.append(_dim(strings.SS_MINUTES))
            suffix.append(switch)
            row = group.add(Row(strings.SS_STEPS[step], suffix=suffix,
                                row_id=profile if first is None else None))
            first = first or row
            self._steps[f"idle.{profile}.{step}"] = (switch, spin)
            self.widgets[f"idle.{profile}.{step}.enabled"] = switch
            self.widgets[f"idle.{profile}.{step}.minutes"] = spin
            key = f"idle.{profile}.{step}"
            switch.connect("notify::active", lambda *_a, k=key: self._on_step(k))
            spin.connect("value-changed", lambda *_a, k=key: self._on_step(k))
        self.rows[profile] = first

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        presets.add_css_class("sh-segmented")
        for preset_id, name in strings.SS_PRESETS.items():
            button = Gtk.Button(label=name)
            button.connect("clicked", lambda *_a, p=profile, i=preset_id:
                           self.controller.preset(p, i))
            presets.append(button)
            self.widgets[f"idle.{profile}.preset.{preset_id}"] = button
        group.add(Row(strings.SS_PRESETS_ROW, suffix=presets))

        warning = Gtk.Label(label=strings.SS_ORDER_WARNING, xalign=0, wrap=True,
                            visible=False)
        warning.add_css_class("sh-group-note")
        warning.add_css_class("sh-warning")
        group.append(warning)
        self.order_labels[profile] = warning
        self.widgets[f"idle.{profile}.order-warning"] = warning

    def _build_night(self) -> None:
        group = self._add(Group(strings.SS_NIGHT_GROUP, strings.SS_NIGHT_NOTE))
        self.temp_label = Gtk.Label(label=strings.SS_KELVIN_UNKNOWN)
        self.temp_label.add_css_class("sh-value")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, ctl.MIN_TEMP,
                                              ctl.MAX_TEMP, ctl.SLIDER_STEP)
        self.scale.set_inverted(True)  # to the right = warmer (fewer kelvin)
        self.scale.set_draw_value(False)
        self.scale.set_round_digits(0)
        self.scale.set_hexpand(True)
        self.scale.set_increments(ctl.SLIDER_STEP, 500)
        self.scale.add_mark(ctl.SLEEP_MARK_TEMP, Gtk.PositionType.BOTTOM, strings.SS_MARK_SLEEP)
        self.scale.add_mark(ctl.MAX_TEMP, Gtk.PositionType.BOTTOM, strings.SS_MARK_OFF)
        self.scale.set_value(ctl.MAX_TEMP)
        self.scale.connect("value-changed", self._on_scale)
        # GTK4's Scale has no "released" signal. The plan's GestureClick is
        # here; its press may be denied once the Range's own drag gesture
        # claims the pointer, so the controller's 600 ms stillness timer and
        # focus-leave end the series too (ending it twice does nothing).
        # (An EventControllerLegacy got event=None from PyGObject 3.58.)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda *_: self.controller.slider_done())
        self.scale.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self.controller.slider_done())
        self.scale.add_controller(focus)
        self.rows["night"] = group.add(Row(strings.SS_NIGHT_NOW, suffix=self.temp_label,
                                           below=self.scale, row_id="night"))
        self.widgets["night.slider"] = self.scale
        self.widgets["night.value"] = self.temp_label

        self.schedule = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.schedule.connect("notify::active", self._on_schedule)
        self.schedule_row = group.add(Row(strings.SS_SCHEDULE, strings.SS_SCHEDULE_ON,
                                          suffix=self.schedule, row_id="schedule"))
        self.rows["schedule"] = self.schedule_row
        self.widgets["night.schedule"] = self.schedule

        self.target = _spin(ctl.MIN_TEMP, ctl.MAX_TEMP, ctl.TARGET_STEP, 4)
        self.target.connect("value-changed", self._on_target)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(self.target)
        box.append(_dim("K"))
        self.rows["target"] = group.add(Row(strings.SS_TARGET, strings.SS_TARGET_HINT,
                                            suffix=box, row_id="target"))
        self.widgets["night.target"] = self.target

        for name, title, hint in (
                ("on", strings.SS_ON_TIME, strings.SS_ON_TIME_HINT.format(
                    step=ctl.RAMP_STEP, minutes=ctl.RAMP_INTERVAL_MIN)),
                ("off", strings.SS_OFF_TIME, strings.SS_OFF_TIME_HINT)):
            hour = _spin(0, 23, 1, 2, pad=True)
            minute = _spin(0, 59, 1, 2, pad=True)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.add_css_class("sh-time")
            box.append(hour)
            box.append(_dim(":"))
            box.append(minute)
            row = group.add(Row(title, hint, suffix=box,
                                row_id="times" if name == "on" else None))
            if name == "on":
                self.rows["times"] = row
            self._times[f"night.{name}"] = (hour, minute)
            self.widgets[f"night.{name}.hour"] = hour
            self.widgets[f"night.{name}.minute"] = minute
            for spin in (hour, minute):
                spin.connect("value-changed", lambda *_a, k=f"night.{name}": self._on_time(k))

        off = Gtk.Button(label=strings.SS_OFF_NOW)
        off.connect("clicked", lambda *_: self.controller.off_now())
        self.rows["off-now"] = group.add(Row(strings.SS_OFF_NOW, strings.SS_OFF_NOW_HINT,
                                             suffix=off, row_id="off-now"))
        self.widgets["night.off-now"] = off

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    def _hidden(self) -> None:
        self.controller.set_visible(False)
        # Hiding the window must not lose a value typed but not yet entered.
        for _switch, spin in self._steps.values():
            spin.update()
        for spins in (*self._times.values(), (self.target,)):
            for spin in spins:
                spin.update()
        self.controller.flush()
        self.controller.slider_done()

    # ---- signals from widgets -------------------------------------------

    @contextmanager
    def _quiet(self):
        self._quiet_depth += 1
        try:
            yield
        finally:
            self._quiet_depth -= 1

    def _on_step(self, key: str) -> None:
        switch, spin = self._steps[key]
        spin.set_sensitive(switch.get_active())
        if self._quiet_depth:
            return
        self.controller.edit(key, {"enabled": switch.get_active(),
                                   "minutes": int(spin.get_value())})

    def _on_target(self, spin: Gtk.SpinButton) -> None:
        if not self._quiet_depth:
            self.controller.edit(ctl.TARGET, int(spin.get_value()))

    def _on_time(self, key: str) -> None:
        if not self._quiet_depth:
            hour, minute = self._times[key]
            self.controller.edit(key, [int(hour.get_value()), int(minute.get_value())])

    def _on_caffeine(self, switch: Gtk.Switch, _pspec) -> None:
        self.caffeine_row.subtitle_label.set_label(
            strings.SS_CAFFEINE_ON if switch.get_active() else strings.SS_CAFFEINE_OFF)
        if not self._quiet_depth:
            self.controller.caffeine_toggled(switch.get_active())

    def _on_schedule(self, switch: Gtk.Switch, _pspec) -> None:
        self.schedule_row.subtitle_label.set_label(
            strings.SS_SCHEDULE_ON if switch.get_active() else strings.SS_SCHEDULE_OFF)
        if not self._quiet_depth:
            self.controller.schedule_toggled(switch.get_active())

    def _on_scale(self, scale: Gtk.Scale) -> None:
        value = int(round(scale.get_value()))
        self.temp_label.set_label(strings.SS_KELVIN.format(value=value))
        if not self._quiet_depth:
            self.controller.slider_moved(value)

    def _open_old_window(self) -> None:
        gui = self.backend.old_window()
        if gui is None:
            return
        try:
            proc = Gio.Subprocess.new(["python3", str(gui)], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.ctx.status(strings.SS_APPLY_FAILED.format(error=exc.message))
            return
        proc.wait_async(None, lambda p, res: p.wait_finish(res))  # reaped, no zombie

    # ---- the controller's view ------------------------------------------

    def show(self, key: str, value: Any) -> None:
        with self._quiet():
            if key in self._steps:
                switch, spin = self._steps[key]
                switch.set_active(bool(value["enabled"]))
                spin.set_value(value["minutes"])
                spin.set_sensitive(bool(value["enabled"]))
            elif key == ctl.TARGET:
                self.target.set_value(value)
            elif key in self._times:
                hour, minute = self._times[key]
                hour.set_value(value[0])
                minute.set_value(value[1])
            elif key == ctl.OVERRIDE:
                self.schedule.set_active(not value)
            elif key == ss_backend.TEMP_KEY:
                self.scale.set_value(value)
                self.temp_label.set_label(strings.SS_KELVIN.format(value=int(value)))
            elif key == ss_backend.CAFFEINE_KEY:
                self.caffeine.set_active(bool(value))

    def focused(self, key: str) -> bool:
        """Only text fields count: a switch or the slider keeps focus after a
        click, and the 10 s rule already covers a change just made."""
        if key in self._steps:
            widgets = (self._steps[key][1],)
        elif key == ctl.TARGET:
            widgets = (self.target,)
        elif key in self._times:
            widgets = self._times[key]
        else:
            return False
        return any(w.get_state_flags() & Gtk.StateFlags.FOCUS_WITHIN for w in widgets)

    def show_order(self, profile: str, bad: bool) -> None:
        self.order_labels[profile].set_visible(bad)

    def show_probe(self, probe: ss_backend.Probe) -> None:
        if probe.power in strings.SS_PROFILES:
            self.power_label.set_label(strings.SS_POWER_NAMES[probe.power].capitalize())
            self.power_row.subtitle_label.set_label(strings.SS_POWER_ACTIVE.format(
                profile=strings.SS_PROFILES[probe.power]))
            self.power_row.subtitle_label.set_visible(True)
            for profile, group in self.profile_groups.items():
                name = strings.SS_PROFILES[profile]
                group.heading.set_label(strings.SS_PROFILE_NOW.format(profile=name)
                                        if profile == probe.power else name)
        for name, value in (("hyprsunset", probe.hyprsunset), ("hypridle", probe.hypridle),
                            ("daemon", probe.daemon)):
            row, badge = self.checks[name]
            ok, message = value if isinstance(value, tuple) else (
                bool(value), "" if value else strings.SS_HYPRIDLE_DOWN)
            badge.show_state(ok)
            row.subtitle_label.set_label(message)
            row.subtitle_label.set_visible(bool(message) and not ok)

    def show_setup(self, state: str, detail: str) -> None:
        ok = state == "ok"
        for group in self._main:
            group.set_visible(ok)
        self.setup_group.set_visible(not ok)
        if not ok:
            title = strings.SS_SETUP_MISSING if state == "missing" else strings.SS_SETUP_ERROR
            hint = strings.SS_SETUP_MISSING_HINT if state == "missing" else detail
            self.setup_row.title_label.set_label(title)
            self.setup_row.subtitle_label.set_label(hint)
            self.setup_row.subtitle_label.set_visible(bool(hint))
            self.widgets["setup.open-old"].set_visible(self.backend.old_window() is not None)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = ScreenSleepPage
