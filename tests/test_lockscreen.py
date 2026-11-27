"""The lock screen: options, the config they give, apply/undo/restore. No GTK, no hyprlock."""

import itertools
import json
from pathlib import Path

import pytest

from settings_hub import strings
from settings_hub.backends import lockscreen as lk
from settings_hub.controllers import lockscreen as ctl
from settings_hub.history import History


class Now:
    def submit(self, _name, fn, on_done=None, key=None):
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        if on_done:
            on_done(result, error)


class Later:
    def __init__(self):
        self.jobs = []

    def submit(self, _name, fn, on_done=None, key=None):
        self.jobs = [j for j in self.jobs if j[0] != key or key is None] + [(key, fn, on_done)]

    def run(self):
        while self.jobs:
            _key, fn, on_done = self.jobs.pop(0)
            try:
                result, error = fn(), None
            except Exception as exc:  # noqa: BLE001
                result, error = None, exc
            if on_done:
                on_done(result, error)


class View:
    def __init__(self):
        self.shown, self.pictures, self.said = [], [], []

    def show_lock(self, info, options):
        self.shown.append((info, options))

    def show_preview(self, path, error):
        self.pictures.append((path, error))

    def status(self, text):
        self.said.append(text)


HAND = """# made by hand
source = ~/.config/hypr/colors.conf
source = /x/.local/state/wallpaper-theme/hyprlock.conf  # wallpaper-theme

input-field {
    monitor =
    size = 300, 50
}
"""


@pytest.fixture
def home(tmp_path):
    hypr = tmp_path / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "colors.conf").write_text(
        "$font = JetBrainsMono Nerd Font\n$c_white = rgba(255,255,255,1)\n")
    conf = hypr / "hyprlock.conf"
    conf.write_text(HAND)
    conf.chmod(0o600)
    return tmp_path


def backend(home):
    return lk.Backend(Now(), home=home)


def blocks_balanced(text):
    return text.count("{") == text.count("}")


# ---- options --------------------------------------------------------------------

@pytest.mark.parametrize(("key", "value"), [
    ("preset", "fancy"), ("clock_format", "%H'; rm -rf ~; '"), ("date_format", "$(id)"),
    ("font", 'Evil"\nsource = /tmp/x'), ("font", "x" * 61), ("clock_size", 300),
    ("clock_size", True), ("blur", -1), ("dim", 10), ("text_size", "12"), ("clock", 1),
])
def test_bad_options_fall_back(key, value):
    assert getattr(lk.clean({key: value}), key) == getattr(lk.DEFAULTS, key)


def test_good_options_and_unknown_keys():
    opts = lk.clean({"preset": "corner", "font": "Onest", "clock_size": 60, "battery": True,
                     "evil": "x"})
    assert (opts.preset, opts.font, opts.clock_size, opts.battery) == ("corner", "Onest", 60, True)
    assert lk.clean("not a dict") == lk.Options()


# ---- the config ---------------------------------------------------------------------

def test_every_combination_keeps_one_password_field(home):
    paths = lk.Paths(home)
    for preset in lk.PRESETS:
        for flags in itertools.product((False, True), repeat=len(lk.PARTS)):
            opts = lk.Options(preset=preset, **dict(zip(lk.PARTS, flags, strict=True)))
            text = lk.render(opts, paths, HAND)
            assert text.startswith(lk.MARK)
            assert text.count("input-field {") == 1 and blocks_balanced(text)
            assert ("poweroff" in text) == opts.power
            assert ("lock-status-cpu.sh" in text) == opts.stats
            assert ("lock-status-wifi.sh" in text) == opts.wifi


def test_default_is_the_hand_made_dock(home):
    text = lk.render(lk.Options(), lk.Paths(home))
    assert "$TIME" in text and "size = 820, 80" in text
    assert "position = 58, 59" in text and "position = 369, 59" in text  # field, button
    assert "position = -364, 62" in text and "position = -258, 62" in text  # CPU, TEMP
    assert "font_family = JetBrainsMono Nerd Font Propo" in text  # the icon font
    assert "blur_passes = 0" in text and "brightness = 0.72" in text
    assert strings.LOCK_CONF_PLACEHOLDER in text


