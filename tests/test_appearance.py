"""Fonts, text scale, icons for GTK, the panel and kitty (all files in tmp_path)."""

import json

import pytest

from settings_hub import strings
from settings_hub.backends import appearance as ap
from settings_hub.controllers import appearance as ctl
from settings_hub.history import History


class GSettings:
    def __init__(self):
        self.values = {"font-name": "'Adwaita Sans 11'", "monospace-font-name": "'Adwaita Mono 11'",
                       "text-scaling-factor": "1.0", "icon-theme": "'zafiro-dark'"}
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["gsettings", "get"]:
            return 0, self.values[argv[3]] + "\n", ""
        if argv[:2] == ["gsettings", "set"]:
            self.values[argv[3]] = argv[4]
            return 0, "", ""
        return 127, "", "no"


class Now:
    def submit(self, _name, fn, on_done=None, key=None):
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        if on_done:
            on_done(result, error)


@pytest.fixture
def env(tmp_path):
    conf = tmp_path / "config"
    (conf / "gtk-3.0").mkdir(parents=True)
    (conf / "gtk-3.0" / "settings.ini").write_text(
        "[Settings]\ngtk-theme-name=Monochrome-Vivid\ngtk-font-name=Adwaita Sans 11\n")
    (conf / "kitty").mkdir()
    (conf / "kitty" / "kitty.conf").write_text("font_family JetBrainsMono Nerd Font\n"
                                               "font_size 12.0\ninclude theme.conf\n")
    (conf / "hyprpanel").mkdir()
    panel = conf / "hyprpanel" / "config.json"
    panel.write_text(json.dumps({"theme.font.name": "JetBrainsMono Nerd Font",
                                 "bar.clock.format": "%H:%M — время"}, ensure_ascii=False))
    panel.chmod(0o600)
    icons = tmp_path / "icons"
    for name, text in (("zafiro-dark", "[Icon Theme]\nDirectories=48x48/apps\n"),
                       ("Adwaita", "[Icon Theme]\nDirectories=scalable/apps\n"),
                       ("Bibata", "[Icon Theme]\nName=Bibata\n"),  # a cursor theme
                       ("Ghost", "[Icon Theme]\nDirectories=x\nHidden=true\n")):
        (icons / name).mkdir(parents=True)
        (icons / name / "index.theme").write_text(text)
    gs = GSettings()
    signals = []
    backend = ap.Backend(Now(), runner=gs, config=conf, icon_dirs=[icons],
                         signal_kitty=lambda: signals.append(1) or 1)
    return backend, gs, conf, signals


def test_probe_reads_every_place(env):
    backend, _gs, _conf, _ = env
    look = backend.probe()
    assert look.values == {ap.FONT: "Adwaita Sans 11", ap.MONO: "Adwaita Mono 11",
                           ap.SCALE: 1.0, ap.ICONS: "zafiro-dark",
                           ap.PANEL_FONT: "JetBrainsMono Nerd Font",
                           ap.KITTY_FONT: "JetBrainsMono Nerd Font 12"}
    assert look.icon_themes == ["Adwaita", "zafiro-dark"]  # no cursor-only, no hidden
    assert look.kitty and look.panel


def test_interface_font_goes_to_gsettings_and_both_settings_ini(env):
    backend, gs, conf, _ = env
    backend.set(ap.FONT, "Inter 10")
    assert gs.values["font-name"] == "'Inter 10'"
    gtk3 = (conf / "gtk-3.0" / "settings.ini").read_text()
    assert "gtk-font-name=Inter 10" in gtk3 and "gtk-theme-name=Monochrome-Vivid" in gtk3
    assert (conf / "gtk-4.0" / "settings.ini").read_text() == "[Settings]\ngtk-font-name=Inter 10\n"


