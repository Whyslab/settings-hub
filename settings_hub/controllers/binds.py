"""The "Binds" page logic. No GTK.

The page is a list of key combinations grouped by kind, each with its name,
its human key label and what it runs. Per row: rebind (capture a new
combination), disable (one action of several, or all), revert ("as it was":
our block lines for the combination - and for the one it was moved from - are
removed). At the bottom: add a bind running a command.

Taking a combination that already does something else asks first ("Replace /
Cancel") with the occupant's name; several actions on one combination are one
row, never a conflict. Every change is one History group; a rebind's group
holds two items (the old and the new combination).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .. import search, strings
from ..backends import binds as bb
from ..binds import conflicts, names, parser, writer
from ..binds.conflicts import Entry
from ..binds.parser import Bind, Combo

GROUP_ORDER = ("apps", "windows", "workspaces", "device", "mouse", "other", "submap",
               "disabled", "live", "lua")


@dataclass
class RowModel:
    id: str
    key: str  # History key, "MODS, KEY"
    name: str
    human: bool  # the name is not just the command
    combo: str  # "Super + Shift + N"
    detail: str
    group: str  # strings.BN_GROUPS id
    group_title: str
    actions: list[tuple[tuple, str]] = field(default_factory=list)  # (action, its name)
    managed: bool = False  # our block has lines for it: "as it was" is possible
    disabled: bool = False
    live_ok: bool | None = None  # None: Hyprland's live list is unknown
    movable: bool = False
    editable: bool = False

    def matches(self, query: str) -> bool:
        if not query.strip():
            return True
        hay = search.normalize(" ".join((self.name, self.combo, self.detail, self.key)))
        q = search.normalize(query)
        return (q in hay or search.normalize(search.to_russian_layout(query)) in hay
                or search.normalize(search.to_english_layout(query)) in hay)


class View(Protocol):
    def show_setup(self, lua: Path | None, not_sourced: bool, error: str,
                   live_known: bool) -> None: ...

    def show_rows(self, rows: list[RowModel], editable: bool) -> None: ...

    def status(self, text: str) -> None: ...

    def ask_conflict(self, combo: str, occupant: str, on_replace: Callable[[], None]) -> None: ...


def _live_bind(item: dict) -> Bind:
    code = int(item.get("keycode", 0) or 0)
    key = f"code:{code}" if code else str(item.get("key", ""))
    mask = int(item.get("modmask", 0))
    dispatcher, arg = str(item.get("dispatcher", "")), str(item.get("arg", ""))
    # Under a Lua config Hyprland reports "HL.Dispatcher(exec_cmd)" or
    # "function: 0x…", and arg is only an internal number: keep the kind.
    if dispatcher.startswith("HL.Dispatcher(") and dispatcher.endswith(")"):
        dispatcher, arg = dispatcher[len("HL.Dispatcher("):-1], ""
    elif dispatcher.startswith("function:"):
        dispatcher, arg = strings.BN_LUA_FUNCTION, ""
    return Bind("bind", parser.mods_text(mask), mask, key, dispatcher, arg,
                str(item.get("description", "")), "", "", "",
                Path("-"), 0, str(item.get("submap", "")))


class Controller:
    def __init__(self, backend: bb.Backend, history, view: View) -> None:
        self.backend = backend
        self.history = history
        self.view = view
        self.state: bb.State | None = None
        self.entries: dict[str, Entry] = {}
        self.models: dict[str, RowModel] = {}
        self.busy = 0
        backend.on_external.append(lambda _keys: self.refresh())

    # ---- reading ----------------------------------------------------------

    def refresh(self) -> None:
        self.backend.queue_load(self._loaded)

    def _loaded(self, state: bb.State | None, error: BaseException | None) -> None:
        if error is not None or state is None:
            state = bb.State(error=str(error))
        self.state = state
        cfg = state.cfg
        self.view.show_setup(state.lua, bool(cfg and not cfg.own_sourced), state.error,
                             state.live is not None)
        rows = self.build(state)
        self.view.show_rows(rows, state.lua is None and cfg is not None)

    def build(self, state: bb.State) -> list[RowModel]:
        self.entries, self.models = {}, {}
        cfg = state.cfg
        if cfg is None:
            return self._lua_rows(state) if state.lua is not None else []
        try:
            text = self.backend.own_text()
        except OSError:
            text = ""

        def ours(key: str) -> bool:
            try:
                return bool(writer.block_lines(text, key))
            except writer.NoBlock:
                return False

        active_ids = {e.id for e in state.entries}
        partly: dict[str, list[Bind]] = {}
        disabled = []
        for e in state.disabled:
            if e.id in active_ids:
                partly[e.id] = e.binds
            else:
                disabled.append(e)
        rows: list[RowModel] = []
        lua_free = state.lua is None
        for e in state.entries:
            rows.append(self._row(e, cfg, state, ours(e.key) and not e.submap, lua_free,
                                  partly.get(e.id, [])))
        for e in disabled:
            name = names.entry_name(e.binds, cfg)
            first = e.binds[0]
            rows.append(RowModel(
                e.id, e.key, name.text, name.human, names.combo_label(first.modmask, first.key),
                " · ".join([names.command_text(b) for b in e.binds] + [strings.BN_DISABLED_NOTE]),
                "disabled", strings.BN_GROUPS["disabled"], managed=ours(e.key),
                disabled=True, editable=lua_free))
            self.entries[e.id] = e
        for i, item in enumerate(state.extra):
            b = _live_bind(item)
            name = names.bind_name(b)
            rows.append(RowModel(f"live|{i}", parser.combo_text(b.modmask, b.key), name.text,
                                 name.human, names.combo_label(b.modmask, b.key),
                                 names.command_text(b), "live", strings.BN_GROUPS["live"],
                                 live_ok=True))
        order = {g: i for i, g in enumerate(GROUP_ORDER)}
        rows.sort(key=lambda r: order.get(r.group, len(order)))  # stable: config order inside
        for r in rows:
            self.models[r.id] = r
        return rows

    def _lua_rows(self, state: bb.State) -> list[RowModel]:
        """Hyprland's own list under a Lua config: nothing here can be edited."""
        rows = []
        for i, item in enumerate(state.extra):
            paired = state.lua_binds[i] if i < len(state.lua_binds) else None
            b = paired or _live_bind(item)
            name = names.bind_name(b)
            group = "submap" if b.submap else "lua"
            title = strings.BN_GROUPS[group].format(name=b.submap)
            rows.append(RowModel(f"lua|{i}", parser.combo_text(b.modmask, b.key), name.text,
                                 name.human, names.combo_label(b.modmask, b.key),
                                 names.command_text(b), group, title, live_ok=True))
        for r in rows:
            self.models[r.id] = r
        return rows

    def _row(self, e: Entry, cfg: parser.Config, state: bb.State, managed: bool,
             lua_free: bool, gone: list[Bind]) -> RowModel:
        self.entries[e.id] = e
        first = e.binds[0]
        name = names.entry_name(e.binds, cfg)
        if len(e.binds) == 1:
            details = [names.command_text(first)]
        else:
            details = [names.bind_name(b, cfg).text for b in e.binds]
        for b in e.binds:
            origin = cfg.def_at(b.origin) if b.managed and b.origin else None
            if origin is not None and origin.combo != e.combo:
                details.append(strings.BN_MOVED_FROM.format(
                    combo=names.combo_label(origin.modmask, origin.key)))
                break
        for b in gone:
            details.append(f"{strings.BN_DISABLED_NOTE}: {names.bind_name(b, cfg).text}")
        group = names.group_of(first)
        title = strings.BN_GROUPS[group].format(name=first.submap)
        live_ok = None
        if state.live is not None:
            live_ok = all(state.found.get((str(b.file), b.line), False) for b in e.binds)
        editable = lua_free and not e.submap
        return RowModel(
            e.id, e.key, name.text, name.human, names.combo_label(first.modmask, first.key),
            " · ".join(details), group, title,
            actions=[(b.action(), names.bind_name(b, cfg).text) for b in e.binds],
            managed=managed, live_ok=live_ok, editable=editable,
            movable=editable and all(b.dispatcher != "mouse" for b in e.binds))

    # ---- changing ---------------------------------------------------------

    def _submit(self, op, label: str, message: str) -> None:
        self.busy += 1
        self.view.status(strings.BN_APPLYING)

        def done(commit: writer.Commit | None, error: BaseException | None) -> None:
            self.busy -= 1
            if error is not None:
                self.view.status(self.describe(error))
            elif not commit.changed:
                self.view.status(strings.BN_NOTHING_CHANGED)
            else:
                self.history.record([(bb.BACKEND, k, label, commit.before[k], commit.after[k])
                                     for k in commit.after])
                self.view.status(message if commit.reloaded else strings.BN_NOT_RELOADED)
            self.refresh()

        self.backend.queue_change(op, done)

    @staticmethod
    def describe(error: BaseException) -> str:
        if isinstance(error, writer.LuaActive):
            return strings.BN_LUA
        if isinstance(error, writer.ConfigErrors):
            return strings.BN_CONFIG_ERRORS.format(errors="; ".join(error.errors))
        if isinstance(error, writer.LaterDefinition):
            return strings.BN_FAILED.format(error=strings.BN_LATER_FILE.format(
                combo=names.combo_label(*_split_key(error.key)), where=error.where))
        if isinstance(error, writer.NoBlock):
            return strings.BN_FAILED.format(
                error=strings.BN_NO_BLOCK.format(path="settings-hub.conf"))
        return strings.BN_FAILED.format(error=error)

    def rebind(self, row_id: str, mask: int, key: str, replace: bool = False) -> None:
        entry, model = self.entries.get(row_id), self.models.get(row_id)
        if entry is None or model is None or not model.movable:
            return
        combo = Combo.of(mask, key)
        if combo == entry.combo:
            self.view.status(strings.BN_SAME_COMBO)
            return
        label = names.combo_label(mask, key)
        occupant = conflicts.conflict(list(self._active()), combo, entry.actions(),
                                      entry.submap, exclude=entry)
        if occupant is not None and not replace:
            self.view.ask_conflict(label, names.entry_name(occupant.binds, self._cfg()).text,
                                   lambda: self.rebind(row_id, mask, key, replace=True))
            return
        self._submit(self.backend.op_rebind(row_id, mask, key),
                     strings.BN_LABEL_REBIND.format(name=model.name, combo=label),
                     strings.BN_DONE_REBIND.format(name=model.name, combo=label))

    def disable(self, row_id: str, action: tuple | None = None) -> None:
        model = self.models.get(row_id)
        if model is None or not model.editable or model.disabled:
            return
        name = model.name
        if action is not None:
            name = next((n for a, n in model.actions if a == action), name)
        self._submit(self.backend.op_disable(row_id, None if action is None else [action]),
                     strings.BN_LABEL_DISABLE.format(name=name),
                     strings.BN_DONE_DISABLE.format(name=name))

    def revert(self, row_id: str) -> None:
        model = self.models.get(row_id)
        if model is None or not model.editable or not model.managed:
            return
        self._submit(self.backend.op_revert(row_id),
                     strings.BN_LABEL_REVERT.format(name=model.name),
                     strings.BN_DONE_REVERT.format(name=model.name))

    def add(self, command: str, mask: int, key: str, replace: bool = False) -> None:
        command = " ".join(command.split())
        if not command or not key:
            return
        label = names.combo_label(mask, key)
        want = writer.want_exec(command)
        occupant = conflicts.conflict(list(self._active()), Combo.of(mask, key),
                                      [want.action()])
        if occupant is not None and not replace:
            self.view.ask_conflict(label, names.entry_name(occupant.binds, self._cfg()).text,
                                   lambda: self.add(command, mask, key, replace=True))
            return
        self._submit(self.backend.op_add(mask, key, command),
                     strings.BN_LABEL_ADD.format(combo=label),
                     strings.BN_DONE_ADD.format(combo=label))

    def _active(self):
        return self.state.entries if self.state is not None else []

    def _cfg(self):
        return self.state.cfg if self.state is not None else None


def _split_key(key: str) -> tuple[int, str]:
    mods, _, k = key.partition(",")
    return parser.modmask(mods), k.strip()
