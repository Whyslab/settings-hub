"""The "Game binds" page: key combinations that are off while a game is focused.

The work is done by Hyprland itself (see backends/game_binds.py); the page
only edits the list: on/off, which windows are games, which combinations.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .. import strings  # noqa: E402
from ..backends import game_binds as gb  # noqa: E402
from ..binds import names  # noqa: E402
from ..controllers.game_binds import Controller  # noqa: E402
from ..widgets.keycapture import Captured, KeyCapture  # noqa: E402
from ..widgets.rows import Group, Row  # noqa: E402
from .base import Page  # noqa: E402


def _remove_button(on_click) -> Gtk.Button:
    button = Gtk.Button(label=strings.GB_REMOVE)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: on_click())
    return button


def _combo_label(combo: str) -> str:
    mask, key = gb.parse_combo(combo)
    return names.combo_label(mask, key)


class GameBindsPage(Page):
    def build(self) -> None:
        backend = self.ctx.backends.get(gb.BACKEND)
        if backend is None:
            backend = gb.Backend(self.ctx.workers)
            gb.register(self.ctx.history, backend)
            self.ctx.backends[gb.BACKEND] = backend
        self.backend = backend
        self._quiet = False
        self._state: dict[str, Any] = backend.load()
        self._probe = gb.Probe()
        self._classes: list[str] = []
        self._combo_rows: dict[str, Row] = {}
        self.capture: KeyCapture | None = None
        self.capture_inhibit = True  # False: tests emulate a compositor that refuses

        mode = self.add_group(Group(strings.GB_MODE, strings.GB_MODE_NOTE))
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._on_switch)
        self.rows["enabled"] = mode.add(Row(strings.GB_ENABLED, suffix=self.switch,
                                            row_id="enabled"))
        self.not_loaded = Gtk.Label(label=strings.GB_NOT_LOADED, xalign=0, wrap=True,
                                    visible=False)
        self.not_loaded.add_css_class("sh-group-note")
        mode.append(self.not_loaded)

        self.games = self.add_group(Group(strings.GB_GAMES, strings.GB_GAMES_NOTE))
        add_game = self.add_group(Group())
        self.open_dropdown = Gtk.DropDown.new_from_strings([strings.GB_NO_OPEN])
        self.open_dropdown.set_valign(Gtk.Align.CENTER)
        self.open_add = Gtk.Button(label=strings.GB_ADD, sensitive=False)
        self.open_add.connect("clicked", lambda *_: self._add_open())
        box = Gtk.Box(spacing=8)
        box.append(self.open_dropdown)
        box.append(self.open_add)
        add_game.add(Row(strings.GB_FROM_OPEN, strings.GB_FROM_OPEN_HINT, suffix=box,
                         row_id="from-open"))
        self.entry = Gtk.Entry(placeholder_text=strings.GB_OWN_PATTERN_PLACEHOLDER,
                               width_chars=22, max_length=gb.MAX_TEXT)
        self.entry.connect("activate", lambda *_: self._add_typed())
        typed_add = Gtk.Button(label=strings.GB_ADD)
        typed_add.connect("clicked", lambda *_: self._add_typed())
        box = Gtk.Box(spacing=8)
        box.append(self.entry)
        box.append(typed_add)
        add_game.add(Row(strings.GB_OWN_PATTERN, suffix=box, row_id="own-pattern"))

        self.combos = self.add_group(Group(strings.GB_COMBOS, strings.GB_COMBOS_NOTE))
        add_combo = self.add_group(Group())
        self.press = Gtk.Button(label=strings.GB_PRESS)
        self.press.connect("clicked", lambda *_: self._start_capture())
        add_combo.add(Row(strings.GB_ADD_COMBO, suffix=self.press, row_id="add-combo"))

        self.controller = Controller(backend, self.ctx.history, self)

    def refresh(self) -> None:
        if self.capture is None:
            self.controller.refresh()

    # ---- View ------------------------------------------------------------

    def status(self, text: str) -> None:
        self.ctx.status(text)

    def show_state(self, state: dict[str, Any]) -> None:
        self._state = state
        self._quiet = True
        try:
            self.switch.set_active(bool(state["enabled"]))
        finally:
            self._quiet = False
        self._fill_games()
        self._fill_combos()
        self._fill_open()

    def show_probe(self, probe: gb.Probe) -> None:
        """Only texts change: the rows stay (a search result keeps its highlight)."""
        self._probe = probe
        self.not_loaded.set_visible(not probe.loaded)
        if set(self._combo_rows) == set(self._state["combos"]):
            for combo, row in self._combo_rows.items():
                row.subtitle_label.set_label(self._action_text(combo))
        else:
            self._fill_combos()
        self._fill_open()

    def _action_text(self, combo: str) -> str:
        action = self._probe.actions.get(combo)
        return strings.GB_ACTION_NONE if action is None else action or strings.GB_ACTION_NO_TEXT

    # ---- lists -----------------------------------------------------------

    def _fill_games(self) -> None:
        self.games.clear()
        if not self._state["patterns"]:
            self.rows["games"] = self.games.add(Row(strings.GB_NO_GAMES, row_id="games"))
            return
        for i, pattern in enumerate(self._state["patterns"]):
            row = self.games.add(Row(pattern, suffix=_remove_button(
                lambda p=pattern: self.controller.remove_pattern(p)),
                row_id="games" if i == 0 else f"game:{pattern}"))
            if i == 0:
                self.rows["games"] = row

    def _fill_combos(self) -> None:
        self.combos.clear()
        self._combo_rows = {}
        if not self._state["combos"]:
            self.rows["combos"] = self.combos.add(Row(strings.GB_NO_COMBOS, row_id="combos"))
            return
        for i, combo in enumerate(self._state["combos"]):
            row = self.combos.add(Row(_combo_label(combo), self._action_text(combo),
                                      suffix=_remove_button(
                lambda c=combo: self.controller.remove_combo(c)),
                row_id="combos" if i == 0 else f"combo:{combo}"))
            self._combo_rows[combo] = row
            row.title_label.add_css_class("sh-keys")
            row.title_label.set_halign(Gtk.Align.START)  # the key pill hugs its text
            if i == 0:
                self.rows["combos"] = row

    def _fill_open(self) -> None:
        """Open windows that no pattern matches yet."""
        classes = [c for c in self._probe.classes
                   if not any(gb.matches(p, c) for p in self._state["patterns"])]
        if classes == self._classes and self.open_dropdown.get_model() is not None \
                and self._classes:
            return  # the same windows: keep what the person picked
        self._classes = classes
        shown = self._classes or [strings.GB_NO_OPEN]
        self.open_dropdown.set_model(Gtk.StringList.new(shown))
        self.open_add.set_sensitive(bool(self._classes))

    # ---- handlers --------------------------------------------------------

    def _on_switch(self, switch: Gtk.Switch, _pspec) -> None:
        if not self._quiet:
            self.controller.set_enabled(switch.get_active())

    def _add_open(self) -> None:
        index = self.open_dropdown.get_selected()
        if 0 <= index < len(self._classes):
            self.controller.add_pattern(self._classes[index])

    def _add_typed(self) -> None:
        if self.controller.add_pattern(self.entry.get_text()):
            self.entry.set_text("")

    def _start_capture(self) -> None:
        if self.capture is not None:
            return

        def done(result: Captured | None) -> None:
            self.capture = None
            self.press.set_label(strings.GB_PRESS)
            self.press.set_sensitive(True)
            if result is not None:
                self.controller.add_combo(result.mask, result.key)

        self.capture = KeyCapture(self.widget, done, self.backend.hyprctl,
                                  inhibit=self.capture_inhibit)
        self.press.set_label(strings.GB_PRESSING)
        self.press.set_sensitive(False)
        self.ctx.status(strings.GB_PRESSING)
        self.capture.start()


PAGE = GameBindsPage
