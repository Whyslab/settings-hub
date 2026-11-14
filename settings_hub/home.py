"""The home screen: tiles with what matters most, a button for every other page.

    home = Home(ctx, open_page, start_search)
    home.widget          # goes into the window's page stack as "home"
    home.refresh()       # re-read every tile (each on its own worker)

Each tile is a view of the same controller its page uses, so a change made on
a tile is applied and logged in History exactly as on the page. The tile's
heading is a button that opens the page.

The search field hands what is typed to the sidebar's search (start_search),
which shows the results.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import modes as hub_modes  # noqa: E402
from . import registry, strings  # noqa: E402
from .backends import audio as aud  # noqa: E402
from .backends import devices as dev  # noqa: E402
from .backends import network as net  # noqa: E402
from .backends import power as pw  # noqa: E402
from .backends import screen_sleep as ss_backend  # noqa: E402
from .backends import themes as th  # noqa: E402
from .controllers import audio as audio_ctl  # noqa: E402
from .controllers import modes as modes_ctl  # noqa: E402
from .controllers import network as net_ctl  # noqa: E402
from .controllers import power as power_ctl  # noqa: E402
from .controllers import screen_sleep as ss_ctl  # noqa: E402
from .controllers import themes as themes_ctl  # noqa: E402
from .pages.power import DEVICES_WORKER  # noqa: E402
from .pages.sound import VOLUME_SETTLE_MS  # noqa: E402
from .widgets.icons import icon  # noqa: E402

HOME = "home"  # the window's id for this screen; not a registry page
TILE_PAGES = ("screen-sleep", "sound", "network", "power", "modes", "themes")
SMALL_COLUMNS = 5
THEME_SWATCHES = 4
SWATCH_W, SWATCH_H = 60, 58  # the smallest; they share the tile's width
CLICK_LOCK_S = 5  # a picked button waits for the refresh, at most this long


def backend(ctx, name: str, make, register=None):
    """The window's backend of this name, made (and registered) if it has none."""
    found = ctx.backends.get(name)
    if found is None:
        found = make(ctx.workers)
        if register is not None:
            register(ctx.history, found)
        ctx.backends[name] = found
    return found


class Seg(Gtk.Box):
    """Joined toggle buttons; on_pick(value) runs only for a person's click."""

    def __init__(self, items: list[tuple[str, str]], on_pick, columns: int = 0) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.add_css_class("sh-seg")
        self.on_pick = on_pick
        self.buttons: dict[str, Gtk.ToggleButton] = {}
        self._quiet = False
        per_row = columns or len(items)
        line = None
        for index, (value, label) in enumerate(items):
            if index % per_row == 0:
                line = Gtk.Box(spacing=3, homogeneous=True)
                self.append(line)
            button = Gtk.ToggleButton(label=label, hexpand=True)
            button.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            button.connect("toggled", self._toggled, value)
            line.append(button)
            self.buttons[value] = button

    def show(self, active: set[str] | str | None) -> None:
        """What is on now; also unlocks every button (callers lock some again)."""
        chosen = {active} if isinstance(active, str) else set(active or ())
        self._quiet = True
        try:
            for value, button in self.buttons.items():
                button.set_active(value in chosen)
                button.set_sensitive(True)
        finally:
            self._quiet = False

    def _toggled(self, button: Gtk.ToggleButton, value: str) -> None:
        if self._quiet:
            return
        # A click must not change the look by itself: the refresh after the
        # change shows what is really on. Until then the button is locked, so
        # a second click cannot act on a stale state (a mode turned off and
        # straight back on); if no refresh comes, it unlocks on its own.
        self._quiet = True
        button.set_active(not button.get_active())
        self._quiet = False
        button.set_sensitive(False)
        GLib.timeout_add_seconds(CLICK_LOCK_S, lambda: button.set_sensitive(True) and False)
        self.on_pick(value)


