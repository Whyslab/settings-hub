"""Animations: the live rofi_hub module, page logic and History, isolated.

The module is a copy (fixtures, or the installed one for `live` tests) in a
temporary HOME; it writes animations.conf/.lua there, never into the real
~/.config/hypr. hyprctl and anim-preview.sh are stubs (step3_env.py).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest
from conftest import ROOT, load_json
from step3_env import World

from settings_hub import loader, strings
from settings_hub.controllers import animations as ctl

CATEGORIES = ("open", "close", "workspaces", "layers")


class FakeView:
    def __init__(self) -> None:
        self.setup = None
        self.state: dict = {}
        self.events: list[str] = []
        self.statuses: list[str] = []

    def show_setup(self, state, detail):
        self.setup = (state, detail)

    def show_state(self, state, keys):
        for key in keys:
            self.state[key] = state[key]

    def hide_window(self):
        self.events.append("hide")

    def show_window(self):
        self.events.append("show")

    def status(self, text):
        self.statuses.append(text)


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.close()


def page(w: World):
    view = FakeView()
    c = ctl.Controller(w.animations, w.history, view)
    c.refresh()
    return c, view


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_conf(w: World, preset_id: str, tuning: dict) -> str:
    """What the module itself writes for this data, computed in a separate,
    plain Python process that imports the copy as `rofi_hub` (not via our loader)."""
    code = (
        "import json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from rofi_hub import hyprconf\n"
        "from rofi_hub.sections import animations as a\n"
        "print(hyprconf.render_conf(a.compose(a.get(sys.argv[2]), json.loads(sys.argv[3]))),"
        " end='')\n")
    env = dict(os.environ, HOME=str(w.home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-c", code, str(w.rofi), preset_id,
                           json.dumps(tuning)], env=env, capture_output=True, text=True,
                          check=True).stdout


def saved_tuning(w: World) -> dict:
    return json.loads((w.cfg / "animation-tuning.json").read_text())


# ---- language and data ----------------------------------------------------------

def test_module_speaks_russian_whatever_the_locale(world):
    expected = load_json("labels_ru.json")
    assert os.environ["LANG"] == "C"
    b = world.animations
    assert b.t("sec_animations") == expected["sec_animations"]
    assert b.preset_name("dissolve") == expected["preset_dissolve"]
    assert {p.id: p.name for p in b.presets()}["dissolve"] == expected["preset_dissolve"]
    assert b.category_title("open") == expected["category_open"]
    assert b.speed_title("fast") == expected["speed_fast"]
    assert strings.PAGES["animations"]["title"] == expected["page_animations"]


def test_module_is_loaded_privately_and_writes_into_tmp(world):
    m = world.animations.mod
    assert m.__name__ == f"{loader.ROFI_PACKAGE}.rofi_hub.sections.animations"
    assert "rofi_hub" not in sys.modules
    assert str(m.hyprconf.GENERATED_CONF).startswith(str(world.root))
    assert str(m.TUNING_FILE).startswith(str(world.root))
    assert m.notify == world.animations.notes.append  # no notify-send
    assert not list(world.rofi.rglob("__pycache__"))


def test_reads_the_saved_state(world):
    _c, view = page(world)
    assert view.state["preset"] == "dissolve"
    assert view.state["override.close"] == "mosaic" and view.state["override.open"] == "zoom"
    assert view.state["override.layers"] is None
    assert view.state["speed.layers"] == "slow" and view.state["speed.open"] == "normal"


def test_preview_images_come_from_the_cache(world):
    previews = world.home / ".cache" / "rofi-launcher" / "anim-previews"
    previews.mkdir(parents=True)
    (previews / "slide.png").write_bytes(b"png")
    images = {p.id: p.image for p in world.animations.presets()}
    assert images["slide"] == previews / "slide.png"
    assert images["dissolve"] is None  # no picture: the page draws a placeholder


# ---- applying -------------------------------------------------------------------

def test_preset_writes_what_compose_gives_and_resets_the_categories(world):
    c, view = page(world)
    c.choose_preset("slide")
    world.loop.pump()
    conf = world.hypr / "animations.conf"
    assert conf.read_text() == expected_conf(world, "slide", {"overrides": {}, "speed": {}})
    assert (world.hypr / "animations.lua").is_file()
    assert (world.cfg / "animation-preset").read_text() == "slide\n"
    assert saved_tuning(world) == {"overrides": {}, "speed": {}}
    assert world.calls_of("hyprctl") == ["hyprctl reload"]
    assert world.calls_of("notify-send") == []
    (group,) = world.history.groups()
    assert {e.key: (e.before, e.after) for e in group.entries} == {
        "preset": ("dissolve", "slide"), "override.close": ("mosaic", None),
        "override.open": ("zoom", None), "speed.layers": ("slow", "normal")}
    assert group.label == strings.AN_LABEL_PRESET_NAMED.format(
        name=world.animations.preset_name("slide"))  # one line, not one per category
    assert view.state["preset"] == "slide"
    assert world.animations.t("anim_applied", name=world.animations.preset_name("slide")) \
        in view.statuses


@pytest.mark.parametrize("category", CATEGORIES)
def test_variant_writes_what_compose_gives(world, category):
    c, _view = page(world)
    variant = world.animations.variants(category)[0].id
    c.choose_variant(category, variant)
    world.loop.pump()
    tuning = {"overrides": {"close": "mosaic", "open": "zoom", category: variant},
              "speed": {"layers": "slow"}}
    assert (world.hypr / "animations.conf").read_text() == expected_conf(
        world, "dissolve", tuning)
    assert saved_tuning(world)["overrides"][category] == variant
    (group,) = world.history.groups()
    assert [e.key for e in group.entries] == [f"override.{category}"]


@pytest.mark.parametrize("category", CATEGORIES)
def test_speed_writes_what_compose_gives(world, category):
    c, _view = page(world)
    c.choose_speed(category, "fast")
    world.loop.pump()
    tuning = {"overrides": {"close": "mosaic", "open": "zoom"},
              "speed": {"layers": "slow", category: "fast"}}
    assert (world.hypr / "animations.conf").read_text() == expected_conf(
        world, "dissolve", tuning)


def test_undo_returns_the_files_to_their_sha256(world):
    files = [world.cfg / "animation-preset", world.cfg / "animation-tuning.json"]
    c, _view = page(world)
    c.choose_variant("close", "fade")  # a first write: animations.conf now exists
    world.loop.pump()
    hashes = {p: sha(p) for p in [*files, world.hypr / "animations.conf"]}
    c.choose_speed("open", "slow")
    world.loop.pump()
    c.choose_variant("close", "dust")
    world.loop.pump()
    c.choose_preset("bounce")
    world.loop.pump()
    assert len(world.history.groups()) == 4
    second = world.history.groups()[0].id
    plan = world.history.plan_return_to(second)
    assert not plan.flagged
    reloads = len(world.calls_of("hyprctl"))
    world.history.execute(plan)
    world.loop.pump()
    assert {p: sha(p) for p in hashes} == hashes
    assert len(world.calls_of("hyprctl")) == reloads + 1  # one write, one reload


def test_ctrl_z_after_a_preset_brings_every_category_back(world):
    c, view = page(world)
    before = world.animations.read_all()
    c.choose_preset("cinema")
    world.loop.pump()
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert world.animations.read_all() == before
    assert view.state == before  # the page re-read after the undo


def test_same_value_from_a_widget_does_nothing(world):
    c, _view = page(world)
    c.choose_variant("open", "zoom")
    c.choose_speed("layers", "slow")
    world.loop.pump()
    assert world.calls_of("hyprctl") == [] and world.history.groups() == []


def test_menu_dissolve_without_window_dissolve_is_refused(world):
    c, view = page(world)
    c.choose_variant("close", "fade")  # windows no longer dissolve
    world.loop.pump()
    c.choose_variant("layers", "dissolve")
    world.loop.pump()
    assert saved_tuning(world)["overrides"].get("layers") is None
    assert view.statuses[-1] == strings.AN_FAILED.format(
        error=world.animations.t("anim_menu_dissolve_needs_windows"))
    assert len(world.history.groups()) == 1


def test_no_preset_saved_is_reported(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, animations=False)
    try:
        c, view = page(w)
        c.choose_variant("open", "fade")
        w.loop.pump()
        assert view.statuses[-1] == strings.AN_FAILED.format(error=w.animations.t(
            "anim_no_preset"))
        assert not (w.hypr / "animations.conf").exists()
    finally:
        w.close()


def test_broken_module_is_reported(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    try:
        (w.rofi / "rofi_hub" / "sections" / "animations.py").write_text("raise ImportError\n")
        _c, view = page(w)
        assert view.setup[0] == "error"
    finally:
        w.close()


# ---- live preview ---------------------------------------------------------------

def test_preview_hides_runs_the_script_without_reopen_and_shows_again(world):
    c, view = page(world)
    c.preview()
    world.loop.pump()
    c.preview("close")
    world.loop.pump()
    assert world.calls_of("anim-preview.sh") == [
        "anim-preview.sh dissolve", "anim-preview.sh cat close var mosaic"]
    assert world.calls_of("reopen") == ["reopen 0", "reopen 0"]
    assert view.events == ["hide", "show", "hide", "show"]
    assert world.calls_of("hyprctl") == [] and world.history.groups() == []


def test_preview_of_a_category_left_to_the_preset(world):
    c, _view = page(world)
    c.preview("layers")
    world.loop.pump()
    assert world.calls_of("anim-preview.sh") == ["anim-preview.sh cat layers var -"]


def test_failed_preview_still_shows_the_window(world):
    (world.rofi / "bin" / "anim-preview.sh").write_text("#!/bin/sh\necho broken >&2\nexit 3\n")
    c, view = page(world)
    c.preview()
    world.loop.pump()
    assert view.events == ["hide", "show"]
    assert view.statuses[-1] == strings.AN_PREVIEW_FAILED.format(error="broken")


# ---- module interface ------------------------------------------------------------

def test_module_functions_the_backend_uses(world):
    m = world.animations.mod
    for name in ("load_all", "get", "active_id", "_set_active", "load_tuning", "save_tuning",
                 "compose", "load_variants", "get_variant", "menu_dissolve_available",
                 "preview_path", "variant_preview_path", "_localized"):
        assert callable(getattr(m, name)), name
    assert callable(m.hyprconf.write)
    assert tuple(m.CATEGORIES) == CATEGORIES
    assert tuple(m.SPEED_ORDER) == ("fast", "normal", "slow")


def test_every_searchable_row_is_registered_by_the_page():
    import re

    source = (ROOT / "settings_hub" / "pages" / "animations.py").read_text()
    ids = set(re.findall(r'row_id="([a-z-]+)"', source)) | set(CATEGORIES)
    assert set(strings.AN_ROWS) <= ids


@pytest.mark.live
def test_installed_module_composes_the_same(tmp_path, monkeypatch):
    """On a copy of the installed hub: same data -> same animations.conf."""
    installed = loader.rofi_dir()  # read before HOME is replaced
    copy = tmp_path / "installed"
    ignore = shutil.ignore_patterns("__pycache__")
    for part in ("rofi_hub", "data"):
        shutil.copytree(installed / part, copy / part, ignore=ignore)
    w = World(tmp_path / "w", monkeypatch, rofi_source=copy)
    try:
        assert w.animations.t("sec_animations") == load_json("labels_ru.json")["sec_animations"]
        c, _view = page(w)
        c.choose_preset("dissolve")
        w.loop.pump()
        c.choose_variant("open", "fade")
        w.loop.pump()
        assert (w.hypr / "animations.conf").read_text() == expected_conf(
            w, "dissolve", {"overrides": {"open": "fade"}, "speed": {}})
        assert str(w.animations.mod.hyprconf.GENERATED_CONF).startswith(str(tmp_path))
    finally:
        w.close()
