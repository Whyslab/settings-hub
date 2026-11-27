"""The "Date, time and language" page.

Time zone, network time, the system language and the login screen's layouts
are the system's (backends.timelang): each change asks for the password and
goes to History, so Ctrl+Z puts it back (asking again). The session's own
layouts and their switch are Hyprland variables (controllers.variables), the
same values the "Keyboard and mouse" page shows as text.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import timelang as tl  # noqa: E402
from ..controllers import variables as vctl  # noqa: E402
from ..history import ASK_WORKER as HISTORY_ASK_WORKER  # noqa: E402
from ..variables import backend as hypr  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

# a password dialog may stay open while the page reads; shared with History's
# reverts so only one dialog is open at a time
ASK_WORKER = HISTORY_ASK_WORKER
LAYOUT = "input:kb_layout"
OPTIONS = "input:kb_options"
MAX_LAYOUTS = 4
TICK_S = 20


def offset_text(delta: timedelta | None) -> str:
    """+01:00, -03:30, +00:00."""
    minutes = int((delta or timedelta()).total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{rest:02d}"


def zone_offset(zone: str, now: datetime | None = None) -> str:
    try:
        info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return ""
    moment = (now or datetime.now(info)).astimezone(info)
    return offset_text(moment.utcoffset())


def locale_name(code: str) -> str:
    return strings.TL_LOCALE_NAMES.get(code, code)


def layout_name(code: str, names: dict[str, str]) -> str:
    base = code.split("(", 1)[0]
    return strings.TL_LAYOUT_NAMES.get(base) or names.get(base) or code


def switch_name(option: str) -> str:
    return strings.TL_SWITCHES.get(option, option)


class DatetimePage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(tl.BACKEND)
        if backend is None:
            backend = tl.Backend(self.ctx.workers)
            tl.register(self.ctx.history, backend)
            self.ctx.backends[tl.BACKEND] = backend
        self.backend = backend
        hyprland = self.ctx.backends.get(hypr.BACKEND)
        if hyprland is None:
            hyprland = hypr.Backend(self.ctx.workers)
            hypr.register(self.ctx.history, hyprland)
            self.ctx.backends[hypr.BACKEND] = hyprland
        self.keys = vctl.Controller(hyprland, self.ctx.history, self)
        self.info: tl.Info | None = None
        self._quiet = False
        self._asking = ""  # the key whose change waits for the password
        self._tick = 0
        self._zones: list[str] = []
        self._zone_texts: list[str] = []
        self._zones_day = None  # the zone list's offsets are of this day
        self._addable: list[str] = []
        self._locales: list[str] = []
        self._switches: list[str] = []
        self._layout_names: dict[str, str] = {}
        self._session = ("", "")  # layouts, options as Hyprland has them
        titles = {k: v[0] for k, v in strings.TL_ROWS.items()}

        when = self.add_group(Group(strings.TL_TIME_GROUP, strings.TL_TIME_NOTE))
        self.now_label = Gtk.Label(xalign=1, wrap=True)
        self.now_label.add_css_class("sh-value")
        self.rows["now"] = when.add(Row(titles["now"], suffix=self.now_label, row_id="now"))
        self.zone_dropdown = self._dropdown(titles["timezone"])
        self.zone_dropdown.connect("notify::selected", lambda *_: self._on_zone())
        self.rows["timezone"] = when.add(Row(titles["timezone"], suffix=self.zone_dropdown,
                                             row_id="timezone"))
        self.ntp_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.ntp_switch.update_property([Gtk.AccessibleProperty.LABEL], [titles["ntp"]])
        self.ntp_switch.connect("notify::active", lambda *_: self._on_ntp())
        self.rows["ntp"] = when.add(Row(titles["ntp"], "", suffix=self.ntp_switch,
                                        row_id="ntp"))

        lang = self.add_group(Group(strings.TL_LANG_GROUP, strings.TL_LOCALE_MORE))
        self.locale_dropdown = self._dropdown(titles["locale"], search=False)
        self.locale_dropdown.connect("notify::selected", lambda *_: self._on_locale())
        self.rows["locale"] = lang.add(Row(titles["locale"], strings.TL_LOCALE_HINT,
                                           suffix=self.locale_dropdown, row_id="locale"))

        self.keys_group = self.add_group(Group(strings.TL_KEYS_GROUP, strings.TL_KEYS_NOTE))
        self._layout_rows: list[Row] = []
        self.rows["layouts"] = self.keys_group.add(Row("…", row_id="layouts"))
        self._layout_rows.append(self.rows["layouts"])
        add_box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.add_dropdown = self._dropdown(titles["add-layout"])
        self.add_button = Gtk.Button(label=strings.TL_LAYOUT_ADD)
        self.add_button.connect("clicked", lambda *_: self._add_layout())
        add_box.append(self.add_dropdown)
        add_box.append(self.add_button)
        self.add_row = Row(titles["add-layout"], suffix=add_box, row_id="add-layout")
        self.switch_dropdown = self._dropdown(titles["switch"], search=False)
        self.switch_dropdown.connect("notify::selected", lambda *_: self._on_switch())
        self.switch_row = Row(titles["switch"], strings.TL_SWITCH_HINT,
                              suffix=self.switch_dropdown, row_id="switch")
        self.login_button = Gtk.Button(label=strings.TL_LOGIN_BUTTON, sensitive=False)
        self.login_button.update_property([Gtk.AccessibleProperty.LABEL],
                                          [strings.TL_LOGIN_A11Y])
        self.login_button.connect("clicked", lambda *_: self._on_login_keys())
        self.login_row = Row(titles["login-keys"], "…", suffix=self.login_button,
                             row_id="login-keys")
        self.extra = self.add_group(Group())  # below the layouts: their number changes
        for row_id, row in (("add-layout", self.add_row), ("switch", self.switch_row),
                            ("login-keys", self.login_row)):
            self.rows[row_id] = self.extra.add(row)

        self.widget.connect("unmap", lambda *_: self._stop_tick())

    @staticmethod
    def _dropdown(label: str, search: bool = True) -> Gtk.DropDown:
        dropdown = Gtk.DropDown(model=Gtk.StringList(), enable_search=search,
                                valign=Gtk.Align.CENTER)
        dropdown.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if search:
            dropdown.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
        dropdown.update_property([Gtk.AccessibleProperty.LABEL], [label])
        return dropdown

    @staticmethod
    def _fill(dropdown: Gtk.DropDown, texts: list[str], selected: int) -> None:
        model = dropdown.get_model()
        if not 0 <= selected < len(texts):
            texts = []  # GTK picks the first item of any list: show nothing, not a wrong one
        if [model.get_string(i) for i in range(model.get_n_items())] != texts:
            model.splice(0, model.get_n_items(), texts)
        dropdown.set_selected(selected if 0 <= selected < len(texts)
                              else Gtk.INVALID_LIST_POSITION)

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.ctx.workers.submit(tl.WORKER, self._read, self._show, key="probe")
        self.keys.refresh()
        self._show_now()
        if not self._tick and self.widget.get_mapped():
            self._tick = GLib.timeout_add_seconds(TICK_S, self._on_tick)

    def _read(self) -> tuple[tl.Info, dict[str, str]]:
        names = self._layout_names or self.backend.layouts()
        return self.backend.probe(), names

    def _on_tick(self) -> bool:
        if not self.widget.get_mapped():
            self._tick = 0
            return False
        self._show_now()
        return True

    def _stop_tick(self) -> None:
        if self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0

    def _show_now(self) -> None:
        zone = self.info.timezone if self.info is not None else ""
        try:  # the system's zone as read: the process's own may still be the old one
            now = datetime.now(ZoneInfo(zone)) if zone else None
        except (ZoneInfoNotFoundError, ValueError, OSError):
            now = None
        if now is None:
            time.tzset()
            now = datetime.now().astimezone()
        self.now_label.set_label(now.strftime(strings.TL_NOW_FORMAT))
        self.now_label.set_tooltip_text(strings.TL_NOW_HINT.format(
            offset=offset_text(now.utcoffset())))

    def _show(self, result, error: BaseException | None) -> None:
        if error is not None or result is None:
            self.ctx.status(strings.TL_READ_FAILED.format(error=error))
            # the controls must not stay off after an ask: show what was known
            result = (self.info or tl.Info(ok_time=False, ok_locale=False),
                      self._layout_names)
        info, names = result
        self.info, self._layout_names = info, names
        self._quiet = True
        try:
            self._show_time(info)
            self._show_locale(info)
            self._show_login(info)
            self._show_layouts()
        finally:
            self._quiet = False
        self._show_now()
        if not (info.ok_time and info.ok_locale):
            self.ctx.status(strings.TL_UNKNOWN)

    def _show_time(self, info: tl.Info) -> None:
        zones = list(info.timezones)
        if info.timezone and info.timezone not in zones:
            zones.insert(0, info.timezone)
        today = datetime.now().date()  # offsets change with summer time
        if zones != self._zones or today != self._zones_day:
            self._zones, self._zones_day = zones, today
            now = datetime.now().astimezone()
            self._zone_texts = [strings.TL_ZONE_ITEM.format(zone=z, offset=zone_offset(z, now))
                                for z in zones]
        self._fill(self.zone_dropdown, self._zone_texts,
                   zones.index(info.timezone) if info.timezone in zones else -1)
        self.zone_dropdown.set_sensitive(info.ok_time and bool(zones) and not self._asking)
        row = self.rows["ntp"]
        self.ntp_switch.set_active(bool(info.ntp))
        self.ntp_switch.set_sensitive(info.can_ntp and info.ntp is not None and not self._asking)
        hint = (strings.TL_TIME_UNKNOWN if not info.ok_time else
                strings.TL_NTP_NONE if not info.can_ntp else
                strings.TL_NTP_HINT_SYNCED if info.ntp and info.synced else
                strings.TL_NTP_HINT_ON if info.ntp else strings.TL_NTP_HINT_OFF)
        row.subtitle_label.set_label(hint)
        row.subtitle_label.set_visible(True)

    def _show_locale(self, info: tl.Info) -> None:
        lang = info.locale.get("LANG", "")
        locales = list(info.locales)
        if lang and lang not in locales:
            locales.insert(0, lang)
        self._locales = locales
        self._fill(self.locale_dropdown, [locale_name(c) for c in locales],
                   locales.index(lang) if lang in locales else -1)
        self.locale_dropdown.set_sensitive(info.ok_locale and bool(locales) and not self._asking)

    def _login_target(self) -> tl.LoginKeys | None:
        layouts, options = self._session
        if self.info is None or not layouts:
            return None
        login = self.info.login
        return tl.LoginKeys(layouts, login.model or "pc105",
                            login.variants if login.layouts == layouts else "",
                            tl.with_switch(login.options, tl.switch_of(options)))

    def _show_login(self, info: tl.Info) -> None:
        row = self.login_row
        target = self._login_target()
        if not info.ok_locale or not info.login.layouts:
            row.subtitle_label.set_label(strings.TL_LOGIN_UNKNOWN)
            self.login_button.set_sensitive(False)
            return
        same = target is not None and target.layouts == info.login.layouts and \
            tl.switch_of(target.options) == tl.switch_of(info.login.options) and \
            target.variants.strip(",") == info.login.variants.strip(",")
        switch = tl.switch_of(info.login.options)
        names = ", ".join(tl.split_list(info.login.layouts))
        shown = strings.TL_LOGIN_SWITCH.format(switch=switch_name(switch)) if switch else ""
        safe = target is not None and tl.login_safe(target)
        row.subtitle_label.set_label(
            strings.TL_LOGIN_SAME if same else
            strings.TL_LOGIN_HINT.format(layouts=names, switch=shown) +
            ("" if safe or target is None else strings.TL_LOGIN_UNSAFE))
        self.login_button.set_sensitive(safe and not same and not self._asking)

    # ---- the session's layouts (Hyprland) ---------------------------------

    def show_values(self, values: dict) -> None:
        """controllers.variables' view: fresh Hyprland values."""
        layouts, options = self._session
        if LAYOUT in values:
            layouts = str(values[LAYOUT] or "")
        if OPTIONS in values:
            options = str(values[OPTIONS] or "")
        self._session = (layouts, options)
        self._quiet = True
        try:
            self._show_layouts()
            if self.info is not None:
                self._show_login(self.info)
        finally:
            self._quiet = False

    def status(self, text: str) -> None:
        self.ctx.status(text)

    def _show_layouts(self) -> None:
        layouts = tl.split_list(self._session[0])
        names = self._layout_names
        while len(self._layout_rows) < max(1, len(layouts)):
            row = Row("…")
            self._layout_rows.append(row)
            self.keys_group.add(row)
        while len(self._layout_rows) > max(1, len(layouts)):
            self.keys_group.list.remove(self._layout_rows.pop())
        for index, row in enumerate(self._layout_rows):
            if index >= len(layouts):
                row.title_label.set_label("…")
                continue
            code = layouts[index]
            name = layout_name(code, names)
            row.title_label.set_label(strings.TL_LAYOUT_ITEM.format(name=name, code=code))
            row.subtitle_label.set_label(strings.TL_LAYOUT_FIRST if index == 0 else "")
            row.subtitle_label.set_visible(index == 0)
            box = getattr(row, "buttons", None)
            if box is None:
                box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
                up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=strings.TL_LAYOUT_UP)
                up.add_css_class("flat")
                remove = Gtk.Button(icon_name="list-remove-symbolic")
                remove.add_css_class("flat")
                up.connect("clicked", lambda _b, r=row: self._move_up(r.layout_index))
                remove.connect("clicked", lambda _b, r=row: self._remove(r.layout_index))
                box.append(up)
                box.append(remove)
                row.get_child().append(box)
                row.buttons, row.up, row.remove = box, up, remove
            row.layout_index = index
            row.up.set_sensitive(index > 0)
            row.up.update_property([Gtk.AccessibleProperty.LABEL],
                                   [strings.TL_LAYOUT_UP_A11Y.format(name=name)])
            row.remove.set_sensitive(len(layouts) > 1)
            row.remove.set_tooltip_text(strings.TL_LAYOUT_REMOVE_A11Y.format(name=name)
                                        if len(layouts) > 1 else strings.TL_LAYOUT_LAST)
            row.remove.update_property([Gtk.AccessibleProperty.LABEL],
                                       [strings.TL_LAYOUT_REMOVE_A11Y.format(name=name)])
        self.rows["layouts"] = self._layout_rows[0]
        # what can be added: every known layout not in use, by its name
        # the ones with a Russian name (the usual ones) first, then the rest
        codes = sorted((c for c in names if c not in layouts and c != "custom"),
                       key=lambda c: (c not in strings.TL_LAYOUT_NAMES,
                                      layout_name(c, names).casefold()))
        # keep what the person picked if it can still be added
        picked = self.add_dropdown.get_selected()
        old = self._addable
        keep = old[picked] if picked < len(old) else None
        self._addable = codes
        self._fill(self.add_dropdown, [strings.TL_LAYOUT_ITEM.format(
            name=layout_name(c, names), code=c) for c in codes],
            codes.index(keep) if keep in codes else 0)
        self.add_button.set_sensitive(bool(layouts) and len(layouts) < MAX_LAYOUTS)
        self.add_button.set_tooltip_text(strings.TL_LAYOUT_MAX if len(layouts) >= MAX_LAYOUTS
                                         else None)
        switch = tl.switch_of(self._session[1])
        switches = list(strings.TL_SWITCHES)
        if switch not in switches:
            switches.insert(0, switch)
        self._switches = switches
        self._fill(self.switch_dropdown, [switch_name(s) for s in switches],
                   switches.index(switch))
        self.switch_dropdown.set_sensitive(bool(layouts))

    def _set_layouts(self, layouts: list[str]) -> None:
        self.keys.edit(LAYOUT, ",".join(layouts))
        # at once, so a second quick click works on this list; a refused change
        # comes back through show_values with the old one
        self._session = (",".join(layouts), self._session[1])
        self._quiet = True
        try:
            self._show_layouts()
        finally:
            self._quiet = False

    def _move_up(self, index: int) -> None:
        layouts = tl.split_list(self._session[0])
        if 0 < index < len(layouts):
            layouts[index - 1], layouts[index] = layouts[index], layouts[index - 1]
            self._set_layouts(layouts)

    def _remove(self, index: int) -> None:
        layouts = tl.split_list(self._session[0])
        if len(layouts) <= 1:
            self.ctx.status(strings.TL_LAYOUT_LAST)
            return
        if 0 <= index < len(layouts):
            del layouts[index]
            self._set_layouts(layouts)

    def _add_layout(self) -> None:
        layouts = tl.split_list(self._session[0])
        index = self.add_dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self._addable):
            return
        code = self._addable[index]
        if code in layouts:
            self.ctx.status(strings.TL_LAYOUT_HAS)
        elif len(layouts) >= MAX_LAYOUTS:
            self.ctx.status(strings.TL_LAYOUT_MAX)
        else:
            self._set_layouts([*layouts, code])

    def _on_switch(self) -> None:
        if self._quiet:
            return
        index = self.switch_dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self._switches):
            return
        self.keys.edit(OPTIONS, tl.with_switch(self._session[1], self._switches[index]))

    # ---- system changes (each asks for the password) ----------------------

    def _on_zone(self) -> None:
        index = self.zone_dropdown.get_selected()
        if self._quiet or self.info is None or index >= len(self._zones):
            return
        zone = self._zones[index]
        if zone != self.info.timezone:
            self._ask("timezone", self.info.timezone, zone, zone,
                      lambda info: self.backend.set_timezone(zone, info))

    def _on_ntp(self) -> None:
        if self._quiet or self.info is None:
            return
        on = self.ntp_switch.get_active()
        if on != self.info.ntp:
            self._ask("ntp", self.info.ntp, on, strings.TL_ON if on else strings.TL_OFF,
                      lambda _info: self.backend.set_ntp(on))

    def _on_locale(self) -> None:
        index = self.locale_dropdown.get_selected()
        if self._quiet or self.info is None or index >= len(self._locales):
            return
        code = self._locales[index]
        before = dict(self.info.locale)
        if not before.get("LANG"):  # not read: nothing to put back on undo
            self.ctx.status(strings.TL_UNKNOWN)
            self._quiet = True
            try:
                self._show_locale(self.info)
            finally:
                self._quiet = False
            return
        if code != before.get("LANG"):
            after = {**before, "LANG": code}
            self._ask("locale", before, after, locale_name(code),
                      lambda info: self.backend.set_locale(after, info))

    def _on_login_keys(self) -> None:
        target = self._login_target()
        if self.info is None or target is None:
            return
        login = self.info.login
        before = [login.layouts, login.model, login.variants, login.options]
        after = [target.layouts, target.model, target.variants, target.options]
        self._ask("login-keys", before, after, ", ".join(tl.split_list(target.layouts)),
                  lambda _info: self.backend.set_login_keys(target))

    def _ask(self, key: str, before, after, shown: str, change) -> None:
        if self._asking:
            return
        self._asking = key
        for widget in (self.zone_dropdown, self.ntp_switch, self.locale_dropdown,
                       self.login_button):
            widget.set_sensitive(False)
        info = self.info

        def done(_result, error: BaseException | None) -> None:
            self._asking = ""
            if isinstance(error, tl.NoAgent):
                self.ctx.status(strings.TL_NO_AGENT)
            elif isinstance(error, PermissionError):
                self.ctx.status(strings.TL_DENIED)
            elif isinstance(error, TimeoutError):
                self.ctx.status(strings.TL_TIMEOUT)
            elif error is not None:
                self.ctx.status(strings.TL_FAILED.format(error=error))
            else:
                self.ctx.history.record([(tl.BACKEND, key, strings.TL_HISTORY[key],
                                          before, after)])
                self.ctx.status(strings.TL_DONE[key].format(value=shown))
            self.refresh()  # the controls show what the system has, changed or not

        try:
            self.ctx.workers.submit(ASK_WORKER, lambda: change(info), done, key="ask")
        except RuntimeError:  # the window is closing
            self._asking = ""


PAGE = DatetimePage
