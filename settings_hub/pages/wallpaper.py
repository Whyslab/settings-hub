"""The "Wallpaper" page: target, picture grid, random wallpapers.

Colour themes (and "colours from the wallpaper") have their own page, "Themes".

Only widgets live here; controllers.wallpaper.Controller decides what to run,
and this page is its view. Thumbnails are decoded on a worker thread (scaled
down with GdkPixbuf) and handed to the GTK thread as textures.
"""

from __future__ import annotations

from contextlib import contextmanager

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import wallpaper as wp  # noqa: E402
from ..controllers import wallpaper as ctl  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402

TILE_W, TILE_H = 132, 74
LOAD_WORKER = "wallpaper-load"


def texture_from(path: str, width: int) -> Gdk.Texture | None:
    """Decode and scale a picture (safe on a worker thread)."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, width, -1, True)
    except GLib.Error:
        return None
    # Always four bytes per pixel: GTK's GL renderer (on Xvfb at least) draws
    # three-byte textures as nothing.
    if not pixbuf.get_has_alpha():
        pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    return Gdk.MemoryTexture.new(pixbuf.get_width(), pixbuf.get_height(),
                                 Gdk.MemoryFormat.R8G8B8A8, pixbuf.read_pixel_bytes(),
                                 pixbuf.get_rowstride())


class FixedPicture(Gtk.Picture):
    """A picture of a fixed size whatever its texture's size (a grid tile).

    Gtk.Picture asks for its texture's size; textures are decoded at twice the
    tile size for sharp HiDPI, which would make tiles -- and the grid's column
    count -- depend on the pictures.
    """

    def __init__(self, width: int, height: int) -> None:
        super().__init__(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self._size = (width, height)
        self.set_size_request(width, height)

    def do_measure(self, orientation, _for_size):
        size = self._size[0 if orientation == Gtk.Orientation.HORIZONTAL else 1]
        return size, size, -1, -1


def segmented(items: dict[str, str], on_pick) -> tuple[Gtk.Box, dict[str, Gtk.ToggleButton]]:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    box.add_css_class("sh-segmented")
    buttons: dict[str, Gtk.ToggleButton] = {}
    first = None
    for key, label in items.items():
        button = Gtk.ToggleButton(label=label)
        if first is None:
            first = button
        else:
            button.set_group(first)
        button.connect("toggled", lambda b, k=key: b.get_active() and on_pick(k))
        box.append(button)
        buttons[key] = button
    return box, buttons


class Tile(Gtk.FlowBoxChild):
    def __init__(self, image: wp.Image) -> None:
        super().__init__()
        self.image = image
        self.picture = FixedPicture(TILE_W, TILE_H)
        frame = Gtk.Box()
        frame.add_css_class("sh-thumb")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_halign(Gtk.Align.CENTER)
        frame.append(self.picture)
        name = Gtk.Label(label=image.name.rsplit(".", 1)[0], xalign=0.5,
                         ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=16)
        name.add_css_class("sh-tile-name")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.append(frame)
        box.append(name)
        self.set_child(box)


class WallpaperPage(Page):
    def build(self) -> None:
        self._quiet_depth = 0
        self.tiles: list[Tile] = []
        backend = self.ctx.backends.get(wp.BACKEND)
        if backend is None:  # normally created by the app, with History appliers
            backend = wp.Backend(self.ctx.workers)
            wp.register(self.ctx.history, backend)
            self.ctx.backends[wp.BACKEND] = backend
            self.ctx.backends[wp.THEME] = backend
        self.backend = backend
        self._main: list[Group] = []

        self.setup_group = self.add_group(Group(strings.WP_SETUP_GROUP))
        self.setup_row = self.setup_group.add(Row(strings.WP_SETUP_MISSING))
        self.setup_group.set_visible(False)

        group = self._add(Group())
        box, self.target_buttons = segmented(strings.WP_TARGETS, self._on_target)
        self.target_row = group.add(Row(strings.WP_TARGET_ROW, " ", suffix=box,
                                        row_id="target"))
        self.rows["target"] = self.target_row

        group = self._add(Group(strings.WP_GRID_ROW, strings.WP_GRID_HINT))
        self.flow = Gtk.FlowBox(homogeneous=True, min_children_per_line=3,
                                max_children_per_line=4, row_spacing=10, column_spacing=10,
                                selection_mode=Gtk.SelectionMode.NONE,
                                activate_on_single_click=True)
        self.flow.add_css_class("sh-tiles")
        self.flow.connect("child-activated", self._on_tile)
        self.empty = Gtk.Label(xalign=0, visible=False, wrap=True)
        self.empty.add_css_class("sh-dim")
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.append(self.flow)
        holder.append(self.empty)
        self.rows["grid"] = group.add(Row(strings.WP_GRID_ROW, below=holder, row_id="grid"))
        self.rows["grid"].title_label.set_visible(False)  # the group title says it
        group = self._add(Group())
        button = Gtk.Button(label=strings.WP_ROFI_BUTTON)
        button.connect("clicked", lambda *_: self._open_picker())
        self.rows["rofi"] = group.add(Row(strings.WP_ROFI, strings.WP_ROFI_HINT, suffix=button,
                                          row_id="rofi"))

        group = self._add(Group(strings.WP_RANDOM_GROUP, strings.WP_RANDOM_NOTE))
        self.random_switches: dict[str, Gtk.Switch] = {}
        for target, title in strings.WP_RANDOM_TARGETS.items():
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.connect("notify::active", lambda s, _p, t=target: self._on_random(t, s))
            row = group.add(Row(title, suffix=switch,
                                row_id="random" if target == "desktop" else None))
            if target == "desktop":
                self.rows["random"] = row
            self.random_switches[target] = switch

        self.controller = ctl.Controller(backend, self.ctx.history, self)
        with self._quiet():
            self.target_buttons[self.controller.target].set_active(True)
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

    def _on_target(self, target: str) -> None:
        if not self._quiet_depth:
            self.controller.set_target(target)

    def _on_tile(self, _flow, tile: Tile) -> None:
        self.controller.choose(tile.image)

    def _on_random(self, target: str, switch: Gtk.Switch) -> None:
        if not self._quiet_depth:
            self.controller.random_toggled(target, switch.get_active())

    def _open_picker(self) -> None:
        try:
            proc = Gio.Subprocess.new(self.backend.picker_argv(), Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.ctx.status(strings.WP_FAILED.format(error=exc.message))
            return
        proc.wait_async(None, lambda p, res: p.wait_finish(res))  # reaped, no zombie
        root = self.widget.get_root()
        if root is not None:
            root.set_visible(False)  # the rofi grid takes over

    # ---- the controller's view ------------------------------------------

    def show_setup(self, state: str, detail: str) -> None:
        ok = state == "ok"
        for group in self._main:
            group.set_visible(ok)
        self.setup_group.set_visible(not ok)
        if not ok:
            self.setup_row.subtitle_label.set_label(
                strings.WP_SETUP_MISSING_HINT.format(path=detail))
            self.setup_row.subtitle_label.set_visible(True)

    def show_images(self, images: list[wp.Image]) -> None:
        self.flow.remove_all()
        self.tiles = []
        for image in images:
            tile = Tile(image)
            self.flow.append(tile)
            self.tiles.append(tile)
            self._load(tile)
        self.empty.set_label(strings.WP_EMPTY.format(folder=self.backend.paths.wallpapers))
        self.empty.set_visible(not images)

    def _load(self, tile: Tile) -> None:
        image = tile.image
        source = str(image.thumb) if wp._nonempty(image.thumb) else image.path

        def done(texture, error) -> None:
            if error is None and texture is not None:
                tile.picture.set_paintable(texture)

        self.ctx.workers.submit(LOAD_WORKER, lambda: texture_from(source, TILE_W * 2), done,
                                key=("load", image.path))

    def thumb_ready(self, image: wp.Image, made: bool) -> None:
        if made:
            for tile in self.tiles:
                if tile.image.path == image.path:
                    self._load(tile)

    def show_current(self, target: str, current: dict[str, str],
                     random: dict[str, bool]) -> None:
        targets = wp.TARGETS if target == wp.ALL else (target,)
        paths = {current.get(t, "") for t in targets}
        if any(random.get(t) for t in targets):
            text = strings.WP_NOW_RANDOM
        elif len(paths) > 1:
            text = strings.WP_NOW_MIXED
        else:
            path = paths.pop()
            text = strings.WP_NOW.format(name=path.rsplit("/", 1)[-1] if path else strings.WP_NONE)
        if any(random.get(t) for t in targets):
            text += " · " + strings.WP_RANDOM_WARNING.lower()
        self.target_row.subtitle_label.set_label(text)
        self.target_row.subtitle_label.set_visible(True)
        for tile in self.tiles:
            if ctl.marked(target, tile.image, current):
                tile.add_css_class("sh-current")
            else:
                tile.remove_css_class("sh-current")

    def show_random(self, target: str, enabled: bool) -> None:
        with self._quiet():
            self.random_switches[target].set_active(enabled)

    def status(self, text: str) -> None:
        self.ctx.status(text)


PAGE = WallpaperPage