class Tile(Gtk.Box):
    page_id = ""

    def __init__(self, home: Home) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.home = home
        self.ctx = home.ctx
        self.add_css_class("sh-tile")
        top = Gtk.Box(spacing=10)
        head = Gtk.Button(hexpand=True)
        head.add_css_class("sh-tile-head")
        head.set_tooltip_text(strings.HOME_OPEN.format(title=registry.title(self.page_id)))
        head.connect("clicked", lambda *_: home.open_page(self.page_id, ""))
        inner = Gtk.Box(spacing=12)
        badge = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
        badge.add_css_class("sh-badge")
        glyph = icon(self.page_id, 18)
        glyph.set_hexpand(True)  # centred in the square ...
        badge.set_hexpand(False)  # ... which stays a square
        badge.append(glyph)
        inner.append(badge)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                        hexpand=True)
        name = Gtk.Label(label=registry.title(self.page_id), xalign=0, wrap=True,
                         wrap_mode=Pango.WrapMode.WORD_CHAR, lines=2,
                         ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("sh-tile-title")
        texts.append(name)
        self.sub = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, visible=False)
        self.sub.add_css_class("sh-dim")
        self.sub.add_css_class("sh-small-text")
        texts.append(self.sub)
        inner.append(texts)
        head.set_child(inner)
        top.append(head)
        self.top = top
        self.append(top)
        self.build()

    def set_sub(self, text: str) -> None:
        self.sub.set_label(text)
        self.sub.set_visible(bool(text))

    def big(self, text: str = "—") -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class("sh-big")
        return label

    def dim(self, text: str = "") -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class("sh-dim")
        label.add_css_class("sh-small-text")
        return label

    def spacer(self) -> None:
        self.append(Gtk.Box(vexpand=True))

    def status(self, text: str) -> None:
        self.ctx.status(text)

    def build(self) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError


# ---- Screen and sleep ---------------------------------------------------------

class ScreenTile(Tile):
    page_id = "screen-sleep"
    STEPS = ("dim", "lock", "dpms")

    def build(self) -> None:
        self.backend = backend(self.ctx, ss_backend.BACKEND, ss_backend.Backend,
                               ss_backend.register)
        self.health = Gtk.Box(spacing=7, valign=Gtk.Align.CENTER)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.dot.add_css_class("sh-dot")
        self.health_label = self.dim()
        self.health.append(self.dot)
        self.health.append(self.health_label)
        self.health.set_visible(False)
        self.top.append(self.health)

        numbers = Gtk.Box(spacing=10, homogeneous=True)
        self.numbers: dict[str, Gtk.Label] = {}
        for step in self.STEPS:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            value = Gtk.Label(label="—", xalign=0)
            value.add_css_class("sh-mid")
            box.append(value)
            box.append(self.dim(strings.HOME_STEPS[step]))
            numbers.append(box)
            self.numbers[step] = value
        self.append(numbers)
        self.spacer()
        self.presets = Seg(list(strings.SS_PRESETS.items()), self._preset)
        self.append(self.presets)

        self.profile = "ac"
        self.probed = False  # the power source is known: presets go to the right set
        self.values: dict[str, dict] = {}
        self.ok_state = False
        self.presets.set_sensitive(False)
        self.controller = ss_ctl.Controller(self.backend, self.ctx.history, self,
                                            settings=self.ctx.settings)

    def refresh(self) -> None:
        self.controller.refresh()

    def _preset(self, preset_id: str) -> None:
        if self.ok_state and self.probed:
            self.controller.preset(self.profile, preset_id)

    def _show_numbers(self) -> None:
        for step, label in self.numbers.items():
            value = self.values.get(f"idle.{self.profile}.{step}")
            if value is None:
                label.set_label("—")
            elif value["enabled"]:
                label.set_label(f"{value['minutes']} {strings.SS_MINUTES}")
            else:
                label.set_label(strings.HOME_OFF)
        try:
            presets = self.backend.ss.common.PRESETS
        except Exception:  # screen-sleep not found: no preset is "on"
            presets = {}
        on = set()
        for preset_id, name in strings.SS_PRESETS.items():
            minutes = presets.get(name)
            if not minutes:
                continue
            same = True
            for step in ss_ctl.STEPS:
                value = self.values.get(f"idle.{self.profile}.{step}")
                if value is None:
                    same = False
                elif minutes[step] is None:
                    same = same and not value["enabled"]
                else:
                    same = same and value["enabled"] and value["minutes"] == minutes[step]
            if same:
                on.add(preset_id)
        self.presets.show(on)

    # the controller's view
    def show(self, key: str, value) -> None:
        if key.startswith("idle."):
            self.values[key] = value
            self._show_numbers()

    def focused(self, _key: str) -> bool:
        return False

    def show_order(self, _profile: str, _bad: bool) -> None:
        pass

    def show_probe(self, probe: ss_backend.Probe) -> None:
        if probe.power in strings.SS_POWER_NAMES:
            self.profile = probe.power
            self.probed = True
            self.presets.set_sensitive(self.ok_state)
            self.set_sub(strings.HOME_NOW.format(power=strings.SS_POWER_NAMES[probe.power]))
            self._show_numbers()
        good = all(ok for ok, _msg in (probe.hyprsunset, probe.daemon)) and probe.hypridle
        self.dot.remove_css_class("ok" if not good else "bad")
        self.dot.add_css_class("ok" if good else "bad")
        self.health_label.set_label(strings.HOME_ALL_OK if good else strings.HOME_SOMETHING_DOWN)
        self.health.set_visible(True)

    def show_setup(self, state: str, _detail: str) -> None:
        self.ok_state = state == "ok"
        self.presets.set_sensitive(self.ok_state and self.probed)
        if not self.ok_state:
            self.set_sub(strings.HOME_NOT_SET_UP)
            self.health.set_visible(False)


