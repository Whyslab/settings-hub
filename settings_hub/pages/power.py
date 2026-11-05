"""The "Power and brightness" page: battery, power profile, brightness."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import power as pw  # noqa: E402
from ..controllers import power as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

BRIGHTNESS_SETTLE_MS = 500


class PowerPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(pw.BACKEND)
        if backend is None:
            backend = pw.Backend(self.ctx.workers)
            pw.register(self.ctx.history, backend)
            self.ctx.backends[pw.BACKEND] = backend
        self.backend = backend

        battery = self.add_group(Group(strings.POWER_BATTERY))
        self.charge_label = Gtk.Label(label="—")
        self.charge_label.add_css_class("sh-value")
        self.rows["battery.charge"] = battery.add(Row(
            strings.POWER_CHARGE, suffix=self.charge_label, row_id="battery.charge"))
        self.status_label = Gtk.Label(label="—")
        self.status_label.add_css_class("sh-dim")
        self.rows["battery.status"] = battery.add(Row(
            strings.POWER_STATUS, suffix=self.status_label, row_id="battery.status"))
        self.health_label = Gtk.Label(label="—")
        self.health_label.add_css_class("sh-dim")
        self.rows["battery.health"] = battery.add(Row(
            strings.POWER_HEALTH, strings.POWER_HEALTH_HINT,
            suffix=self.health_label, row_id="battery.health"))
        self.cycles_label = Gtk.Label(label="—")
        self.cycles_label.add_css_class("sh-dim")
        self.rows["battery.cycles"] = battery.add(Row(
            strings.POWER_CYCLES, suffix=self.cycles_label, row_id="battery.cycles"))
        self.ac_label = Gtk.Label(label="—")
        self.ac_label.add_css_class("sh-dim")
        self.rows["battery.ac"] = battery.add(Row(
            strings.POWER_AC, suffix=self.ac_label, row_id="battery.ac"))

        profile = self.add_group(Group(strings.POWER_PROFILE))
        self.profile_dropdown = Gtk.DropDown.new_from_strings(
            [strings.POWER_PROFILES.get(p, p) for p in pw.PROFILES])
        self.profile_dropdown.set_valign(Gtk.Align.CENTER)
        self.profile_dropdown.connect("notify::selected", self._on_profile)
        self.rows["profile"] = profile.add(Row(
            strings.POWER_PROFILE_ROW, strings.POWER_PROFILE_HINT,
            suffix=self.profile_dropdown, row_id="profile"))

        screen = self.add_group(Group(strings.POWER_SCREEN))
        self.brightness_label = Gtk.Label(label="—")
        self.brightness_label.add_css_class("sh-value")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_round_digits(0)
        self.scale.set_increments(1, 10)
        self.scale.connect("value-changed", self._on_brightness)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda *_: self._commit())
        self.scale.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._commit())
        self.scale.add_controller(focus)
        self.rows["brightness"] = screen.add(Row(
            strings.POWER_BRIGHTNESS, suffix=self.brightness_label, below=self.scale,
            row_id="brightness"))

        self._quiet = False
        self._settle_source = 0
        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- signals --------------------------------------------------------

    def _on_profile(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._quiet:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(pw.PROFILES):
            self.controller.set_profile(pw.PROFILES[index])

    def _on_brightness(self, scale: Gtk.Scale) -> None:
        percent = int(round(scale.get_value()))
        self.brightness_label.set_label(strings.AUDIO_PERCENT.format(percent=percent))
        if self._quiet:
            return
        self.controller.brightness_moved(percent)
        if self._settle_source:
            GLib.source_remove(self._settle_source)
        self._settle_source = GLib.timeout_add(BRIGHTNESS_SETTLE_MS, self._settle)

    def _settle(self) -> bool:
        self._settle_source = 0
        self._commit()
        return False

    def _commit(self) -> None:
        if self._settle_source:
            GLib.source_remove(self._settle_source)
            self._settle_source = 0
        self.controller.commit_brightness()

    # ---- the controller's view -----------------------------------------

    def show_power(self, info: pw.Power) -> None:
        self._quiet = True
        try:
            if info.charge is None:
                self.charge_label.set_label(strings.POWER_NO_BATTERY)
                for row_id in ("battery.status", "battery.health", "battery.cycles"):
                    self.rows[row_id].set_visible(False)
            else:
                self.charge_label.set_label(strings.POWER_PERCENT.format(
                    percent=info.charge))
                self.status_label.set_label(
                    strings.POWER_STATES.get(info.status, info.status or "—"))
                if info.full_wh and info.design_wh:
                    health = round(info.full_wh / info.design_wh * 100)
                    self.health_label.set_label(strings.POWER_HEALTH_VALUE.format(
                        percent=health, full=info.full_wh, design=info.design_wh))
                self.cycles_label.set_label(
                    str(info.cycles) if info.cycles is not None else "—")
            if info.ac_online is None:
                self.ac_label.set_label("—")
            else:
                self.ac_label.set_label(strings.POWER_AC_ON if info.ac_online
                                        else strings.POWER_AC_OFF)
            if info.profile in pw.PROFILES:
                self.profile_dropdown.set_selected(pw.PROFILES.index(info.profile))
            self.scale.set_sensitive(info.brightness is not None)
        finally:
            self._quiet = False

    def show_brightness(self, percent: int) -> None:
        self._quiet = True
        try:
            self.scale.set_value(percent)
            self.brightness_label.set_label(strings.AUDIO_PERCENT.format(percent=percent))
        finally:
            self._quiet = False

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = PowerPage