def test_names_that_could_break_a_file_are_refused(env):
    backend, gs, _conf, _ = env
    for bad in ("Evil' 10", "two\nlines", "a" * 200, "", "x#y"):
        with pytest.raises(ValueError):
            backend.set(ap.FONT, bad)
    with pytest.raises(ValueError):
        backend.set(ap.ICONS, "../../etc")
    assert not any(c[1] == "set" for c in gs.calls)


def test_scale_is_clamped(env):
    backend, gs, _conf, _ = env
    backend.set(ap.SCALE, 5)
    assert gs.values["text-scaling-factor"] == "2.0"


def test_panel_font_keeps_the_rest_of_its_config_and_its_rights(env):
    backend, _gs, conf, _ = env
    backend.set(ap.PANEL_FONT, "Inter")
    path = conf / "hyprpanel" / "config.json"
    data = json.loads(path.read_text())
    assert data == {"theme.font.name": "Inter", "bar.clock.format": "%H:%M — время"}
    assert "время" in path.read_text()  # not \\u-escaped
    assert path.stat().st_mode & 0o777 == 0o600


def test_kitty_font_goes_into_its_own_file_included_once(env):
    backend, _gs, conf, signals = env
    backend.set(ap.KITTY_FONT, "Iosevka 13")
    backend.set(ap.KITTY_FONT, "Iosevka 14")
    kitty = (conf / "kitty" / "kitty.conf").read_text()
    assert kitty.count("include settings-hub-font.conf") == 1
    assert kitty.startswith("font_family JetBrainsMono Nerd Font\n")  # untouched above
    assert "font_family Iosevka\nfont_size 14.0" in (conf / "kitty" / ap.KITTY_FILE).read_text()
    assert backend.read([ap.KITTY_FONT]) == {ap.KITTY_FONT: "Iosevka 14"}
    assert signals == [1, 1]


def test_set_ini_adds_a_section_when_there_is_none():
    assert ap.set_ini("", {"a": "1"}) == "[Settings]\na=1\n"
    out = ap.set_ini("[Other]\nx=1\n[Settings]\nb=2\n[More]\n", {"b": "3", "c": "4"})
    assert out == "[Other]\nx=1\n[Settings]\nb=3\nc=4\n[More]\n"


class View:
    def __init__(self):
        self.statuses = []

    def show_look(self, look, pending):
        self.look = look

    def status(self, text):
        self.statuses.append(text)


def controller(env, tmp_path):
    backend = env[0]
    history = History(tmp_path / "h.jsonl")
    ap.register(history, backend)
    c = ctl.Controller(backend, history, View())
    c.refresh()
    return c, history


def test_a_font_change_is_undoable(env, tmp_path):
    c, history = controller(env, tmp_path)
    c.set(ap.FONT, "Inter 10")
    entry = history.groups()[-1].entries[0]
    assert (entry.key, entry.before, entry.after) == (ap.FONT, "Adwaita Sans 11", "Inter 10")
    history.execute(history.plan_undo_last())
    assert env[1].values["font-name"] == "'Adwaita Sans 11'"


def test_same_as_takes_the_family_and_keeps_kittys_size(env, tmp_path):
    c, history = controller(env, tmp_path)
    c.same_as(ap.KITTY_FONT)
    assert c.value(ap.KITTY_FONT) == "Adwaita Mono 12"
    c.same_as(ap.PANEL_FONT)
    assert c.value(ap.PANEL_FONT) == "Adwaita Sans"
    assert [g.entries[0].key for g in history.groups()] == [ap.KITTY_FONT, ap.PANEL_FONT]


def test_a_scale_drag_is_one_item(env, tmp_path):
    c, history = controller(env, tmp_path)
    for value in (1.1, 1.2, 1.25):
        c.scale_moved(value)
    c.commit_scale()
    entries = [e for g in history.groups() for e in g.entries]
    assert [(e.before, e.after) for e in entries] == [(1.0, 1.25)]
    assert c.pending == set()
    assert strings.LOOK_APPLIED.format(name=strings.LOOK_LABELS[ap.SCALE]) in c.view.statuses


