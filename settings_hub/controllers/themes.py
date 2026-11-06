"""The "Themes" page logic. No GTK.

* A card applies its theme to the whole system at once, on the "themes" worker;
  what really changed is read back and logged as ONE History group.
* Per-program themes and "change wallpapers with the theme" work the same way.
* One theme command at a time: a click while one runs is ignored (the page
  shows it is busy), so quick clicks cannot interleave two recolourings.
* The page re-reads everything when shown or after History changed a key.
"""

from __future__ import annotations

from typing import Any, Protocol

from .. import strings
from ..backends import themes as th
from ..backends.wallpaper import Change


class View(Protocol):
    def show(self, themes: list[th.ThemeInfo], state: th.State) -> None: ...

    def show_missing(self, detail: str) -> None: ...

    def show_walls(self, theme_id: str, paths: list[str]) -> None: ...

    def busy(self, on: bool) -> None: ...

    def custom_saved(self) -> None: ...

    def status(self, text: str) -> None: ...


def label_for(key: str) -> str:
    if key == th.SYSTEM_KEY:
        return strings.TH_LABEL_SYSTEM
    if key == th.WALLS_KEY:
        return strings.TH_LABEL_WALLS
    target = key.rsplit(".", 1)[-1]
    return strings.TH_LABEL_TARGET.format(target=strings.TH_TARGETS.get(target, target))


def history_items(change: Change) -> list[tuple[str, str, str, Any, Any]]:
    return [(th.BACKEND, key, label_for(key), before, after)
            for key, (before, after) in change.changed().items()]


class Controller:
    def __init__(self, backend: th.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.running = False
        self.themes: list[th.ThemeInfo] = []
        self.state = th.State()
        backend.on_external.append(lambda _keys: self.refresh())

    def name(self, theme_id: str) -> str:
        for theme in self.themes:
            if theme.id == theme_id:
                return theme.name
        return theme_id

    # ---- reading ----------------------------------------------------------

    def refresh(self) -> None:
        if not self.backend.available():
            self.view.show_missing(self.backend.command)
            return

        def done(result, error) -> None:
            if error is not None or result is None:
                self.view.status(strings.TH_FAILED.format(error=error))
                return
            self.themes, self.state = result
            if not self.running:
                self.view.show(self.themes, self.state)

        self.backend.queue(self.backend.load, done, key="load")

    def load_walls(self, theme_id: str) -> None:
        def done(paths, error) -> None:
            if error is None and paths is not None:
                self.view.show_walls(theme_id, paths)

        self.backend.queue(lambda: self.backend.walls(theme_id), done, key=("walls", theme_id))

    # ---- changing ---------------------------------------------------------

    def _start(self, job, ok_text) -> bool:
        if self.running:
            return False
        self.running = True
        self.view.busy(True)
        self.view.status(strings.TH_APPLYING)

        def done(change: Change | None, error: BaseException | None) -> None:
            self.running = False
            self.view.busy(False)
            if error is not None or change is None:
                self.view.status(strings.TH_FAILED.format(error=error))
            else:
                items = history_items(change)
                if items:
                    self.history.record(items)
                if change.message:  # done, but something could not be recoloured
                    self.view.status(strings.TH_PARTLY.format(error=change.message))
                elif not change.ok:
                    self.view.status(strings.TH_FAILED.format(error=change.message))
                else:
                    self.view.status(ok_text(change))
            self.refresh()

        self.backend.queue(job, done, key="apply")
        return True

    def choose(self, theme_id: str) -> bool:
        if theme_id == self.state.system and not self.running:
            return False
        name = self.name(theme_id)
        return self._start(lambda: self.backend.set_system(theme_id),
                           lambda _c: strings.TH_DONE.format(name=name))

    def random(self) -> bool:
        def text(change: Change) -> str:
            return strings.TH_DONE.format(name=self.name(str(change.after.get(th.SYSTEM_KEY))))

        return self._start(self.backend.random, text)

    def set_target(self, target: str, theme_id: str) -> bool:
        current = self.state.targets.get(target, th.AS_SYSTEM)
        if theme_id == current:
            return False  # the drop-down echoed a value it was given
        label = strings.TH_TARGETS[target]
        name = strings.TH_AS_SYSTEM if theme_id == th.AS_SYSTEM else self.name(theme_id)
        return self._start(lambda: self.backend.set_target(target, theme_id),
                           lambda _c: strings.TH_TARGET_DONE.format(target=label, name=name))

    def set_wallpapers(self, enabled: bool) -> bool:
        if enabled == self.state.wallpapers:
            return False
        text = strings.TH_WALLS_ON if enabled else strings.TH_WALLS_OFF
        return self._start(lambda: self.backend.set_wallpapers(enabled), lambda _c: text)

    def save_custom(self, name: str, accent: str, background: str, text: str) -> None:
        name = name.strip()
        if not name:
            self.view.status(strings.TH_CUSTOM_NO_NAME)
            return

        def done(theme_id, error) -> None:
            if error is not None:
                self.view.status(strings.TH_FAILED.format(error=error))
            else:
                self.view.status(strings.TH_CUSTOM_SAVED.format(name=name))
                self.view.custom_saved()
            self.refresh()

        self.backend.queue(lambda: self.backend.custom_save(name, accent, background, text),
                           done)

    def delete_custom(self, theme_id: str) -> None:
        if self.running:
            return
        name = self.name(theme_id)

        def done(_result, error) -> None:
            self.view.status(strings.TH_FAILED.format(error=error) if error is not None
                             else strings.TH_CUSTOM_DELETED.format(name=name))
            self.refresh()

        self.backend.queue(lambda: self.backend.custom_delete(theme_id), done)

    def toggle_wall(self, theme_id: str, path: str, on: bool) -> None:
        def done(_result, error) -> None:
            if error is not None:
                self.view.status(strings.TH_FAILED.format(error=error))
            self.load_walls(theme_id)
            self.refresh()  # the card's picture count

        self.backend.queue(lambda: self.backend.walls_set(theme_id, path, on), done)
