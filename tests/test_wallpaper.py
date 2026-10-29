"""Wallpaper and theme: backend, page logic and History, isolated (plan section 4).

wallpaper.sh, wallpaper-theme and magick are stubs (step3_env.py); no GTK.
"""

import hashlib
import os
import subprocess

import pytest
from conftest import ROOT, load_json
from step3_env import World

from settings_hub import strings
from settings_hub.backends import wallpaper as wp
from settings_hub.controllers import wallpaper as ctl


class FakeView:
    def __init__(self) -> None:
        self.setup = None
        self.images = []
        self.current = None
        self.random: dict = {}
        self.theme = []
        self.thumbs = []
        self.statuses = []

    def show_setup(self, state, detail):
        self.setup = (state, detail)

    def show_images(self, images):
        self.images = list(images)

    def show_current(self, target, current, random):
        self.current = (target, dict(current), dict(random))

    def show_random(self, target, enabled):
        self.random[target] = enabled

    def show_theme(self, available, mode):
        self.theme.append((available, mode))

    def thumb_ready(self, image, made):
        self.thumbs.append((image.name, made))

    def status(self, text):
        self.statuses.append(text)


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    yield w
    w.close()


def page(w: World):
    view = FakeView()
    c = ctl.Controller(w.wallpaper, w.history, view)
    c.refresh()
    w.loop.pump()
    return c, view


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start(w: World, desktop="amber.jpg", lock="forest.png", sddm="amber.jpg", random="off"):
    """A known state, as wallpaper.sh would have left it."""
    for target, name in (("desktop", desktop), ("lock", lock), ("sddm", sddm)):
        (w.state / f"{target}.path").write_text(str(w.library / name) + "\n")
    (w.state / "random.conf").write_text(
        "".join(f"{t}={random if t == 'desktop' else 'off'}\n" for t in wp.TARGETS))


# ---- library and thumbnails ------------------------------------------------------

def test_library_lists_pictures_like_the_picker(world):
    names = [i.name for i in world.wallpaper.images()]
    assert names == sorted(["amber.jpg", "blue-dusk.jpg", "forest.png", "graphite.webp",
                            "plasma.jpg"])  # readme.txt is not a picture


def test_thumbnail_key_is_the_pickers(world):
    """The very pipeline from wallpaper-picker.sh's thumb_path, run in sh."""
    image = world.image("forest.png")
    key = subprocess.run(
        ["sh", "-c", 'printf "%s|%s" "$1" "$(stat -c %Y "$1")" | sha1sum | cut -c1-16', "_",
         image.path], capture_output=True, text=True, check=True).stdout.strip()
    assert image.thumb == world.thumbs / f"{key}.jpg"


def test_missing_thumbnails_are_made_by_magick_on_a_worker(world):
    # One thumbnail already in the cache: magick is not run for it.
    have = world.image("amber.jpg")
    world.thumbs.mkdir(parents=True)
    have.thumb.write_text("cached")
    _c, view = page(world)
    made = world.calls_of("magick")
    assert len(made) == 4 and not [m for m in made if have.path in m]
    assert all("-auto-orient -thumbnail 480x -strip -quality 85" in m for m in made)
    assert sorted(n for n, ok in view.thumbs if ok) == [
        "blue-dusk.jpg", "forest.png", "graphite.webp", "plasma.jpg"]
    for image in world.wallpaper.images():
        assert image.thumb.read_text()  # made where the picker looks for it
    assert have.thumb.read_text() == "cached"
    assert not [p for p in world.thumbs.iterdir() if p.name.startswith(".")]  # no temp files
    assert strings.WP_THUMBS.format(n=4) in view.statuses


def test_failed_thumbnail_leaves_nothing_behind(world):
    (world.root / "fail-magick").write_text("")
    _c, view = page(world)
    assert view.thumbs and not any(ok for _n, ok in view.thumbs)
    assert list(world.thumbs.iterdir()) == []