def test_only_kittys_reading_this_config_are_signalled(tmp_path):
    proc = tmp_path / "proc"
    mine, other, sandbox = tmp_path / "home" / ".config", tmp_path / "x", tmp_path / "sb"
    for pid, comm, env in (("10", "kitty", b"HOME=" + bytes(tmp_path / "home")),
                           ("11", "kitty", b"XDG_CONFIG_HOME=" + bytes(other)),
                           ("12", "bash", b"HOME=" + bytes(tmp_path / "home")),
                           ("13", "kitty", b"XDG_CONFIG_HOME=" + bytes(sandbox))):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "comm").write_text(comm + "\n")
        (proc / pid / "environ").write_bytes(b"A=1\0" + env + b"\0")
    mine.mkdir(parents=True)
    assert ap.kitty_pids(mine, proc) == [10]
    assert ap.kitty_pids(sandbox, proc) == [13]


def test_same_as_uses_the_family_the_view_read(env, tmp_path):
    c, _history = controller(env, tmp_path)
    c.look.values[ap.FONT] = "Adwaita Sans Bold 11"
    c.same_as(ap.PANEL_FONT, "Adwaita Sans")  # Pango's reading, not "Adwaita Sans Bold"
    assert c.value(ap.PANEL_FONT) == "Adwaita Sans"


class Later:
    """Workers that hold jobs until run(): a stale picture between two changes."""

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


def test_quick_changes_chain_in_history(env, tmp_path):
    c, history = controller(env, tmp_path)
    c.backend.workers = later = Later()
    c.set(ap.FONT, "Inter 10")
    c.set(ap.FONT, "Inter 12")  # before the first one is done: the picture is stale
    later.run()
    pairs = [(g.entries[0].before, g.entries[0].after) for g in history.groups()]
    assert pairs == [("Adwaita Sans 11", "Inter 10"), ("Inter 10", "Inter 12")]
    assert c.pending == set()
    c.set(ap.FONT, "Adwaita Sans 11")  # back to what the stale picture still shows
    later.run()
    assert env[1].values["font-name"] == "'Adwaita Sans 11'"


def test_a_scale_drag_reads_its_before_on_the_worker(env, tmp_path):
    c, history = controller(env, tmp_path)
    c.backend.workers = later = Later()
    c.scale_moved(1.5)
    c.commit_scale()
    later.run()
    c.scale_moved(1.75)
    c.commit_scale()
    later.run()
    pairs = [(g.entries[0].before, g.entries[0].after) for g in history.groups()]
    assert pairs == [(1.0, 1.5), (1.5, 1.75)]
    assert c.pending == set()


def test_a_drag_that_replaces_an_unapplied_move_keeps_history_whole(env, tmp_path):
    c, history = controller(env, tmp_path)
    c.backend.workers = later = Later()
    c.scale_moved(1.5)
    c.commit_scale()
    c.scale_moved(1.75)  # replaces 1.5 before it ran: 1.5 never happened
    c.commit_scale()
    later.run()
    pairs = [(g.entries[0].before, g.entries[0].after) for g in history.groups()]
    assert pairs == [(1.0, 1.75)]
    assert c.pending == set() and env[1].values["text-scaling-factor"] == "1.75"


def test_a_panel_without_a_font_logs_hyprpanels_default(env, tmp_path):
    (env[2] / "hyprpanel" / "config.json").write_text("{}")
    c, history = controller(env, tmp_path)
    c.set(ap.PANEL_FONT, "Inter")
    entry = history.groups()[-1].entries[0]
    assert (entry.before, entry.after) == (ap.PANEL_FONT_DEFAULT, "Inter")


def test_a_kitty_font_this_page_cannot_write_back_is_applied_but_said_so(env, tmp_path):
    (env[2] / "kitty" / "kitty.conf").write_text('font_family family="JetBrains Mono"\n')
    c, history = controller(env, tmp_path)
    assert c.value(ap.KITTY_FONT) is None
    c.set(ap.KITTY_FONT, "Iosevka 13")
    assert history.groups() == []
    assert c.view.statuses[-1] == strings.LOOK_APPLIED_NO_UNDO.format(
        name=strings.LOOK_LABELS[ap.KITTY_FONT])


