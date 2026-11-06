"""The "Game binds" page logic. No GTK.

The whole list (on/off, games, combinations) is one History item, so every
change can be undone from the journal. The page shows the new list at once;
if writing it fails, what is on disk comes back. A failed Hyprland reload is
only a warning: the list is saved (and logged), Hyprland takes it at its next
reload.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import game_binds as gb


class View(Protocol):
    def show_state(self, state: dict[str, Any]) -> None: ...

    def show_probe(self, probe: gb.Probe) -> None: ...

    def status(self, text: str) -> None: ...


class Controller:
    def __init__(self, backend: gb.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.state: dict[str, Any] = backend.load()

    def refresh(self) -> None:
        self.state = self.backend.load()
        self.view.show_state(self.state)
        self.backend.queue_probe(list(self.state["combos"]), self._probed)

    def _probed(self, probe: gb.Probe | None, error: BaseException | None) -> None:
        if error is None and probe is not None:
            self.view.show_probe(probe)

    # ---- changes ---------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self._change({**self.state, "enabled": bool(enabled)},
                     strings.GB_DONE_ON if enabled else strings.GB_DONE_OFF)

    def add_pattern(self, text: str) -> bool:
        pattern = gb.clean_pattern(text)
        if pattern is None:
            self.view.status(strings.GB_BAD_PATTERN)
            return False
        if pattern.lower() in (p.lower() for p in self.state["patterns"]):
            self.view.status(strings.GB_PATTERN_EXISTS.format(pattern=pattern))
            return False
        if len(self.state["patterns"]) >= gb.MAX_ITEMS:
            self.view.status(strings.GB_FULL)
            return False
        self._change({**self.state, "patterns": [*self.state["patterns"], pattern]},
                     strings.GB_DONE_PATTERN_ADDED.format(pattern=pattern))
        return True

    def remove_pattern(self, pattern: str) -> None:
        left = [p for p in self.state["patterns"] if p != pattern]
        self._change({**self.state, "patterns": left},
                     strings.GB_DONE_PATTERN_REMOVED.format(pattern=pattern))

    def add_combo(self, mask: int, key: str) -> bool:
        combo = gb.clean_combo(gb.combo_of(mask, key))
        if combo is None:
            self.view.status(strings.GB_BAD_COMBO)
            return False
        if any(gb.same_combo(combo, c) for c in self.state["combos"]):
            self.view.status(strings.GB_COMBO_EXISTS.format(combo=combo))
            return False
        if len(self.state["combos"]) >= gb.MAX_ITEMS:
            self.view.status(strings.GB_FULL)
            return False
        self._change({**self.state, "combos": [*self.state["combos"], combo]},
                     strings.GB_DONE_COMBO_ADDED.format(combo=combo))
        return True

    def remove_combo(self, combo: str) -> None:
        left = [c for c in self.state["combos"] if c != combo]
        self._change({**self.state, "combos": left},
                     strings.GB_DONE_COMBO_REMOVED.format(combo=combo))

    def _change(self, new: dict[str, Any], done_text: str) -> None:
        new = gb.normalize(new)
        before = self.state
        if new == before:
            return
        self.state = new
        self.view.show_state(new)

        def done(result: tuple[bool, str] | None, error: BaseException | None) -> None:
            written, message = result if result is not None else (False, str(error))
            if error is not None or not written:
                self.state = self.backend.load()  # what is really on disk now
                self.view.show_state(self.state)
                self.view.status(strings.GB_FAILED.format(error=message or error))
                return
            self.history.record([(gb.BACKEND, gb.KEY, strings.GB_LABEL, before, new)])
            self.view.status(strings.GB_NO_RELOAD.format(error=message) if message
                             else done_text)
            self.backend.queue_probe(list(new["combos"]), self._probed)

        self.backend.queue_save(new, done)