def test_unchanged_library_does_not_rebuild_the_grid(world):
    c, view = page(world)
    first = view.images
    view.images = None
    c.refresh()
    world.loop.pump()
    assert view.images is None and first


# ---- choosing a picture ----------------------------------------------------------

@pytest.mark.parametrize("target", ["desktop", "lock", "sddm"])
def test_choosing_a_picture_calls_the_script_and_undo_restores(world, target):
    start(world)
    before = {t: sha(world.state / f"{t}.path") for t in wp.TARGETS}
    c, view = page(world)
    c.set_target(target)
    old = (world.state / f"{target}.path").read_text().strip()
    image = world.image("blue-dusk.jpg")
    c.choose(image)
    world.loop.pump()
    assert world.calls_of("wallpaper.sh")[-1] == f"wallpaper.sh set {target} {image.path}"
    assert (world.state / f"{target}.path").read_text().strip() == image.real
    (group,) = world.history.groups()
    assert [(e.backend, e.key, e.before, e.after) for e in group.entries] == [
        ("wallpaper", f"wallpaper.{target}", old, image.real)]
    assert group.label == strings.WP_LABEL_SET.format(target=strings.WP_TARGET_NAMES[target])
    assert view.current[1][target] == image.real
    assert strings.WP_SET_DONE.format(target=strings.WP_TARGETS[target],
                                      name=image.name) in view.statuses

    plan = world.history.plan_undo_last()
    assert not plan.flagged
    world.history.execute(plan)
    world.loop.pump()
    assert world.calls_of("wallpaper.sh")[-1] == f"wallpaper.sh set {target} {old}"
    assert {t: sha(world.state / f"{t}.path") for t in wp.TARGETS} == before


def test_all_three_is_one_command_and_one_group(world):
    start(world)
    c, _view = page(world)
    c.set_target("all")
    image = world.image("graphite.webp")
    c.choose(image)
    world.loop.pump()
    assert world.calls_of("wallpaper.sh") == [f"wallpaper.sh set all {image.path}"]
    (group,) = world.history.groups()
    assert sorted(e.key for e in group.entries) == [
        "wallpaper.desktop", "wallpaper.lock", "wallpaper.sddm"]
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    assert world.wallpaper.current() == {
        "desktop": str(world.library / "amber.jpg"), "lock": str(world.library / "forest.png"),
        "sddm": str(world.library / "amber.jpg")}


def test_choosing_switches_random_off_and_the_group_says_so(world):
    start(world, random="on")
    c, _view = page(world)
    image = world.image("forest.png")
    c.choose(image)
    world.loop.pump()
    (group,) = world.history.groups()
    assert {e.key: (e.before, e.after) for e in group.entries} == {
        "wallpaper.desktop": (str(world.library / "amber.jpg"), image.real),
        "random.desktop": ("on", "off")}


def test_a_failing_script_is_reported_and_nothing_is_logged(world):
    start(world)
    (world.root / "fail-set").write_text("")
    c, view = page(world)
    c.choose(world.image("forest.png"))
    world.loop.pump()
    assert view.statuses[-1] == strings.WP_FAILED.format(error="awww failed")
    assert world.history.groups() == []


def test_marked_picture_follows_the_target(world):
    start(world)
    current = world.wallpaper.current()
    amber, forest = world.image("amber.jpg"), world.image("forest.png")
    assert ctl.marked("desktop", amber, current) and not ctl.marked("desktop", forest, current)
    assert ctl.marked("lock", forest, current)
    assert not ctl.marked("all", amber, current)  # lock shows something else
    (world.state / "lock.path").write_text(amber.real + "\n")
    assert ctl.marked("all", amber, world.wallpaper.current())


# ---- random wallpapers ------------------------------------------------------------

