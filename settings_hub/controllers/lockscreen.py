"""The "Lock screen" page logic. No GTK.

Choices are a draft: each one is saved to lockscreen.json and redrawn in the
preview, nothing else. "Apply" writes hyprlock.conf as one History item (the
whole file before and after), so Ctrl+Z gives back the previous lock screen.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Protocol

from .. import strings
from ..backends import lockscreen as lk


class View(Protocol):
    def show_lock(self, info: lk.Info, options: lk.Options) -> None: ...

    def show_preview(self, path: Path | None, error: str) -> None: ...

    def status(self, text: str) -> None: ...


class Controller:
    def __init__(self, backend: lk.Backend, history, view: View, preview_dir: Path) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.preview_dir = preview_dir
        self.info: lk.Info | None = None
        self.options = lk.Options()
        self._shots = itertools.count()
        self._rev = 0  # one more for every change of the draft
        self._probed = (lk.Options(), False)  # options and "applied" as last read
        self._drawn: lk.Options | None = None  # what the picture on the page shows

    def refresh(self) -> None:
        rev = self._rev
        self.backend.workers.submit(lk.WORKER, self.backend.probe,
                                    lambda info, error: self._read(info, error, rev),
                                    key="probe")

    def _read(self, info: lk.Info | None, error: BaseException | None, rev: int = 0) -> None:
        if error is not None or info is None:
            self.view.status(strings.LOCK_READ_FAILED.format(error=error))
            return
        self._probed = (info.options, info.applied)
        if rev != self._rev:
            # Read before a change made since: the file facts are new, the choices
            # are not — keep the draft the person is editing.
            info = replace(info, options=self.options, applied=self._applied(self.options))
        self.info = info
        self.options = info.options
        self.view.show_lock(info, self.options)
        if self.options != self._drawn:
            self.redraw()

    def _applied(self, opts: lk.Options) -> bool:
        probed, applied = self._probed
        return applied and opts == probed

    # ---- the draft ---------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        if self.info is None:
            return  # not read yet: a choice now would be laid over the defaults
        wanted = lk.clean({**asdict(self.options), key: value})
        if getattr(wanted, key) != value:
            self.view.status(strings.LOCK_BAD_VALUE)
            self.view.show_lock(self.info, self.options)  # the control goes back
            return
        if wanted == self.options:
            return
        self._rev += 1
        self.options = wanted
        self.info = replace(self.info, options=wanted, applied=self._applied(wanted))
        self.view.show_lock(self.info, wanted)
        self.backend.workers.submit(lk.WORKER, lambda: self.backend.save_options(wanted),
                                    self._saved, key="save")
        self.redraw()

    def _saved(self, _result, error: BaseException | None) -> None:
        if error is not None:
            self.view.status(strings.LOCK_SAVE_FAILED.format(error=error))

    def redraw(self) -> None:
        """A new picture of the draft; a newer request replaces one still waiting."""
        if self.info is not None and not self.info.simulator:
            self.view.show_preview(None, strings.LOCK_NO_SIMULATOR)
            return
        opts = self.options
        out = self.preview_dir / f"preview-{next(self._shots) % 2}.png"  # not the one shown

        def done(path, error: BaseException | None) -> None:
            if opts != self.options:
                return  # an older picture; the newer one is on its way
            if error is None:
                self._drawn = opts
            self.view.show_preview(path if error is None else None,
                                   "" if error is None else
                                   strings.LOCK_PREVIEW_FAILED.format(error=error))

        self.backend.workers.submit(lk.PREVIEW_WORKER,
                                    lambda: self.backend.preview(opts, out), done,
                                    key="preview")

    # ---- the file ------------------------------------------------------------------

    def apply(self) -> None:
        opts = self.options
        self.backend.workers.submit(lk.WORKER, lambda: self.backend.apply(opts),
                                    self._written, key="apply")

    def restore(self) -> None:
        self.backend.workers.submit(lk.WORKER, self.backend.restore_backup,
                                    lambda r, e: self._written(r, e, restored=True),
                                    key="apply")

    def _written(self, result, error: BaseException | None, restored: bool = False) -> None:
        if error is not None:
            self.view.status(strings.LOCK_APPLY_FAILED.format(error=error))
            self.refresh()
            return
        before, after = result
        if before != after:
            self.history.record([(lk.BACKEND, lk.KEY, strings.LOCK_HISTORY, before, after)])
            self.view.status(strings.LOCK_RESTORED if restored else strings.LOCK_APPLIED)
        else:
            self.view.status(strings.LOCK_ALREADY)
        self.refresh()
