"""The "Themes" page: theme cards, wallpapers of a theme, per-program themes, own themes.

Only widgets live here; controllers.themes.Controller decides what to run, and
this page is its view. A card's preview is drawn from the theme's palette, so
it needs no picture files.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import themes as th  # noqa: E402
from ..backends import wallpaper as wp  # noqa: E402
from ..controllers import themes as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402
from .wallpaper import TILE_W, Tile, texture_from  # noqa: E402

CARD_W, CARD_H = 148, 88
LOAD_WORKER = "wallpaper-load"
DEFAULT_COLOURS = ("#7aa2f7", "#1a1b26", "#c0caf5")  # accent, background, text


def rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def rgba_hex(rgba: Gdk.RGBA) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}"
                         for c in (rgba.red, rgba.green, rgba.blue))


def _rounded(cr, x, y, w, h, r) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def draw_preview(cr, width: int, height: int, theme: th.ThemeInfo) -> None:
    """A tiny desktop in the theme's colours: sidebar, a card, text, an accent button."""
    p = theme.palette
    if p is None:  # "from the wallpaper" without a ready palette: a soft gradient
        import cairo

        grad = cairo.LinearGradient(0, 0, width, height)
        grad.add_color_stop_rgb(0, 0.36, 0.36, 0.90)
        grad.add_color_stop_rgb(0.5, 0.69, 0.32, 0.87)
        grad.add_color_stop_rgb(1, 1.0, 0.58, 0.0)
        cr.set_source(grad)
        cr.paint()
        return
    cr.set_source_rgb(*rgb(p["surface_container_lowest"]))
    cr.paint()
    side = width * 0.28
    cr.set_source_rgb(*rgb(p["surface"]))
    cr.rectangle(0, 0, side, height)
    cr.fill()
    for i in range(3):  # sidebar items, the first one chosen
        cr.set_source_rgb(*rgb(p["primary"] if i == 0 else p["outline_variant"]))
        _rounded(cr, 7, 12 + i * 13, side - 14, 6, 3)
        cr.fill()
    x0, y0 = side + 9, 11
    cw, ch = width - side - 18, height * 0.48
    cr.set_source_rgb(*rgb(p["surface_container"]))
    _rounded(cr, x0, y0, cw, ch, 5)
    cr.fill()
    cr.set_source_rgb(*rgb(p["on_surface"]))
    _rounded(cr, x0 + 7, y0 + 8, cw * 0.55, 5, 2.5)
    cr.fill()
    cr.set_source_rgb(*rgb(p["on_surface_variant"]))
    _rounded(cr, x0 + 7, y0 + 18, cw * 0.38, 4, 2)
    cr.fill()
    cr.set_source_rgb(*rgb(p["primary"]))
    _rounded(cr, x0 + cw - 30, y0 + ch - 14, 23, 9, 4.5)
    cr.fill()
    cr.set_source_rgb(*rgb(p["on_primary"]))
    cr.arc(x0 + cw - 18.5, y0 + ch - 9.5, 2, 0, 6.2832)
    cr.fill()
    accents = list(theme.accents) or [p["primary"]]
    for i, color in enumerate(accents[:5]):  # the theme's colours along the bottom
        cr.set_source_rgb(*rgb(color))
        cr.arc(x0 + 6 + i * 13, height - 12, 4.5, 0, 6.2832)
        cr.fill()


class Card(Gtk.FlowBoxChild):
    def __init__(self, theme: th.ThemeInfo) -> None:
        super().__init__()
        self.theme = theme
        self.area = Gtk.DrawingArea(content_width=CARD_W, content_height=CARD_H)
        self.area.set_draw_func(lambda _a, cr, w, h: draw_preview(cr, w, h, self.theme))
        frame = Gtk.Overlay()
        frame.add_css_class("sh-thumb")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_halign(Gtk.Align.CENTER)
        frame.set_child(self.area)
        if theme.kind == "wallpaper" and theme.palette is None:
            badge = Gtk.Label(label=strings.TH_FROM_WALLPAPER)
            badge.add_css_class("sh-theme-badge")
            frame.add_overlay(badge)
        name = Gtk.Label(label=theme.name, xalign=0.5, ellipsize=Pango.EllipsizeMode.END,
                         max_width_chars=18)
        name.add_css_class("sh-tile-name")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.append(frame)
        box.append(name)
        self.set_child(box)
        self.set_tooltip_text(theme.name)


