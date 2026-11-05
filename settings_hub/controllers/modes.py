"""Applying a mode and finding out which one is on. No GTK.

Every item is read before anything is applied, so History records honest
"before" values; each backend is applied once (one hyprctl batch, one power
command set, one hypridle restart), and the whole mode is one History group.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .. import modes as hub_modes
from .. import strings

log = logging.getLogger(__name__)

WORKER = "modes"


class View(Protocol):
    def show_active(self, active: set[str]) -> None: ...

    def status(self, text: str) -> None: ...


class Controller:
    def __init__(self, history, workers, view: View) -> None:
        self.history = history
        self.workers = workers
        self.view = view
        self.pending = False

    # ---- which mode is on ------------------------------------------------

    def refresh(self) -> None:
        def job() -> dict[tuple[str, str], Any]:
            current: dict[tuple[str, str], Any] = {}
            for mode in hub_modes.MODES:
                for backend in hub_modes.backends(mode):
                    applier = self.history.applier(backend)
                    if applier is None:
                        continue
                    keys = list(hub_modes.values_for(mode, backend))
                    try:
                        values = applier.read(keys)
                    except Exception:  # a missing tool must not break the page
                        continue
                    for key in keys:
                        if key in values:
                            current[(backend, key)] = values[key]
            return current

        self.workers.submit(WORKER, job, self._read_done, key="refresh")

    def _read_done(self, current: dict[tuple[str, str], Any] | None,
                   error: BaseException | None) -> None:
        if error is not None or current is None:
            return
        active = {mode.id for mode in hub_modes.MODES
                  if hub_modes.matches(mode, current)}
        self.view.show_active(active)

    # ---- applying --------------------------------------------------------

    def apply(self, mode_id: str) -> None:
        mode = hub_modes.BY_ID.get(mode_id)
        if mode is None or self.pending:
            return
        self.pending = True

        def job() -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]],
                           list[str]]:
            before: dict[str, dict[str, Any]] = {}
            after: dict[str, dict[str, Any]] = {}
            wanted: dict[str, dict[str, Any]] = {}
            failed: set[str] = set()
            errors: list[str] = []
            for backend in hub_modes.backends(mode):
                applier = self.history.applier(backend)
                values = hub_modes.values_for(mode, backend)
                wanted[backend] = values
                if applier is None:
                    failed.add(backend)
                    errors.append(f"{backend}: {strings.MODE_NO_APPLIER}")
                    continue
                try:
                    before[backend] = applier.read(list(values))
                except Exception as exc:
                    failed.add(backend)
                    errors.append(f"{backend}: {exc}")
            for backend, values in wanted.items():
                if backend in failed:
                    continue
                applier = self.history.applier(backend)
                try:
                    applier.apply(values)
                    # What is in use (a backlight rounds); a queued write is not
                    # done yet, so it counts as asked.
                    after[backend] = dict(values)
                    if not getattr(applier, "queued", False):
                        try:
                            after[backend].update(applier.read(list(values)))
                        except Exception as exc:
                            log.warning("reading %s after a mode: %s", backend, exc)
                except Exception as exc:
                    errors.append(f"{backend}: {exc}")
                    # It may have done a part of it: ask what is in use.
                    try:
                        after[backend] = applier.read(list(values))
                    except Exception:
                        after[backend] = {}
            return mode_id, before, after, errors

        self.workers.submit(WORKER, job, self._applied, key="apply")

    def _applied(self, result, error: BaseException | None) -> None:
        self.pending = False
        if error is not None or result is None:
            self.view.status(strings.MODE_FAILED.format(error=error))
            return
        mode_id, before, after, errors = result
        mode = hub_modes.BY_ID[mode_id]
        items = []
        for backend, values in after.items():
            for key, value in values.items():
                was = before.get(backend, {}).get(key)
                if was is None or was == value:  # nothing to take back
                    continue
                items.append((backend, key, hub_modes.label_for(backend, key),
                              was, value))
        if items:
            self.history.record(items)
        if errors:
            self.view.status(strings.MODE_FAILED.format(error="; ".join(errors)))
            return
        self.view.status(strings.MODE_APPLIED.format(
            name=strings.MODES[mode.id][0]))
        self.refresh()