def test_kitty_without_a_font_has_kittys_default(env):
    backend, _gs, conf, _ = env
    (conf / "kitty" / "kitty.conf").write_text("include theme.conf\n")
    assert backend.read([ap.KITTY_FONT]) == {ap.KITTY_FONT: "monospace 11"}


def test_our_kitty_file_counts_only_while_included(env):
    backend, _gs, conf, _ = env
    (conf / "kitty" / ap.KITTY_FILE).write_text("font_family Iosevka\n")
    assert backend.read([ap.KITTY_FONT]) == {ap.KITTY_FONT: "JetBrainsMono Nerd Font 12"}


def test_an_unwritable_settings_ini_does_not_lose_the_change(env, tmp_path):
    (env[2] / "gtk-4.0").write_text("not a folder")
    c, history = controller(env, tmp_path)
    c.set(ap.FONT, "Inter 10")
    assert env[1].values["font-name"] == "'Inter 10'"
    assert history.groups()[-1].entries[0].after == "Inter 10"
    assert "gtk-font-name=Inter 10" in (env[2] / "gtk-3.0" / "settings.ini").read_text()


def test_set_ini_sets_every_copy_and_adds_before_trailing_blanks():
    out = ap.set_ini("[Settings]\nk=1\nk=2\n\n[Next]\n", {"k": "X", "new": "Y"})
    assert out == "[Settings]\nk=X\nk=X\nnew=Y\n\n[Next]\n"


def test_an_icon_theme_in_use_but_not_found_is_still_listed(env):
    backend, gs, _conf, _ = env
    gs.values["icon-theme"] = "'Elsewhere'"
    assert backend.probe().icon_themes[-1] == "Elsewhere"


def test_a_deleted_include_line_is_put_back_even_if_the_mark_stays(env):
    backend, _gs, conf, _ = env
    backend.set(ap.KITTY_FONT, "Iosevka 13")
    kitty = conf / "kitty" / "kitty.conf"
    kitty.write_text(kitty.read_text().replace(f"include {ap.KITTY_FILE}\n", ""))
    assert backend.read([ap.KITTY_FONT]) == {ap.KITTY_FONT: "JetBrainsMono Nerd Font 12"}
    backend.set(ap.KITTY_FONT, "Iosevka 14")
    assert kitty.read_text().count(f"include {ap.KITTY_FILE}") == 1
    assert backend.read([ap.KITTY_FONT]) == {ap.KITTY_FONT: "Iosevka 14"}


# ---- fonts that cannot write the interface's text --------------------------------


class _Coverage:
    def __init__(self, chars):
        self.chars = {ord(c) for c in chars}

    def get(self, codepoint):
        from gi.repository import Pango
        return Pango.CoverageLevel.EXACT if codepoint in self.chars else Pango.CoverageLevel.NONE


class _Font:
    def __init__(self, chars):
        self.chars = chars

    def get_coverage(self, _language):
        return _Coverage(self.chars)


class _Context:
    def __init__(self, fonts):
        self.fonts = fonts  # family -> letters it has
        self.loaded = []

    def load_font(self, desc):
        self.loaded.append((desc.get_family(), desc.get_size()))
        chars = self.fonts.get(desc.get_family())
        return None if chars is None else _Font(chars)


