"""The "Wallpaper" page logic. No GTK.

* A picture applies at once to the chosen target (desktop, lock, login screen
  or all three) through wallpaper.sh, on the "wallpaper" worker. What the
  command changed -- the picture, and random mode it switches off -- is read
  back and logged as ONE History group.
* "Random wallpapers" per target works the same way. (The theme mode moved to
  the Themes page; its History entries still undo through backends.wallpaper.)
* The page re-reads the state files when shown; a re-read never overwrites a
  control whose change is still queued.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from .. import strings
from ..backends import wallpaper as wp
from ..backends.wallpaper import ALL, BACKEND, TARGETS, Change


class View(Protocol):
    def show_setup(self, state: str, detail: str) -> None: ...

    def show_images(self, images: list[wp.Image]) -> None: ...

    def show_current(self, target: str, current: dict[str, str],
                     random: dict[str, bool]) -> None: ...

    def show_random(self, target: str, enabled: bool) -> None: ...

    def thumb_ready(self, image: wp.Image, made: bool) -> None: ...

    def status(self, text: str) -> None: ...


def label_for(key: str) -> str:
    kind, _, target = key.partition(".")
    if kind == "wallpaper":
        return strings.WP_LABEL_SET.format(target=strings.WP_TARGET_NAMES[target])
    if kind == "random":
        return strings.WP_LABEL_RANDOM.format(target=strings.WP_TARGET_NAMES[target])
    return strings.WP_LABEL_THEME


def history_items(change: Change, backend: str) -> list[tuple[str, str, str, Any, Any]]:
    return [(backend, key, label_for(key), before, after)
            for key, (before, after) in change.changed().items()]


def marked(target: str, image: wp.Image, current: dict[str, str]) -> bool:
    """Is this picture what the target shows (for "all": what all three show)?"""
    targets = TARGETS if target == ALL else (target,)
    return all(current.get(t) and os.path.realpath(current[t]) == image.real for t in targets)


class Controller:
    def __init__(self, backend: wp.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.target = "desktop"
        self.pending: set[str] = set()  # keys with a queued command
        self.images: list[wp.Image] = []
        self._image_sig: tuple = ()
        backend.on_external.append(lambda _keys: self.refresh())

    # ---- reading ----------------------------------------------------------

    def refresh(self) -> None:
        state, detail = self.backend.state()
        self.view.show_setup(state, detail)
        images = self.backend.images()
        sig = tuple((i.path, i.mtime) for i in images)
        if sig != self._image_sig:  # rebuild the grid only when the library changed
            self._image_sig = sig
            self.images = images
            self.view.show_images(images)
            missing = self.backend.queue_thumbs(images, self.view.thumb_ready)
            if missing:
                self.view.status(strings.WP_THUMBS.format(n=missing))
        self._show_state()

    def _show_state(self) -> None:
        current, random = self.backend.current(), self.backend.random()
        self.view.show_current(self.target, current, random)
        for t in TARGETS:
            if wp.random_key(t) not in self.pending:
                self.view.show_random(t, random[t])

    def set_target(self, target: str) -> None:
        if target not in (*TARGETS, ALL):
            raise ValueError(target)
        self.target = target
        self._show_state()

    # ---- changing ---------------------------------------------------------

    def _finish(self, keys: set[str], backend: str, ok_text: str):
        def done(change: Change | None, error: BaseException | None) -> None:
            self.pending -= keys
            if error is not None:
                self.view.status(strings.WP_FAILED.format(error=error))
            else:
                items = history_items(change, backend)
                if items:
                    self.history.record(items)
                self.view.status(ok_text if change.ok
                                 else strings.WP_FAILED.format(error=change.message))
            self._show_state()

        return done

    def choose(self, image: wp.Image) -> None:
        target = self.target
        targets = TARGETS if target == ALL else (target,)
        keys = {wp.path_key(t) for t in targets} | {wp.random_key(t) for t in targets}
        self.pending |= keys
        self.view.status(strings.WP_APPLYING)
        text = strings.WP_SET_DONE.format(target=strings.WP_TARGETS[target], name=image.name)
        self.backend.queue_set(target, image.path, self._finish(keys, BACKEND, text))

    def random_toggled(self, target: str, enabled: bool) -> None:
        if wp.random_key(target) not in self.pending and \
                self.backend.random()[target] == enabled:
            return  # the switch echoed a value it was given
        keys = {wp.random_key(target), wp.path_key(target)}
        self.pending |= keys
        name = strings.WP_RANDOM_TARGETS[target]
        text = (strings.WP_RANDOM_ON if enabled else strings.WP_RANDOM_OFF).format(target=name)
        self.backend.queue_random(target, enabled, self._finish(keys, BACKEND, text))
