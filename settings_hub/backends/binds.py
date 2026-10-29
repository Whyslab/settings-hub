"""Binds: Hyprland's config (read-only) and settings-hub's own block. No GTK.

Paths (each can be overridden by an environment variable, for tests):

    main  ~/.config/hypr/hyprland.conf      SETTINGS_HUB_HYPR_CONF
    own   ~/.config/hypr/settings-hub.conf  SETTINGS_HUB_BINDS_CONF
    lua   ~/.config/hypr/hyprland.lua       SETTINGS_HUB_HYPR_LUA

load() parses the config (binds/parser.py) and asks Hyprland for its live list
(`hyprctl binds -j`) to mark binds whose file and live versions differ. Every
change runs on the "binds" worker as "fresh read -> plan -> commit"
(binds/writer.py): the entry is looked up again by its id in a fresh parse, so
nothing decided from an old reading is written.

History backend "binds": key = "MODS, KEY", value = the block lines of that
combination (a list, possibly empty). A rebind is one group of two items.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..binds import conflicts, parser, writer
from ..binds.conflicts import Entry
from ..binds.parser import Config, combo_text
from ..workers import Dispatch, Workers, glib_dispatch

log = logging.getLogger(__name__)

BACKEND = "binds"
WORKER = "binds"
READ_WORKER = "binds-read"
TIMEOUT_S = 10


@dataclass(frozen=True)
class Paths:
    main: Path
    own: Path
    lua: Path

    @classmethod
    def default(cls) -> Paths:
        config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        hypr = Path(config) / "hypr"
        env = os.environ.get
        return cls(Path(env("SETTINGS_HUB_HYPR_CONF") or hypr / "hyprland.conf"),
                   Path(env("SETTINGS_HUB_BINDS_CONF") or hypr / "settings-hub.conf"),
                   Path(env("SETTINGS_HUB_HYPR_LUA") or hypr / "hyprland.lua"))


def run_hyprctl(args: list[str]) -> tuple[int, str]:
    """hyprctl from PATH (tests put a stub first; no absolute path is ever used)."""
    try:
        done = subprocess.run(["hyprctl", *args], capture_output=True, text=True,
                              timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("hyprctl %s: %s", " ".join(args[:2]), exc)
        return 127, ""
    return done.returncode, done.stdout


@dataclass
class State:
    cfg: Config | None = None
    entries: list[Entry] = field(default_factory=list)
    disabled: list[Entry] = field(default_factory=list)  # unbound by our block
    live: list[dict] | None = None  # None: Hyprland did not answer
    found: dict[tuple[str, int], bool] = field(default_factory=dict)  # (file, line) -> live?
    extra: list[dict] = field(default_factory=list)  # live binds not in the files
    lua: Path | None = None
    error: str = ""


def disabled_entries(cfg: Config) -> list[Entry]:
    """Binds our block unbinds and does not carry to another combination."""
    carried = {b.origin for b in cfg.binds if b.managed and b.origin}
    gone: list[parser.Bind] = []
    for u in cfg.unbinds:
        if not u.managed:
            continue
        for b in u.removed:
            if not b.managed and cfg.where(b) not in carried and b not in gone:
                gone.append(b)
    return conflicts.entries(gone)


def revert_keys(cfg: Config, text: str, entry: Entry) -> list[str]:
    """The combination itself, plus the one a moved bind came from if only unbound there."""
    keys = [entry.key]
    for b in entry.binds:
        origin = cfg.def_at(b.origin) if b.managed and b.origin else None
        if origin is None or origin.combo == entry.combo:
            continue
        key = combo_text(origin.modmask, origin.key)
        lines = writer.block_lines(text, key)
        if key not in keys and lines and all(x.lstrip().startswith("unbind") for x in lines):
            keys.append(key)
    return keys


Op = Callable[[writer.Planner, Config, str], tuple[dict, dict]]


class Backend:
    def __init__(self, workers: Workers, paths: Paths | None = None,
                 hyprctl: writer.Runner | None = None, dispatch: Dispatch | None = None) -> None:
        self.workers = workers
        self.paths = paths or Paths.default()
        self.hyprctl = hyprctl or run_hyprctl
        self._dispatch = dispatch or glib_dispatch
        self.on_external: list[Callable[[set[str]], None]] = []

    # ---- reading ----------------------------------------------------------

    def lua(self) -> Path | None:
        return self.paths.lua if self.paths.lua.exists() else None

    def parse(self) -> Config:
        return parser.parse(self.paths.main, self.paths.own)

    def live(self) -> list[dict] | None:
        rc, out = self.hyprctl(["binds", "-j"])
        if rc != 0:
            return None
        try:
            data = json.loads(out)
        except ValueError:
            return None
        return data if isinstance(data, list) else None

    def load(self) -> State:
        state = State(lua=self.lua())
        try:
            cfg = self.parse()
        except OSError as exc:
            state.error = str(exc)
            return state
        state.cfg = cfg
        state.entries = conflicts.entries(cfg.binds)
        state.disabled = disabled_entries(cfg)
        state.live = self.live()
        if state.live is not None:
            found, state.extra = parser.reconcile(cfg.binds, state.live)
            state.found = {(str(b.file), b.line): ok for b, ok in zip(cfg.binds, found,
                                                                       strict=True)}
        return state

    def queue_load(self, on_done) -> None:
        self.workers.submit(READ_WORKER, self.load, on_done, key="load")

    def own_text(self) -> str:
        return writer.read_own(self.paths.own)[0]

    def read(self, keys) -> dict[str, list[str]]:
        try:
            text = self.own_text()
            return {k: writer.block_lines(text, k) for k in keys}
        except writer.NoBlock:
            return {k: [] for k in keys}

    # ---- changing ---------------------------------------------------------

    def change(self, op: Op) -> writer.Commit:
        """Fresh read -> plan -> commit. On the worker."""
        if self.lua() is not None:
            raise writer.LuaActive(self.paths.lua)
        text = self.own_text()
        writer.split(text)  # raises NoBlock before anything else happens
        planner = writer.Planner(self.paths.main, self.paths.own, text)
        cfg = planner.parse()
        changes, expected = op(planner, cfg, text)
        return writer.commit(self.paths.own, changes, self.hyprctl, self.paths.lua, planner,
                             expected)

    def queue_change(self, op: Op, on_done) -> None:
        self.workers.submit(WORKER, lambda: self.change(op), on_done, key=object())

    @staticmethod
    def find(cfg: Config, entry_id: str) -> Entry:
        for e in conflicts.entries(cfg.binds) + disabled_entries(cfg):
            if e.id == entry_id:
                return e
        raise writer.WriterError(entry_id)

    def op_rebind(self, entry_id: str, mask: int, key: str) -> Op:
        def op(planner, cfg, _text):
            return planner.rebind(self.find(cfg, entry_id), mask, key, cfg)
        return op

    def op_disable(self, entry_id: str, actions: list[tuple] | None = None) -> Op:
        """actions: which of the entry's actions to drop (None: all of them)."""
        def op(planner, cfg, _text):
            entry = self.find(cfg, entry_id)
            drop = [b for b in entry.binds if actions is None or b.action() in actions]
            return planner.disable(entry, drop, cfg)
        return op

    def op_add(self, mask: int, key: str, command: str) -> Op:
        def op(planner, _cfg, _text):
            return planner.add(mask, key, command)
        return op

    def op_revert(self, entry_id: str) -> Op:
        def op(planner, cfg, text):
            return planner.revert(revert_keys(cfg, text, self.find(cfg, entry_id)))
        return op

    # ---- History ------------------------------------------------------------

    def notify_external(self, keys: set[str]) -> None:
        def call() -> None:
            for fn in list(self.on_external):
                fn(set(keys))

        self._dispatch(call)

    def apply_lines(self, values: dict[str, list[str]]) -> writer.Commit:
        if self.lua() is not None:
            raise writer.LuaActive(self.paths.lua)
        return writer.commit(self.paths.own, {k: list(v) for k, v in values.items()},
                             self.hyprctl, self.paths.lua)

    def reset_submap(self) -> None:
        """At startup, on the worker: leave the capture submap if we were left in it."""
        from ..binds import capture

        self.workers.submit(WORKER, lambda: capture.reset_if_stuck(self.hyprctl), None,
                            key="reset-submap")


class BindsApplier:
    """History backend "binds": block lines per key combination."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.backend.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        if self.backend.lua() is not None:
            raise writer.LuaActive(self.backend.paths.lua)

        def done(_commit, error) -> None:
            if error is not None:
                log.warning("history binds: %s", error)
            self.backend.notify_external(set(values))

        self.backend.workers.submit(WORKER, lambda: self.backend.apply_lines(values), done,
                                    key=object())


def register(history, backend: Backend) -> None:
    history.register(BACKEND, BindsApplier(backend))