# ---- Sound ------------------------------------------------------------------

class SoundTile(Tile):
    page_id = "sound"

    def build(self) -> None:
        self.backend = backend(self.ctx, aud.BACKEND, aud.Backend, aud.register)
        self.value = self.big()
        self.append(self.value)
        self.spacer()
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_round_digits(0)
        self.scale.set_increments(5, 10)
        self.scale.set_sensitive(False)
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], [strings.AUDIO_VOLUME])
        self.scale.connect("value-changed", self._moved)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda *_: self._settle_now())
        self.scale.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._settle_now())
        self.scale.add_controller(focus)
        # The home screen is the first thing seen: a wheel turned over the
        # slider must not change the volume (the slider is dragged or keyed).
        wheel = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        wheel.connect("scroll", lambda *_: True)
        self.scale.add_controller(wheel)
        self.append(self.scale)
        self.device = self.dim()
        self.append(self.device)
        self._quiet = False
        self._settle_source = 0
        self.controller = audio_ctl.Controller(self.backend, self.ctx.history, self)

    def refresh(self) -> None:
        self.controller.refresh()

    def _moved(self, scale: Gtk.Scale) -> None:
        percent = int(round(scale.get_value()))
        self.value.set_label(strings.AUDIO_PERCENT.format(percent=percent))
        if self._quiet:
            return
        self.controller.volume_moved("sink", percent)
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
        self.controller.commit_volume("sink")

    def _show_percent(self, percent: int, mute: bool = False) -> None:
        self._quiet = True
        try:
            self.scale.set_value(min(100, percent))
        finally:
            self._quiet = False
        text = strings.AUDIO_PERCENT.format(percent=percent)
        self.value.set_label(f"{text} · {strings.HOME_MUTED}" if mute else text)

    # the controller's view
    def show_audio(self, audio: aud.Audio) -> None:
        device = next((d for d in audio.sinks if d.name == audio.default_sink), None)
        self.scale.set_sensitive(device is not None)
        if device is None:
            self.value.set_label("—")
            self.device.set_label(strings.HOME_NO_SOUND)
            return
        self._show_percent(device.volume, device.mute)
        self.device.set_label(device.description)

    def show_volume(self, kind: str, percent: int) -> None:
        if kind == "sink":
            self._show_percent(percent)


# ---- Network and Bluetooth --------------------------------------------------

