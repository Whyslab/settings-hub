"""The "Appearance" page: fonts, text size, icons, and the cursor.

Fonts and icons are controllers.appearance; the cursor rows are the variable
table's (page "appearance"), built by the shared VariablesPage, which this page
extends: its own groups come first.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .. import settings as hub_settings  # noqa: E402
from .. import strings  # noqa: E402
from ..backends import appearance as ap  # noqa: E402
from ..controllers import appearance as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .variables import VariablesPage  # noqa: E402

SCALE_SETTLE_MS = 600
# A few icons most themes have, shown next to the theme list as a preview.
SAMPLE_ICONS = ("folder", "user-home", "text-x-generic", "image-x-generic",
                "audio-x-generic", "applications-system", "web-browser")
SAMPLE_PX = 24
# fontconfig aliases, never in Pango's family list, always "installed"
GENERIC_FAMILIES = frozenset({"sans", "sans-serif", "serif", "monospace", "mono", "system-ui",
                              "cursive", "fantasy", "emoji"})
# A font for text must draw these: Latin A z, Cyrillic Zhe and ya. Most of the
# installed families are for one other script (Noto Sans Adlam, ...): offered
# here they only turn every label into boxes.
TEXT_CODEPOINTS = (0x41, 0x7A, 0x416, 0x44F)
OWN_FONT = "appearance.own_font"
_READABLE: dict[str, bool] = {}  # family name -> draws TEXT_CODEPOINTS


def _monospace(item: Any) -> bool:
    """The font dialog's filter: its items are families (or faces of one)."""
    family = item if isinstance(item, Pango.FontFamily) else (
        item.get_family() if hasattr(item, "get_family") else None)
    return bool(family is not None and family.is_monospace())


def draws_text(context: Pango.Context, desc: Pango.FontDescription) -> bool:
    """Whether the font `desc` names has Latin and Cyrillic letters."""
    desc = desc.copy()
    if desc.get_size() <= 0:
        desc.set_size(11 * Pango.SCALE)
    font = context.load_font(desc)
    if font is None:
        return False
    coverage = font.get_coverage(Pango.Language.from_string("ru"))
    return all(coverage.get(c) == Pango.CoverageLevel.EXACT for c in TEXT_CODEPOINTS)


def readable_family(context: Pango.Context, item: Any) -> bool:
    """The font dialog's filter: hide the families that cannot write Russian."""
    family = item  # a Pango.FontFamily, or a face of one
    if not hasattr(family, "get_face") and hasattr(family, "get_family"):
        family = family.get_family()
    if family is None or not hasattr(family, "get_face"):
        return False
    name = family.get_name()
    if name not in _READABLE:
        face = family.get_face(None)
        _READABLE[name] = face is not None and draws_text(context, face.describe())
    return _READABLE[name]


