"""The "Sound" page: output and input device, volume, mute."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import audio as aud  # noqa: E402
from ..controllers import audio as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

VOLUME_SETTLE_MS = 600


class KindGroup:
    """One device picker: a drop-down, a volume slider and a mute switch."""

    def __init__(self, page: SoundPage, kind: str, title: str) -> None:
        self.page = page
        self.kind = kind
        self.group = page.add_group(Group(title))
        self.names: list[str] = []
        self.dropdown = Gtk.DropDown.new_from_strings([])
        self.dropdown.set_valign(Gtk.Align.CENTER)
        self.dropdown.set_hexpand(True)
        self.dropdown.connect("notify::selected", self._on_selected)
        self.page.rows[f"{kind}.device"] = self.group.add(
            Row(strings.AUDIO_DEVICE, suffix=self.dropdown, row_id=f"{kind}.device"))

        self.value_label = Gtk.Label(label="—")
        self.value_label.add_css_class("sh-value")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_round_digits(0)
        self.scale.set_increments(5, 10)
        self.scale.connect("value-changed", self._on_volume)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda *_: self._settle_now())
        self.scale.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._settle_now())
        self.scale.add_controller(focus)
        page.rows[f"{kind}.volume"] = self.group.add(
            Row(strings.AUDIO_VOLUME, suffix=self.value_label, below=self.scale,
                row_id=f"{kind}.volume"))

        self.mute = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.mute.connect("notify::active", self._on_mute)
        page.rows[f"{kind}.mute"] = self.group.add(
            Row(strings.AUDIO_MUTE, suffix=self.mute, row_id=f"{kind}.mute"))

        self._quiet = False
        self._settle_source = 0

    # ---- showing ---------------------------------------------------------

    def show(self, devices: list[aud.Device], default: str) -> None:
        names = [d.name for d in devices]
        index = names.index(default) if default in names else -1
        # All of it quiet: a new model selects its first item and notifies, and
        # that must not look like a person choosing a device.
        self._quiet = True
        try:
            if names != self.names:
                self.names = names
                self.dropdown.set_model(Gtk.StringList.new(
                    [d.description for d in devices] or [strings.AUDIO_NO_DEVICES]))
                self.dropdown.set_sensitive(bool(devices))
            self.dropdown.set_selected(max(0, index))
            device = devices[index] if 0 <= index < len(devices) else None
            if device is not None:
                self.scale.set_value(device.volume)
                self.value_label.set_label(strings.AUDIO_PERCENT.format(percent=device.volume))
                self.mute.set_active(device.mute)
        finally:
            self._quiet = False

    def show_volume(self, percent: int) -> None:
        self._quiet = True
        try:
            self.scale.set_value(percent)
            self.value_label.set_label(strings.AUDIO_PERCENT.format(percent=percent))
        finally:
            self._quiet = False

    # ---- signals ---------------------------------------------------------

    def _on_selected(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._quiet:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(self.names):
            self.page.controller.set_default(self.kind, self.names[index])

    def _on_volume(self, scale: Gtk.Scale) -> None:
        percent = int(round(scale.get_value()))
        self.value_label.set_label(strings.AUDIO_PERCENT.format(percent=percent))
        if self._quiet:
            return
        self.page.controller.volume_moved(self.kind, percent)
        if self._settle_source:
            GLib.source_remove(self._settle_source)
        self._settle_source = GLib.timeout_add(VOLUME_SETTLE_MS, self._settle)

    def _settle(self) -> bool:
        self._settle_source = 0
        self._settle_now()
        return False

    def _settle_now(self) -> None:
        if self._settle_source:
            GLib.source_remove(self._settle_source)
            self._settle_source = 0
        self.page.controller.commit_volume(self.kind)

    def _on_mute(self, switch: Gtk.Switch, _pspec) -> None:
        if self._quiet:
            return
        index = self.dropdown.get_selected()
        if 0 <= index < len(self.names):
            self.page.controller.set_mute(self.kind, self.names[index],
                                          switch.get_active())


class SoundPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(aud.BACKEND)
        if backend is None:  # normally created by the app, with a History applier
            backend = aud.Backend(self.ctx.workers)
            aud.register(self.ctx.history, backend)
            self.ctx.backends[aud.BACKEND] = backend
        self.backend = backend
        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self.kinds = {
            "sink": KindGroup(self, "sink", strings.AUDIO_GROUP_OUT),
            "source": KindGroup(self, "source", strings.AUDIO_GROUP_IN),
        }
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- the controller's view -----------------------------------------

    def show_audio(self, audio: aud.Audio) -> None:
        self.kinds["sink"].show(audio.sinks, audio.default_sink)
        self.kinds["source"].show(audio.sources, audio.default_source)

    def show_volume(self, kind: str, percent: int) -> None:
        group = self.kinds.get(kind)
        if group is not None:
            group.show_volume(percent)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = SoundPage
