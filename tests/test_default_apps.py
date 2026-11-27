"""Default applications: desktop files, mimeapps.list, the terminal list, xdg-terminal-exec."""

import os
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

from settings_hub.backends import default_apps as da
from settings_hub.history import History


def desktop(folder: Path, name: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("[Desktop Entry]\nType=Application\n" + body)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = Path(os.environ["HOME"])
    system = tmp_path / "system"
    monkeypatch.setenv("XDG_DATA_DIRS", str(system))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "etc"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    apps = system / "applications"
    desktop(apps, "firefox.desktop",
            "Name=Firefox\nExec=firefox %u\nMimeType=x-scheme-handler/https;"
            "x-scheme-handler/http;text/html;image/png;\n")
    desktop(apps, "chrome.desktop", "Name=Chrome\nExec=chrome %U\n"
            "MimeType=x-scheme-handler/https;x-scheme-handler/http;text/html;\n")
    desktop(apps, "imv.desktop", "Name=imv\nNoDisplay=true\nExec=imv %F\n"
            "MimeType=image/png;image/jpeg;\n")
    desktop(apps, "opener.desktop", "Name=Opener\nNoDisplay=true\nExec=opener %U\n"
            "MimeType=image/*;inode/directory;\n")
    desktop(apps, "gone.desktop", "Name=Gone\nTryExec=/nowhere/gone\nMimeType=text/plain;\n")
    desktop(apps, "hidden.desktop", "Name=Hidden\nHidden=true\nMimeType=text/plain;\n")
    desktop(apps, "zed.desktop", "Name=Zed\nName[ru]=Зед\nExec=zed %F\nMimeType=text/plain;\n")
    desktop(apps, "kitty.desktop", "Name=kitty\nExec=kitty\nCategories=System;TerminalEmulator;\n")
    desktop(apps, "ghostty.desktop", "Name=Ghostty\nExec=ghostty\n"
            "Categories=System;TerminalEmulator;\n")
    return home


def backend(home):
    return da.Backend(None, home=home)


def mimeapps(home) -> Path:
    return home / ".config" / "mimeapps.list"


def test_installed_reads_what_can_be_offered(home):
    apps = da.installed(da.Paths(home))
    assert "gone.desktop" not in apps and "hidden.desktop" not in apps  # TryExec, Hidden
    assert apps["zed.desktop"].name == "Зед"  # the person's language
    assert apps["imv.desktop"].hidden and apps["kitty.desktop"].terminal


def test_a_users_file_hides_the_systems_of_the_same_id(home):
    desktop(home / ".local" / "share" / "applications", "zed.desktop", "Name=Zed\nHidden=true\n")
    assert "zed.desktop" not in da.installed(da.Paths(home))


def test_wildcards_and_hidden_viewers_are_offered(home):
    info = backend(home).probe()
    images = [a.id for a in info.choices["images"].options]
    assert {"imv.desktop", "opener.desktop", "firefox.desktop"} <= set(images)
    assert [a.id for a in info.choices["files"].options] == ["opener.desktop"]


def test_nothing_chosen_and_mixed(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text("[Default Applications]\nimage/png=imv.desktop\n"
                              "image/jpeg=firefox.desktop\n")
    info = backend(home).probe()
    assert info.choices["browser"].current == "" and not info.choices["browser"].explicit
    images = info.choices["images"]
    assert images.current == "imv.desktop" and images.mixed


def test_a_missing_program_in_a_list_is_skipped(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text("[Default Applications]\ntext/plain=gone.desktop;zed.desktop\n")
    assert backend(home).probe().choices["text"].current == "zed.desktop"


def test_the_stronger_file_wins(home, tmp_path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "mimeapps.list").write_text("[Default Applications]\ntext/plain=zed.desktop\n")
    assert backend(home).probe().choices["text"].current == "zed.desktop"
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text("[Default Applications]\ntext/plain=firefox.desktop\n")
    # firefox does not say it opens text, but the person chose it: it is shown
    text = backend(home).probe().choices["text"]
    assert text.current == "firefox.desktop" and text.options[0].id == "firefox.desktop"


ORIGINAL = """# my notes
[Default Applications]
text/html=chrome.desktop
x-scheme-handler/claude=claude.desktop

[Added Associations]
image/png=imv.desktop;
"""


def test_choose_sets_the_whole_kind_and_keeps_the_rest(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text(ORIGINAL)
    before, after = backend(home).choose("browser", "firefox.desktop")
    text = mimeapps(home).read_text()
    for mime in da.KINDS["browser"]:
        assert f"{mime}=firefox.desktop" in text
    assert text.count("text/html=") == 1
    assert "# my notes" in text and "x-scheme-handler/claude=claude.desktop" in text
    assert "[Added Associations]\nimage/png=imv.desktop;" in text
    assert text.index("x-scheme-handler/https=") < text.index("[Added Associations]")
    assert before[str(mimeapps(home))]["text/html"] == "chrome.desktop"
    assert before[str(mimeapps(home))]["x-scheme-handler/https"] is None
    assert backend(home).probe().choices["browser"].current == "firefox.desktop"
    assert after == backend(home).current_values("browser")  # History sees no outside change


def test_undo_gives_the_file_back_byte_for_byte(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text(ORIGINAL)
    b = backend(home)
    history = History()
    da.register(history, b)
    before, after = b.choose("browser", "firefox.desktop")
    history.record([(da.BACKEND, "browser", "browser", before, after)])
    b.choose("images", "imv.desktop")
    history.record([(da.BACKEND, "images", "images", {str(mimeapps(home)): {
        m: None for m in da.KINDS["images"]}}, b.current_values("images"))])
    history.execute(history.plan_undo_last())
    history.execute(history.plan_undo_last())
    assert mimeapps(home).read_text() == ORIGINAL


def test_a_file_without_the_section_gets_one(home):
    desktop(Path(os.environ["XDG_DATA_DIRS"]) / "applications", "pdf.desktop",
            "Name=PDF\nExec=pdf %f\nMimeType=application/pdf;\n")
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text("[Added Associations]\ntext/plain=zed.desktop;\n")
    backend(home).choose("pdf", "pdf.desktop")
    assert mimeapps(home).read_text() == (
        "[Added Associations]\ntext/plain=zed.desktop;\n\n"
        "[Default Applications]\napplication/pdf=pdf.desktop\n")


def test_the_desktops_own_file_is_kept_in_step(home):
    own = home / ".config" / "hyprland-mimeapps.list"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("[Default Applications]\nimage/png=firefox.desktop\n")
    backend(home).choose("images", "imv.desktop")
    assert "image/png=imv.desktop" in own.read_text()
    assert backend(home).probe().choices["images"].current == "imv.desktop"


@pytest.mark.parametrize("kind, app", [("browser", "nope.desktop"), ("browser", "../x.desktop"),
                                       ("nope", "firefox.desktop"),
                                       ("browser", "firefox.desktop\nx=y")])
def test_choose_refuses(home, kind, app):
    with pytest.raises(ValueError):
        backend(home).choose(kind, app)
    assert not mimeapps(home).exists()


@pytest.mark.parametrize("kind, values", [
    ("text", {"/etc/passwd": {"text/plain": "zed.desktop"}}),  # not a file of this page
    ("text", {"MIME": {"text/plain": "zed.desktop"}}),
    ("text", {"{mime}": {"text/plain": "zed.desktop\n[Other]\nx=y"}}),  # a new group
    ("text", {"{mime}": {"text/plain": "a.desktop;\nb.desktop"}}),  # a bare line
    ("text", {"{mime}": {"text/plain": "a.desktop;\x1cb.desktop"}}),  # a line to Python
    ("text", {"{mime}": {"text/plain": "a.desktop;\x0bb.desktop"}}),
    ("text", {"{mime}": {"text/plain": "../a.desktop"}}),
    ("text", {"{mime}": {"application/x-evil": "zed.desktop"}}),  # not a type of this page
    ("pdf", {"{mime}": {"image/png": "zed.desktop"}}),  # not a type of this kind
    ("text", {"{mime}": "text/plain=zed.desktop"}),
    ("text", {"{terms}": "zed.desktop\n"}),  # the terminal list is not a file of text
    ("terminal", {"{terms}": "kitty.desktop\nrm -rf ~\n"}),
    ("terminal", {"{terms}": "\x1ckitty.desktop\n"}),
    ("terminal", {"{mime}": {"text/plain": "zed.desktop"}}),
    ("nope", {"{mime}": {"text/plain": "zed.desktop"}}),
])
def test_a_crafted_history_line_is_refused(home, kind, values):
    names = {"{mime}": str(mimeapps(home)), "{terms}": str(home / ".config" /
                                                          "xdg-terminals.list")}
    values = {names.get(k, k): v for k, v in values.items()}
    with pytest.raises(ValueError):
        backend(home).apply_values(values, kind)
    assert not mimeapps(home).exists()
    assert not (home / ".config" / "xdg-terminals.list").exists()


def test_one_bad_value_writes_nothing_at_all(home):
    own = home / ".config" / "hyprland-mimeapps.list"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("[Default Applications]\nimage/png=firefox.desktop\n")
    b = backend(home)
    history = History()
    applier = da.register(history, b)
    with pytest.raises(ValueError):
        applier.apply({"text": {str(mimeapps(home)): {"text/plain": "zed.desktop"}},
                       "images": {str(own): {"image/png": "bad id"}}})
    assert not mimeapps(home).exists()
    assert own.read_text() == "[Default Applications]\nimage/png=firefox.desktop\n"


def test_an_unreadable_file_is_never_replaced(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    original = b"[Default Applications]\n# caf\xe9\ntext/plain=zed.desktop\n" \
               b"[Added Associations]\nimage/png=imv.desktop;\n"
    mimeapps(home).write_bytes(original)
    with pytest.raises(UnicodeDecodeError):
        backend(home).choose("images", "imv.desktop")
    assert mimeapps(home).read_bytes() == original


def test_line_endings_blank_lines_and_a_missing_last_newline_are_kept(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    original = "[Default Applications]\r\ntext/plain=zed.desktop\r\n\r\n\r\n[Other]\r\nq=z"
    mimeapps(home).write_bytes(original.encode())
    b = backend(home)
    before, _ = b.choose("pdf", "firefox.desktop")
    text = mimeapps(home).read_bytes().decode()
    assert "application/pdf=firefox.desktop\r\n\r\n\r\n[Other]" in text and text.endswith("q=z")
    b.apply_values(before, "pdf")
    assert mimeapps(home).read_bytes().decode() == original


def test_two_groups_of_defaults_read_and_write_like_glib(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    mimeapps(home).write_text("[Default Applications]\ntext/plain=firefox.desktop\n"
                              "[Added Associations]\n[Default Applications]\n"
                              "text/plain=zed.desktop\n")
    assert backend(home).probe().choices["text"].current == "zed.desktop"  # the later wins
    backend(home).choose("text", "firefox.desktop")
    text = mimeapps(home).read_text()
    assert "zed.desktop" not in text and da.read_defaults(text)["text/plain"] == "firefox.desktop"


def test_the_terminal_goes_first_in_its_list(home):
    terms = home / ".config" / "xdg-terminals.list"
    terms.parent.mkdir(parents=True, exist_ok=True)
    terms.write_text("# mine\nkitty.desktop\nghostty.desktop\n")
    b = backend(home)
    assert b.probe().choices["terminal"].current == "kitty.desktop"
    before, _ = b.choose("terminal", "ghostty.desktop")
    assert terms.read_text() == "ghostty.desktop\n# mine\nkitty.desktop\n"
    assert b.probe().choices["terminal"].current == "ghostty.desktop"
    b.apply_values(before, "terminal")
    assert terms.read_text() == "# mine\nkitty.desktop\nghostty.desktop\n"


def test_the_desktops_own_terminal_list_is_read_first_and_kept_in_step(home):
    own = home / ".config" / "hyprland-xdg-terminals.list"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("ghostty.desktop\n")
    (home / ".config" / "xdg-terminals.list").write_text("kitty.desktop\n")
    b = backend(home)
    assert b.probe().choices["terminal"].current == "ghostty.desktop"
    b.choose("terminal", "kitty.desktop")
    assert own.read_text().splitlines()[0] == "kitty.desktop"
    assert b.probe().choices["terminal"].current == "kitty.desktop"


def test_only_a_terminal_can_be_the_terminal(home):
    with pytest.raises(ValueError):
        backend(home).choose("terminal", "zed.desktop")


def test_only_show_in_another_desktop_is_not_offered(home):
    desktop(Path(os.environ["XDG_DATA_DIRS"]) / "applications", "gnomish.desktop",
            "Name=Gnomish\nOnlyShowIn=GNOME;\nMimeType=text/plain;\n")
    desktop(Path(os.environ["XDG_DATA_DIRS"]) / "applications", "nothypr.desktop",
            "Name=NotHypr\nNotShowIn=Hyprland;\nMimeType=text/plain;\n")
    apps = da.installed(da.Paths(home))
    assert "gnomish.desktop" not in apps and "nothypr.desktop" not in apps


def test_names_follow_lc_all_first(home, monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8@euro")
    assert da.installed(da.Paths(home))["zed.desktop"].name == "Зед"
    monkeypatch.setenv("LC_ALL", "C")
    assert da.installed(da.Paths(home))["zed.desktop"].name == "Zed"


def test_terminals_are_offered_by_category(home):
    names = [a.id for a in backend(home).probe().choices["terminal"].options]
    assert names == ["ghostty.desktop", "kitty.desktop"]


def test_with_defaults_drops_a_second_line_and_removes():
    text = "[Default Applications]\na/b=x.desktop\na/b=y.desktop\nc/d=z.desktop\n"
    assert da.with_defaults(text, {"a/b": None}) == "[Default Applications]\nc/d=z.desktop\n"
    assert da.with_defaults("", {"a/b": None}) == ""


# ---- bin/xdg-terminal-exec -------------------------------------------------------------

SHIM = ROOT / "bin" / "xdg-terminal-exec"


def fake_terminal(tmp_path, name: str, extra: str = "") -> tuple[Path, Path]:
    log = tmp_path / f"{name}.log"
    script = tmp_path / "bin" / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\n')
    script.chmod(0o755)
    desktop(tmp_path / "share" / "applications", f"{name}.desktop",
            f"Name={name}\nExec={script} --title X %u\nCategories=TerminalEmulator;\n" + extra)
    return script, log


def run_shim(tmp_path, *args):
    env = dict(os.environ, XDG_DATA_DIRS=str(tmp_path / "share"),
               XDG_DATA_HOME=str(tmp_path / "nodata"), XDG_CONFIG_DIRS=str(tmp_path / "noetc"))
    return subprocess.run([str(SHIM), *args], env=env, capture_output=True, text=True,
                          timeout=20)


def test_shim_runs_the_listed_terminal_with_the_command_as_arguments(tmp_path, home):
    _, alpha = fake_terminal(tmp_path, "alpha")
    _, zeta = fake_terminal(tmp_path, "zeta")
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "xdg-terminals.list").write_text("# c\nmissing.desktop\nzeta.desktop\n")
    done = run_shim(tmp_path, "btop", "a b;c", "$HOME")
    assert done.returncode == 0, done.stderr
    assert zeta.read_text().splitlines() == ["--title", "X", "-e", "btop", "a b;c", "$HOME"]
    assert not alpha.exists()


def test_shim_without_a_list_takes_a_terminal_by_name(tmp_path, home):
    _, beta = fake_terminal(tmp_path, "beta")
    fake_terminal(tmp_path, "gamma")
    assert run_shim(tmp_path).returncode == 0
    assert beta.read_text().splitlines() == ["--title", "X"]  # no command: just the terminal


def test_shim_takes_the_entrys_own_exec_flag(tmp_path, home):
    _, log = fake_terminal(tmp_path, "delta", "X-TerminalArgExec=\n")
    assert run_shim(tmp_path, "htop").returncode == 0
    assert log.read_text().splitlines() == ["--title", "X", "htop"]


def test_shim_ignores_list_lines_that_are_paths(tmp_path, home):
    _, good = fake_terminal(tmp_path, "good")
    evil_dir = tmp_path / "evil"
    _, evil = fake_terminal(evil_dir, "evil")
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "xdg-terminals.list").write_text(
        f"{evil_dir}/share/applications/evil.desktop\n../../evil/share/applications/evil.desktop\n")
    assert run_shim(tmp_path, "x").returncode == 0
    assert good.exists() and not evil.exists()


def test_shim_moves_on_from_a_terminal_it_cannot_run(tmp_path, home):
    apps = tmp_path / "share" / "applications"
    desktop(apps, "aa-relative.desktop", "Name=aa\nExec=bin/term\nCategories=TerminalEmulator;\n")
    desktop(apps, "ab-quote.desktop", "Name=ab\nExec=term 'open\nCategories=TerminalEmulator;\n")
    desktop(apps, "ac-gone.desktop", "Name=ac\nTryExec=/nowhere/x\nExec=sh\n"
            "Categories=TerminalEmulator;\n")
    _, last = fake_terminal(tmp_path, "zz")
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "xdg-terminals.list").write_text(
        "aa-relative.desktop\nab-quote.desktop\nac-gone.desktop\n")
    done = run_shim(tmp_path, "top")
    assert done.returncode == 0, done.stderr
    assert last.read_text().splitlines()[-1] == "top"


def test_shim_with_no_terminal_says_so(tmp_path, home):
    done = run_shim(tmp_path, "btop")
    assert done.returncode == 127 and "no terminal" in done.stderr


def test_undo_brings_back_a_hand_written_odd_value(home):
    mimeapps(home).parent.mkdir(parents=True, exist_ok=True)
    original = ("[Default Applications]\ntext/plain=zed.desktop; weird@x.desktop\n"
                "text/markdown=\n")
    mimeapps(home).write_text(original)
    b = backend(home)
    before, _ = b.choose("text", "zed.desktop")
    b.apply_values(before, "text")
    assert mimeapps(home).read_text() == original


def test_a_terminal_list_in_xdg_terminal_exec_syntax_is_kept(home):
    terms = home / ".config" / "xdg-terminals.list"
    terms.parent.mkdir(parents=True, exist_ok=True)
    terms.write_text("/execarg_default:-e\nkitty.desktop:server \n")
    b = backend(home)
    assert b.probe().choices["terminal"].current == "kitty.desktop"
    b.choose("terminal", "ghostty.desktop")
    assert terms.read_text() == "ghostty.desktop\n/execarg_default:-e\nkitty.desktop:server \n"
