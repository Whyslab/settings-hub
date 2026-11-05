"""Page logic for the desktop variables. No GTK.

The page builds a control per variable and forwards edits here. A change is
one user action: read the live value, change it in the session (the backend
also remembers it and rewrites the Lua file), read it back, log it in History as
one group, and show the value Hyprland really uses.

Re-reading the whole page happens on a worker: it is one `hyprctl getoption`
per variable and must never run on the GTK thread. A key with a queued change
is never overwritten by a read.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .. import strings
from ..variables import Var
from ..variables import backend as hypr
from ..variables import get as get_var

log = logging.getLogger(__name__)


class View(Protocol):
    def show_values(self, values: dict[str, Any]) -> None: ...

    def status(self, text: str) -> None: ...


def label(option: str) -> str:
    text = strings.VARS.get(option)
    return text[0] if text else option


class Controller:
    def __init__(self, backend: hypr.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.values: dict[str, Any] = {}
        self.pending: set[str] = set()
        self.busy: set[str] = set()  # queued or running reads

    # ---- reading ---------------------------------------------------------

    def refresh(self) -> None:
        if self.busy:
            return
        self.busy.add("read")
        self.backend.queue_read_all(self._read_done)

    def _read_done(self, values: dict[str, Any] | None,
                   error: BaseException | None) -> None:
        self.busy.discard("read")
        if error is not None:
            self.view.status(strings.VAR_READ_FAILED.format(error=error))
            return
        fresh = {k: v for k, v in (values or {}).items() if k not in self.pending}
        self.values.update(fresh)
        self.view.show_values(fresh)

    # ---- changing --------------------------------------------------------

    def edit(self, option: str, value: Any) -> None:
        var = get_var(option)
        if var is None:
            raise KeyError(option)
        if var.kind == "str" and option not in self.values:
            self.view.status(strings.VAR_NOT_READ)  # the field has not shown the live value
            return
        if option == "input:kb_layout" and not str(value).strip():
            self.view.status(strings.VAR_EMPTY_LAYOUT)  # no way to type otherwise
            self.view.show_values({option: self.values[option]})
            return
        # Nothing to do when the value is the one in use. A queued change is the
        # exception: going back to the old value has to overtake it.
        if option not in self.pending and option in self.values \
                and self.values[option] == value:
            return
        self.pending.add(option)

        def job() -> tuple[str, Any, Any, hypr.ApplyResult]:
            try:
                before = self.backend.read_one(option)
            except (RuntimeError, ValueError) as exc:
                log.warning("reading %s before a change: %s", option, exc)
                before = self.values.get(option)
            return option, value, before, self.backend.apply_now({option: value})

        self.backend.workers.submit(hypr.WORKER, job, self._applied, key=option)

    def _applied(self, result, error: BaseException | None) -> None:
        if error is not None:
            self._finish()
            self.view.status(strings.VAR_APPLY_FAILED.format(error=error))
            return
        if result is None:
            self._finish()
            return
        option, asked, before, applied = result
        self.pending.discard(option)
        if not applied.ok:
            self.view.status(strings.VAR_APPLY_FAILED.format(error=applied.message))
            if option in self.values:  # the field must not show what is not in use
                self.view.show_values({option: self.values[option]})
            return
        after = applied.values.get(option, self.values.get(option))
        self.values[option] = after
        if not hypr.same(before, after):
            self.history.record([(hypr.BACKEND, option, label(option), before, after)])
        self.view.show_values({option: after})
        if hypr.same(after, asked):
            self.view.status(strings.VAR_APPLIED.format(name=label(option)))
        else:
            self.view.status(strings.VAR_NOT_TAKEN.format(name=label(option), value=after))

    def _finish(self) -> None:
        self.pending.clear()

    # ---- reset -----------------------------------------------------------

    def reset(self, options: list[str]) -> None:
        """Forget the window's values; the config files decide again after a reload."""
        options = list(options)
        if not options:
            return
        for option in options:
            self.pending.add(option)

        def job() -> tuple[list[str], dict[str, Any], dict[str, Any], bool, str]:
            before = self.backend.read(options)
            if not self.backend.remembers(options):
                return options, before, before, True, ""  # nothing to forget
            with self.backend.lock:  # an undo or a mode must not slip in between
                saved = self.backend.snapshot()
                cleared = self.backend.clear(options)
                ok, message = self.backend.reload()
                if not ok:  # the session keeps the values, so the files must too
                    self.backend.restore(saved)
                else:
                    ok, message = self.backend.set_cursor(cleared.values)
            after = self.backend.read(options)  # outside: an undo waits less
            return options, before, after, ok, message

        self.backend.workers.submit(hypr.WORKER, job, self._reset_done, key="reset")

    def _reset_done(self, result, error: BaseException | None) -> None:
        if error is not None:
            self.pending.clear()
            self.view.status(strings.VAR_APPLY_FAILED.format(error=error))
            return
        options, before, after, ok, message = result
        self.pending.difference_update(options)
        if not ok:
            self.view.status(strings.VAR_APPLY_FAILED.format(error=message))
        self.values.update({o: v for o, v in after.items() if v is not None})
        self.view.show_values(after)
        items = [(hypr.BACKEND, option, label(option), before[option], after[option])
                 for option in options
                 if option in before and option in after and before[option] != after[option]]
        if items:
            self.history.record(items)
        if ok:
            self.view.status(strings.VAR_RESET_DONE)


def options_of(vars_: list[Var]) -> list[str]:
    return [v.option for v in vars_]
