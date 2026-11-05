"""The "Network and Bluetooth" page: Wi-Fi, Bluetooth, Tailscale."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import network as net  # noqa: E402
from ..controllers import network as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


class NetworkPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(net.BACKEND)
        if backend is None:
            backend = net.Backend(self.ctx.workers)
            net.register(self.ctx.history, backend)
            self.ctx.backends[net.BACKEND] = backend
        self.backend = backend
        self.controller = ctl.Controller(backend, self.ctx.history, self)

        wifi = self.add_group(Group(strings.NET_WIFI_GROUP))
        self.wifi_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.wifi_switch.connect("notify::active", self._on_wifi)
        self.rows["wifi.radio"] = wifi.add(Row(
            strings.NET_WIFI, strings.NET_WIFI_HINT, suffix=self.wifi_switch,
            row_id="wifi.radio"))
        self.current_label = Gtk.Label(label="")
        self.current_label.add_css_class("sh-dim")
        self.rows["wifi.current"] = wifi.add(Row(
            strings.NET_WIFI_CURRENT, suffix=self.current_label, row_id="wifi.current"))

        self.saved_group = self.add_group(Group(strings.NET_SAVED_GROUP))
        self.rows["wifi.saved"] = self.saved_group.add(
            Row(strings.NET_SAVED_EMPTY, row_id="wifi.saved"))
        self.visible_group = self.add_group(Group(strings.NET_VISIBLE_GROUP))

        bluetooth = self.add_group(Group(strings.NET_BLUETOOTH_GROUP))
        self.bt_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bt_switch.connect("notify::active", self._on_bluetooth)
        self.rows["bluetooth.power"] = bluetooth.add(Row(
            strings.NET_BLUETOOTH, strings.NET_BLUETOOTH_HINT, suffix=self.bt_switch,
            row_id="bluetooth.power"))
        self.bt_group = bluetooth
        self._bt_rows: list[Row] = []

        tailscale = self.add_group(Group(strings.NET_TAILSCALE_GROUP))
        self.tailscale_label = Gtk.Label(label="")
        self.tailscale_label.add_css_class("sh-dim")
        self.rows["tailscale"] = tailscale.add(Row(
            strings.NET_TAILSCALE, suffix=self.tailscale_label, row_id="tailscale"))
        self.tailscale_group = tailscale
        self._quiet = False
        self.refresh()

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- signals --------------------------------------------------------

    def _on_wifi(self, switch: Gtk.Switch, _pspec) -> None:
        if self._quiet:
            return
        if switch.get_active():
            self.controller.set_wifi(True)
            return

        def keep_on() -> None:
            self._quiet = True
            switch.set_active(True)
            self._quiet = False
            self.refresh()  # the radio may have changed while the question was up

        # It can be the only link, and Tailscale goes with it.
        self.confirm(strings.NET_WIFI_OFF_ASK, strings.NET_WIFI_OFF_DETAIL,
                     strings.NET_WIFI_OFF_OK, lambda: self.controller.set_wifi(False), keep_on)

    def _on_bluetooth(self, switch: Gtk.Switch, _pspec) -> None:
        if not self._quiet:
            self.controller.set_bluetooth(switch.get_active())

    # ---- the controller's view -----------------------------------------

    def show_network(self, info: net.Network) -> None:
        self._quiet = True
        try:
            if info.wifi_on is not None:
                self.wifi_switch.set_active(info.wifi_on)
            if info.bluetooth_on is not None:
                self.bt_switch.set_active(info.bluetooth_on)
                self.bt_switch.set_sensitive(True)
            else:
                self.bt_switch.set_sensitive(False)
        finally:
            self._quiet = False

        current = next((w for w in info.wifi if w.in_use), None)
        if current is not None:
            self.current_label.set_label(strings.NET_WIFI_SIGNAL.format(
                ssid=current.ssid, signal=current.signal))
        elif info.wifi_on is False:
            self.current_label.set_label(strings.NET_WIFI_OFF)
        else:
            self.current_label.set_label(strings.NET_WIFI_NONE)

        self.saved_group.clear()
        if not info.saved:
            self.rows["wifi.saved"] = self.saved_group.add(
                Row(strings.NET_SAVED_EMPTY, row_id="wifi.saved"))
        for index, saved in enumerate(info.saved):
            button = Gtk.Button(label=strings.NET_CONNECT)
            button.set_sensitive(not saved.active and bool(info.wifi_on))
            button.connect("clicked", lambda *_a, name=saved.name:
                           self.controller.connect(name))
            subtitle = strings.NET_SAVED_ACTIVE if saved.active else strings.NET_SAVED_OFF
            row = self.saved_group.add(Row(saved.name, subtitle, suffix=button,
                                           row_id=f"saved.{saved.name}"))
            if index == 0:  # what a search result for saved networks scrolls to
                self.rows["wifi.saved"] = row

        self.visible_group.clear()
        visible = [w for w in info.wifi if not w.in_use][:8]
        self.visible_group.set_visible(bool(visible))
        for wifi in visible:
            name = wifi.ssid if wifi.security and wifi.security != "--" else (
                wifi.ssid + strings.NET_OPEN_SUFFIX)
            self.visible_group.add(Row(
                strings.NET_VISIBLE.format(ssid=name),
                strings.NET_VISIBLE_DETAIL.format(signal=wifi.signal,
                                                  security=wifi.security or "—")))

        # Only the device rows change; the row with the switch stays where it is.
        for row in self._bt_rows:
            self.bt_group.list.remove(row)
        if info.bluetooth:
            self._bt_rows = [self.bt_group.add(Row(device.name, strings.NET_BT_CONNECTED,
                                                   row_id=f"bt.{device.name}"))
                             for device in info.bluetooth]
        else:
            self._bt_rows = [self.bt_group.add(Row(strings.NET_BT_NONE,
                                                   row_id="bluetooth.none"))]

        state = info.tailscale_state or strings.NET_UNKNOWN
        names = ", ".join(info.tailscale_names) or strings.NET_NO_IP
        self.tailscale_label.set_label(strings.NET_TAILSCALE_STATE.format(
            state=(state or "—"), addresses=names))

    def refresh_later(self, seconds: int) -> None:
        def again() -> bool:
            self.refresh()
            return False

        GLib.timeout_add_seconds(seconds, again)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = NetworkPage
