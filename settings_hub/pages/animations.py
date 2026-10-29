"""The "Animations" page: presets with pictures, four categories, live preview.

Only widgets live here; controllers.animations.Controller decides what to
write, and this page is its view. Names of presets, categories, variants and
speeds come from rofi-launcher's animations module, in Russian.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import animations as an  # noqa: E402
from ..controllers import animations as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402
from .wallpaper import FixedPicture, segmented, texture_from  # noqa: E402

TILE_W, TILE_H = 118, 74
LOAD_WORKER = "animations-load"


class PresetTile(Gtk.FlowBoxChild):
    def __init__(self, choice: an.Choice) -> None:
        super().__init__()
        self.choice = choice
        frame = Gtk.Overlay()
        frame.add_css_class("sh-thumb")
        frame.add_css_class("sh-anim-thumb")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_halign(Gtk.Align.CENTER)
        frame.set_size_request(TILE_W, TILE_H)
        self.picture = FixedPicture(TILE_W, TILE_H)
        frame.set_child(self.picture)
        if choice.image is None:  # no picture in the cache: the initial, like an avatar
            letter = Gtk.Label(label=choice.name[:1].upper())
            letter.add_css_class("sh-anim-letter")
            frame.add_overlay(letter)
        name = Gtk.Label(label=choice.name, ellipsize=Pango.EllipsizeMode.END,
                         max_width_chars=14)
        name.add_css_class("sh-tile-name")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.append(frame)
        box.append(name)
        self.set_child(box)


class AnimationsPage(Page):
    def build(self) -> None:
        self._quiet_depth = 0
        backend = self.ctx.backends.get(an.BACKEND)
        if backend is None:  # normally created by the app, with History appliers
            backend = an.Backend(self.ctx.workers)
            an.register(self.ctx.history, backend)
            self.ctx.backends[an.BACKEND] = backend
        self.backend = backend
        self.controller = ctl.Controller(backend, self.ctx.history, self)
        self._main: list[Group] = []
        self.tiles: list[PresetTile] = []
        self.dropdowns: dict[str, tuple[Gtk.DropDown, list[str | None]]] = {}
        self.speed_buttons: dict[str, dict[str, Gtk.ToggleButton]] = {}
        self.variant_rows: dict[str, Row] = {}
        self.preview_buttons: list[Gtk.Button] = []

        self.setup_group = self.add_group(Group(strings.AN_SETUP_GROUP))
        self.setup_row = self.setup_group.add(Row(strings.AN_SETUP_ERROR, " "))
        self.setup_group.set_visible(False)
        state, _detail = backend.state()
        if state == "ok":
            self._build_presets()
            for category in backend.categories:
                self._build_category(category)
        self.refresh()

    # ---- building -------------------------------------------------------

    def _add(self, group: Group) -> Group:
        self._main.append(self.add_group(group))
        return group

    def _preview_button(self, category: str | None) -> Gtk.Button:
        button = Gtk.Button(label=strings.AN_PREVIEW, tooltip_text=strings.AN_PREVIEW_HINT)
        button.connect("clicked", lambda *_: self.controller.preview(category))
        self.preview_buttons.append(button)
        return button

    def _build_presets(self) -> None:
        group = self._add(Group(strings.AN_PRESETS_GROUP, strings.AN_PRESETS_NOTE))
        self.preset_row = group.add(Row(strings.AN_PRESET_ROW, " ",
                                        suffix=self._preview_button(None), row_id="presets"))
        self.rows["presets"] = self.preset_row
        self.flow = Gtk.FlowBox(homogeneous=True, min_children_per_line=3,
                                max_children_per_line=5, row_spacing=10, column_spacing=8,
                                selection_mode=Gtk.SelectionMode.NONE,
                                activate_on_single_click=True)
        self.flow.add_css_class("sh-tiles")
        self.flow.connect("child-activated",
                          lambda _f, tile: self.controller.choose_preset(tile.choice.id))
        for choice in self.backend.presets():
            tile = PresetTile(choice)
            self.flow.append(tile)
            self.tiles.append(tile)
            if choice.image is not None:
                self._load(tile)
        grid = group.add(Row(strings.AN_PRESETS_GROUP, below=self.flow))
        grid.title_label.set_visible(False)

    def _load(self, tile: PresetTile) -> None:
        path = str(tile.choice.image)

        def done(texture, error) -> None:
            if error is None and texture is not None:
                tile.picture.set_paintable(texture)

        self.ctx.workers.submit(LOAD_WORKER, lambda: texture_from(path, TILE_W * 2), done,
                                key=("load", path))

    def _build_category(self, category: str) -> None:
        b = self.backend
        group = self._add(Group(b.category_title(category)))
        ids: list[str | None] = [None] + [v.id for v in b.variants(category)]
        names = [b.as_preset_title()] + [v.name for v in b.variants(category)]
        dropdown = Gtk.DropDown.new_from_strings(names)
        dropdown.set_valign(Gtk.Align.CENTER)
        dropdown.connect("notify::selected", lambda d, _p, c=category: self._on_variant(c, d))
        self.dropdowns[category] = (dropdown, ids)
        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        suffix.append(dropdown)
        suffix.append(self._preview_button(category))
        row = group.add(Row(strings.AN_VARIANT_ROW, " ", suffix=suffix, row_id=category))
        self.rows[category] = row
        self.variant_rows[category] = row
        box, buttons = segmented({s: b.speed_title(s) for s in b.speeds},
                                 lambda s, c=category: self._on_speed(c, s))
        self.speed_buttons[category] = buttons
        group.add(Row(strings.AN_SPEED_ROW, suffix=box))

    # ---- page protocol --------------------------------------------------

    def refresh(self) -> None:
        self.controller.refresh()

    @contextmanager
    def _quiet(self):
        self._quiet_depth += 1
        try:
            yield
        finally:
            self._quiet_depth -= 1

    # ---- signals ----------------------------------------------------------

    def _on_variant(self, category: str, dropdown: Gtk.DropDown) -> None:
        if self._quiet_depth:
            return
        ids = self.dropdowns[category][1]
        index = dropdown.get_selected()
        if 0 <= index < len(ids):
            self.controller.choose_variant(category, ids[index])

    def _on_speed(self, category: str, speed: str) -> None:
        if not self._quiet_depth:
            self.controller.choose_speed(category, speed)

    # ---- the controller's view ------------------------------------------

    def show_setup(self, state: str, detail: str) -> None:
        ok = state == "ok"
        for group in self._main:
            group.set_visible(ok)
        self.setup_group.set_visible(not ok)
        if not ok:
            self.setup_row.subtitle_label.set_label(detail)

    def show_state(self, state: dict[str, Any], keys: set[str]) -> None:
        if not self.tiles and not self.dropdowns:
            return  # built without the module (it failed to load)
        b = self.backend
        with self._quiet():
            if an.PRESET_KEY in keys:
                name = b.preset_name(state[an.PRESET_KEY])
                text = strings.AN_PRESET_NOW.format(name=name) if name else strings.AN_PRESET_NONE
                if name and b.is_custom(state):
                    text += " · " + b.t("anim_customised")
                self.preset_row.subtitle_label.set_label(text)
                for tile in self.tiles:
                    if tile.choice.id == state[an.PRESET_KEY]:
                        tile.add_css_class("sh-current")
                    else:
                        tile.remove_css_class("sh-current")
            for category, (dropdown, ids) in self.dropdowns.items():
                key = an.override_key(category)
                if key in keys:
                    value = state[key]
                    dropdown.set_selected(ids.index(value) if value in ids else 0)
                    variant = b.mod.get_variant(category, value) if value else None
                    hint = b.mod._localized(variant.get("description")) if variant else ""
                    row = self.variant_rows[category]
                    row.subtitle_label.set_label(hint)
                    row.subtitle_label.set_visible(bool(hint))
                key = an.speed_key(category)
                if key in keys and state[key] in self.speed_buttons[category]:
                    self.speed_buttons[category][state[key]].set_active(True)

    def hide_window(self) -> None:
        for button in self.preview_buttons:
            button.set_sensitive(False)
        root = self.widget.get_root()
        if root is not None:
            root.set_visible(False)

    def show_window(self) -> None:
        for button in self.preview_buttons:
            button.set_sensitive(True)
        root = self.widget.get_root()
        if root is not None:
            root.present()

    def status(self, text: str) -> None:
        if text:
            self.ctx.status(text)


PAGE = AnimationsPage