def test_random_on_and_undo(world):
    start(world)
    h_random, h_path = sha(world.state / "random.conf"), sha(world.state / "lock.path")
    c, view = page(world)
    c.random_toggled("lock", True)
    world.loop.pump()
    assert world.calls_of("wallpaper.sh")[-1] == "wallpaper.sh random lock on"
    assert world.wallpaper.random()["lock"] is True and view.random["lock"] is True
    (group,) = world.history.groups()
    assert {e.key for e in group.entries} == {"random.lock", "wallpaper.lock"}
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    # The picture first (set turns random off), then random off: both files as before.
    assert world.calls_of("wallpaper.sh")[-2:] == [
        f"wallpaper.sh set lock {world.library / 'forest.png'}", "wallpaper.sh random lock off"]
    assert sha(world.state / "random.conf") == h_random
    assert sha(world.state / "lock.path") == h_path


def test_switch_echo_does_nothing(world):
    start(world)
    c, _view = page(world)
    c.random_toggled("desktop", False)  # already off: the widget echoed it
    world.loop.pump()
    assert world.calls_of("wallpaper.sh") == []


def test_reread_keeps_a_queued_switch(world):
    start(world)
    c, view = page(world)
    c.random_toggled("sddm", True)
    view.random["sddm"] = True  # what the user sees
    c._show_state()  # a re-read while the command is still queued or running
    assert view.random["sddm"] is True
    world.loop.pump()
    assert view.random["sddm"] is True


# ---- theme -------------------------------------------------------------------------

def test_theme_mode_calls_wallpaper_theme_and_undo(world):
    c, view = page(world)
    assert view.theme[-1] == (True, "off")  # parsed from the real status format
    c.theme_chosen("vivid")
    world.loop.pump()
    assert "wallpaper-theme mode vivid" in world.calls_of("wallpaper-theme")
    assert view.theme[-1] == (True, "vivid")
    (group,) = world.history.groups()
    assert [(e.backend, e.key, e.before, e.after) for e in group.entries] == [
        ("theme", "theme.mode", "off", "vivid")]
    world.history.execute(world.history.plan_undo_last())
    world.loop.pump()
    modes = [c for c in world.calls_of("wallpaper-theme") if " mode " in c]
    assert modes == ["wallpaper-theme mode vivid", "wallpaper-theme mode off"]
    assert (world.root / "theme-mode").read_text().strip() == "off"


def test_parse_mode():
    status = (ROOT / "tests" / "fixtures" / "wallpaper_theme_status.txt").read_text()
    for mode in wp.MODES:
        assert wp.parse_mode(status.replace("MODE", mode)) == mode
    assert wp.parse_mode("") is None
    assert wp.parse_mode(status.replace("MODE", "rainbow")) is None


def test_without_wallpaper_theme_the_row_is_off(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, theme=False)
    try:
        _c, view = page(w)
        assert view.theme == [(False, None)]
        assert w.calls_of("wallpaper-theme") == []
        with pytest.raises(RuntimeError):
            w.history.applier("theme").apply({"theme.mode": "vivid"})
    finally:
        w.close()


def test_without_the_script_the_page_says_so(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, wallpaper_script=False)
    try:
        _c, view = page(w)
        assert view.setup == ("missing", str(w.script))
    finally:
        w.close()


# ---- isolation, labels, search ---------------------------------------------------

def test_isolation_refuses_real_programs(world):
    with pytest.raises(AssertionError, match="real program"):
        wp.subprocess.run(["/usr/bin/true"])
    with pytest.raises(AssertionError, match="real program"):
        wp.subprocess.run(["true"])
    assert str(world.wallpaper.paths.script).startswith(str(world.root))
    assert str(world.wallpaper.paths.thumbs).startswith(str(world.root))
    assert "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ


def test_labels_are_russian():
    expected = load_json("labels_ru.json")
    assert strings.PAGES["wallpaper"]["title"] == expected["page_wallpaper"]
    assert set(strings.WP_TARGETS) == {*wp.TARGETS, wp.ALL}
    assert set(strings.WP_THEME_MODES) == set(wp.MODES)


def test_every_searchable_row_is_registered_by_the_page():
    import re

    source = (ROOT / "settings_hub" / "pages" / "wallpaper.py").read_text()
    assert set(strings.WP_ROWS) <= set(re.findall(r'row_id="([a-z-]+)"', source))
