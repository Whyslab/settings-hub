"""The window's own settings: defaults, validation, the file, and undo."""

import json
from pathlib import Path

import pytest

from settings_hub import registry, settings, strings


def make(tmp_path: Path, *, start: dict | None = None) -> settings.Settings:
    path = tmp_path / "settings.json"
    if start is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(start), encoding="utf-8")
    return settings.Settings(path)


def test_defaults_are_used_when_the_file_is_missing(tmp_path):
    s = make(tmp_path)
    assert s.get("appearance.theme") == "system"
    assert s.get("appearance.window_width") == 920
    assert s.get("behavior.start_page") == settings.START_PAGE_LAST
    assert not s.path.exists()  # reading must not create the file


def test_only_changed_values_are_written(tmp_path):
    s = make(tmp_path)
    s.set("appearance.theme", "dark")
    s.set("behavior.apply_delay_ms", 900)
    stored = json.loads(s.path.read_text(encoding="utf-8"))
    assert stored == {"appearance.theme": "dark", "behavior.apply_delay_ms": 900}
    # Another window (another Settings object) sees the same values.
    again = make(tmp_path)
    assert again.get("appearance.theme") == "dark"
    assert again.get("behavior.apply_delay_ms") == 900
    assert again.get("behavior.history_keep") == 1000


def test_a_value_equal_to_the_default_is_not_stored(tmp_path):
    s = make(tmp_path)
    s.set("appearance.theme", "light")
    s.set("appearance.theme", "system")
    stored = json.loads(s.path.read_text(encoding="utf-8"))
    assert "appearance.theme" not in stored


@pytest.mark.parametrize("key,value", [
    ("appearance.theme", "violet"),  # not a choice
    ("appearance.theme", 3),  # wrong type
    ("appearance.sidebar_width", 10),  # below lo
    ("appearance.sidebar_width", 5000),  # above hi
    ("appearance.remember_size", "yes"),  # not a boolean
    ("behavior.start_page", "no-such-page"),
])
def test_a_bad_value_is_rejected_keeps_the_old_one(tmp_path, key, value):
    s = make(tmp_path)
    before = s.get(key)
    with pytest.raises(ValueError):
        s.set(key, value)
    assert s.get(key) == before
    assert not s.path.exists()


def test_a_broken_file_falls_back_to_defaults_and_keeps_the_rest(tmp_path):
    s = make(tmp_path, start={
        "appearance.theme": "dark",
        "appearance.sidebar_width": "wide",  # a hand edit gone wrong
        "no.such.field": 1,
    })
    assert s.get("appearance.theme") == "dark"
    assert s.get("appearance.sidebar_width") == 220


def test_a_torn_file_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert settings.Settings(path).get("appearance.theme") == "system"


def test_subscribers_hear_each_change_once(tmp_path):
    s = make(tmp_path)
    heard = []
    s.subscribe(lambda key, value: heard.append((key, value)))
    s.set("appearance.theme", "dark")
    s.set("appearance.theme", "dark")  # unchanged: no second call
    assert heard == [("appearance.theme", "dark")]


def test_reset_returns_what_changed_and_removes_it_from_the_file(tmp_path):
    s = make(tmp_path)
    s.set("appearance.theme", "dark")
    s.set("appearance.status_ms", 9000)
    items = s.reset()
    assert {(k, b, a) for k, b, a in items} == {
        ("appearance.theme", "dark", "system"),
        ("appearance.status_ms", 9000, 5000),
    }
    assert json.loads(s.path.read_text(encoding="utf-8")) == {}
    assert s.reset() == []


def test_groups_and_fields_come_from_the_table(tmp_path):
    s = make(tmp_path)
    assert s.groups() == ("appearance", "behavior")
    assert {f.key for f in s.fields_of("appearance")} >= {"appearance.theme"}
    for field in s:
        assert field.group in settings.GROUPS
        assert field.key in strings.HUB_SETTINGS


def test_start_pages_are_real_pages_and_have_titles():
    assert settings.START_PAGES[0] == settings.START_PAGE_LAST
    for page_id in settings.START_PAGES[1:]:
        assert registry.get(page_id) is not None, page_id
        assert strings.PAGES[page_id]["title"], page_id


def test_every_group_has_a_title():
    for group in settings.GROUPS:
        assert strings.HUB_GROUPS.get(group), group


def test_settings_are_undone_by_history(tmp_path):
    from settings_hub.history import History

    s = make(tmp_path)
    history = History(tmp_path / "history.jsonl")
    settings.register(history, s)
    before = s.get("appearance.theme")
    s.set("appearance.theme", "dark")
    group = history.record([
        ("settings", "appearance.theme", strings.HUB_SETTINGS["appearance.theme"][0],
         before, "dark")])
    assert group
    plan = history.plan_undo_last()
    assert plan is not None and not plan.missing
    result = history.execute(plan)
    assert not result.errors
    assert s.get("appearance.theme") == before
    # The undo itself is logged as a new group.
    assert len(history.groups()) == 2
