"""Themes page logic, backend and History, with a stub wallpaper-theme. No GTK.

The stub keeps its state in a JSON file and logs every call; the real command
lives in the wallpaper-theme project and has its own tests.
"""

import json
import os
import sys
import textwrap

import pytest

from settings_hub import strings
from settings_hub.backends import themes as th
from settings_hub.controllers import themes as ctl
from settings_hub.history import History

STUB = textwrap.dedent('''\
    #!{python}
    import json, os, random, sys
    root = os.environ["FAKE_THEME_DIR"]
    path = os.path.join(root, "state.json")
    with open(os.path.join(root, "calls.log"), "a") as log:
        log.write(" ".join(sys.argv[1:]) + "\\n")
    state = json.load(open(path))
    ids = ["monochrome", "nord", "dracula", "wallpaper-vivid"] + sorted(state["custom"])
    args = [a for a in sys.argv[1:] if a not in ("--quiet", "--json")]
    cmd, rest = args[0], args[1:]
    def save():
        json.dump(state, open(path, "w"))
    if cmd == "themes":
        pal = {{"surface_container_lowest": "#000000", "primary": "#ffffff"}}
        print(json.dumps([{{"id": i, "name": i.title(), "kind": "preset", "palette": pal,
                           "accents": [], "wallpapers": 0,
                           "active": i == state["system"]}} for i in ids]))
    elif cmd == "state":
        print(json.dumps({{"system": state["system"], "targets": state["targets"],
                          "wallpapers": state["wallpapers"]}}))
    elif cmd == "theme":
        if rest[0] not in ids:
            print("error: no such theme", file=sys.stderr); sys.exit(1)
        state["system"] = rest[0]; save()
        if os.environ.get("FAKE_THEME_WARN"):
            print("warning: panel not recoloured", file=sys.stderr); sys.exit(1)
    elif cmd == "target":
        if rest[1] == "system":
            state["targets"].pop(rest[0], None)
        else:
            state["targets"][rest[0]] = rest[1]
        save()
    elif cmd == "wallpapers":
        state["wallpapers"] = rest[0] == "on"; save()
    elif cmd == "random":
        state["system"] = [i for i in ids if i != state["system"]][0]; save()
    elif cmd == "custom-save":
        state["custom"].append("custom-x"); save(); print("custom-x")
    elif cmd == "custom-delete":
        state["custom"].remove(rest[0]); save()
    elif cmd == "walls":
        print(json.dumps(state["walls"].get(rest[0], [])))
    elif cmd == "walls-set":
        walls = state["walls"].setdefault(rest[0], [])
        (walls.append if rest[2] == "on" else walls.remove)(rest[1]); save()
    else:
        sys.exit(2)
''')


class SyncWorkers:
    """Runs a job at once, like a worker that is never busy."""

    def submit(self, _name, fn, on_done=None, key=None):
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001 -- handed to on_done like Workers does
            result, error = None, exc
        if on_done is not None:
            on_done(result, error)


class FakeView:
    def __init__(self):
        self.shown = []
        self.walls = {}
        self.statuses = []
        self.busy_log = []
        self.missing = None

    def show(self, themes, state):
        self.shown.append(([t.id for t in themes], state))

    def show_missing(self, detail):
        self.missing = detail

    def show_walls(self, theme_id, paths):
        self.walls[theme_id] = list(paths)

    def busy(self, on):
        self.busy_log.append(on)

    def status(self, text):
        self.statuses.append(text)

    def custom_saved(self):
        self.statuses.append("saved")


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "theme"
    root.mkdir()
    (root / "state.json").write_text(json.dumps(
        {"system": "monochrome", "targets": {}, "wallpapers": True, "custom": [], "walls": {}}))
    stub = tmp_path / "wallpaper-theme"
    stub.write_text(STUB.format(python=sys.executable))
    stub.chmod(0o755)
    monkeypatch.setenv("FAKE_THEME_DIR", str(root))
    history = History(tmp_path / "history.jsonl")
    backend = th.Backend(SyncWorkers(), command=str(stub), dispatch=lambda fn: fn())
    th.register(history, backend)
    view = FakeView()
    controller = ctl.Controller(backend, history, view)

    class W:
        pass
    w = W()
    w.root, w.history, w.backend, w.view, w.c = root, history, backend, view, controller
    w.calls = lambda: (root / "calls.log").read_text().splitlines()
    w.state = lambda: json.loads((root / "state.json").read_text())
    return w


def test_refresh_shows_every_theme_and_the_state(world):
    world.c.refresh()
    ids, state = world.view.shown[-1]
    assert ids == ["monochrome", "nord", "dracula", "wallpaper-vivid"]
    assert state.system == "monochrome" and state.wallpapers is True