def test_draws_text_needs_latin_and_cyrillic():
    pytest.importorskip("gi")
    import gi
    gi.require_version("Pango", "1.0")
    from gi.repository import Pango

    from settings_hub.pages import appearance as page
    ctx = _Context({"Good": "AzЖяbc", "Latin": "Az", "Han": "一", "Ru": "Жя"})
    desc = Pango.FontDescription.from_string
    assert page.draws_text(ctx, desc("Good 11"))
    assert not page.draws_text(ctx, desc("Latin 11"))
    assert not page.draws_text(ctx, desc("Han 11"))
    assert not page.draws_text(ctx, desc("Ru 11"))
    assert not page.draws_text(ctx, desc("Missing 11"))  # nothing loaded
    page.draws_text(ctx, desc("Good"))  # a face's description has no size
    assert ctx.loaded[-1][1] > 0


def test_readable_family_is_cached_per_family():
    pytest.importorskip("gi")
    import gi
    gi.require_version("Pango", "1.0")
    from gi.repository import Pango

    from settings_hub.pages import appearance as page

    class Face:
        def __init__(self, name):
            self.name = name

        def describe(self):
            return Pango.FontDescription.from_string(self.name)

    class Family:
        def __init__(self, name):
            self.name = name

        def get_name(self):
            return self.name

        def get_face(self, _name):
            return Face(self.name)

    page._READABLE.clear()
    ctx = _Context({"Test Good": "AzЖя", "Test Han": "一"})
    assert page.readable_family(ctx, Family("Test Good"))
    assert not page.readable_family(ctx, Family("Test Han"))
    assert page.readable_family(ctx, Family("Test Good"))
    assert len(ctx.loaded) == 2  # the third call came from the cache
    assert not page.readable_family(ctx, object())  # not a family nor a face


def test_own_font_setting_defaults_to_onest():
    from settings_hub import settings, strings
    field = settings.BY_KEY["appearance.own_font"]
    assert field.kind == "bool" and field.default is True and field.group == "appearance"
    assert "appearance.own_font" in strings.HUB_SETTINGS


def test_readable_family_with_real_pango_items():
    """The dialog hands real Pango families (and faces): both must work."""
    pytest.importorskip("gi")
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo

    from settings_hub.pages import appearance as page
    fontmap = PangoCairo.FontMap.get_default()
    ctx = fontmap.create_context()
    families = fontmap.list_families()
    assert families
    page._READABLE.clear()
    results = [page.readable_family(ctx, f) for f in families]
    assert any(results)  # some installed family writes Russian
    family = families[results.index(True)]
    face = family.get_face(None)
    assert page.readable_family(ctx, face)  # a face goes through its family


def test_refused_font_is_not_applied():
    """_on_font with a font that draws no letters: nothing set, button reset."""
    pytest.importorskip("gi")
    import gi
    gi.require_version("Pango", "1.0")
    from gi.repository import Pango

    from settings_hub.pages import appearance as page

    class Button:
        def __init__(self, name):
            self.desc = Pango.FontDescription.from_string(name)

        def get_font_desc(self):
            return self.desc

        def set_font_desc(self, desc):
            self.desc = desc

    class Look:
        def __init__(self):
            self.sets = []

        def value(self, _key):
            return "Good 11"

        def set(self, key, value):
            self.sets.append((key, value))

    class Widget:
        def get_pango_context(self):
            return _Context({"Good": "AzЖя", "Han": "一"})

    view = page.AppearancePage.__new__(page.AppearancePage)
    view._look_quiet = False
    view.look = Look()
    view.widget = Widget()
    said = []
    view.status = said.append
    button = Button("Han Bold 11")
    view._on_font(ap.FONT, button)
    assert view.look.sets == []
    assert button.desc.to_string() == "Good 11"
    assert said and "Han" in said[0]
    good = Button("Good 13")
    view._on_font(ap.FONT, good)
    assert view.look.sets == [(ap.FONT, "Good 13")]


def test_base_css_sizes_follow_the_interface_font():
    """Text sizes are rem and the window sets no font: the own_font switch decides."""
    pytest.importorskip("gi")
    import re

    from settings_hub import theme
    css = theme.CSS_PATH.read_text()
    assert not re.search(r"font-size:\s*[\d.]+px", css)
    assert "font-family" not in css
    assert "Onest" in theme.OWN_FONT_CSS
