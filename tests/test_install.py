"""install.sh / uninstall.sh in a sandbox. hyprctl and gdbus are stubs that fail
loudly: a sandbox install or uninstall must never call them."""

import json
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

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
            "float true, size 920 640, center true") in conf
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


@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_without_prefix_nothing_happens(sb, script):
    proc = sb.run(script, check=False)
    assert proc.returncode == 2
    assert "sandbox" in proc.stderr
    assert list(sb.home.iterdir()) == []