class NetworkTile(Tile):
    page_id = "network"

    def build(self) -> None:
        self.backend = backend(self.ctx, net.BACKEND, net.Backend, net.register)
        self.wifi_label = Gtk.Label(label="—", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.wifi_label.add_css_class("sh-mid")
        self.append(self.wifi_label)
        self.bt_label = self.dim()
        self.append(self.bt_label)
        self.spacer()
        self.radios = Seg([("wifi", strings.NET_WIFI), ("bt", strings.NET_BLUETOOTH)],
                          self._pick)
        self.append(self.radios)
        self.info: net.Network | None = None
        self.controller = net_ctl.Controller(self.backend, self.ctx.history, self)

    def refresh(self) -> None:
        self.controller.refresh()

    def _pick(self, which: str) -> None:
        if self.info is None:
            return
        if which == "bt":
            if self.info.bluetooth_on is not None:
                self.controller.set_bluetooth(not self.info.bluetooth_on)
            return
        if self.info.wifi_on is None:  # unknown (nmcli did not answer): do nothing
            return
        if not self.info.wifi_on:
            self.controller.set_wifi(True)
            return
        # It can be the only link, and Tailscale goes with it (as on the page).
        dialog = Gtk.AlertDialog(message=strings.NET_WIFI_OFF_ASK,
                                 detail=strings.NET_WIFI_OFF_DETAIL,
                                 buttons=[strings.NET_WIFI_OFF_OK,
                                          strings.HISTORY_CONFLICT_CANCEL],
                                 cancel_button=1, default_button=1, modal=True)

        def answered(dlg, result) -> None:
            try:
                choice = dlg.choose_finish(result)
            except GLib.Error:
                choice = 1
            if choice == 0:
                self.controller.set_wifi(False)

        dialog.choose(self.get_root(), None, answered)

    # the controller's view
    def show_network(self, info: net.Network) -> None:
        self.info = info
        current = next((w for w in info.wifi if w.in_use), None)
        if current is not None:
            self.wifi_label.set_label(strings.HOME_WIFI_ON.format(ssid=current.ssid))
        elif info.wifi_on is False:
            self.wifi_label.set_label(strings.HOME_WIFI_OFF)
        else:
            self.wifi_label.set_label(strings.HOME_WIFI_NONE)
        connected = [d.name for d in info.bluetooth if d.connected]
        if info.bluetooth_on and connected:
            self.bt_label.set_label(strings.HOME_BT_DEVICES.format(names=", ".join(connected)))
        elif info.bluetooth_on:
            self.bt_label.set_label(strings.HOME_BT_ON)
        else:
            self.bt_label.set_label(strings.HOME_BT_OFF)
        on = set()
        if info.wifi_on:
            on.add("wifi")
        if info.bluetooth_on:
            on.add("bt")
        self.radios.show(on)
        self.radios.buttons["wifi"].set_sensitive(info.wifi_on is not None)
        self.radios.buttons["bt"].set_sensitive(info.bluetooth_on is not None)

    def refresh_later(self, seconds: int) -> None:
        GLib.timeout_add_seconds(seconds, lambda: self.refresh() and False)


# ---- Power and brightness ---------------------------------------------------

class PowerTile(Tile):
    page_id = "power"

    def build(self) -> None:
        self.backend = backend(self.ctx, pw.BACKEND, pw.Backend, pw.register)
        self.value = self.big()
        self.append(self.value)
        self.spacer()
        self.extra = self.dim()
        self.extra.set_wrap(True)
        self.extra.set_ellipsize(Pango.EllipsizeMode.NONE)
        self.append(self.extra)
        self.devices: list[dev.Device] = []
        self.brightness: int | None = None
        self.controller = power_ctl.Controller(self.backend, self.ctx.history, self)

    def refresh(self) -> None:
        self.controller.refresh()
        self.ctx.workers.submit(DEVICES_WORKER, dev.probe, self._devices_read, key="home")

    def _devices_read(self, devices, error: BaseException | None) -> None:
        self.devices = list(devices or []) if error is None else []
        self._show_extra()

    def _show_extra(self) -> None:
        parts = []
        for device in self.devices:
            if device.percent is not None:
                kind = strings.POWER_DEVICE_KINDS.get(device.kind, device.name)
                parts.append(strings.HOME_DEVICE.format(kind=kind, percent=device.percent))
        if self.brightness is not None:
            parts.append(strings.HOME_BRIGHTNESS.format(percent=self.brightness))
        self.extra.set_label(" · ".join(parts))

    # the controller's view
    def show_power(self, info: pw.Power) -> None:
        if info.charge is None:
            self.value.set_label(strings.POWER_NO_BATTERY)
            self.set_sub("")
        else:
            self.value.set_label(strings.POWER_PERCENT.format(percent=info.charge))
            self.set_sub(strings.POWER_STATES.get(info.status, info.status))
        self.brightness = info.brightness
        self._show_extra()

    def show_brightness(self, percent: int) -> None:
        self.brightness = percent
        self._show_extra()


# ---- Modes -------------------------------------------------------------------

class ModesTile(Tile):
    page_id = "modes"

    def build(self) -> None:
        hint = self.dim(strings.HOME_MODES_HINT)
        hint.set_wrap(True)
        hint.set_ellipsize(Pango.EllipsizeMode.NONE)
        self.append(hint)
        self.spacer()
        self.modes = Seg([(m.id, strings.MODES[m.id][0]) for m in hub_modes.MODES],
                         self._pick, columns=2)
        self.append(self.modes)
        self._on_group: dict[str, list[str]] = {}
        self.controller = modes_ctl.Controller(self.ctx.history, self.ctx.workers, self)

    def refresh(self) -> None:
        self.controller.refresh()

    def _pick(self, mode_id: str) -> None:
        group_ids = self._on_group.pop(mode_id, None)
        if group_ids is None:
            self.controller.apply(mode_id)
        elif self.ctx.undo_group is not None:
            self.ctx.undo_group(group_ids)  # back to how it was before the mode

    # the controller's view
    def show_active(self, active: set[str]) -> None:
        groups = self.ctx.history.groups() if active else []
        self._on_group.clear()
        for mode_id in active:
            group_ids = hub_modes.groups_that_turned_on(
                hub_modes.BY_ID[mode_id], groups, strings.HISTORY_UNDO_PREFIX)
            if group_ids:
                self._on_group[mode_id] = group_ids
        self.modes.show(active)
        for mode_id, button in self.modes.buttons.items():
            # On by coincidence, without its History groups: nothing to go back to.
            button.set_sensitive(mode_id not in active or mode_id in self._on_group)


# ---- Themes -------------------------------------------------------------------

class ThemesTile(Tile):
    page_id = "themes"

    def build(self) -> None:
        self.backend = backend(self.ctx, th.BACKEND, th.Backend, th.register)
        self.set_sub(strings.HOME_THEMES_HINT)
        self.spacer()
        self.row = Gtk.Box(spacing=10, homogeneous=True)
        self.append(self.row)
        self.swatches: list[tuple[str, Gtk.ToggleButton]] = []
        self._quiet = False
        self.controller = themes_ctl.Controller(self.backend, self.ctx.history, self)

    def refresh(self) -> None:
        self.controller.refresh()

    def _clicked(self, button: Gtk.ToggleButton, theme_id: str) -> None:
        if self._quiet:
            return
        self._quiet = True
        button.set_active(not button.get_active())  # the refresh shows the result
        self._quiet = False
        self.controller.choose(theme_id)

    # the controller's view
    def show(self, themes: list[th.ThemeInfo], state: th.State) -> None:
        from .pages.themes import draw_preview  # its GTK page module, only for drawing

        self.set_sub(strings.HOME_THEMES_HINT)
        self.row.set_visible(True)
        shown = list(themes[:THEME_SWATCHES])
        active = next((t for t in themes if t.id == state.system), None)
        if active is not None and active not in shown and shown:
            shown[-1] = active
        if [t.id for t in shown] != [theme_id for theme_id, _b in self.swatches]:
            while (child := self.row.get_first_child()) is not None:
                self.row.remove(child)
            self.swatches = []
            for theme in shown:
                area = Gtk.DrawingArea(content_width=SWATCH_W, content_height=SWATCH_H,
                                       hexpand=True)
                area.set_draw_func(lambda _a, cr, w, h, t=theme: draw_preview(cr, w, h, t))
                button = Gtk.ToggleButton()
                button.add_css_class("sh-swatch")
                button.set_overflow(Gtk.Overflow.HIDDEN)
                button.set_child(area)
                button.set_tooltip_text(theme.name)
                button.update_property([Gtk.AccessibleProperty.LABEL], [theme.name])
                button.connect("toggled", self._clicked, theme.id)
                self.row.append(button)
                self.swatches.append((theme.id, button))
        self._quiet = True
        try:
            for theme_id, button in self.swatches:
                button.set_active(theme_id == state.system)
        finally:
            self._quiet = False

    def show_missing(self, _detail: str) -> None:
        self.set_sub(strings.HOME_THEMES_MISSING)
        self.row.set_visible(False)

    def show_walls(self, _theme_id: str, _paths: list[str]) -> None:
        pass

    def busy(self, on: bool) -> None:
        self.row.set_sensitive(not on)

    def custom_saved(self) -> None:
        pass


# ---- the screen ---------------------------------------------------------------

class Home:
    def __init__(self, ctx, open_page, start_search) -> None:
        self.ctx = ctx
        self.open_page = open_page  # (page_id, row_id)
        self._start_search = start_search  # (text)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.add_css_class("sh-home")

        header = Gtk.Box(spacing=16)
        title = Gtk.Label(label=strings.APP_TITLE, xalign=0, hexpand=True)
        title.add_css_class("sh-home-title")
        header.append(title)
        self.entry = Gtk.SearchEntry(placeholder_text=strings.HOME_SEARCH)
        self.entry.add_css_class("sh-home-search")
        self.entry.set_size_request(300, -1)
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.connect("changed", self._typed)
        header.append(self.entry)
        box.append(header)

        grid = Gtk.Grid(column_spacing=14, row_spacing=12, column_homogeneous=True)
        grid.add_css_class("sh-home-tiles")
        self.tiles: list[Tile] = [ScreenTile(self), SoundTile(self), NetworkTile(self),
                                  PowerTile(self), ModesTile(self), ThemesTile(self)]
        places = ((0, 0, 2), (2, 0, 1), (3, 0, 1), (0, 1, 1), (1, 1, 1), (2, 1, 2))
        for tile, (col, row, span) in zip(self.tiles, places, strict=True):
            grid.attach(tile, col, row, span, 1)
        box.append(grid)

        small = Gtk.Grid(column_spacing=12, row_spacing=10, column_homogeneous=True)
        others = [p for p in registry.PAGES if p.id not in TILE_PAGES]
        for index, page in enumerate(others):
            button = Gtk.Button()
            button.add_css_class("sh-small")
            inner = Gtk.Box(spacing=10)
            inner.append(icon(page.id, 18))
            # Whole words on up to two lines: "Клавиатура и мышь" fits a narrow column.
            inner.append(Gtk.Label(label=registry.title(page.id), xalign=0, hexpand=True,
                                   wrap=True, wrap_mode=Pango.WrapMode.WORD, lines=2,
                                   ellipsize=Pango.EllipsizeMode.END, width_chars=6))
            button.set_child(inner)
            button.set_tooltip_text(registry.title(page.id))
            button.connect("clicked", lambda *_a, pid=page.id: self.open_page(pid, ""))
            small.attach(button, index % SMALL_COLUMNS, index // SMALL_COLUMNS, 1, 1)
        box.append(small)

        self.widget = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        # Sideways too: a window narrower than the tiles scrolls instead of growing.
        self.widget.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.widget.set_child(box)

    def refresh(self) -> None:
        for tile in self.tiles:
            tile.refresh()

    def focus_first(self) -> bool:
        return self.tiles[0].top.get_first_child().grab_focus()

    def _typed(self, entry: Gtk.SearchEntry) -> None:
        text = entry.get_text()
        if text:
            entry.set_text("")  # the sidebar's field takes it from here
            self._start_search(text)
