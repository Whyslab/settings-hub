"""install.sh / uninstall.sh in a sandbox. hyprctl and gdbus are stubs that fail
loudly: a sandbox install or uninstall must never call them."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

from settings_hub import strings

FAIL_STUB = """#!/bin/sh
echo "{name} $*" >>"{log}"
exit 97
"""


class Sandbox:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.prefix = tmp / "sb"
        self.stubs = tmp / "stubs"
        self.called = tmp / "CALLED"
        self.home.mkdir()
        self.stubs.mkdir()
        for name in ("hyprctl", "gdbus"):
            stub = self.stubs / name
            stub.write_text(FAIL_STUB.format(name=name, log=self.called))
            stub.chmod(0o755)
        self.env = {"PATH": f"{self.stubs}:/usr/bin:/bin", "HOME": str(self.home)}

    def path(self, rel: str) -> Path:
        """Where a home-relative path lands inside the sandbox."""
        return Path(f"{self.prefix}{self.home}/{rel}")

    def run(self, script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["sh", str(ROOT / script), *args], env=self.env,
                              capture_output=True, text=True)
        if check:
            assert proc.returncode == 0, proc.stderr + proc.stdout
        return proc

    def install(self):
        return self.run("install.sh", "--prefix", str(self.prefix))

    def uninstall(self, *extra):
        return self.run("uninstall.sh", "--prefix", str(self.prefix), *extra)

    def files(self) -> list[Path]:
        return sorted(p for p in self.prefix.rglob("*") if p.is_file())


@pytest.fixture
def sb(tmp_path):
    s = Sandbox(tmp_path)
    yield s
    assert not s.called.exists(), s.called.read_text()  # never hyprctl, never gdbus


EXPECTED = [
    ".local/share/settings-hub/app.py",
    ".local/share/settings-hub/settings_hub/app.py",
    ".local/share/settings-hub/settings_hub/window.py",
    ".local/share/settings-hub/settings_hub/strings.py",
    ".local/share/settings-hub/settings_hub/pages/history.py",
    ".local/share/settings-hub/settings_hub/widgets/sidebar.py",
    ".local/share/settings-hub/style/base.css",
    ".local/share/settings-hub/style/icons/history.svg",
    ".local/share/settings-hub/pages.json",
    ".local/share/settings-hub/open-failed.txt",
    ".local/share/applications/settings-hub.desktop",
    ".local/bin/settings-open",
    ".local/bin/settings-hub-uninstall",
    ".config/hypr/settings-hub.conf",
    ".config/hypr/settings-hub.lua",
    ".local/state/settings-hub/install-manifest",
]


def test_install_then_purge_leaves_nothing(sb):
    sb.install()
    for rel in EXPECTED:
        assert sb.path(rel).is_file(), rel
    assert sb.path(".local/bin/settings-open").stat().st_mode & 0o111
    pages = json.loads(sb.path(".local/share/settings-hub/pages.json").read_text())
    assert [p["id"] for p in pages][0] == "screen-sleep"
    desktop = sb.path(".local/share/applications/settings-hub.desktop").read_text()
    assert f"Exec={sb.home}/.local/bin/settings-open\n" in desktop  # the real path, no prefix
    sb.uninstall("--purge")
    assert sb.files() == []
    assert [p for p in sb.prefix.rglob("*")] == []


def test_generated_hyprland_file(sb):
    sb.install()
    conf = sb.path(".config/hypr/settings-hub.conf").read_text()
    assert f"exec-once = python3 {sb.home}/.local/share/settings-hub/app.py --daemon" in conf
    assert ("windowrule = match:class ^(settings-hub|io\\.github\\.whyslab\\.SettingsHub)$, "
            f"match:initial_title ^({strings.APP_TITLE})$, float true, size 920 640, "
            "center true") in conf
    assert f"bind   = SUPER SHIFT, N, exec, {sb.home}/.local/bin/settings-open screen-sleep" in conf
    assert "unbind = SUPER SHIFT, W" in conf
    assert f"bind   = SUPER, I, exec, {sb.home}/.local/bin/settings-open\n" in conf
    assert "submap = settings-hub-capture\nbind   = SUPER CTRL ALT, Escape, submap, reset\n" \
           "submap = reset\n" in conf
    assert conf.endswith("# >>> settings-hub binds\n# <<< settings-hub binds\n")
    assert str(sb.prefix) not in conf


@pytest.mark.parametrize("original", [
    "bind = SUPER, C, killactive\n",
    "bind = SUPER, C, killactive",  # no final newline
    "",
])
def test_one_line_in_hyprland_conf_and_exact_removal(sb, original):
    conf = sb.path(".config/hypr/hyprland.conf")
    conf.parent.mkdir(parents=True)
    conf.write_text(original)
    conf.chmod(0o640)
    inode = conf.stat().st_ino
    sb.install()
    sb.install()  # a reinstall must not add the line twice
    lines = conf.read_text().splitlines()
    assert lines[-1] == "source = ~/.config/hypr/settings-hub.conf  # settings-hub"
    assert lines.count(lines[-1]) == 1
    backups = list(conf.parent.glob("hyprland.conf.bak-*-settings-hub"))
    assert len(backups) == 1 and backups[0].read_text() == original
    sb.uninstall("--purge")
    assert conf.read_text() == original  # byte for byte
    assert conf.stat().st_ino == inode and conf.stat().st_mode & 0o777 == 0o640
    assert backups[0].exists()  # the dated copy is the user's, never removed
    assert sorted(p.name for p in sb.files()) == sorted(["hyprland.conf", backups[0].name])


LUA_LINE = 'dofile(os.getenv("HOME") .. "/.config/hypr/settings-hub.lua")  -- settings-hub'
CONF_LINE = "source = ~/.config/hypr/settings-hub.conf  # settings-hub"


@pytest.mark.parametrize("original", ['hl.config({ general = { gaps_in = 2 } })\n',
                                      "hl.bind(\"SUPER + C\", hl.dsp.window.close())"])
def test_lua_config_gets_one_dofile_line_and_exact_removal(sb, original):
    # Hyprland 0.57+ reads hyprland.lua only; hyprland.conf stays for a rollback.
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    conf, lua = hypr / "hyprland.conf", hypr / "hyprland.lua"
    conf.write_text("bind = SUPER, C, killactive\n")
    lua.write_text(original)
    sb.install()
    sb.install()
    assert lua.read_text().splitlines()[-1] == LUA_LINE
    assert lua.read_text().count(LUA_LINE) == 1
    assert conf.read_text().splitlines()[-1] == CONF_LINE
    assert len(list(hypr.glob("hyprland.lua.bak-*-settings-hub"))) == 1
    sb.uninstall("--purge")
    assert lua.read_text() == original
    assert conf.read_text() == "bind = SUPER, C, killactive\n"


def test_lua_config_that_loads_us_itself_is_left_alone(sb):
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    lua = hypr / "hyprland.lua"
    original = 'safe_dofile(home .. "/.config/hypr/settings-hub.lua")\n'
    lua.write_text(original)
    out = sb.install().stdout
    assert "loads settings-hub.lua itself" in out
    assert lua.read_text() == original
    assert not list(hypr.glob("hyprland.lua.bak-*"))
    sb.uninstall("--purge")
    assert lua.read_text() == original


def test_a_commented_mention_does_not_count_as_loading(sb):
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    lua = hypr / "hyprland.lua"
    lua.write_text('-- dofile(home .. "/.config/hypr/settings-hub.lua")\n')
    sb.install()
    assert lua.read_text().splitlines()[-1] == LUA_LINE


def test_generated_lua_file(sb):
    sb.install()
    text = sb.path(".config/hypr/settings-hub.lua").read_text()
    assert f'hl.exec_cmd("python3 {sb.home}/.local/share/settings-hub/app.py --daemon")' in text
    assert f'initial_title = "^({strings.APP_TITLE})$"' in text  # UTF-8, not \\u escapes
    assert f'hl.bind("SUPER + I", hl.dsp.exec_cmd("{sb.home}/.local/bin/settings-open"))' in text
    assert 'hl.bind("SUPER + CTRL + ALT + Escape", hl.dsp.submap("reset"))' in text
    assert text.endswith("-- >>> settings-hub binds\n-- <<< settings-hub binds\n")
    assert str(sb.prefix) not in text


@pytest.mark.skipif(shutil.which("Hyprland") is None, reason="needs Hyprland 0.57+")
def test_hyprland_accepts_the_generated_lua_file(sb):
    version = subprocess.run(["Hyprland", "--version"], capture_output=True, text=True).stdout
    if not any(f"Hyprland 0.{n}" in version for n in range(57, 100)):
        pytest.skip("Hyprland before 0.57 has no Lua config")
    sb.install()
    lua = sb.path(".config/hypr/settings-hub.lua")
    done = subprocess.run(["Hyprland", "--verify-config", "-c", str(lua)],
                          capture_output=True, text=True, timeout=60)
    assert "config ok" in done.stdout, done.stdout + done.stderr


def test_line_edited_by_hand_is_left_alone(sb):
    conf = sb.path(".config/hypr/hyprland.conf")
    conf.parent.mkdir(parents=True)
    conf.write_text("a\n")
    sb.install()
    text = conf.read_text()
    conf.write_text(text + text.splitlines()[-1] + "\n")  # now it occurs twice
    out = sb.uninstall().stdout
    assert "occurs 2 times" in out
    assert conf.read_text().count("# settings-hub") == 2


def test_uninstall_without_purge_keeps_history(sb):
    sb.install()
    state = sb.path(".local/state/settings-hub")
    (state / "history.jsonl").write_text("{}\n")
    (state / "app.log").write_text("log\n")
    sb.uninstall()
    assert sorted(p.name for p in sb.files()) == ["app.log", "history.jsonl"]
    sb.uninstall("--purge")  # no manifest any more; --purge still clears state
    assert sb.files() == []


def test_reinstall_removes_files_no_longer_shipped(sb):
    sb.install()
    manifest = sb.path(".local/state/settings-hub/install-manifest")
    stale = sb.path(".local/share/settings-hub/settings_hub/old_module.py")
    stale.write_text("")
    manifest.write_text(manifest.read_text() + f"file\t{stale}\n")
    sb.install()
    assert not stale.exists()


def test_manifest_paths_outside_the_prefix_are_never_removed(sb, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    sb.install()
    manifest = sb.path(".local/state/settings-hub/install-manifest")
    manifest.write_text(manifest.read_text() + f"file\t{victim}\n")
    sb.uninstall("--purge")
    assert victim.read_text() == "keep me"


def test_dry_run_into_a_sandbox_writes_nothing(sb):
    out = sb.run("install.sh", "--prefix", str(sb.prefix), "--dry-run").stdout
    assert "would write" in out
    assert not sb.prefix.exists()


def test_generated_file_does_not_size_dialogs(sb):
    """The 920x640 rule matches the main window's title; dialogs share the class only."""
    sb.install()
    rules = [line for line in sb.path(".config/hypr/settings-hub.conf").read_text().splitlines()
             if line.startswith("windowrule")]
    assert len(rules) == 2
    main, dialogs = rules
    assert f"match:initial_title ^({strings.APP_TITLE})$" in main and "size 920 640" in main
    assert "match:modal true" in dialogs and "size" not in dialogs


def test_bind_lines_in_the_conf_block_are_flagged_under_lua(sb):
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    (hypr / "hyprland.lua").write_text("-- lua\n")
    sb.install()
    own = hypr / "settings-hub.conf"
    own.write_text(own.read_text().replace(
        "# >>> settings-hub binds\n", "# >>> settings-hub binds\nbind = SUPER, K, exec, kitty\n"))
    assert "1 bind line(s) from the Binds page" in sb.install().stdout


def test_a_trailing_comment_naming_us_does_not_count_as_loading(sb):
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    lua = hypr / "hyprland.lua"
    lua.write_text("x = 1 -- see settings-hub.lua\n")
    sb.install()
    assert lua.read_text().splitlines()[-1] == LUA_LINE


def test_uninstall_warns_about_a_line_of_the_users_own(sb):
    hypr = sb.path(".config/hypr")
    hypr.mkdir(parents=True)
    (hypr / "hyprland.lua").write_text(
        'dofile(os.getenv("HOME") .. "/.config/hypr/settings-hub.lua")\n')
    sb.install()
    assert "loads settings-hub.lua by its own line" in sb.uninstall("--purge").stdout