def test_formats_and_font_go_in_as_chosen(home):
    opts = lk.Options(clock_format="%H:%M:%S", date_format="%d.%m.%Y", font="Onest", blur=2,
                      dim=50)
    text = lk.render(opts, lk.Paths(home))
    assert "date '+%H:%M:%S'" in text and "date '+%d.%m.%Y'" in text
    assert "font_family = Onest" in text and "$TIME" not in text
    assert "blur_passes = 2" in text and "brightness = 0.50" in text


def test_the_wallpaper_theme_hook_is_kept(home):
    text = lk.render(lk.Options(), lk.Paths(home), HAND)
    lines = text.splitlines()
    colors = lines.index("source = ~/.config/hypr/colors.conf")
    assert lines[colors + 1].endswith("# wallpaper-theme")
    assert "wallpaper-theme" not in lk.render(lk.Options(), lk.Paths(home), "")


def test_sizes_move_the_date_off_the_clock(home):
    for size in (40, 112, 160):
        lay = lk.placed(lk.Options(preset="center", clock_size=size))
        assert lay.clock.y - lay.date.y >= size * 1.7 / 2  # under the clock's box
        assert lay.input.y < lay.date.y


def test_check_refuses():
    with pytest.raises(ValueError):
        lk.check("background {\n}\n")
    with pytest.raises(ValueError):
        lk.check("input-field {\n}\ninput-field {\n}\n")


# ---- the file ---------------------------------------------------------------------

def test_first_apply_backs_up_the_hand_made_file(home):
    b = backend(home)
    before, after = b.apply(lk.Options())
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    assert before == HAND and conf.read_text() == after and lk.is_ours(after)
    assert oct(conf.stat().st_mode & 0o777) == "0o600"
    backups = list((home / ".config" / "hypr" / "backups").glob(
        "*-settings-hub-lock/hyprlock.conf"))
    assert len(backups) == 1 and backups[0].read_text() == HAND
    b.apply(lk.Options(preset="corner"))  # ours now: no second copy
    assert len(list((home / ".config" / "hypr" / "backups").iterdir())) == 1


def test_apply_writes_through_a_symlink(home, tmp_path):
    real = tmp_path / "dotfiles" / "hyprlock.conf"
    real.parent.mkdir()
    real.write_text(HAND)
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    conf.unlink()
    conf.symlink_to(real)
    backend(home).apply(lk.Options())
    assert conf.is_symlink() and lk.is_ours(real.read_text())


def test_undo_and_restore_give_back_the_hand_made_file(home):
    b = backend(home)
    history = History()
    lk.register(history, b)
    view = View()
    c = ctl.Controller(b, history, view, home / "cache")
    c.refresh()
    c.set("preset", "minimal")
    assert (home / ".config" / "hypr" / "hyprlock.conf").read_text() == HAND  # a draft only
    assert json.loads(b.paths.options.read_text())["preset"] == "minimal"
    c.apply()
    assert len(history.groups()) == 1 and view.said[-1] == strings.LOCK_APPLIED
    history.execute(history.plan_undo_last())
    assert (home / ".config" / "hypr" / "hyprlock.conf").read_text() == HAND
    c.apply()
    c.restore()
    assert (home / ".config" / "hypr" / "hyprlock.conf").read_text() == HAND
    assert view.said[-1] == strings.LOCK_RESTORED
    c.apply()
    c.apply()
    assert view.said[-1] == strings.LOCK_ALREADY


def test_undo_never_writes_a_lock_screen_without_a_field(home):
    b = backend(home)
    with pytest.raises(ValueError):
        b.write_text("background {\n}\n")
    with pytest.raises(ValueError):
        b.write_text("")
    assert (home / ".config" / "hypr" / "hyprlock.conf").read_text() == HAND


def test_probe(home):
    b = backend(home)
    info = b.probe()
    assert info.found and not info.ours and not info.applied and info.backup == ""
    assert info.theme_font == "JetBrainsMono Nerd Font"
    b.apply(info.options)
    info = b.probe()
    assert info.ours and info.applied and info.backup