class AppearancePage(VariablesPage):
    RESET_TITLE = strings.LOOK_CURSOR_RESET
    RESET_HINT = strings.LOOK_CURSOR_RESET_HINT
    RESET_ASK = strings.LOOK_CURSOR_RESET_ASK

    def build(self) -> None:
        backend = self.ctx.backends.get(ap.BACKEND)
        if backend is None:
            backend = ap.Backend(self.ctx.workers)
            ap.register(self.ctx.history, backend)
            self.ctx.backends[ap.BACKEND] = backend
        self._look_quiet = False
        self._scale_source = 0
        self._sample_theme: str | None = None
        self.look = ctl.Controller(backend, self.ctx.history, self)

        fonts = self.add_group(Group(strings.LOOK_FONTS))
        self.font_button = self._font_button(ap.FONT)
        self.rows["font"] = fonts.add(Row(strings.LOOK_FONT, strings.LOOK_FONT_HINT,
                                          suffix=self.font_button, row_id="font"))
        self.mono_button = self._font_button(ap.MONO, monospace=True)
        self.rows["mono"] = fonts.add(Row(strings.LOOK_MONO, strings.LOOK_MONO_HINT,
                                          suffix=self.mono_button, row_id="mono"))
        self.scale_label = Gtk.Label(label="—")
        self.scale_label.add_css_class("sh-value")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,
                                              ap.SCALE_MIN, ap.SCALE_MAX, 0.05)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_increments(0.05, 0.25)
        self.scale.add_mark(1.0, Gtk.PositionType.BOTTOM, None)
        self.scale.connect("value-changed", self._on_scale)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda *_: self._settle_scale_now())
        self.scale.add_controller(click)
        self.rows["scale"] = fonts.add(Row(strings.LOOK_SCALE, strings.LOOK_SCALE_HINT,
                                           suffix=self.scale_label, below=self.scale,
                                           row_id="scale"))
        self.hub = self.ctx.settings  # the window's own settings (always given)
        self.own_font = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.own_font.set_active(bool(self.hub.get(OWN_FONT)))
        self.own_font.connect("notify::active", self._on_own_font)
        self.rows["own_font"] = fonts.add(Row(strings.LOOK_OWN_FONT, strings.LOOK_OWN_FONT_HINT,
                                              suffix=self.own_font, row_id="own_font"))
        # Undo and the General page change it too.
        self.hub.subscribe(lambda key, _v: key == OWN_FONT and self._show_own_font())

        elsewhere = self.add_group(Group(strings.LOOK_ELSEWHERE,
                                         note=strings.LOOK_ELSEWHERE_NOTE))
        self.panel_value, self.panel_same = self._same_row(
            elsewhere, "panel_font", strings.LOOK_PANEL_FONT, strings.LOOK_SAME_AS_UI,
            ap.PANEL_FONT)
        self.kitty_value, self.kitty_same = self._same_row(
            elsewhere, "kitty_font", strings.LOOK_KITTY_FONT, strings.LOOK_SAME_AS_MONO,
            ap.KITTY_FONT)

        icons = self.add_group(Group(strings.LOOK_ICONS_GROUP))
        self.icon_names: list[str] = []
        self.icon_model = Gtk.StringList()
        self.icon_dropdown = Gtk.DropDown(model=self.icon_model, valign=Gtk.Align.CENTER)
        self.icon_dropdown.connect("notify::selected", self._on_icons)
        self.icon_sample = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.icon_sample.add_css_class("sh-icon-sample")
        self.rows["icons"] = icons.add(Row(strings.LOOK_ICONS, strings.LOOK_ICONS_HINT,
                                           suffix=self.icon_dropdown, below=self.icon_sample,
                                           row_id="icons"))

        super().build()  # the cursor rows, then the first refresh

    # ---- building helpers --------------------------------------------------------

    def _font_button(self, key: str, monospace: bool = False) -> Gtk.FontDialogButton:
        dialog = Gtk.FontDialog(modal=True)
        context = self.widget.get_pango_context()
        if monospace:
            dialog.set_filter(Gtk.CustomFilter.new(
                lambda item: _monospace(item) and readable_family(context, item)))
        else:
            dialog.set_filter(Gtk.CustomFilter.new(lambda item: readable_family(context, item)))
        button = Gtk.FontDialogButton(dialog=dialog, valign=Gtk.Align.CENTER)
        button.set_level(Gtk.FontLevel.FONT)
        button.set_use_font(True)
        button.connect("notify::font-desc", lambda b, _p: self._on_font(key, b))
        return button

    def _same_row(self, group: Group, row_id: str, title: str, button_text: str,
                  key: str) -> tuple[Gtk.Label, Gtk.Button]:
        value = Gtk.Label(label="—", ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        value.add_css_class("sh-dim")
        button = Gtk.Button(label=button_text, valign=Gtk.Align.CENTER)
        button.set_tooltip_text(strings.LOOK_SAME_TIP)
        button.connect("clicked", lambda *_: self._same(key))
        box = Gtk.Box(spacing=10)
        box.append(value)
        box.append(button)
        self.rows[row_id] = group.add(Row(title, suffix=box, row_id=row_id))
        return value, button

    def _family(self, key: str) -> str:
        text = self.look.value(key) or ""
        return (Pango.FontDescription.from_string(text).get_family() or "") if text else ""

    def _same(self, target: str) -> None:
        self.look.same_as(target, self._family(ap.FONT if target == ap.PANEL_FONT else ap.MONO))

    # ---- page protocol -------------------------------------------------------------

    def refresh(self) -> None:
        super().refresh()
        self.look.refresh()

    # ---- the appearance controller's view -------------------------------------------

    def show_look(self, look: ap.Look, pending: set[str]) -> None:
        values = look.values
        self._look_quiet = True
        try:
            for key, button in ((ap.FONT, self.font_button), (ap.MONO, self.mono_button)):
                if key in values and key not in pending:
                    button.set_font_desc(Pango.FontDescription.from_string(values[key]))
            if ap.SCALE in values and ap.SCALE not in pending and not self._scale_source:
                self.scale.set_value(values[ap.SCALE])
                self._show_scale(values[ap.SCALE])
            if look.icon_themes != self.icon_names:
                self.icon_names = list(look.icon_themes)
                self.icon_model.splice(0, self.icon_model.get_n_items(), self.icon_names)
            current = values.get(ap.ICONS)
            if current in self.icon_names and ap.ICONS not in pending:
                self.icon_dropdown.set_selected(self.icon_names.index(current))
                self._show_icon_sample(current)
        finally:
            self._look_quiet = False
        context = self.widget.get_pango_context()
        installed = {f.get_name().casefold() for f in context.list_families()}
        for key, row_id, hint in ((ap.FONT, "font", strings.LOOK_FONT_HINT),
                                  (ap.MONO, "mono", strings.LOOK_MONO_HINT)):
            family = self._family(key)
            text = hint
            if family and family.casefold() not in installed | GENERIC_FAMILIES:
                text = f"{hint}\n{strings.LOOK_MISSING.format(family=family)}"
            elif family and not draws_text(context, Pango.FontDescription.from_string(
                    values.get(key, ""))):
                # set elsewhere (or before this check existed): say why it is boxes
                text = f"{hint}\n{strings.LOOK_UNREADABLE.format(family=family)}"
            self.rows[row_id].subtitle_label.set_label(text)
        ui_family, mono_family = self._family(ap.FONT), self._family(ap.MONO)
        panel = values.get(ap.PANEL_FONT, "")
        kitty = values.get(ap.KITTY_FONT, "")
        self.panel_value.set_label(panel or strings.LOOK_NOT_FOUND)
        self.kitty_value.set_label(kitty or strings.LOOK_NOT_FOUND)
        self.panel_same.set_sensitive(look.panel and bool(ui_family) and panel != ui_family)
        self.kitty_same.set_sensitive(look.kitty and bool(mono_family)
                                      and ap.split_font(kitty)[0] != mono_family)

    # status() comes from VariablesPage

    # ---- signals ------------------------------------------------------------------

    def _on_font(self, key: str, button: Gtk.FontDialogButton) -> None:
        if self._look_quiet:
            return
        desc = button.get_font_desc()
        if desc is not None:
            if not draws_text(self.widget.get_pango_context(), desc):
                self._look_quiet = True
                try:  # the button goes back to the font in use at once
                    current = self.look.value(key)
                    if current:
                        button.set_font_desc(Pango.FontDescription.from_string(current))
                finally:
                    self._look_quiet = False
                self.status(strings.LOOK_UNREADABLE.format(family=desc.get_family() or ""))
                return
            desc = desc.copy()
            # "Name 11", not "Name 11 @wght=700": the family is reused for the panel.
            desc.unset_fields(Pango.FontMask.VARIATIONS | Pango.FontMask.GRAVITY)
            self.look.set(key, desc.to_string())

    def _show_own_font(self) -> None:
        self._look_quiet = True
        try:
            self.own_font.set_active(bool(self.hub.get(OWN_FONT)))
        finally:
            self._look_quiet = False

    def _on_own_font(self, switch: Gtk.Switch, _pspec) -> None:
        if self._look_quiet:
            return
        value = switch.get_active()
        before = self.hub.get(OWN_FONT)
        if before == value:
            return
        self.hub.set(OWN_FONT, value)
        label = strings.HUB_SETTINGS[OWN_FONT][0]
        self.ctx.history.record([(hub_settings.SettingsApplier.backend, OWN_FONT, label,
                                  before, value)])
        self.status(strings.HUB_APPLIED.format(name=label))

    def _show_scale(self, value: float) -> None:
        self.scale_label.set_label(strings.LOOK_PERCENT.format(percent=int(round(value * 100))))

    def _on_scale(self, scale: Gtk.Scale) -> None:
        value = round(scale.get_value() / 0.05) * 0.05
        self._show_scale(value)
        if self._look_quiet:
            return
        self.look.scale_moved(value)
        if self._scale_source:
            GLib.source_remove(self._scale_source)
        self._scale_source = GLib.timeout_add(SCALE_SETTLE_MS, self._settle_scale)

    def _settle_scale(self) -> bool:
        self._scale_source = 0
        self.look.commit_scale()
        return False

    def _settle_scale_now(self) -> None:
        if self._scale_source:
            GLib.source_remove(self._scale_source)
            self._settle_scale()

    def _on_icons(self, dropdown: Gtk.DropDown, _pspec) -> None:
        index = dropdown.get_selected()
        if not 0 <= index < len(self.icon_names):
            return
        name = self.icon_names[index]
        self._show_icon_sample(name)
        if not self._look_quiet:
            self.look.set(ap.ICONS, name)

    def _show_icon_sample(self, theme_name: str) -> None:
        """The same few icons, drawn from the chosen theme (not the one in use)."""
        if theme_name == self._sample_theme:
            return
        self._sample_theme = theme_name
        child = self.icon_sample.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.icon_sample.remove(child)
            child = following
        theme = Gtk.IconTheme()
        theme.set_theme_name(theme_name)
        scale = self.widget.get_scale_factor() or 1
        for name in SAMPLE_ICONS:
            if not theme.has_icon(name):
                continue
            paintable = theme.lookup_icon(name, None, SAMPLE_PX, scale,
                                          Gtk.TextDirection.NONE, 0)
            image = Gtk.Image.new_from_paintable(paintable)
            image.set_pixel_size(SAMPLE_PX)
            self.icon_sample.append(image)


PAGE = AppearancePage
