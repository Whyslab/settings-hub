"""Window minimize animation: the minimize tool's anim module, page logic, History.

The tool is a copy in tests/fixtures/minimize (anim.py is the real module,
`minimize` a stub that records its arguments). The choice file lands in the
temporary HOME (conftest), never in the real ~/.config/minimize.
"""

import json
import os
import shutil

import pytest
from conftest import FIXTURES
from screen_sleep_env import Loop

from settings_hub import strings
from settings_hub.backends import minimize_anim as ma
from settings_hub.controllers import minimize_anim as mctl
from settings_hub.history import History


class FakeView:
    def __init__(self) -> None:
        self.setup = None
        self.state: dict = {}
        self.busy: list[bool] = []
        self.statuses: list[str] = []

    def show_minimize_setup(self, state, detail):
        self.setup = (state, detail)

    def show_minimize(self, state, keys):
        for key in keys:
            self.state[key] = state[key]

    def set_minimize_busy(self, busy):
        self.busy.append(busy)

    def status(self, text):
        self.statuses.append(text)


class World:
    def __init__(self, tmp_path):
        self.tool = tmp_path / "minimize"
        shutil.copytree(FIXTURES / "minimize", self.tool)
        self.log = tmp_path / "calls.log"
        os.environ["MINIMIZE_STUB_LOG"] = str(self.log)
        self.loop = Loop()
        self.backend = ma.Backend(self.loop.workers, self.tool, dispatch=self.loop.queue.put)
        self.history = History(tmp_path / "history.jsonl")
        ma.register(self.history, self.backend)
        self.config = os.path.join(os.environ["XDG_CONFIG_HOME"], "minimize", "animation.json")

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def saved(self) -> dict:
        with open(self.config) as f:
            return json.load(f)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMIZE_STUB_RC", raising=False)
    w = World(tmp_path)
    yield w
    w.loop.workers.stop_all(2)
    os.environ.pop("MINIMIZE_STUB_LOG", None)


def page(w: World):
    view = FakeView()
    c = mctl.Controller(w.backend, w.history, view)
    c.refresh()
    return c, view


def test_choice_file_is_in_the_temporary_home(world):
    import pwd
    assert world.config.startswith(os.environ["HOME"])
    assert not world.config.startswith(pwd.getpwuid(os.getuid()).pw_dir + os.sep)


def test_defaults_without_a_file(world):
    c, view = page(world)
    assert view.setup == ("ok", "")
    assert view.state == {"style": "fly", "speed": "normal"}
    assert not os.path.exists(world.config)


def test_styles_come_from_the_tool_in_its_order(world):
    ids = [s.id for s in world.backend.styles()]
    assert ids == ["fly", "fade", "shrink", "slide", "dissolve", "none"]
    assert world.backend.style_name("dissolve") == "Рассыпается на пиксели"
    assert world.backend.speeds == ("fast", "normal", "slow")


def test_choose_style_writes_the_file_and_one_history_line(world):
    c, view = page(world)
    c.choose_style("dissolve")
    world.loop.pump()
    assert world.saved() == {"style": "dissolve", "speed": "normal"}
    assert view.state["style"] == "dissolve"
    entries = world.history.entries()
    assert [(e.backend, e.key, e.before, e.after) for e in entries] == \
        [(ma.BACKEND, "style", "fly", "dissolve")]
    assert entries[0].label == strings.MA_LABEL_STYLE


def test_speed_keeps_the_style(world):
    c, _view = page(world)
    c.choose_style("slide")
    world.loop.pump()
    c.choose_speed("slow")
    world.loop.pump()
    assert world.saved() == {"style": "slide", "speed": "slow"}


def test_undo_brings_the_old_style_back(world):
    c, view = page(world)
    c.choose_style("none")
    world.loop.pump()
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert world.saved()["style"] == "fly"
    assert view.state["style"] == "fly"  # the page re-read after the undo


def test_same_value_from_a_widget_does_nothing(world):
    c, _view = page(world)
    c.choose_style("fly")      # the default, echoed by the drop-down
    world.loop.pump()
    assert world.history.entries() == []
    assert not os.path.exists(world.config)


def test_unknown_values_are_refused(world):
    with pytest.raises(ma.MinimizeAnimError):
        world.backend.write({"style": "genie"})
    with pytest.raises(ma.MinimizeAnimError):
        world.backend.write({"speed": "ludicrous"})
    with pytest.raises(KeyError):
        world.backend.read(["colour"])
    assert not os.path.exists(world.config)


def test_broken_file_reads_as_defaults_and_is_replaced(world):
    os.makedirs(os.path.dirname(world.config))
    with open(world.config, "w") as f:
        f.write("{not json")
    assert world.backend.read_all() == {"style": "fly", "speed": "normal"}
    world.backend.write({"speed": "fast"})
    assert world.saved() == {"style": "fly", "speed": "fast"}


def test_preview_runs_the_tool_with_the_saved_choice(world):
    c, view = page(world)
    c.choose_style("shrink")
    c.choose_speed("fast")
    world.loop.pump()
    c.preview()
    world.loop.pump()
    assert world.calls() == ["preview shrink fast"]
    assert view.busy == [True, False]
    assert view.statuses[-1] == ""


def test_preview_failure_is_reported(world, monkeypatch):
    monkeypatch.setenv("MINIMIZE_STUB_RC", "1")
    c, view = page(world)
    c.preview()
    world.loop.pump()
    assert view.statuses[-1].startswith(strings.AN_PREVIEW_FAILED.split("{")[0])


def test_preview_without_animation_runs_nothing(world):
    c, view = page(world)
    c.choose_style("none")
    world.loop.pump()
    c.preview()
    world.loop.pump()
    assert world.calls() == []
    assert view.statuses[-1] == strings.MA_PREVIEW_NONE


def test_missing_tool_shows_an_error_not_a_crash(tmp_path):
    loop = Loop()
    backend = ma.Backend(loop.workers, tmp_path / "nowhere", dispatch=loop.queue.put)
    view = FakeView()
    mctl.Controller(backend, History(tmp_path / "h.jsonl"), view).refresh()
    assert view.setup[0] == "error"
    assert view.state == {}
    loop.workers.stop_all(2)


def test_preview_right_after_a_choice_shows_the_new_style(world):
    c, _view = page(world)
    c.choose_style("slide")   # still queued when Look is pressed
    c.preview()
    world.loop.pump()
    assert world.calls() == ["preview slide normal"]


def test_broken_anim_module_is_an_error_not_a_crash(world):
    (world.tool / "anim.py").write_text("STYLES = undefined_name\n")
    backend = ma.Backend(world.loop.workers, world.tool, dispatch=world.loop.queue.put)
    assert backend.state()[0] == "error"
    (world.tool / "anim.py").write_text("STYLES = {}\n")
    backend = ma.Backend(world.loop.workers, world.tool, dispatch=world.loop.queue.put)
    assert backend.state()[0] == "error"
