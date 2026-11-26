"""The editor of the home screen: which big tiles and in what order, pinned rows, commands.

    editor = Editor(home)    # home.Home; shown by home.edit(True) in place of the tiles
    editor.fill()            # re-read the three lists from the window's settings

Every change goes through home.change(), so it is saved at once and undone with
Ctrl+Z like any setting on the General page; the home screen follows the
settings, so it is rebuilt behind the editor while it is open.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import home_items, registry, strings  # noqa: E402
from . import search as hub_search  # noqa: E402
from . import settings as hub_settings  # noqa: E402
from .widgets.rows import Group, Row  # noqa: E402

TILES, PINS, COMMANDS = "home.tiles", "home.pins", "home.commands"
RESULTS = 8


class Editor:
    def __init__(self, home) -> None:
        self.home = home
        self.settings = home.settings
        self._queued = False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.add_css_class("sh-home")
        box.add_css_class("sh-home-editor")

        header = Gtk.Box(spacing=16)
        title = Gtk.Label(label=strings.HOME_EDIT_TITLE, xalign=0, hexpand=True)
        title.add_css_class("sh-home-title")
        header.append(title)
        self.done = Gtk.Button(label=strings.HOME_EDIT_DONE, valign=Gtk.Align.CENTER)
        self.done.add_css_class("suggested-action")
        self.done.connect("clicked", lambda *_: home.edit(False))
        header.append(self.done)
        box.append(header)

        self.tiles_group = Group(strings.HOME_EDIT_TILES, strings.HOME_EDIT_TILES_HINT)
        box.append(self.tiles_group)

        self.pins_group = Group(strings.HOME_EDIT_PINS, strings.HOME_EDIT_PINS_HINT)
        box.append(self.pins_group)
        self.search = Gtk.SearchEntry(placeholder_text=strings.HOME_EDIT_PIN_SEARCH)
        self.search.connect("search-changed", lambda *_: self._fill_results())
        box.append(self.search)
        self.results = Group()
        self.results.set_visible(False)
        box.append(self.results)

        self.commands_group = Group(strings.HOME_EDIT_COMMANDS, strings.HOME_EDIT_COMMANDS_HINT)
        box.append(self.commands_group)
        add = Gtk.Box(spacing=8)
        self.name_entry = Gtk.Entry(placeholder_text=strings.HOME_EDIT_NAME,
                                    max_length=hub_settings.NAME_MAX, width_chars=14)
        self.cmd_entry = Gtk.Entry(placeholder_text=strings.HOME_EDIT_COMMAND,
                                   max_length=hub_settings.COMMAND_MAX, hexpand=True)
        self.cmd_entry.connect("activate", lambda *_: self._add_command())
        self.add_button = Gtk.Button(label=strings.HOME_EDIT_ADD)
        self.add_button.connect("clicked", lambda *_: self._add_command())
        for widget in (self.name_entry, self.cmd_entry, self.add_button):
            add.append(widget)
        box.append(add)
        self.add_note = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.add_note.add_css_class("sh-group-note")
        box.append(self.add_note)
        self.widget = box

    # ---- showing ---------------------------------------------------------------

    def fill_later(self) -> None:
        """fill() once the click that changed a list has finished (its row goes away)."""
        if not self._queued:
            self._queued = True
            GLib.idle_add(self._fill_idle)

    def _fill_idle(self) -> bool:
        self._queued = False
        self.fill()
        return False

    @staticmethod
    def _buttons(count: int, index: int, on_move, on_remove=None) -> Gtk.Box:
        box = Gtk.Box(spacing=4)
        for text, tip, step, enabled in (("↑", strings.HOME_EDIT_UP, -1, index > 0),
                                         ("↓", strings.HOME_EDIT_DOWN, 1, index < count - 1)):
            button = Gtk.Button(label=text, valign=Gtk.Align.CENTER, sensitive=enabled)
            button.set_tooltip_text(tip)
            button.connect("clicked", lambda *_a, d=step: on_move(index, d))
            box.append(button)
        if on_remove is not None:
            remove = Gtk.Button(label="✕", valign=Gtk.Align.CENTER)
            remove.set_tooltip_text(strings.HOME_EDIT_REMOVE)
            remove.connect("clicked", lambda *_a: on_remove(index))
            box.append(remove)
        return box

    def fill(self) -> None:
        order = self.settings.get(TILES)
        self.tiles_group.clear()
        for index, page_id in enumerate(order):
            suffix = self._buttons(len(order), index, self._move_tile)
            suffix.append(self._tile_switch(page_id, True))
            self.tiles_group.add(Row(registry.title(page_id), suffix=suffix))
        for page_id in hub_settings.HOME_TILES:
            if page_id not in order:
                self.tiles_group.add(Row(registry.title(page_id),
                                         suffix=self._tile_switch(page_id, False)))

        pins = self.settings.get(PINS)
        self.pins_group.clear()
        for index, address in enumerate(pins):
            pin = home_items.pin_of(address)
            suffix = self._buttons(len(pins), index, self._move_pin, self._unpin)
            if pin is None:
                row = Row(strings.HOME_EDIT_PIN_GONE.format(address=address), suffix=suffix)
            else:
                row = Row(pin.row_title, pin.page_title, suffix=suffix)
            self.pins_group.add(row)
        if not pins:
            self.pins_group.add(Row(strings.HOME_EDIT_EMPTY))
        self._fill_results()

        commands = self.settings.get(COMMANDS)
        self.commands_group.clear()
        for index, command in enumerate(commands):
            suffix = self._buttons(len(commands), index, self._move_command,
                                   self._remove_command)
            row = Row(command["name"], command["cmd"], suffix=suffix)
            row.subtitle_label.set_selectable(True)  # the command can be copied
            self.commands_group.add(row)
        if not commands:
            self.commands_group.add(Row(strings.HOME_EDIT_EMPTY))

    def _tile_switch(self, page_id: str, on: bool) -> Gtk.Switch:
        switch = Gtk.Switch(active=on, valign=Gtk.Align.CENTER)
        switch.update_property([Gtk.AccessibleProperty.LABEL], [registry.title(page_id)])
        switch.connect("notify::active", lambda s, _p: self._toggle_tile(page_id, s.get_active()))
        return switch

    def _fill_results(self) -> None:
        self.results.clear()
        text = self.search.get_text().strip()
        found = [r for r in hub_search.search(text, RESULTS * 2) if r.row_id] if text else []
        found = [r for r in found if home_items.pin_of(
            home_items.address(r.page_id, r.row_id)) is not None][:RESULTS]
        self.results.set_visible(bool(found))
        pins = self.settings.get(PINS)
        full = len(pins) >= hub_settings.BY_KEY[PINS].hi
        for result in found:
            address = home_items.address(result.page_id, result.row_id)
            if address in pins:
                suffix: Gtk.Widget = Gtk.Label(label=strings.HOME_EDIT_PINNED)
                suffix.add_css_class("sh-dim")
            else:
                suffix = Gtk.Button(label=strings.HOME_EDIT_PIN, sensitive=not full)
                if full:
                    suffix.set_tooltip_text(strings.HOME_EDIT_PINS_FULL.format(
                        count=hub_settings.BY_KEY[PINS].hi))
                suffix.connect("clicked", lambda *_a, a=address: self._pin(a))
            self.results.add(Row(result.row_title or "", result.title, suffix=suffix))

    # ---- changes ---------------------------------------------------------------

    def _change(self, key: str, value) -> bool:
        if self.home.change(key, value):
            self.home.ctx.status(strings.HOME_EDIT_SAVED)
            return True
        return False

    def _move_tile(self, index: int, step: int) -> None:
        self._change(TILES, home_items.moved(self.settings.get(TILES), index, step))

    def _toggle_tile(self, page_id: str, on: bool) -> None:
        order = self.settings.get(TILES)
        if on and page_id not in order:
            order.append(page_id)
        elif not on and page_id in order:
            order.remove(page_id)
        else:
            return
        self._change(TILES, order)

    def _pin(self, address: str) -> None:
        pins = self.settings.get(PINS)
        if address not in pins:
            self._change(PINS, [*pins, address])

    def _move_pin(self, index: int, step: int) -> None:
        self._change(PINS, home_items.moved(self.settings.get(PINS), index, step))

    def _unpin(self, index: int) -> None:
        pins = self.settings.get(PINS)
        if 0 <= index < len(pins):
            pins.pop(index)
            self._change(PINS, pins)

    def _add_command(self) -> None:
        commands = self.settings.get(COMMANDS)
        most = hub_settings.BY_KEY[COMMANDS].hi
        if len(commands) >= most:
            self._note(strings.HOME_EDIT_COMMANDS_FULL.format(count=most))
            return
        item = {"name": self.name_entry.get_text(), "cmd": self.cmd_entry.get_text()}
        if {k: v.strip() for k, v in item.items()} in commands:
            self._note(strings.HOME_EDIT_SAME_COMMAND)
            return
        if not self._change(COMMANDS, [*commands, item]):
            self._note(strings.HOME_EDIT_BAD_COMMAND.format(
                name=hub_settings.NAME_MAX, cmd=hub_settings.COMMAND_MAX))
            return
        self._note("")
        self.name_entry.set_text("")
        self.cmd_entry.set_text("")

    def clear_typing(self, focus: Gtk.Widget | None) -> bool:
        """Esc in a filled field of the editor empties it (instead of leaving)."""
        for entry in (self.search, self.name_entry, self.cmd_entry):
            if focus is not None and (focus is entry or focus.is_ancestor(entry)) \
                    and entry.get_text():
                entry.set_text("")
                return True
        return False

    def _note(self, text: str) -> None:
        self.add_note.set_label(text)
        self.add_note.set_visible(bool(text))

    def _move_command(self, index: int, step: int) -> None:
        self._change(COMMANDS, home_items.moved(self.settings.get(COMMANDS), index, step))

    def _remove_command(self, index: int) -> None:
        commands = self.settings.get(COMMANDS)
        if 0 <= index < len(commands):
            commands.pop(index)
            self._change(COMMANDS, commands)
