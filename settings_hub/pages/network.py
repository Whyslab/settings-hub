"""The "Network and Bluetooth" page: Wi-Fi, Bluetooth, Tailscale."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import bluez as bz  # noqa: E402
from ..backends import network as net  # noqa: E402
from ..backends import nm_wifi  # noqa: E402
from ..controllers import bluetooth as btctl  # noqa: E402
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
        self._join_buttons: dict[str, Gtk.Button] = {}  # ssid -> its "Connect"
        self._joining = ""  # the ssid being joined now
        self._joining_hidden = False
        self._deferred: net.Network | None = None  # a redraw held while a form is open
        self._last_info: net.Network | None = None  # what the visible networks show
        self._join_errors: dict[str, str] = {}  # ssid ("" = hidden) -> why it failed
        self._reopen: str | None = None  # popover to show again after a failure
        self.hidden_menu = Gtk.MenuButton(label=strings.NET_HIDDEN_BUTTON,
                                          valign=Gtk.Align.CENTER)
        self.hidden_menu.set_popover(self._join_popover("", hidden=True))
        # The last row of the visible networks (added again after each redraw).
        self.hidden_row = Row(strings.NET_HIDDEN, strings.NET_HIDDEN_HINT,
                              suffix=self.hidden_menu, row_id="wifi.hidden")
        self.rows["wifi.hidden"] = self.visible_group.add(self.hidden_row)
        self.rows["wifi.visible"] = self.rows["wifi.hidden"]  # until networks are seen

        bluetooth = self.add_group(Group(strings.NET_BLUETOOTH_GROUP))
        self.bt_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.bt_switch.connect("notify::active", self._on_bluetooth)
        self.rows["bluetooth.power"] = bluetooth.add(Row(
            strings.NET_BLUETOOTH, strings.NET_BLUETOOTH_HINT, suffix=self.bt_switch,
            row_id="bluetooth.power"))
        self.rows["bluetooth.devices"] = self.rows["bluetooth.power"]
        self.bt_group = bluetooth
        self._bt_rows: list[Row] = []
        bz_backend = self.ctx.backends.get("bluez")
        if bz_backend is None:
            bz_backend = bz.Backend(self.ctx.workers)
            self.ctx.backends["bluez"] = bz_backend
        self.bt = btctl.Controller(
            bz_backend, self, lambda seconds, fn: GLib.timeout_add_seconds(
                seconds, lambda: fn() and False), GLib.source_remove)
        self.search_button = Gtk.Button(label=strings.BT_SEARCH_BUTTON)
        self.search_button.connect("clicked", lambda *_: self._on_search())
        self.found_group = self.add_group(Group(strings.BT_SEARCH))
        self.rows["bluetooth.search"] = self.found_group.add(Row(
            strings.BT_SEARCH, strings.BT_SEARCH_HINT.format(seconds=bz.SEARCH_S),
            suffix=self.search_button, row_id="bluetooth.search"))
        self._found_rows: list[Row] = []
        self.widget.connect("unmap", lambda *_: self.bt.stop_search())

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
        self.bt.refresh()

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
            button = None  # the network in use needs no "Connect": its subtitle says so
            if not saved.active:
                button = Gtk.Button(label=strings.NET_CONNECT)
                button.set_sensitive(bool(info.wifi_on))
                button.connect("clicked", lambda *_a, name=saved.name:
                               self.controller.connect(name))
            subtitle = strings.NET_SAVED_ACTIVE if saved.active else strings.NET_SAVED_OFF
            row = self.saved_group.add(Row(saved.name, subtitle, suffix=button,
                                           row_id=f"saved.{saved.name}"))
            if index == 0:  # what a search result for saved networks scrolls to
                self.rows["wifi.saved"] = row

        # A redraw would destroy an open password form (and what was typed in it):
        # the visible networks wait until it closes.
        if self._form_open():
            self._deferred = info
        else:
            self._show_visible(info)

        # The device rows come from BlueZ (show_bluetooth); the radio may have
        # changed, so read them again.
        self.bt.refresh()

        state = info.tailscale_state or strings.NET_UNKNOWN
        names = ", ".join(info.tailscale_names) or strings.NET_NO_IP
        self.tailscale_label.set_label(strings.NET_TAILSCALE_STATE.format(
            state=(state or "—"), addresses=names))

    def _form_open(self) -> bool:
        menus = [self.hidden_menu, *self._join_buttons.values()]
        return any(isinstance(m, Gtk.MenuButton) and m.get_popover() is not None
                   and m.get_popover().get_visible() for m in menus)

    def _form_closed(self) -> None:
        if self._deferred is not None and not self._form_open():
            info, self._deferred = self._deferred, None
            self._show_visible(info)

    def _show_visible(self, info: net.Network) -> None:
        self.visible_group.clear()
        self._join_buttons.clear()
        self._last_info = info
        saved_names = {s.name for s in info.saved}
        self.rows["wifi.visible"] = self.rows["wifi.hidden"]
        for index, (wifi, kind, mixed) in enumerate(one_per_name(info.wifi)[:8]):
            name = wifi.ssid if kind != nm_wifi.OPEN else wifi.ssid + strings.NET_OPEN_SUFFIX
            detail = strings.NET_VISIBLE_DETAIL.format(signal=wifi.signal,
                                                       security=wifi.security or "—")
            row = self.visible_group.add(Row(
                strings.NET_VISIBLE.format(ssid=name),
                detail + (strings.NET_VISIBLE_MIXED if mixed else ""),
                suffix=self._join_widget(wifi, kind, wifi.ssid in saved_names,
                                         bool(info.wifi_on)),
                row_id=f"visible.{wifi.ssid}"))
            if index == 0:
                self.rows["wifi.visible"] = row
        self.visible_group.add(self.hidden_row)
        self.hidden_menu.set_sensitive(bool(info.wifi_on) and not self._joining)
        if self._reopen is not None:
            key, self._reopen = self._reopen, None
            target = self.hidden_menu if key == "" else self._join_buttons.get(key)
            if isinstance(target, Gtk.MenuButton) and self.widget.get_mapped():
                GLib.idle_add(lambda: target.popup() and False)

    # ---- Bluetooth devices -------------------------------------------------

    def _on_search(self) -> None:
        if self.bt.searching:
            self.bt.stop_search()
        else:
            self.bt.start_search()

    def show_bluetooth(self, state: bz.State, busy: set[str], searching: bool) -> None:
        """Paired devices under the switch; new ones (while searching) in their group."""
        on = state.powered
        for row in self._bt_rows:
            self.bt_group.list.remove(row)
        self._bt_rows = []
        for device in state.paired:
            self._bt_rows.append(self.bt_group.add(self._device_row(device, busy, on)))
        if not self._bt_rows:
            if state.adapter:
                title, why = strings.BT_MY_DEVICES_NONE, None
            else:  # no adapter, or BlueZ did not answer: say why, once, here
                title, why = strings.BT_NO_DEVICES_LIST, state.error or strings.BT_ERR_NO_BLUEZ
            self._bt_rows.append(self.bt_group.add(Row(title, why, row_id="bluetooth.none")))
        self.rows["bluetooth.devices"] = self._bt_rows[0]

        self.search_button.set_label(strings.BT_SEARCH_STOP if searching
                                     else strings.BT_SEARCH_BUTTON)
        self.search_button.set_sensitive(bool(state.adapter) and on)
        for row in self._found_rows:
            self.found_group.list.remove(row)
        self._found_rows = []
        if searching or state.found:
            for device in state.found[:12]:
                button = Gtk.Button(label=strings.BT_WORKING if device.path in busy
                                    else strings.BT_PAIR)
                button.set_sensitive(on and device.path not in busy)
                button.connect("clicked", lambda *_a, d=device: self._ask_pair(d))
                self._found_rows.append(self.found_group.add(Row(
                    device.name, strings.BT_FOUND_DETAIL.format(
                        kind=bt_kind(device.icon), address=device.address),
                    suffix=button, row_id=f"bt-new.{device.address}")))
            if searching and not state.found:
                spinner = Gtk.Spinner(spinning=True)
                self._found_rows.append(self.found_group.add(Row(
                    strings.BT_SEARCHING, strings.BT_FOUND_NONE, suffix=spinner,
                    row_id="bluetooth.found-none")))

    def _ask_pair(self, device: bz.Device) -> None:
        """Pairing trusts the device: it may reconnect by itself later. Ask first."""
        risky = bz.risky(device)
        detail = strings.BT_PAIR_DETAIL_RISKY if risky else strings.BT_PAIR_DETAIL
        self.confirm(strings.BT_PAIR_ASK.format(name=device.name),
                     detail.format(kind=bt_kind(device.icon), address=device.address),
                     strings.BT_PAIR, lambda: self.bt.pair(device.path, input_ok=risky))

    def _device_row(self, device: bz.Device, busy: set[str], on: bool) -> Row:
        subtitle = strings.BT_CONNECTED if device.connected else strings.BT_NOT_CONNECTED
        if device.battery is not None:
            subtitle += strings.BT_BATTERY.format(percent=device.battery)
        box = Gtk.Box(spacing=6)
        working = device.path in busy
        main = Gtk.Button(label=strings.BT_WORKING if working else (
            strings.BT_DISCONNECT if device.connected else strings.BT_CONNECT))
        main.set_sensitive(on and not working)
        main.connect("clicked", lambda *_a, d=device: (
            self.bt.disconnect(d.path) if d.connected else self.bt.connect(d.path)))
        box.append(main)
        forget = Gtk.Button(label=strings.BT_FORGET, sensitive=not working)
        forget.add_css_class("flat")
        forget.set_tooltip_text(strings.BT_FORGET_TIP)
        forget.connect("clicked", lambda *_a, d=device: self.confirm(
            strings.BT_FORGET_ASK.format(name=d.name), strings.BT_FORGET_DETAIL,
            strings.BT_FORGET, lambda: self.bt.forget(d.path)))
        box.append(forget)
        return Row(device.name, subtitle, suffix=box, row_id=f"bt.{device.address}")

    # ---- joining a new network --------------------------------------------

    def _join_widget(self, wifi: net.Wifi, kind: str, saved: bool,
                     radio_on: bool) -> Gtk.Widget:
        """A visible network's button: saved -> connect; open -> join; else ask."""
        if saved:
            button = Gtk.Button(label=strings.NET_CONNECT)
            button.connect("clicked", lambda *_a, n=wifi.ssid: self.controller.connect(n))
        elif kind in (nm_wifi.ENTERPRISE, nm_wifi.WEP):
            button = Gtk.Button(label=strings.NET_JOIN, sensitive=False)
            button.set_tooltip_text(strings.NET_JOIN_UNSUPPORTED_TIP)
            self._join_buttons[wifi.ssid] = button
            return button
        elif kind in nm_wifi.NO_PASSWORD:
            button = Gtk.Button(label=strings.NET_JOIN)
            button.connect("clicked", lambda *_a, n=wifi.ssid, k=kind: self._join(
                n, "", expect=k))
        else:
            button = Gtk.MenuButton(label=strings.NET_JOIN)
            button.set_popover(self._join_popover(wifi.ssid))
        joining = self._joining == wifi.ssid
        if joining:
            button.set_label(strings.NET_JOINING)
        button.set_sensitive(radio_on and not self._joining)
        self._join_buttons[wifi.ssid] = button
        return button

    def _join_popover(self, ssid: str, hidden: bool = False) -> Gtk.Popover:
        """A small form under the button: the password (and the name of a hidden network)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("sh-popover-form")
        name_entry = None
        if hidden:
            name_entry = Gtk.Entry(placeholder_text=strings.NET_JOIN_SSID, max_length=32)
            box.append(name_entry)
        password = Gtk.PasswordEntry(show_peek_icon=True,
                                     placeholder_text=strings.NET_JOIN_PASSWORD)
        if ssid:
            password.set_tooltip_text(strings.NET_JOIN_PASSWORD_HINT.format(ssid=ssid))
        box.append(password)
        key = "" if hidden else ssid
        error = Gtk.Label(xalign=0, wrap=True, max_width_chars=32,
                          label=self._join_errors.get(key, ""),
                          visible=bool(self._join_errors.get(key)))
        error.add_css_class("sh-warning")
        box.append(error)
        go = Gtk.Button(label=strings.NET_JOIN)
        go.add_css_class("suggested-action")
        box.append(go)
        popover = Gtk.Popover(child=box)
        popover.join_error = error  # the hidden form is built once: updated in place

        def submit(*_args) -> None:
            target = name_entry.get_text().strip() if name_entry is not None else ssid
            if not target:
                if name_entry is not None:
                    name_entry.grab_focus()
                return
            secret = password.get_text()
            password.set_text("")  # nothing lingers in the widget
            error.set_visible(False)
            self._join_errors.pop(key, None)
            popover.popdown()
            self._join(target, secret, hidden=hidden,
                       expect="" if hidden else nm_wifi.PERSONAL)

        def closed(*_args) -> None:
            password.set_text("")  # closed without joining: forget what was typed
            GLib.idle_add(lambda: self._form_closed() and False)

        go.connect("clicked", submit)
        popover.connect("closed", closed)
        password.connect("activate", submit)
        if name_entry is not None:
            name_entry.connect("activate", lambda *_: password.grab_focus())
        popover.connect("show", lambda *_: (name_entry or password).grab_focus())
        return popover

    def _join(self, ssid: str, password: str, hidden: bool = False, expect: str = "") -> None:
        if self._joining:
            return
        self._joining = ssid
        self._joining_hidden = hidden
        for button in self._join_buttons.values():
            button.set_sensitive(False)
        if ssid in self._join_buttons:
            self._join_buttons[ssid].set_label(strings.NET_JOINING)
        self.hidden_menu.set_sensitive(False)
        self.controller.join(ssid, password, hidden, expect)

    def join_finished(self, ssid: str, error: str) -> None:
        """A failure opens the form again with the reason. The buttons come back at
        once: a busy refusal or a failed read brings no redraw of its own."""
        hidden = self._joining_hidden
        self._joining = ""
        key = "" if hidden else ssid
        if error:
            self._join_errors[key] = error
            if hidden:
                form = self.hidden_menu.get_popover()
                form.join_error.set_label(error)
                form.join_error.set_visible(True)
            self._reopen = key
        else:
            self._join_errors.pop(key, None)
        if self._last_info is not None and not self._form_open():
            self._show_visible(self._last_info)  # also reopens the form (_reopen)

    def refresh_later(self, seconds: int) -> None:
        def again() -> bool:
            self.refresh()
            return False

        GLib.timeout_add_seconds(seconds, again)

    def status(self, text: str) -> None:
        self.ctx.status(text)


_KIND_ORDER = {nm_wifi.PERSONAL: 0, nm_wifi.OWE: 1, nm_wifi.ENTERPRISE: 2, nm_wifi.WEP: 3,
               nm_wifi.OPEN: 4}


def one_per_name(networks: list[net.Wifi]) -> list[tuple[net.Wifi, str, bool]]:
    """nmcli lists every access point: a mesh or a 2.4/5 GHz router shows one name
    several times. -> (the strongest point, its kind, mixed?) per name, in list order.

    mixed: the name is seen with different kinds of security -- a likely evil twin.
    The row then offers the protected kind (an open twin cannot take the password:
    nm_wifi only joins points of the kind the page expects).
    """
    order: list[str] = []
    points: dict[str, list[tuple[net.Wifi, str]]] = {}
    in_use = {w.ssid for w in networks if w.in_use}
    for wifi in networks:
        if wifi.in_use or wifi.ssid in in_use or not wifi.ssid:
            continue
        if wifi.ssid not in points:
            order.append(wifi.ssid)
            points[wifi.ssid] = []
        points[wifi.ssid].append((wifi, nm_wifi.security_kind(wifi.security)))
    out = []
    for ssid in order:
        group = points[ssid]
        kinds = {kind for _w, kind in group}
        best = min(kinds, key=lambda k: _KIND_ORDER.get(k, 9))
        strongest = max((w for w, kind in group if kind == best), key=lambda w: w.signal)
        out.append((strongest, best, len(kinds) > 1))
    return out


def bt_kind(icon: str) -> str:
    """BlueZ's icon name -> a word ("audio-headphones" -> "headphones")."""
    for prefix, word in strings.BT_KINDS.items():
        if icon.startswith(prefix):
            return word
    return strings.BT_KIND_UNKNOWN


PAGE = NetworkPage