def test_a_bad_value_from_the_page_is_refused(home):
    view = View()
    c = ctl.Controller(backend(home), History(), view, home / "cache")
    c.refresh()
    c.set("clock_format", "%s; reboot")
    assert view.said[-1] == strings.LOCK_BAD_VALUE
    assert c.options.clock_format == lk.DEFAULTS.clock_format


# ---- the preview -------------------------------------------------------------------

def test_preview_runs_the_simulator(home):
    b = backend(home)
    with pytest.raises(RuntimeError):
        b.preview(lk.Options(), home / "cache" / "p.png")  # not installed
    sim = b.paths.simulator
    sim.parent.mkdir(parents=True)
    sim.write_text("import sys, os\nopen(sys.argv[2], 'wb').write(b'png')\n"
                   "open(os.path.join(os.environ['TMPDIR'], 'tmpdir-ok'), 'w').close()\n")
    out = b.preview(lk.Options(), home / "cache" / "p.png")
    assert out.read_bytes() == b"png"
    assert (home / "cache" / "tmpdir-ok").exists()  # its scratch files stay in our folder
    assert lk.is_ours((home / "cache" / "p.conf").read_text())
    sim.write_text("import sys\nsys.exit('boom')\n")
    with pytest.raises(RuntimeError, match="boom"):
        b.preview(lk.Options(), home / "cache" / "q.png")


def test_no_simulator_says_so(home):
    view = View()
    c = ctl.Controller(backend(home), History(), view, home / "cache")
    c.refresh()
    assert view.pictures[-1] == (None, strings.LOCK_NO_SIMULATOR)


def test_nothing_is_started_but_the_simulator():
    """hyprlock really locks the screen: the module never names it as a command."""
    text = Path(lk.__file__).read_text(encoding="utf-8")
    assert '"hyprlock"' not in text and "'hyprlock'" not in text


# ---- what the reviews found ---------------------------------------------------------

def test_a_read_started_before_a_change_keeps_the_change(home):
    b = lk.Backend(Later(), home=home)
    view = View()
    c = ctl.Controller(b, History(), view, home / "cache")
    c.refresh()
    b.workers.run()  # the page is shown
    c.refresh()  # queued again (window shown): reads the old options
    c.set("preset", "corner")  # chosen before the read comes back
    b.workers.run()
    assert c.options.preset == "corner" and view.shown[-1][1].preset == "corner"
    assert json.loads(b.paths.options.read_text())["preset"] == "corner"


def test_a_refused_value_puts_the_control_back(home):
    view = View()
    c = ctl.Controller(backend(home), History(), view, home / "cache")
    c.refresh()
    shown = len(view.shown)
    c.set("font", "Foo (Bar)")
    assert len(view.shown) == shown + 1 and view.shown[-1][1].font == ""


def test_every_new_hand_made_file_gets_its_own_copy(home):
    b = backend(home)
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    b.apply(lk.Options())
    second = HAND.replace("300, 50", "320, 50")
    conf.write_text(second)  # hand-made again
    b.apply(lk.Options())
    copies = sorted(p.read_text() for p in (home / ".config" / "hypr" / "backups").glob(
        "*-settings-hub-lock/hyprlock.conf"))
    assert copies == sorted([HAND, second])
    assert b.backup_path().read_text() == second  # "Restore" gives the newest
    b.apply(lk.Options(preset="corner"))  # ours: no third copy
    assert len(list((home / ".config" / "hypr" / "backups").iterdir())) == 2


def test_a_hand_edit_of_a_generated_file_is_copied_too(home):
    b = backend(home)
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    b.apply(lk.Options())
    edited = conf.read_text().replace("blur_passes = 0", "blur_passes = 3")
    conf.write_text(edited)  # the first line still says it is ours
    b.apply(lk.Options(preset="minimal"))
    assert b._newest("edit").read_text() == edited and b.backup_path().read_text() == HAND


def test_no_colors_no_apply(home):
    (home / ".config" / "hypr" / "colors.conf").unlink()
    b = backend(home)
    view = View()
    c = ctl.Controller(b, History(), view, home / "cache")
    c.refresh()
    assert view.shown[-1][0].colors is False
    c.apply()
    assert view.said[-1].startswith(strings.LOCK_APPLY_FAILED.split("{")[0])
    assert (home / ".config" / "hypr" / "hyprlock.conf").read_text() == HAND


