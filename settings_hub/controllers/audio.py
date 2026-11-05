"""The "Sound" page logic: output and input device, volume, mute. No GTK.

A volume change applies at once (so it can be heard while dragging) and is
logged once, when the slider rests: one series of moves is one History group.
Device and mute changes are logged immediately, one item each.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import audio as aud
from ..backends.audio import BACKEND


class View(Protocol):
    def show_audio(self, audio: aud.Audio) -> None: ...

    def show_volume(self, kind: str, percent: int) -> None: ...

    def status(self, text: str) -> None: ...


def label(key: str) -> str:
    if key == aud.DEFAULT_KEYS["sink"]:
        return strings.AUDIO_DEFAULT_SINK
    if key == aud.DEFAULT_KEYS["source"]:
        return strings.AUDIO_DEFAULT_SOURCE
    if key.startswith("volume."):
        return strings.AUDIO_LABEL_VOLUME.format(kind=kind_name(key))
    return strings.AUDIO_LABEL_MUTE.format(kind=kind_name(key))


def kind_name(key: str) -> str:
    kind = key.split(".", 2)[1] if key.count(".") >= 1 else "sink"
    return strings.AUDIO_KINDS.get(kind, kind)


class Controller:
    def __init__(self, backend: aud.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.audio: aud.Audio | None = None
        self.pending: set[str] = set()
        self._volume_before: dict[str, int] = {}  # kind -> percent before the drag
        self._volume_last: dict[str, int] = {}  # kind -> percent last applied

    # ---- reading ---------------------------------------------------------

    def refresh(self) -> None:
        self.backend.queue_probe(self._read)

    def _read(self, audio: aud.Audio | None, error: BaseException | None) -> None:
        if error is not None or audio is None:
            self.view.status(strings.AUDIO_READ_FAILED.format(error=error))
            return
        self.audio = audio
        self.view.show_audio(audio)
        for kind in aud.KINDS:
            device = next((d for d in audio.devices(kind) if d.name == audio.default(kind)),
                          None)
            if device is not None and aud.key_volume(kind, device.name) not in self.pending:
                self.view.show_volume(kind, device.volume)

    # ---- changing --------------------------------------------------------

    def set_default(self, kind: str, name: str) -> None:
        if not name or self.audio is None or self.audio.default(kind) == name:
            return
        key = aud.DEFAULT_KEYS[kind]
        before = self.audio.default(kind)
        self._submit(key, before, name,
                     lambda: self.backend.set_default(kind, name))

    def set_mute(self, kind: str, name: str, mute: bool) -> None:
        device = self._device(kind, name)
        before = device.mute if device else not mute
        key = aud.key_mute(kind, name)
        self._submit(key, before, mute, lambda: self.backend.set_mute(kind, name, mute))

    def _submit(self, key: str, before: Any, value: Any, action) -> None:
        self.pending.add(key)

        def job() -> tuple[str, Any, Any, bool, str]:
            ok, message = action()
            return key, before, value, ok, message

        self.backend.workers.submit(aud.WORKER, job, self._done, key=key)

    def _done(self, result, error: BaseException | None) -> None:
        if error is not None or result is None:
            self.pending.clear()
            self.view.status(strings.AUDIO_APPLY_FAILED.format(error=error))
            return
        key, before, value, ok, message = result
        self.pending.discard(key)
        if not ok:
            self.view.status(strings.AUDIO_APPLY_FAILED.format(error=message))
        else:
            self.history.record([(BACKEND, key, label(key), before, value)])
            self.view.status(strings.AUDIO_APPLIED.format(name=label(key)))
        self.refresh()

    # ---- volume ----------------------------------------------------------

    def volume_moved(self, kind: str, percent: int) -> None:
        """Apply at once; the History entry comes from commit_volume()."""
        if self.audio is None:
            return
        name = self.audio.default(kind)
        if not name:
            return
        percent = max(0, min(150, int(percent)))
        if kind not in self._volume_before:
            device = self._device(kind, name)
            self._volume_before[kind] = device.volume if device else percent
        self._volume_last[kind] = percent

        def job():
            return self.backend.set_volume(kind, name, percent)

        self.pending.add(aud.key_volume(kind, name))
        self.backend.workers.submit(aud.WORKER, job, self._volume_applied,
                                    key=aud.key_volume(kind, name))

    def _volume_applied(self, result, error: BaseException | None) -> None:
        if error is not None:
            self.view.status(strings.AUDIO_APPLY_FAILED.format(error=error))

    def commit_volume(self, kind: str) -> None:
        """The slider rested: log the series as one History item."""
        before = self._volume_before.pop(kind, None)
        after = self._volume_last.pop(kind, None)
        if before is None or after is None or before == after or self.audio is None:
            return
        name = self.audio.default(kind)
        if not name:
            return
        key = aud.key_volume(kind, name)
        self.history.record([(BACKEND, key, label(key), before, after)])
        self.pending.discard(key)
        self.view.status(strings.AUDIO_APPLIED.format(
            name=strings.AUDIO_VOLUME_DONE.format(percent=after)))

    def _device(self, kind: str, name: str) -> aud.Device | None:
        if self.audio is None:
            return None
        return next((d for d in self.audio.devices(kind) if d.name == name), None)
