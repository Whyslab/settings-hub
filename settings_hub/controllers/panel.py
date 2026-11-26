"""The "Panel" page logic: HyprPanel's position, look, clock, font, modules. No GTK.

Each change is one History item whose "before" is read on the serial worker
right before the write (two quick changes log A->B, B->C). Module moves edit
the layout the page shows and write it whole.
"""

from __future__ import annotations

import itertools
from typing import Any, Protocol

from .. import strings
from ..backends import panel as pb
from ..backends.panel import BACKEND


class View(Protocol):
    def show_panel(self, info: pb.Info, pending: set[str]) -> None: ...

    def status(self, text: str) -> None: ...


def label(key: str) -> str:
    return strings.PANEL_LABELS.get(key, key)


def module_name(module: str) -> str:
    """A module as people call it: strings.PANEL_MODULES, or the name of a custom/ one."""
    if module in strings.PANEL_MODULES:
        return strings.PANEL_MODULES[module]
    if module.startswith("custom/"):
        return strings.PANEL_CUSTOM.format(name=module.split("/", 1)[1])
    return module


class Controller:
    def __init__(self, backend: pb.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.info: pb.Info | None = None
        self.pending: set[str] = set()
        self._inflight: dict[str, int] = {}
        self._jobs = itertools.count()

    def refresh(self) -> None:
        self.backend.queue_probe(self._read)

    def _read(self, info: pb.Info | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.view.status(strings.PANEL_READ_FAILED.format(error=error))
            return
        if self.info is not None:
            # A read that started before a write landed: keep what is being written,
            # or the next module move would start from the old layout.
            for key in self.pending:
                if key in self.info.values:
                    info.values[key] = self.info.values[key]
        self.info = info
        self.view.show_panel(info, set(self.pending))

    def value(self, key: str) -> Any:
        return self.info.values.get(key) if self.info else None

    # ---- changes ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        try:
            value = pb.clean(key, value)
        except (KeyError, ValueError):
            self.view.status(strings.PANEL_BAD_VALUE)
            return
        if self.info is not None:  # what it will be: the next change starts from it
            self.info.values[key] = value
        self.pending.add(key)
        self._inflight[key] = self._inflight.get(key, 0) + 1

        def job() -> tuple[Any, Any]:
            before = self.backend.read([key]).get(key)
            if before != value:
                self.backend.set(key, value)
            return before, self.backend.read([key]).get(key, value)

        try:
            self.backend.workers.submit(pb.WORKER, job, lambda r, e: self._done(key, r, e),
                                        key=("set", next(self._jobs)))
        except RuntimeError:  # the worker is stopped (the app is closing)
            self._done(key, None, RuntimeError("stopped"))

    def _done(self, key: str, result, error: BaseException | None) -> None:
        self._inflight[key] -= 1
        if self._inflight[key] <= 0:
            self._inflight.pop(key)
            self.pending.discard(key)
        if error is not None:
            self.view.status(strings.PANEL_APPLY_FAILED.format(name=label(key), error=error))
        else:
            before, actual = result
            if before is not None and before != actual:
                self.history.record([(BACKEND, key, label(key), before, actual)])
                self.view.status(strings.PANEL_APPLIED.format(name=label(key)))
        if not self._inflight:
            self.refresh()

    # ---- modules ---------------------------------------------------------------

    def sections(self) -> dict[str, list[str]]:
        return pb.sections_of(self.value(pb.LAYOUTS) or {})

    def editable(self) -> bool:
        return self.info is not None and self.info.layouts_ok

    def _write_sections(self, sections: dict[str, list[str]]) -> None:
        if not self.editable():
            self.view.status(strings.PANEL_LAYOUT_UNREADABLE)
            return
        layouts = self.value(pb.LAYOUTS) or {}
        self.set(pb.LAYOUTS, pb.with_sections(layouts, sections))
        if self.info is not None:
            self.view.show_panel(self.info, set(self.pending))

    def move(self, section: str, index: int, step: int) -> None:
        """One place up (-1) or down (+1); past an end, into the next section."""
        if not self.editable():
            self.view.status(strings.PANEL_LAYOUT_UNREADABLE)
            return
        sections = self.sections()
        names = sections.get(section, [])
        if not 0 <= index < len(names):
            return
        target = index + step
        if 0 <= target < len(names):
            names[index], names[target] = names[target], names[index]
        else:
            order = list(pb.SECTIONS)
            other = order.index(section) + step
            if not 0 <= other < len(order):
                return
            module = names.pop(index)
            if step < 0:
                sections[order[other]].append(module)
            else:
                sections[order[other]].insert(0, module)
        self._write_sections(sections)

    def remove(self, section: str, index: int) -> None:
        if not self.editable():
            self.view.status(strings.PANEL_LAYOUT_UNREADABLE)
            return
        sections = self.sections()
        if 0 <= index < len(sections.get(section, [])):
            sections[section].pop(index)
            self._write_sections(sections)

    def add(self, module: str, section: str) -> None:
        if not self.editable():
            self.view.status(strings.PANEL_LAYOUT_UNREADABLE)
            return
        if section not in pb.SECTIONS or not pb.MODULE.fullmatch(module or ""):
            return
        sections = self.sections()
        if any(module in names for names in sections.values()):
            self.view.status(strings.PANEL_ALREADY.format(name=module_name(module)))
            return
        sections[section].append(module)
        self._write_sections(sections)

    def available(self) -> list[str]:
        """Modules that can be added: HyprPanel's and the user's, not on the panel yet."""
        present = {m for names in self.sections().values() for m in names}
        custom = self.info.custom if self.info else []
        return [m for m in (*pb.BUILTIN, *custom) if m not in present]

    # ---- the panel itself --------------------------------------------------------

    def restart(self) -> None:
        def done(_result, error: BaseException | None) -> None:
            self.view.status(strings.PANEL_RESTART_FAILED.format(error=error)
                             if error is not None else strings.PANEL_RESTARTED)
            self.refresh()

        self.view.status(strings.PANEL_RESTARTING)
        self.backend.workers.submit(pb.WORKER, self.backend.restart, done, key="restart")