def test_a_card_applies_quietly_records_history_and_undo_returns(world):
    world.c.refresh()
    assert world.c.choose("nord")
    assert "theme nord --quiet" in world.calls()
    assert world.state()["system"] == "nord"
    assert world.view.busy_log == [True, False]
    assert world.view.statuses[-1] == strings.TH_DONE.format(name="Nord")
    (group,) = world.history.groups()
    assert [(e.backend, e.key, e.before, e.after) for e in group.entries] == [
        ("themes", "theme.system", "monochrome", "nord")]
    world.history.execute(world.history.plan_undo_last())
    assert world.state()["system"] == "monochrome"
    assert "theme monochrome --quiet --keep-wallpapers" in world.calls()  # undo: colours only


def test_clicking_the_current_theme_does_nothing(world):
    world.c.refresh()
    assert not world.c.choose("monochrome")
    assert not any(c.startswith("theme ") for c in world.calls())


def test_a_warning_still_records_the_new_theme(world, monkeypatch):
    world.c.refresh()
    monkeypatch.setenv("FAKE_THEME_WARN", "1")
    world.c.choose("dracula")
    assert world.state()["system"] == "dracula"
    assert world.view.statuses[-1].startswith(strings.TH_PARTLY.split("{")[0])
    assert world.history.groups()  # the change happened, so it can be undone


def test_a_program_gets_its_own_theme_and_back(world):
    world.c.refresh()
    world.c.set_target("rofi", "dracula")
    assert world.state()["targets"] == {"rofi": "dracula"}
    entries = world.history.groups()[-1].entries
    assert [(e.key, e.before, e.after) for e in entries] == [
        ("theme.target.rofi", th.AS_SYSTEM, "dracula")]
    world.history.execute(world.history.plan_undo_last())
    assert world.state()["targets"] == {}
    assert "target rofi system --quiet" in world.calls()


def test_the_dropdown_echo_does_not_run_a_command(world):
    world.c.refresh()
    assert not world.c.set_target("panel", th.AS_SYSTEM)
    assert not world.c.set_wallpapers(True)
    assert not any(c.startswith(("target", "wallpapers")) for c in world.calls())


def test_wallpapers_switch_and_random(world):
    world.c.refresh()
    world.c.set_wallpapers(False)
    assert world.state()["wallpapers"] is False
    world.c.random()
    assert world.state()["system"] != "monochrome"
    keys = [e.key for g in world.history.groups() for e in g.entries]
    assert keys == ["theme.wallpapers", "theme.system"]


def test_a_second_click_while_busy_is_ignored(world):
    world.c.refresh()
    world.c.running = True  # a recolouring is under way
    assert not world.c.choose("nord")
    assert world.state()["system"] == "monochrome"


def test_custom_theme_save_and_delete(world):
    world.c.refresh()
    world.c.save_custom("  ", "#ff0000", "#000000", "#ffffff")
    assert world.view.statuses[-1] == strings.TH_CUSTOM_NO_NAME
    world.c.save_custom("Mine", "#ff0000", "#000000", "#ffffff")
    assert "custom-save Mine #ff0000 #000000 #ffffff" in world.calls()
    assert "custom-x" in world.view.shown[-1][0]
    world.c.delete_custom("custom-x")
    assert "custom-x" not in world.view.shown[-1][0]


def test_theme_wallpapers_toggle(world):
    world.c.refresh()
    world.c.toggle_wall("nord", "/lib/a.jpg", True)
    assert world.view.walls["nord"] == ["/lib/a.jpg"]
    world.c.toggle_wall("nord", "/lib/a.jpg", False)
    assert world.view.walls["nord"] == []


def test_without_the_command_the_page_says_so(tmp_path):
    history = History(tmp_path / "h.jsonl")
    backend = th.Backend(SyncWorkers(), command=str(tmp_path / "nope"), dispatch=lambda f: f())
    view = FakeView()
    ctl.Controller(backend, history, view).refresh()
    assert view.missing == str(tmp_path / "nope")
    with pytest.raises(RuntimeError):
        th.ThemesApplier(backend).apply({th.SYSTEM_KEY: "nord"})


def test_applier_refuses_unknown_keys(world):
    with pytest.raises(KeyError):
        th.ThemesApplier(world.backend).apply({"theme.target.firefox": "nord"})


def test_every_label_and_target_name_is_russian():
    assert set(strings.TH_TARGETS) == set(th.TARGETS)
    for key in (th.SYSTEM_KEY, th.WALLS_KEY, *(th.target_key(t) for t in th.TARGETS)):
        assert ctl.label_for(key)


def test_page_registers_every_searchable_row():
    import re

    from conftest import ROOT
    source = (ROOT / "settings_hub" / "pages" / "themes.py").read_text()
    registered = set(re.findall(r'self\.rows\["([a-z-]+)"\]', source))
    assert set(strings.PAGES["themes"]["rows"]) <= registered


def test_parsers_tolerate_missing_fields():
    themes = th.parse_themes(json.dumps([{"id": "x", "name": "X"}]))
    assert themes[0].palette is None and themes[0].accents == () and not themes[0].active
    state = th.parse_state(json.dumps({"targets": {"rofi": "x", "bogus": "y"}}))
    assert state.system == "monochrome" and state.targets == {"rofi": "x"}


def test_stub_is_isolated():
    assert "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ
