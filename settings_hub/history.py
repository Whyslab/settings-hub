"""History of changes and undo. No GTK.

The journal is history.jsonl: append-only, the last 1000 entries are kept. One
entry is one item that changed:

    {"id", "group", "ts", "backend", "key", "label", "before", "after"}

Whole files are never stored, so reverting one item never overwrites anything
else in the same file. A *group* is one user action that may change several
items (a preset sets four idle fields, a slider drag sets the temperature and
the manual-override flag, a rebind writes the old and the new key combination).
Undo always works on whole groups.

Reverting is two-phase so a GUI can ask its question asynchronously:

    plan = history.plan_undo_last()            # or plan_return_to(group_id)
    if plan.flagged: ...ask once, listing plan.flagged...
    result = history.execute(plan, skip={group ids the user chose to keep})

Backends plug in through an Applier (see below). A plan folds all later groups
into one target value per (backend, key) -- the "before" of the earliest entry
-- and execute() calls each backend's apply() exactly once. The revert itself is
logged as a new group.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

KEEP = 1000


class Applier(Protocol):
    """How History reads and writes one backend's items."""

    def read(self, keys: list[str]) -> dict[str, Any]:
        """Current value of each key, read fresh from the source of truth."""
        ...

    def apply(self, values: dict[str, Any]) -> None:
        """Set all these keys at once (one hypridle restart, one reload...)."""
        ...


def default_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "settings-hub" / "history.jsonl"


def _canon(value: Any) -> Any:
    """Compare values the way they come back from JSON (tuples become lists)."""
    return json.loads(json.dumps(value))


@dataclass(frozen=True)
class Entry:
    id: str
    group: str
    ts: str
    backend: str
    key: str
    label: str
    before: Any
    after: Any

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict) -> Entry:
        return cls(**{k: raw[k] for k in
                      ("id", "group", "ts", "backend", "key", "label", "before", "after")})


@dataclass(frozen=True)
class Group:
    id: str
    entries: tuple[Entry, ...]

    @property
    def ts(self) -> str:
        return self.entries[0].ts

    @property
    def label(self) -> str:
        seen: list[str] = []
        for e in self.entries:
            if e.label not in seen:
                seen.append(e.label)
        return ", ".join(seen)

    @property
    def backends(self) -> list[str]:
        out: list[str] = []
        for e in self.entries:
            if e.backend not in out:
                out.append(e.backend)
        return out


@dataclass
class Plan:
    """What a revert would do. Built by plan_*; carried out by execute()."""

    groups: list[Group]  # groups being reverted, oldest first
    targets: dict[tuple[str, str], Any]  # (backend, key) -> value to restore
    labels: dict[tuple[str, str], str]
    flagged: list[Group]  # groups whose items were changed outside the window
    missing: list[str]  # backends without a registered applier
    label_prefix: str = ""


@dataclass
class Result:
    applied: dict[str, dict[str, Any]] = field(default_factory=dict)  # backend -> values
    skipped: list[str] = field(default_factory=list)  # group ids left as they are
    errors: dict[str, str] = field(default_factory=dict)  # backend -> message
    group: str | None = None  # id of the group that logs this revert


