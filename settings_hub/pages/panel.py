"""The "Panel" page: HyprPanel's position and look, its clock, font and modules.

The logic is controllers.panel; every change is one History item (Ctrl+Z).
A number is written once it has been still for SETTLE_MS, so clicking + five
times is one item.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import panel as pb  # noqa: E402
from ..controllers import panel as ctl  # noqa: E402
from ..variables import Var  # noqa: E402
from ..widgets import fields  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

SETTLE_MS = 600
CLOCK_TICK_S = 1
CUSTOM = "custom"  # the clock list's last entry


def clock_text(fmt: str) -> str | None:
    """What a clock with this format shows now (GLib's strftime, as HyprPanel's)."""
    try:
        return GLib.DateTime.new_now_local().format(fmt)
    except (TypeError, GLib.Error):
        return None


class PanelPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(pb.BACKEND)
        if backend is None:
            backend = pb.Backend(self.ctx.workers)
            pb.register(self.ctx.history, backend)
            self.ctx.backends[pb.BACKEND] = backend
        self.panel = ctl.Controller(backend, self.ctx.history, self)
        self._quiet = False
        self._settle: dict[str, int] = {}  # key -> GLib source of a number still moving
        self._clock_formats = [fmt for fmt, _ in strings.PANEL_CLOCK_PRESETS]

        self.banner = self.add_group(Group())
        self.banner_row = self.banner.add(Row(strings.PANEL_NOT_RUNNING))
        self.banner.set_visible(False)

        # ---- position and look
        look = self.add_group(Group(strings.PANEL_LOOK))
        self.controls: dict[str, fields.Control] = {}

        def control(group: Group, row_id: str, key: str, var: Var, title: str, hint: str,
                    choices: list[tuple[str, str]] | None = None) -> None:
            widget = fields.make(var, lambda value, k=key: self._changed(k, value), choices)
            self.controls[key] = widget
            self.rows[row_id] = group.add(Row(title, hint, suffix=widget.widget, row_id=row_id))

        control(look, "location", pb.LOCATION,
                Var(pb.LOCATION, "choice", "top", choices=pb.LOCATIONS),
                strings.PANEL_LOCATION, strings.PANEL_LOCATION_HINT,
                [(v, strings.PANEL_LOCATIONS[v]) for v in pb.LOCATIONS])
        control(look, "floating", pb.FLOATING, Var(pb.FLOATING, "bool", False),
                strings.PANEL_FLOATING, strings.PANEL_FLOATING_HINT)
        control(look, "opacity", pb.OPACITY,
                Var(pb.OPACITY, "int", 100, lo=pb.OPACITY_MIN, hi=pb.OPACITY_MAX, step=5,
                    unit="%"),
                strings.PANEL_OPACITY, strings.PANEL_OPACITY_HINT)
        control(look, "autohide", pb.AUTOHIDE,
                Var(pb.AUTOHIDE, "choice", "never", choices=pb.AUTOHIDES),
                strings.PANEL_AUTOHIDE, strings.PANEL_AUTOHIDE_HINT,
                [(v, strings.PANEL_AUTOHIDES[v]) for v in pb.AUTOHIDES])
        control(look, "scaling", pb.SCALING,
                Var(pb.SCALING, "int", 100, lo=pb.SCALING_MIN, hi=pb.SCALING_MAX, step=5,
                    unit="%"),
                strings.PANEL_SCALING, strings.PANEL_SCALING_HINT)

        # ---- the clock
        clock = self.add_group(Group(strings.PANEL_CLOCK_GROUP))
        self.clock_model = Gtk.StringList()
        self.clock_dropdown = Gtk.DropDown(model=self.clock_model, valign=Gtk.Align.CENTER)
        self.clock_dropdown.connect("notify::selected", self._on_clock_choice)
        self.clock_entry = Gtk.Entry(hexpand=True, max_length=pb.CLOCK_MAX)
        self.clock_entry.connect("activate", lambda *_: self._on_clock_entry())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._on_clock_entry())
        self.clock_entry.add_controller(focus)
        self.clock_entry.connect("changed", lambda *_: self._show_clock_preview())
        self.clock_preview = Gtk.Label(xalign=0)
        self.clock_preview.add_css_class("sh-dim")
        below = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        below.append(self.clock_entry)
        below.append(self.clock_preview)
        self.rows["clock"] = clock.add(Row(strings.PANEL_CLOCK, strings.PANEL_CLOCK_HINT,
                                           suffix=self.clock_dropdown, below=below,
                                           row_id="clock"))
        self.clock_entry.set_tooltip_text(strings.PANEL_CLOCK_ENTRY_HINT)
        self._fill_clock_list()
        self._clock_tick = GLib.timeout_add_seconds(CLOCK_TICK_S, self._tick)

        # ---- the font
        font = self.add_group(Group(strings.PANEL_FONT_GROUP))
        dialog = Gtk.FontDialog(modal=True)
        self.font_button = Gtk.FontDialogButton(dialog=dialog, valign=Gtk.Align.CENTER)
        self.font_button.set_level(Gtk.FontLevel.FAMILY)
        self.font_button.connect("notify::font-desc", self._on_font)
        self.rows["font"] = font.add(Row(strings.PANEL_FONT, strings.PANEL_FONT_HINT,
                                         suffix=self.font_button, row_id="font"))
        control(font, "font_size", pb.FONT_SIZE,
                Var(pb.FONT_SIZE, "int", 19, lo=pb.FONT_PX_MIN, hi=pb.FONT_PX_MAX, step=1,
                    unit=strings.PANEL_PX),
                strings.PANEL_FONT_SIZE, strings.PANEL_FONT_SIZE_HINT)

        # ---- modules
        self.modules_note = Group(strings.PANEL_MODULES_GROUP, note=strings.PANEL_MODULES_NOTE)
        self.add_group(self.modules_note)
        self.other_row = self.modules_note.add(Row(""))
        self.other_row.set_visible(False)
        self.section_groups: dict[str, Group] = {}
        for section in pb.SECTIONS:
            self.section_groups[section] = self.add_group(Group(strings.PANEL_SECTIONS[section]))
        add = self.add_group(Group())
        self.add_names: list[str] = []
        self.add_model = Gtk.StringList()
        self.add_dropdown = Gtk.DropDown(model=self.add_model, valign=Gtk.Align.CENTER,
                                         enable_search=True)
        self.add_dropdown.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None,
                                                                    "string"))
        self.add_section = Gtk.DropDown.new_from_strings(
            [strings.PANEL_SECTIONS[s] for s in pb.SECTIONS])
        self.add_section.set_valign(Gtk.Align.CENTER)
        self.add_section.set_selected(len(pb.SECTIONS) - 1)
        self.add_button = Gtk.Button(label=strings.PANEL_ADD, valign=Gtk.Align.CENTER)
        self.add_button.connect("clicked", lambda *_: self._add_module())
        box = Gtk.Box(spacing=8)
        for widget in (self.add_dropdown, self.add_section, self.add_button):
            box.append(widget)
        self.rows["modules"] = add.add(Row(strings.PANEL_ADD_ROW, suffix=box, row_id="modules"))

        # ---- the panel itself
        service = self.add_group(Group(strings.PANEL_SERVICE_GROUP))
        restart = Gtk.Button(label=strings.PANEL_RESTART_BUTTON, valign=Gtk.Align.CENTER)
        restart.connect("clicked", lambda *_: self.panel.restart())
        self.rows["restart"] = service.add(Row(strings.PANEL_RESTART, strings.PANEL_RESTART_HINT,
                                               suffix=restart, row_id="restart"))

    # ---- page protocol -------------------------------------------------------------

    def refresh(self) -> None:
        self.panel.refresh()

    def status(self, text: str) -> None:
        self.ctx.status(text)

    # ---- the controller's view -----------------------------------------------------

    def show_panel(self, info: pb.Info, pending: set[str]) -> None:
        values = info.values
        self.banner.set_visible(not info.running or not info.found)
        self.banner_row.title_label.set_label(
            strings.PANEL_NO_CONFIG if not info.found else strings.PANEL_NOT_RUNNING)
        self._quiet = True
        try:
            for key, control in self.controls.items():
                if key in pending or key in self._settle:
                    continue
                if key == pb.FONT_SIZE:
                    px = pb.size_px(values[key])
                    control.set(int(round(px)) if px is not None else 19)
                else:
                    control.set(values[key])
            if pb.CLOCK not in pending and not self.clock_entry.has_focus():
                self._show_clock(values[pb.CLOCK])
            if pb.FONT not in pending:
                desc = Pango.FontDescription()  # not from_string: "Sans Condensed"
                desc.set_family(values[pb.FONT])  # would lose its "Condensed"
                desc.set_size(11 * Pango.SCALE)
                self.font_button.set_font_desc(desc)
        finally:
            self._quiet = False
        family = values[pb.FONT]
        hint = strings.PANEL_FONT_HINT
        if "nerd" not in family.casefold():
            hint = f"{hint}\n{strings.PANEL_FONT_NO_NERD.format(family=family)}"
        self.rows["font"].subtitle_label.set_label(hint)
        self._show_modules(info)

    def _show_modules(self, info: pb.Info) -> None:
        if not info.layouts_ok:
            self.other_row.title_label.set_label(strings.PANEL_LAYOUT_UNREADABLE)
        elif info.other_monitors:
            self.other_row.title_label.set_label(strings.PANEL_OTHER_MONITORS.format(
                monitors=", ".join(info.other_monitors)))
        self.other_row.set_visible(bool(info.other_monitors) or not info.layouts_ok)
        for group in self.section_groups.values():
            group.set_sensitive(info.layouts_ok)
        sections = self.panel.sections()
        order = list(pb.SECTIONS)
        for section, group in self.section_groups.items():
            group.clear()
            names = sections[section]
            if not names:
                group.add(Row(strings.PANEL_SECTION_EMPTY))
            for index, module in enumerate(names):
                first = index == 0 and order.index(section) == 0
                last = index == len(names) - 1 and order.index(section) == len(order) - 1
                box = Gtk.Box(spacing=4)
                for text, tip, step, enabled in (("↑", strings.PANEL_UP, -1, not first),
                                                 ("↓", strings.PANEL_DOWN, 1, not last)):
                    button = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
                    button.set_tooltip_text(tip)
                    button.set_sensitive(enabled)
                    button.connect("clicked", lambda *_a, s=section, i=index, d=step:
                                   self.panel.move(s, i, d))
                    box.append(button)
                remove = Gtk.Button(label="✕", valign=Gtk.Align.CENTER)
                remove.set_tooltip_text(strings.PANEL_REMOVE)
                remove.connect("clicked", lambda *_a, s=section, i=index:
                               self.panel.remove(s, i))
                box.append(remove)
                group.add(Row(ctl.module_name(module), module, suffix=box))
        self.add_names = self.panel.available()
        labels = [ctl.module_name(m) for m in self.add_names]
        self.add_model.splice(0, self.add_model.get_n_items(),
                              labels or [strings.PANEL_ADD_NOTHING])
        self.add_dropdown.set_sensitive(bool(labels) and info.layouts_ok)
        self.add_button.set_sensitive(bool(labels) and info.layouts_ok)

    # ---- the clock -----------------------------------------------------------------

    def _fill_clock_list(self) -> None:
        items = []
        for fmt, name in strings.PANEL_CLOCK_PRESETS:
            sample = clock_text(fmt)
            items.append(f"{name} — {sample.strip()}" if sample else name)
        items.append(strings.PANEL_CLOCK_CUSTOM)
        selected = self.clock_dropdown.get_selected()
        self._quiet, quiet = True, self._quiet
        try:
            self.clock_model.splice(0, self.clock_model.get_n_items(), items)
            if selected != Gtk.INVALID_LIST_POSITION:
                self.clock_dropdown.set_selected(selected)
        finally:
            self._quiet = quiet

    def _show_clock(self, fmt: str) -> None:
        index = self._clock_formats.index(fmt) if fmt in self._clock_formats \
            else len(self._clock_formats)
        self.clock_dropdown.set_selected(index)
        self.clock_entry.set_text(fmt)
        self.clock_entry.set_visible(index == len(self._clock_formats))
        self._show_clock_preview()

    def _show_clock_preview(self) -> None:
        text = clock_text(self.clock_entry.get_text())
        self.clock_preview.set_label(strings.PANEL_CLOCK_PREVIEW.format(text=text)
                                     if text else strings.PANEL_CLOCK_BAD)

    def _tick(self) -> bool:
        if self.widget.get_mapped():
            self._show_clock_preview()
            if GLib.DateTime.new_now_local().get_second() == 0:
                self._fill_clock_list()
        return True

    def _on_clock_choice(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._quiet:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(self._clock_formats):
            self.clock_entry.set_visible(False)
            self.clock_entry.set_text(self._clock_formats[index])
            self.panel.set(pb.CLOCK, self._clock_formats[index])
        else:  # "own format": show the field with what is there now
            self.clock_entry.set_visible(True)
            self.clock_entry.grab_focus()

    def _on_clock_entry(self) -> None:
        if self._quiet or not self.clock_entry.get_visible():
            return
        fmt = self.clock_entry.get_text()
        if fmt == self.panel.value(pb.CLOCK):
            return
        if not clock_text(fmt) or not fmt.strip():
            self.status(strings.PANEL_CLOCK_BAD)
            return
        self.panel.set(pb.CLOCK, fmt)

    # ---- other changes ---------------------------------------------------------------

    def _changed(self, key: str, value: Any) -> None:
        if self._quiet:
            return
        if key in (pb.OPACITY, pb.SCALING, pb.FONT_SIZE):  # numbers: once they rest
            if key in self._settle:
                GLib.source_remove(self._settle[key])
            self._settle[key] = GLib.timeout_add(SETTLE_MS, self._rested, key, value)
            return
        self.panel.set(key, value)

    def _rested(self, key: str, value: Any) -> bool:
        self._settle.pop(key, None)
        if key == pb.FONT_SIZE:
            value = pb.px_text(float(value))
        self.panel.set(key, value)
        return False

    def _on_font(self, button: Gtk.FontDialogButton, _pspec) -> None:
        if self._quiet:
            return
        desc = button.get_font_desc()
        family = desc.get_family() if desc is not None else None
        if family and family != self.panel.value(pb.FONT):
            self.panel.set(pb.FONT, family)

    def _add_module(self) -> None:
        index = self.add_dropdown.get_selected()
        if not 0 <= index < len(self.add_names):
            return
        section = pb.SECTIONS[min(self.add_section.get_selected(), len(pb.SECTIONS) - 1)]
        self.panel.add(self.add_names[index], section)


PAGE = PanelPage
