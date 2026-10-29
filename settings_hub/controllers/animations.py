"""The "Animations" page logic. No GTK.

* A preset tile applies the whole preset at once and resets the four
  categories (as in the rofi grid); a variant or a speed changes one category
  on top of the preset. Each choice is one History group: a preset logs the
  preset and every category it reset.
* "Look" hides the window, runs anim-preview.sh (ANIM_PREVIEW_REOPEN=0, so no
  rofi grid opens afterwards) and shows the window again when it is done.
* The page re-reads the module's files when shown; a re-read never overwrites
  a control whose change is still queued.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import animations as an
from ..backends.animations import BACKEND, PRESET_KEY, Change


class View(Protocol):
    def show_setup(self, state: str, detail: str) -> None: ...

    def show_state(self, state: dict[str, Any], keys: set[str]) -> None:
        """Show these keys of the state (others have a change queued)."""

    def hide_window(self) -> None: ...

    def show_window(self) -> None: ...

    def status(self, text: str) -> None: ...


class Controller:
    def __init__(self, backend: an.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.pending: set[str] = set()
        self.previewing = False
        backend.on_external.append(lambda _keys: self.refresh())

    def label_for(self, key: str) -> str:
        kind, _, category = key.partition(".")
        if key == PRESET_KEY:
            return strings.AN_LABEL_PRESET
        title = self.backend.category_title(category).lower()
        if kind == "override":
            return strings.AN_LABEL_OVERRIDE.format(category=title)
        return strings.AN_LABEL_SPEED.format(category=title)

    # ---- reading ----------------------------------------------------------

    def refresh(self) -> None:
        state, detail = self.backend.state()
        self.view.show_setup(state, detail)
        if state != "ok":
            return
        current = self.backend.read_all()
        self.view.show_state(current, set(current) - self.pending)

    # ---- changing ---------------------------------------------------------

    def _submit(self, values: dict[str, Any], message: str, guard: bool = False,
                label: str | None = None) -> None:
        keys = set(values)
        self.pending |= keys
        self.view.status(strings.AN_APPLYING)

        def done(change: Change | None, error: BaseException | None) -> None:
            self.pending -= keys
            if error is not None:
                self.view.status(strings.AN_FAILED.format(error=error))
            else:
                items = [(BACKEND, k, label or self.label_for(k), before, after)
                         for k, (before, after) in change.changed().items()]
                if items:
                    self.history.record(items)
                self.view.status(message if change.reload_ok else strings.AN_FAILED.format(
                    error="hyprctl reload"))
            self.refresh()

        self.backend.queue_write(values, done, guard=guard)

    def choose_preset(self, preset_id: str) -> None:
        before = self.backend.read_all()
        name = self.backend.preset_name(preset_id)
        if before[PRESET_KEY] == preset_id and not self.backend.is_custom(before):
            message = self.backend.t("anim_already", name=name)
        else:
            message = self.backend.t("anim_applied", name=name)
        # One action, one line in History: the categories it reset are part of it.
        self._submit(self.backend.preset_values(preset_id), message,
                     label=strings.AN_LABEL_PRESET_NAMED.format(name=name))

    def choose_variant(self, category: str, variant_id: str | None) -> None:
        key = an.override_key(category)
        if key not in self.pending and self.backend.read([key])[key] == (variant_id or None):
            return  # the drop-down echoed a value it was given
        title = self.backend.category_title(category)
        if variant_id:
            message = self.backend.t("anim_cat_applied", category=title,
                                     name=self.backend.variant_name(category, variant_id))
        else:
            message = self.backend.t("anim_cat_reset", category=title)
        self._submit({key: variant_id or None}, message, guard=True)

    def choose_speed(self, category: str, speed: str) -> None:
        key = an.speed_key(category)
        if key not in self.pending and self.backend.read([key])[key] == speed:
            return
        message = self.backend.t("anim_speed_applied",
                                 category=self.backend.category_title(category),
                                 speed=self.backend.speed_title(speed).lower())
        self._submit({key: speed}, message)

    # ---- live preview -----------------------------------------------------

    def preview(self, category: str | None = None) -> None:
        """Show the saved preset, or one category as it is set now, live."""
        if self.previewing:
            return
        state = self.backend.read_all()
        if category is None:
            argv = self.backend.preview_argv(preset=state[PRESET_KEY])
        else:  # the saved tuning with this row as it is: includes the saved speed
            argv = self.backend.preview_argv(category, state[an.override_key(category)])
        self.previewing = True
        self.view.status(strings.AN_PREVIEWING)
        self.view.hide_window()

        def done(result, error) -> None:
            self.previewing = False
            ok, message = (False, str(error)) if error is not None else result
            self.view.show_window()
            self.view.status("" if ok else strings.AN_PREVIEW_FAILED.format(error=message))

        self.backend.queue_preview(argv, done)