class History:
    def __init__(self, path: Path | None = None, keep: int = KEEP,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = Path(path) if path else default_path()
        self.keep = keep
        self._clock = clock
        self._appliers: dict[str, Applier] = {}

    # ---- appliers -------------------------------------------------------

    def register(self, backend: str, applier: Applier) -> None:
        self._appliers[backend] = applier

    def applier(self, backend: str) -> Applier | None:
        return self._appliers.get(backend)

    # ---- journal --------------------------------------------------------

    def entries(self) -> list[Entry]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        out = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                out.append(Entry.from_dict(json.loads(line)))
            except (ValueError, KeyError, TypeError):
                continue  # a torn or foreign line must not hide the rest
        return out

    def groups(self) -> list[Group]:
        """All groups, oldest first."""
        order: list[str] = []
        members: dict[str, list[Entry]] = {}
        for e in self.entries():
            if e.group not in members:
                order.append(e.group)
                members[e.group] = []
            members[e.group].append(e)
        return [Group(g, tuple(members[g])) for g in order]

    def record(self, items: Iterable[tuple[str, str, str, Any, Any]]) -> str | None:
        """Log one user action. items: (backend, key, label, before, after).

        Items whose value did not change are dropped; returns the group id, or
        None if nothing changed.
        """
        group = uuid.uuid4().hex[:12]
        ts = self._clock().strftime("%Y-%m-%dT%H:%M:%S")
        new = [
            Entry(uuid.uuid4().hex[:12], group, ts, backend, key, label,
                  _canon(before), _canon(after))
            for backend, key, label, before, after in items
            if _canon(before) != _canon(after)
        ]
        if not new:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for e in new:
                fh.write(e.to_json() + "\n")
        self._trim()
        return group

    def _trim(self) -> None:
        """Keep the last `keep` entries, dropping whole groups from the front."""
        entries = self.entries()
        if len(entries) <= self.keep:
            return
        groups = self.groups()
        total = len(entries)
        while groups and total > self.keep:
            total -= len(groups.pop(0).entries)
        lines = "".join(e.to_json() + "\n" for g in groups for e in g.entries)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".history.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(lines)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---- reverting ------------------------------------------------------

    def plan_undo_last(self, label_prefix: str = "") -> Plan | None:
        groups = self.groups()
        if not groups:
            return None
        return self._plan(groups[-1:], label_prefix)

    def plan_undo(self, group_ids: list[str], label_prefix: str = "") -> Plan:
        """Undo these groups only; items changed since are asked about (flagged)."""
        groups = [g for g in self.groups() if g.id in set(group_ids)]
        if len(groups) != len(set(group_ids)):
            raise KeyError(group_ids)
        return self._plan(groups, label_prefix)

    def plan_return_to(self, group_id: str, label_prefix: str = "") -> Plan | None:
        """Return to the moment right after `group_id` was applied."""
        groups = self.groups()
        ids = [g.id for g in groups]
        if group_id not in ids:
            raise KeyError(group_id)
        later = groups[ids.index(group_id) + 1:]
        if not later:
            return None
        return self._plan(later, label_prefix)

    def _plan(self, groups: list[Group], label_prefix: str) -> Plan:
        targets: dict[tuple[str, str], Any] = {}
        labels: dict[tuple[str, str], str] = {}
        last_after: dict[tuple[str, str], Any] = {}
        for g in groups:  # oldest first: the first "before" seen is the target
            for e in g.entries:
                k = (e.backend, e.key)
                targets.setdefault(k, e.before)
                labels.setdefault(k, e.label)
                last_after[k] = e.after
        backends = sorted({b for b, _ in targets})
        missing = [b for b in backends if b not in self._appliers]
        changed_outside: set[tuple[str, str]] = set()
        for b in backends:
            if b in missing:
                continue
            keys = [k for bb, k in targets if bb == b]
            current = self._appliers[b].read(keys)
            for k in keys:
                if _canon(current.get(k)) != _canon(last_after[(b, k)]):
                    changed_outside.add((b, k))
        flagged = [g for g in groups
                   if any((e.backend, e.key) in changed_outside for e in g.entries)]
        return Plan(groups, targets, labels, flagged, missing, label_prefix)

    def execute(self, plan: Plan, skip: Iterable[str] = ()) -> Result:
        """Revert the plan's groups except `skip`; one apply() per backend.

        Skipping a group keeps all of its items. Any other group sharing an item
        with a skipped group is skipped too, so no group is ever half-reverted
        (a rebind's unbind + bind always move together).
        """
        result = Result()
        skipped = set(skip)
        while True:
            frozen = {(e.backend, e.key) for g in plan.groups if g.id in skipped
                      for e in g.entries}
            more = {g.id for g in plan.groups if g.id not in skipped
                    and any((e.backend, e.key) in frozen for e in g.entries)}
            if not more:
                break
            skipped |= more
        result.skipped = [g.id for g in plan.groups if g.id in skipped]
        keep = [g for g in plan.groups if g.id not in skipped]
        wanted: dict[str, dict[str, Any]] = {}
        for g in keep:
            for e in g.entries:
                wanted.setdefault(e.backend, {})[e.key] = plan.targets[(e.backend, e.key)]
        log: list[tuple[str, str, str, Any, Any]] = []
        for backend, values in wanted.items():
            applier = self._appliers.get(backend)
            if applier is None:
                result.errors[backend] = "no applier"
                continue
            try:
                before = applier.read(list(values))
                applier.apply(values)
            except Exception as exc:  # report per backend, keep going with the rest
                result.errors[backend] = str(exc) or type(exc).__name__
                continue
            result.applied[backend] = values
            for key, value in values.items():
                label = plan.labels[(backend, key)]
                if plan.label_prefix:
                    label = f"{plan.label_prefix}: {label}"
                log.append((backend, key, label, before.get(key), value))
        if log:
            result.group = self.record(log)
        return result
