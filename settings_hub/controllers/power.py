"""The "Power and brightness" page logic. No GTK.

Brightness applies while dragging and is logged once when the slider rests; the
power profile is logged at once. Values come from the sysfs probe on every show.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import power as pw
from ..backends.power import BACKEND


class View(Protocol):
    def show_power(self, info: pw.Power) -> None: ...

    def show_brightness(self, percent: int) -> None: ...

    def status(self, text: str) -> None: ...


def label(key: str) -> str:
    return strings.POWER_LABELS.get(key, key)


class Controller:
    def __init__(self, backend: pw.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.info: pw.Power | None = None
        self.pending: set[str] = set()
        self._brightness_before: int | None = None
        self._brightness_last: int | None = None

    # ---- reading ---------------------------------------------------------

    def refresh(self) -> None:
        self.backend.queue_probe(self._read)

    def _read(self, info: pw.Power | None, error: BaseException | None) -> None:
        if error is not None or info is None:
            self.view.status(strings.POWER_READ_FAILED.format(error=error))
            return
        self.info = info
        self.view.show_power(info)
        if info.brightness is not None and pw.BRIGHTNESS_KEY not in self.pending:
            self.view.show_brightness(info.brightness)

    # ---- changes ---------------------------------------------------------

    def set_profile(self, profile: str) -> None:
        before = self.info.profile if self.info else ""
        if before == profile:
            return
        self.pending.add(pw.PROFILE_KEY)

        def job() -> tuple[str, Any, Any, bool, str]:
            ok, message = self.backend.set_profile(profile)
            return pw.PROFILE_KEY, before, profile, ok, message

        self.backend.workers.submit(pw.WORKER, job, self._done, key=pw.PROFILE_KEY)

    def brightness_moved(self, percent: int) -> None:
        percent = max(1, min(100, int(percent)))
        if self._brightness_before is None:
            self._brightness_before = self.info.brightness if self.info else percent
        self._brightness_last = percent

        def job():
            return self.backend.set_brightness(percent)

        self.pending.add(pw.BRIGHTNESS_KEY)
        self.backend.workers.submit(pw.WORKER, job, self._brightness_applied,
                                    key=pw.BRIGHTNESS_KEY)

    def _brightness_applied(self, result, error: BaseException | None) -> None:
        if error is not None:
            self.view.status(strings.POWER_APPLY_FAILED.format(error=error))
        elif result is not None and not result[0]:
            self.view.status(strings.POWER_APPLY_FAILED.format(error=result[1]))

    def commit_brightness(self) -> None:
        """The slider rested: log what is really in use, after the queued moves."""
        before = self._brightness_before
        last = self._brightness_last
        self._brightness_before = self._brightness_last = None
        if before is None or last is None:
            self.pending.discard(pw.BRIGHTNESS_KEY)
            return
        if self.info is not None:
            self.info.brightness = last  # a drag starting right now starts from here

        def job() -> tuple[int, Any]:
            return before, self.backend.read([pw.BRIGHTNESS_KEY]).get(pw.BRIGHTNESS_KEY)

        self.backend.workers.submit(pw.WORKER, job, self._brightness_committed, key="commit")

    def _brightness_committed(self, result, error: BaseException | None) -> None:
        if self._brightness_before is None:  # no new series has started meanwhile
            self.pending.discard(pw.BRIGHTNESS_KEY)
        if error is not None or result is None:
            self.view.status(strings.POWER_APPLY_FAILED.format(error=error))
            return
        before, actual = result
        if actual is None:
            if self.info is not None and self._brightness_before is None:
                self.info.brightness = before  # not known: the last known
            return
        if self.info is not None:
            self.info.brightness = actual  # the next series starts from this
        if self._brightness_before is None:
            self.view.show_brightness(actual)
        if actual != before:
            self.history.record([(BACKEND, pw.BRIGHTNESS_KEY, label(pw.BRIGHTNESS_KEY),
                                  before, actual)])
            self.view.status(strings.POWER_APPLIED.format(name=label(pw.BRIGHTNESS_KEY)))

    def _done(self, result, error: BaseException | None) -> None:
        if error is not None or result is None:
            self.pending.clear()
            self.view.status(strings.POWER_APPLY_FAILED.format(error=error))
            return
        key, before, value, ok, message = result
        self.pending.discard(key)
        if not ok:
            self.view.status(strings.POWER_APPLY_FAILED.format(error=message))
        else:
            self.history.record([(BACKEND, key, label(key), before, value)])
            self.view.status(strings.POWER_APPLIED.format(name=label(key)))
        self.refresh()
