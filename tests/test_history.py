"""History: the journal format, groups, undo and "return to a moment"."""

import json
from datetime import datetime

import pytest

from settings_hub.history import KEEP, History


class FakeBackend:
    """An applier over a dict, counting reads and applies."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.reads = 0
        self.applies = []

    def read(self, keys):
        self.reads += 1
        return {k: self.values.get(k) for k in keys}

    def apply(self, values):
        self.applies.append(dict(values))
        self.values.update(values)


class FailingBackend(FakeBackend):
    def apply(self, values):
        raise RuntimeError("hypridle did not restart")


def clock():
    return datetime(2026, 10, 29, 14, 3, 12)


@pytest.fixture
def hist(tmp_path):
    return History(tmp_path / "history.jsonl", clock=clock)


def change(history, name, backend, items):
    """Do what a page does: read fresh, change, then log one group."""
    before = backend.read([k for k, _l, _v in items])
    backend.values.update({k: v for k, _l, v in items})
    return history.record((name, k, label, before[k], v) for k, label, v in items)


# ---- journal ---------------------------------------------------------------

def test_entry_has_exactly_the_planned_fields(hist):
    ss = FakeBackend({"idle.ac.dim": 5})
    gid = change(hist, "screen-sleep", ss, [("idle.ac.dim", "dim", 3)])
    lines = hist.path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert set(entry) == {"id", "group", "ts", "backend", "key", "label", "before", "after"}
    assert entry["group"] == gid
    assert entry["ts"] == "2026-10-29T14:03:12"
    assert (entry["backend"], entry["key"], entry["before"], entry["after"]) == (
        "screen-sleep", "idle.ac.dim", 5, 3)


def test_unchanged_items_are_not_logged(hist):
    assert hist.record([("screen-sleep", "k", "l", 1, 1)]) is None
    assert not hist.path.exists()
    gid = hist.record([("screen-sleep", "a", "l", 1, 1), ("screen-sleep", "b", "l", 1, 2)])
    assert [e.key for e in hist.groups()[0].entries] == ["b"]
    assert hist.groups()[0].id == gid


def test_journal_is_append_only(hist):
    ss = FakeBackend({"a": 1})
    change(hist, "screen-sleep", ss, [("a", "a", 2)])
    first = hist.path.read_text()
    change(hist, "screen-sleep", ss, [("a", "a", 3)])
    assert hist.path.read_text().startswith(first)


def test_keeps_the_last_entries_dropping_whole_groups(tmp_path):
    hist = History(tmp_path / "h.jsonl", keep=5, clock=clock)
    ss = FakeBackend({"a": 0, "b": 0})
    ids = [change(hist, "screen-sleep", ss, [("a", "a", i), ("b", "b", i)])
           for i in range(1, 5)]
    groups = hist.groups()
    assert [g.id for g in groups] == ids[-2:]  # 8 entries -> whole groups until <= 5
    assert all(len(g.entries) == 2 for g in groups)
    assert KEEP == 1000


def test_torn_lines_do_not_hide_the_rest(hist):
    ss = FakeBackend({"a": 1})
    change(hist, "screen-sleep", ss, [("a", "a", 2)])
    with hist.path.open("a") as fh:
        fh.write('{"id": "half\n')
    change(hist, "screen-sleep", ss, [("a", "a", 3)])
    assert len(hist.groups()) == 2


# ---- undo of one group -----------------------------------------------------

def test_undo_preset_restores_all_four_fields_in_one_apply(hist):
    old = {f"idle.ac.{s}": {"enabled": True, "minutes": m}
           for s, m in (("dim", 3), ("lock", 5), ("dpms", 8), ("suspend", 15))}
    ss = FakeBackend(old)
    hist.register("screen-sleep", ss)
    preset = [(k, "preset", {"enabled": True, "minutes": 1}) for k in old]
    change(hist, "screen-sleep", ss, preset)
    plan = hist.plan_undo_last("undo")
    assert plan.flagged == [] and plan.missing == []
    result = hist.execute(plan)
    assert ss.values == old
    assert len(ss.applies) == 1 and set(ss.applies[0]) == set(old)
    assert result.errors == {}
    undo_group = hist.groups()[-1]
    assert undo_group.id == result.group
    assert len(undo_group.entries) == 4
    assert all(e.label == "undo: preset" for e in undo_group.entries)


def test_undo_slider_restores_temperature_and_override_together(hist):
    night = FakeBackend({"night.current_temp": 6500, "night.manual_override": False})
    hist.register("night", night)
    change(hist, "night", night, [("night.current_temp", "now", 4200),
                                  ("night.manual_override", "now", True)])
    hist.execute(hist.plan_undo_last())
    assert night.values == {"night.current_temp": 6500, "night.manual_override": False}
    assert night.applies == [{"night.current_temp": 6500, "night.manual_override": False}]


def test_undo_rebind_reverts_unbind_and_bind_together(hist):
    binds = FakeBackend({"SUPER SHIFT, T": [], "SUPER SHIFT, K": []})
    hist.register("binds", binds)
    change(hist, "binds", binds, [
        ("SUPER SHIFT, T", "rebind timer", ["unbind = SUPER SHIFT, T"]),
        ("SUPER SHIFT, K", "rebind timer", ["bind = SUPER SHIFT, K, exec, timer"]),
    ])
    hist.execute(hist.plan_undo_last())
    assert binds.values == {"SUPER SHIFT, T": [], "SUPER SHIFT, K": []}
    assert len(binds.applies) == 1 and len(binds.applies[0]) == 2


def test_undo_twice_redoes(hist):
    ss = FakeBackend({"a": 1})
    hist.register("screen-sleep", ss)
    change(hist, "screen-sleep", ss, [("a", "a", 2)])
    hist.execute(hist.plan_undo_last())
    assert ss.values["a"] == 1
    hist.execute(hist.plan_undo_last())  # the undo is itself the last group
    assert ss.values["a"] == 2
    assert len(hist.groups()) == 3


def test_nothing_to_undo(hist):
    assert hist.plan_undo_last() is None


def test_missing_applier_is_reported_not_guessed(hist):
    ss = FakeBackend({"a": 1})
    change(hist, "screen-sleep", ss, [("a", "a", 2)])
    plan = hist.plan_undo_last()
    assert plan.missing == ["screen-sleep"]
    result = hist.execute(plan)
    assert result.errors == {"screen-sleep": "no applier"}
    assert result.group is None
    assert len(hist.groups()) == 1


def test_a_failing_backend_does_not_stop_the_others(hist):
    ok = FakeBackend({"x": 1})
    bad = FailingBackend({"y": 1})
    hist.register("screen-sleep", ok)
    hist.register("binds", bad)
    hist.record([("screen-sleep", "x", "x", 1, 2), ("binds", "y", "y", 1, 2)])
    ok.values["x"], bad.values["y"] = 2, 2
    result = hist.execute(hist.plan_undo_last())
    assert ok.values["x"] == 1
    assert "binds" in result.errors and "screen-sleep" in result.applied
    logged = hist.groups()[-1]
    assert [e.backend for e in logged.entries] == ["screen-sleep"]  # only what happened


# ---- return to a moment ----------------------------------------------------

def test_return_to_folds_per_key_and_applies_once_per_backend(hist):
    ss = FakeBackend({"a": 1, "b": "x"})
    binds = FakeBackend({"K": []})
    hist.register("screen-sleep", ss)
    hist.register("binds", binds)
    g1 = change(hist, "screen-sleep", ss, [("a", "a", 2)])
    change(hist, "screen-sleep", ss, [("a", "a", 3), ("b", "b", "y")])
    change(hist, "binds", binds, [("K", "k", ["bind = K"])])
    change(hist, "screen-sleep", ss, [("a", "a", 4)])
    ss.reads = binds.reads = 0

    plan = hist.plan_return_to(g1)
    assert plan.targets == {("screen-sleep", "a"): 2, ("screen-sleep", "b"): "x",
                            ("binds", "K"): []}
    assert plan.flagged == []
    assert ss.reads == 1 and binds.reads == 1  # one read per backend for the whole plan
    hist.execute(plan)
    assert ss.values == {"a": 2, "b": "x"} and binds.values == {"K": []}
    assert ss.applies == [{"a": 2, "b": "x"}]  # one hypridle restart, not three
    assert binds.applies == [{"K": []}]  # one reload
    logged = hist.groups()[-1]
    assert sorted((e.key, json.dumps(e.before), json.dumps(e.after)) for e in logged.entries) == [
        ("K", '["bind = K"]', "[]"), ("a", "4", "2"), ("b", '"y"', '"x"')]


def test_external_change_is_one_question_decided_per_group(hist):
    ss = FakeBackend({"x": 1, "y": 1})
    binds = FakeBackend({"OLD": ["bind = OLD"], "NEW": []})
    hist.register("screen-sleep", ss)
    hist.register("binds", binds)
    moment = change(hist, "screen-sleep", ss, [("x", "x", 2)])
    change(hist, "screen-sleep", ss, [("x", "x", 3)])
    pair = change(hist, "binds", binds, [("OLD", "rebind", ["unbind = OLD"]),
                                         ("NEW", "rebind", ["bind = NEW"])])
    change(hist, "screen-sleep", ss, [("y", "y", 5)])
    binds.values["NEW"] = ["bind = NEW, edited by hand"]  # changed outside the window

    plan = hist.plan_return_to(moment)
    assert [g.id for g in plan.flagged] == [pair]  # the one question lists one group

    result = hist.execute(plan, skip=[pair])  # "keep it": the whole pair stays
    assert result.skipped == [pair]
    assert binds.applies == []
    assert binds.values == {"OLD": ["unbind = OLD"], "NEW": ["bind = NEW, edited by hand"]}
    assert ss.values == {"x": 2, "y": 1}
    assert ss.applies == [{"x": 2, "y": 1}]


def test_external_change_reverted_anyway_when_user_says_so(hist):
    binds = FakeBackend({"OLD": ["bind = OLD"], "NEW": []})
    hist.register("binds", binds)
    change(hist, "binds", binds, [("OLD", "rebind", ["unbind = OLD"]),
                                  ("NEW", "rebind", ["bind = NEW"])])
    binds.values["NEW"] = ["bind = NEW, edited"]
    plan = hist.plan_undo_last()
    assert len(plan.flagged) == 1
    hist.execute(plan)  # nothing skipped
    assert binds.values == {"OLD": ["bind = OLD"], "NEW": []}
    assert len(binds.applies) == 1


def test_skipping_a_group_also_skips_groups_sharing_its_items(hist):
    ss = FakeBackend({"a": 0, "b": 0})
    hist.register("screen-sleep", ss)
    moment = change(hist, "screen-sleep", ss, [("b", "b", 1)])
    first = change(hist, "screen-sleep", ss, [("a", "a", 1), ("b", "b", 2)])
    second = change(hist, "screen-sleep", ss, [("a", "a", 2)])
    result = hist.execute(hist.plan_return_to(moment), skip=[second])
    # reverting `first` alone would rewrite `a`, which `second` must keep
    assert sorted(result.skipped) == sorted([first, second])
    assert ss.applies == []
    assert result.group is None


def test_return_to_latest_or_unknown(hist):
    ss = FakeBackend({"a": 1})
    last = change(hist, "screen-sleep", ss, [("a", "a", 2)])
    assert hist.plan_return_to(last) is None
    with pytest.raises(KeyError):
        hist.plan_return_to("nope")


def test_values_compare_as_json(hist):
    """Tuples written become lists on reading; that is not an outside change."""
    binds = FakeBackend({"K": ("bind = K",)})
    hist.register("binds", binds)
    hist.record([("binds", "K", "k", [], ("bind = K",))])
    assert hist.plan_undo_last().flagged == []
