"""Binds grouped by key combination, and who occupies a combination. No GTK.

Several binds on one combination in one submap fire together (ALT, Tab:
cyclenext + bringactivetotop): that is one Entry with several actions, never a
conflict. A conflict is only a *new* use of a combination that already does
something else in the same submap; the occupant's name goes into the warning.
"""

from __future__ import annotations

from dataclasses import dataclass

from .parser import Bind, Combo, combo_text


@dataclass
class Entry:
    combo: Combo
    submap: str
    binds: list[Bind]

    @property
    def key(self) -> str:
        """The History key: 'SUPER SHIFT, K' (key spelled as in the config)."""
        first = self.binds[0]
        return combo_text(first.modmask, first.key)

    @property
    def id(self) -> str:
        return f"{self.submap}|{self.key}" if self.submap else self.key

    def actions(self) -> list[tuple[str, str, str, str]]:
        return [b.action() for b in self.binds]


def entries(binds: list[Bind]) -> list[Entry]:
    """One entry per (submap, combination), in the order of first appearance."""
    out: dict[tuple[str, Combo], Entry] = {}
    for b in binds:
        k = (b.submap, b.combo)
        if k in out:
            out[k].binds.append(b)
        else:
            out[k] = Entry(b.combo, b.submap, [b])
    return list(out.values())


def occupant(all_entries: list[Entry], combo: Combo, submap: str = "",
             exclude: Entry | None = None) -> Entry | None:
    for e in all_entries:
        if e is exclude or (exclude is not None and e.id == exclude.id):
            continue
        if e.submap == submap and e.combo == combo:
            return e
    return None


def conflict(all_entries: list[Entry], combo: Combo, actions: list[tuple[str, str, str, str]],
             submap: str = "", exclude: Entry | None = None) -> Entry | None:
    """The entry already on `combo` doing something else, if any."""
    other = occupant(all_entries, combo, submap, exclude)
    if other is None or other.actions() == list(actions):
        return None
    return other