class ThemesPage(Page):
    def build(self) -> None:
        self._quiet_depth = 0
        self.cards: list[Card] = []
        self.tiles: list[Tile] = []
        self.walls_theme: str | None = None  # whose pictures the grid shows
        self.walls_paths: set[str] = set()
        self.target_ids: list[str] = []  # drop-down index -> theme id
        self.walls_ids: list[str] = []
        self.custom_rows: list[Row] = []
        backend = self.ctx.backends.get(th.BACKEND)
        if backend is None:  # normally created by the app, with its History applier
            backend = th.Backend(self.ctx.workers)
            th.register(self.ctx.history, backend)
            self.ctx.backends[th.BACKEND] = backend
        self.backend = backend
        self.wallpaper = self.ctx.backends.get(wp.BACKEND) or wp.Backend(self.ctx.workers)
        self._main: list[Group] = []

        self.missing_group = self.add_group(Group(strings.TH_SYSTEM_GROUP))
        self.missing_row = self.missing_group.add(Row(strings.TH_MISSING, " "))
        self.missing_group.set_visible(False)

        # ---- the system theme: cards -----------------------------------
        group = self._add(Group(strings.TH_SYSTEM_GROUP, strings.TH_SYSTEM_NOTE))
        self.flow = Gtk.FlowBox(homogeneous=True, min_children_per_line=2,
                                max_children_per_line=4, row_spacing=12, column_spacing=10,
                                selection_mode=Gtk.SelectionMode.NONE,
                                activate_on_single_click=True)
        self.flow.add_css_class("sh-tiles")
        self.flow.connect("child-activated", self._on_card)
        self.rows["system"] = group.add(Row(strings.TH_SYSTEM_GROUP, below=self.flow,
                                            row_id="system"))
        self.rows["system"].title_label.set_visible(False)  # the group title says it
        self.random_button = Gtk.Button(label=strings.TH_RANDOM_BUTTON)
        self.random_button.connect("clicked", lambda *_: self.controller.random())
        self.rows["random"] = group.add(Row(strings.TH_RANDOM, strings.TH_RANDOM_HINT,
                                            suffix=self.random_button, row_id="random"))

        # ---- wallpapers -------------------------------------------------
        group = self._add(Group(strings.TH_WALLS_GROUP))
        self.walls_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.walls_switch.connect("notify::active", self._on_walls_switch)
        self.rows["walls"] = group.add(Row(strings.TH_WALLS, strings.TH_WALLS_HINT,
                                           suffix=self.walls_switch, row_id="walls"))
        self.walls_dropdown = Gtk.DropDown.new_from_strings([])
        self.walls_dropdown.connect("notify::selected", self._on_walls_theme)
        self.walls_edit = Gtk.ToggleButton(label=strings.TH_THEME_WALLS_EDIT)
        self.walls_edit.connect("toggled", self._on_walls_edit)
        suffix = Gtk.Box(spacing=8)
        suffix.append(self.walls_dropdown)
        suffix.append(self.walls_edit)
        self.lib_flow = Gtk.FlowBox(homogeneous=True, min_children_per_line=3,
                                    max_children_per_line=4, row_spacing=10, column_spacing=10,
                                    selection_mode=Gtk.SelectionMode.NONE,
                                    activate_on_single_click=True)
        self.lib_flow.add_css_class("sh-tiles")
        self.lib_flow.connect("child-activated", self._on_lib_tile)
        note = Gtk.Label(label=strings.TH_THEME_WALLS_NOTE, xalign=0, wrap=True)
        note.add_css_class("sh-group-note")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.append(note)
        inner.append(self.lib_flow)
        self.lib_revealer = Gtk.Revealer(child=inner, reveal_child=False)
        self.walls_row = group.add(Row(strings.TH_THEME_WALLS, " ", suffix=suffix,
                                       below=self.lib_revealer, row_id="theme-walls"))
        self.rows["theme-walls"] = self.walls_row

        # ---- per program ------------------------------------------------
        group = self._add(Group(strings.TH_TARGETS_GROUP, strings.TH_TARGETS_NOTE))
        self.target_dropdowns: dict[str, Gtk.DropDown] = {}
        for target in th.TARGETS:
            dropdown = Gtk.DropDown.new_from_strings([strings.TH_AS_SYSTEM])
            dropdown.connect("notify::selected", lambda d, _p, t=target: self._on_target(t, d))
            row = group.add(Row(strings.TH_TARGETS[target], suffix=dropdown,
                                row_id="targets" if target == th.TARGETS[0] else None))
            if target == th.TARGETS[0]:
                self.rows["targets"] = row
            self.target_dropdowns[target] = dropdown

        # ---- own themes -------------------------------------------------
        self.custom_group = self._add(Group(strings.TH_CUSTOM_GROUP, strings.TH_CUSTOM_NOTE))
        self.name_entry = Gtk.Entry(placeholder_text=strings.TH_CUSTOM_NAME_HINT, hexpand=True)
        self.colour_buttons: dict[str, Gtk.ColorDialogButton] = {}
        colours = Gtk.Box(spacing=14)
        for key, label, default in (("accent", strings.TH_CUSTOM_ACCENT, DEFAULT_COLOURS[0]),
                                    ("bg", strings.TH_CUSTOM_BG, DEFAULT_COLOURS[1]),
                                    ("fg", strings.TH_CUSTOM_FG, DEFAULT_COLOURS[2])):
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
            colour = Gdk.RGBA()
            colour.parse(default)
            button.set_rgba(colour)
            pair = Gtk.Box(spacing=6)
            pair.append(Gtk.Label(label=label))
            pair.append(button)
            colours.append(pair)
            self.colour_buttons[key] = button
        save = Gtk.Button(label=strings.TH_CUSTOM_SAVE)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save_custom())
        self.name_entry.connect("activate", lambda *_: self._save_custom())
        below = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        below.append(self.name_entry)
        line = Gtk.Box(spacing=12)
        colours.set_hexpand(True)
        line.append(colours)
        line.append(save)
        below.append(line)
        self.rows["custom"] = self.custom_group.add(Row(strings.TH_CUSTOM_NAME, below=below,
                                                        row_id="custom"))

        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self.refresh()

    def _add(self, group: Group) -> Group:
        self._main.append(self.add_group(group))
        return group

    @contextmanager
    def _quiet(self):
        self._quiet_depth += 1
        try:
            yield
        finally:
            self._quiet_depth -= 1

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    # ---- signals ----------------------------------------------------------

    def _on_card(self, _flow, card: Card) -> None:
        self.controller.choose(card.theme.id)

    def _on_walls_switch(self, switch: Gtk.Switch, _pspec) -> None:
        if not self._quiet_depth:
            self.controller.set_wallpapers(switch.get_active())

    def _on_target(self, target: str, dropdown: Gtk.DropDown) -> None:
        if self._quiet_depth:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(self.target_ids):
            self.controller.set_target(target, self.target_ids[index])

    def _on_walls_theme(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._quiet_depth:
            return
        index = dropdown.get_selected()
        if 0 <= index < len(self.walls_ids):
            self.walls_theme = self.walls_ids[index]
            self.controller.load_walls(self.walls_theme)

    def _on_walls_edit(self, button: Gtk.ToggleButton) -> None:
        on = button.get_active()
        button.set_label(strings.TH_THEME_WALLS_DONE if on else strings.TH_THEME_WALLS_EDIT)
        if on and not self.tiles:
            self._fill_library()
        self.lib_revealer.set_reveal_child(on)

    def _on_lib_tile(self, _flow, tile: Tile) -> None:
        if self.walls_theme is None:
            return
        on = tile.image.real not in self.walls_paths
        # Show it at once (a quick second click must undo it); the reply re-reads.
        (self.walls_paths.add if on else self.walls_paths.discard)(tile.image.real)
        (tile.add_css_class if on else tile.remove_css_class)("sh-current")
        self.controller.toggle_wall(self.walls_theme, tile.image.path, on)

    def _save_custom(self) -> None:
        b = self.colour_buttons
        self.controller.save_custom(self.name_entry.get_text(), rgba_hex(b["accent"].get_rgba()),
                                    rgba_hex(b["bg"].get_rgba()), rgba_hex(b["fg"].get_rgba()))

    def custom_saved(self) -> None:
        self.name_entry.set_text("")

    # ---- library grid ---------------------------------------------------

    def _fill_library(self) -> None:
        images = self.wallpaper.images()
        for image in images:
            tile = Tile(image)
            self.lib_flow.append(tile)
            self.tiles.append(tile)
            self._load(tile)
        self.wallpaper.queue_thumbs(images, self._thumb_ready)
        self._mark_tiles()

    def _load(self, tile: Tile) -> None:
        image = tile.image
        source = str(image.thumb) if wp._nonempty(image.thumb) else image.path

        def done(texture, error) -> None:
            if error is None and texture is not None:
                tile.picture.set_paintable(texture)

        self.ctx.workers.submit(LOAD_WORKER, lambda: texture_from(source, TILE_W * 2), done,
                                key=("load", image.path))

    def _thumb_ready(self, image: wp.Image, made: bool) -> None:
        if made:
            for tile in self.tiles:
                if tile.image.path == image.path:
                    self._load(tile)

    def _mark_tiles(self) -> None:
        for tile in self.tiles:
            if tile.image.real in self.walls_paths:
                tile.add_css_class("sh-current")
            else:
                tile.remove_css_class("sh-current")

    # ---- the controller's view ------------------------------------------

    def show_missing(self, detail: str) -> None:
        for group in self._main:
            group.set_visible(False)
        self.missing_group.set_visible(True)
        self.missing_row.subtitle_label.set_label(strings.TH_MISSING_HINT.format(path=detail))
        self.missing_row.subtitle_label.set_visible(True)

    def show(self, themes: list[th.ThemeInfo], state: th.State) -> None:
        self.missing_group.set_visible(False)
        for group in self._main:
            group.set_visible(True)
        signature = [(t.id, t.name, t.kind, tuple(sorted((t.palette or {}).items())))
                     for t in themes]
        if signature != [(c.theme.id, c.theme.name, c.theme.kind,
                          tuple(sorted((c.theme.palette or {}).items()))) for c in self.cards]:
            self.flow.remove_all()
            self.cards = [Card(t) for t in themes]
            for card in self.cards:
                self.flow.append(card)
        else:  # same cards; only the counts and the active one may differ
            for card, theme in zip(self.cards, themes, strict=True):
                card.theme = theme
        for card in self.cards:
            if card.theme.id == state.system:
                card.add_css_class("sh-current")
            else:
                card.remove_css_class("sh-current")

        names = {t.id: t.name for t in themes}
        with self._quiet():
            self.walls_switch.set_active(state.wallpapers)
            ids = [th.AS_SYSTEM, *names]
            labels = [strings.TH_AS_SYSTEM, *names.values()]
            if ids != self.target_ids:
                self.target_ids = ids
                for dropdown in self.target_dropdowns.values():
                    dropdown.set_model(Gtk.StringList.new(labels))
            for target, dropdown in self.target_dropdowns.items():
                dropdown.set_selected(ids.index(state.targets.get(target, th.AS_SYSTEM))
                                      if state.targets.get(target, th.AS_SYSTEM) in ids else 0)
            walls_ids = [t.id for t in themes if t.kind != "wallpaper"]
            if walls_ids != self.walls_ids:
                self.walls_ids = walls_ids
                self.walls_dropdown.set_model(Gtk.StringList.new([names[i] for i in walls_ids]))
            if self.walls_theme not in walls_ids:
                self.walls_theme = state.system if state.system in walls_ids else (
                    walls_ids[0] if walls_ids else None)
            if self.walls_theme is not None:
                self.walls_dropdown.set_selected(walls_ids.index(self.walls_theme))
        if self.walls_theme is not None:
            self.controller.load_walls(self.walls_theme)
        self._show_custom(themes)

    def _show_custom(self, themes: list[th.ThemeInfo]) -> None:
        for row in self.custom_rows:
            self.custom_group.list.remove(row)
        self.custom_rows = []
        for theme in themes:
            if theme.kind != "custom":
                continue
            button = Gtk.Button(label=strings.TH_CUSTOM_DELETE)
            button.add_css_class("destructive-action")
            button.connect("clicked", lambda *_a, t=theme: self._ask_delete(t))
            row = self.custom_group.add(Row(theme.name, suffix=button))
            self.custom_rows.append(row)

    def _ask_delete(self, theme: th.ThemeInfo) -> None:
        self.confirm(strings.TH_CUSTOM_DELETE + f" «{theme.name}»?", "",
                     strings.TH_CUSTOM_DELETE, lambda: self.controller.delete_custom(theme.id))

    def show_walls(self, theme_id: str, paths: list[str]) -> None:
        if theme_id != self.walls_theme:
            return
        self.walls_paths = {os.path.realpath(p) for p in paths}
        own_dir = os.sep + os.path.join("themes", theme_id) + os.sep
        in_set = sum(1 for p in paths if own_dir in p)
        hint = (strings.TH_THEME_WALLS_HINT.format(n=in_set, m=len(paths) - in_set)
                if paths else strings.TH_THEME_WALLS_NONE)
        self.walls_row.subtitle_label.set_label(hint)
        self.walls_row.subtitle_label.set_visible(True)
        self._mark_tiles()

    def busy(self, on: bool) -> None:
        for widget in (self.flow, self.random_button, self.walls_switch,
                       *self.target_dropdowns.values()):
            widget.set_sensitive(not on)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = ThemesPage