@pytest.mark.parametrize("text", [
    "# input-field {\nbackground {\n}\n",  # only in a comment
    "input-field {\n    size = 0, 0\n}\n",  # too small to see
    "input-field {\n}\ninput-field {\n}\n",  # two
])
def test_check_reads_lines_not_text(text):
    with pytest.raises(ValueError):
        lk.check(text)


def test_check_takes_a_hand_made_spelling():
    lk.check("input-field{\n    size = 300, 50\n}\n# input-field { (an old one)\n")


def test_center_without_date_keeps_the_field_off_the_clock():
    for size in (40, 112, 160):
        lay = lk.placed(lk.Options(preset="center", date=False, clock_size=size))
        clock_bottom = lay.clock.y - size * 1.7 / 2
        assert lay.input.y + lay.input_size[1] / 2 < clock_bottom


def test_corner_caps_the_clock(home):
    text = lk.render(lk.Options(preset="corner", clock_size=160), lk.Paths(home))
    assert "font_size = 104" in text and "font_size = 160" not in text


def test_preview_is_written_whole(home):
    b = backend(home)
    sim = b.paths.simulator
    sim.parent.mkdir(parents=True)
    sim.write_text("import sys\nopen(sys.argv[2], 'wb').write(b'png')\n")
    out = b.preview(lk.Options(), home / "cache" / "p.png")
    assert out.read_bytes() == b"png" and not (home / "cache" / "p.part.png").exists()


def test_showing_the_page_again_does_not_redraw_the_same_picture(home):
    b = backend(home)
    sim = b.paths.simulator
    sim.parent.mkdir(parents=True)
    sim.write_text("import sys\nopen(sys.argv[2], 'wb').write(b'png')\n")
    view = View()
    c = ctl.Controller(b, History(), view, home / "cache")
    c.refresh()
    c.refresh()
    assert len(view.pictures) == 1


def test_a_choice_before_the_first_read_is_not_laid_over_defaults(home):
    b = lk.Backend(Later(), home=home)
    b.save_options(lk.Options(preset="minimal"))
    c = ctl.Controller(b, History(), View(), home / "cache")
    c.refresh()
    c.set("clock", False)  # the page has not shown the real choices yet
    b.workers.run()
    assert c.options.preset == "minimal" and c.options.clock is True
    assert json.loads(b.paths.options.read_text())["preset"] == "minimal"


@pytest.mark.parametrize("size", ["1%, 1%", "0.5, 0.5", "-400, -50", "$s", "10, 300", "2, 50%"])
def test_check_refuses_odd_field_sizes(size):
    with pytest.raises(ValueError):
        lk.check(f"input-field {{\n    size = {size}\n}}\n")


def test_check_needs_the_block_closed():
    with pytest.raises(ValueError):
        lk.check("input-field {\n    size = 300, 50\n")
    lk.check("input-field {\n    size = 25%, 5%\n}\n")


def test_an_edited_generated_file_is_kept_apart_from_the_hand_made_copy(home):
    b = backend(home)
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    b.apply(lk.Options())
    assert b.probe().edited is False
    conf.write_text(conf.read_text().replace("blur_passes = 0", "blur_passes = 3"))
    assert b.probe().edited is True
    b.apply(lk.Options(preset="minimal"))
    assert b.backup_path().read_text() == HAND  # "Restore" is still the Dock
    edits = list((home / ".config" / "hypr" / "backups").glob(
        "*-settings-hub-edit/hyprlock.conf"))
    assert len(edits) == 1 and "blur_passes = 3" in edits[0].read_text()


def test_a_dangling_backup_link_is_skipped(home):
    b = backend(home)
    b.apply(lk.Options())
    broken = home / ".config" / "hypr" / "backups" / "2099-01-01-settings-hub-lock"
    broken.mkdir()
    (broken / "hyprlock.conf").symlink_to(home / "nowhere")
    assert b.backup_path().read_text() == HAND
    b.probe()


def test_a_backup_is_as_private_as_the_file(home):
    conf = home / ".config" / "hypr" / "hyprlock.conf"
    conf.chmod(0o600)
    b = backend(home)
    b.apply(lk.Options())
    assert b.backup_path().stat().st_mode & 0o777 == 0o600
