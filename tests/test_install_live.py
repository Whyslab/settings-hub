"""install.sh / uninstall.sh in live mode (no --prefix), with HOME pointing at a
temporary directory: a copy of hyprland.conf (the anonymised fixture; with
`-m live` also this machine's real one), a fake screen-sleep.desktop, and stub
hyprctl/gdbus that record every call outside HOME. The real Hyprland session is
never reached: no HYPRLAND_INSTANCE_SIGNATURE, stubs first in PATH."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from conftest import FIXTURES, ROOT

from settings_hub.binds import parser

REAL_CONF = Path.home() / ".config/hypr/hyprland.conf"
LINE = "source = ~/.config/hypr/settings-hub.conf  # settings-hub"
DESKTOP = """[Desktop Entry]
Type=Application
Name=Screen and sleep
Exec=python3 /opt/screen-sleep/gui.py
Categories=Settings;
"""

# configerrors reports the config as of the last reload, like Hyprland does;
# with flags/break, a loaded source line of ours is an error.
HYPRCTL = """#!/bin/sh
echo "hyprctl $*" >>"{log}"
case $1 in
    reload)
        if grep -q '# settings-hub$' "$HOME/.config/hypr/hyprland.conf"
        then touch "{flags}/loaded"; else rm -f "{flags}/loaded"; fi
        echo ok ;;
    configerrors)
        if [ -e "{flags}/break" ] && [ -e "{flags}/loaded" ]
        then echo "Config error in settings-hub.conf at line 3: invalid field type"; fi
        printf '\\n\\n' ;;
    dispatch) [ "$2" = exec ] && touch "{flags}/owner"; echo ok ;;
    *) echo ok ;;
esac
"""
GDBUS = """#!/bin/sh
echo "gdbus $*" >>"{log}"
case "$*" in
    *NameHasOwner*) if [ -e "{flags}/owner" ]; then echo '(true,)'; else echo '(false,)'; fi ;;
    *"Activate quit"*) rm -f "{flags}/owner" ;;
esac
"""


def tree(root: Path) -> dict[str, tuple[str, int]]:
    """Every file under root: relative path -> (sha256, mode)."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() or p.is_symlink():
            out[str(p.relative_to(root))] = (hashlib.sha256(p.read_bytes()).hexdigest(),
                                             p.lstat().st_mode)
    return out


class Live:
    def __init__(self, tmp: Path, conf_source: Path):
        self.home = tmp / "home"
        self.stubs = tmp / "stubs"
        self.flags = tmp / "flags"
        self.log = tmp / "calls.log"
        for d in (self.home, self.stubs, self.flags):
            d.mkdir()
        for name, text in (("hyprctl", HYPRCTL), ("gdbus", GDBUS)):
            stub = self.stubs / name
            stub.write_text(text.format(log=self.log, flags=self.flags))
            stub.chmod(0o755)
        self.conf = self.home / ".config/hypr/hyprland.conf"
        self.conf.parent.mkdir(parents=True)
        self.conf.write_bytes(conf_source.read_bytes())
        self.conf.chmod(0o640)
        self.desktop = self.home / ".local/share/applications/screen-sleep.desktop"
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text(DESKTOP)
        self.own = self.home / ".config/hypr/settings-hub.conf"
        self.manifest = self.home / ".local/state/settings-hub/install-manifest"
        self.env = {"PATH": f"{self.stubs}:/usr/bin:/bin", "HOME": str(self.home),
                    "LC_ALL": "C"}

    def run(self, script: str, *args: str, rc: int = 0) -> subprocess.CompletedProcess:
        proc = subprocess.run(["sh", str(ROOT / script), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == rc, proc.stdout + proc.stderr
        return proc

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def hypr_calls(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("hyprctl")]


@pytest.fixture(params=[
    FIXTURES / "hypr" / "hyprland.conf",
    pytest.param(REAL_CONF, marks=pytest.mark.live),
], ids=["fixture", "real-copy"])
def live(tmp_path, request):
    return Live(tmp_path, request.param)


def test_install_adds_one_line_at_the_end_and_starts_the_app_through_hyprland(live):
    original = live.conf.read_bytes()
    desktop = live.desktop.read_bytes()
    inode = live.conf.stat().st_ino
    live.run("install.sh")
    text = live.conf.read_bytes()
    assert text == original + (LINE + "\n").encode()  # the fixture ends in a newline
    assert live.conf.stat().st_ino == inode and live.conf.stat().st_mode & 0o777 == 0o640
    backups = list(live.conf.parent.glob("hyprland.conf.bak-*-settings-hub"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert live.desktop.read_bytes() == desktop + b"NoDisplay=true\n"
    own = live.own.read_text()
    assert f"exec-once = python3 {live.home}/.local/share/settings-hub/app.py --daemon" in own
    assert own.endswith("# >>> settings-hub binds\n# <<< settings-hub binds\n")
    assert live.hypr_calls()[:3] == ["hyprctl configerrors", "hyprctl reload",
                                     "hyprctl configerrors"]
    app = live.home / ".local/share/settings-hub/app.py"
    log = live.home / ".local/state/settings-hub/app.log"
    assert live.hypr_calls()[3:] == [
        f"hyprctl dispatch exec python3 '{app}' --daemon >>'{log}' 2>&1"]
    manifest = live.manifest.read_text().splitlines()
    assert f"line\t{live.conf}\t{LINE}\t0" in manifest
    assert f"line\t{live.desktop}\tNoDisplay=true\t0" in manifest
    for rel in (".local/bin/settings-open", ".local/bin/settings-hub-uninstall",
                ".local/share/applications/settings-hub.desktop",
                ".local/share/settings-hub/pages.json", ".config/hypr/settings-hub.conf"):
        assert f"file\t{live.home}/{rel}" in manifest


def test_the_generated_file_is_read_after_hyprland_conf_and_rebinds_n_and_w(live, monkeypatch):
    live.run("install.sh")
    monkeypatch.setenv("HOME", str(live.home))  # the source line says ~/.config/...
    cfg = parser.parse(live.conf, live.own)
    assert cfg.own_sourced
    by_combo = {(b.modmask, b.key): b.arg for b in cfg.binds if not b.submap}
    opener = f"{live.home}/.local/bin/settings-open"
    assert by_combo[(65, "N")] == f"{opener} screen-sleep"
    assert by_combo[(65, "W")] == f"{opener} wallpaper"
    assert by_combo[(64, "I")] == opener


def test_reinstall_keeps_the_binds_block_and_adds_nothing_twice(live):
    live.run("install.sh")
    manifest = live.manifest.read_text()
    conf = live.conf.read_bytes()
    desktop = live.desktop.read_bytes()
    custom = "unbind = SUPER, E  # hyprland.conf:44\nbind = SUPER, E, exec, thunar  # x\n"
    text = live.own.read_text().replace("# >>> settings-hub binds\n",
                                        "# >>> settings-hub binds\n" + custom)
    live.own.write_text("# an older header\n" + text.split("\n", 1)[1] + "after the block\n")
    live.run("install.sh")  # the background copy is running now: quit, then start again
    own = live.own.read_text()
    assert own.startswith("# Generated by settings-hub.")
    assert own.endswith("# >>> settings-hub binds\n" + custom
                        + "# <<< settings-hub binds\nafter the block\n")
    assert own.count("windowrule") == 2
    assert live.conf.read_bytes() == conf and live.desktop.read_bytes() == desktop
    assert sorted(live.manifest.read_text().splitlines()) == sorted(manifest.splitlines())
    assert len(list(live.conf.parent.glob("hyprland.conf.bak-*"))) == 1
    calls = live.calls()
    quit_at = next(i for i, c in enumerate(calls) if "Activate quit" in c)
    exec_at = [i for i, c in enumerate(calls) if c.startswith("hyprctl dispatch exec")]
    assert len(exec_at) == 2 and exec_at[0] < quit_at < exec_at[1]


def test_new_config_errors_take_our_line_out_again(live):
    original = live.conf.read_bytes()
    inode = live.conf.stat().st_ino
    (live.flags / "break").touch()
    proc = live.run("install.sh", rc=1)
    assert "Config error in settings-hub.conf" in proc.stderr
    assert live.conf.read_bytes() == original and live.conf.stat().st_ino == inode
    assert live.hypr_calls() == ["hyprctl configerrors", "hyprctl reload",
                                 "hyprctl configerrors", "hyprctl reload"]
    assert "\tsettings-hub\t" not in live.manifest.read_text()
    assert f"line\t{live.conf}\t" not in live.manifest.read_text()
    (live.flags / "break").unlink()
    live.run("uninstall.sh", "--purge")
    assert live.conf.read_bytes() == original
    assert live.desktop.read_text() == DESKTOP


def test_old_config_errors_do_not_count(live):
    """An error that was there before the install is not ours."""
    stub = live.stubs / "hyprctl"
    stub.write_text(stub.read_text().replace(
        "printf '\\\\n\\\\n' ;;", "echo 'old error in hyprland.conf'; printf '\\\\n\\\\n' ;;"))
    live.run("install.sh")
    assert live.conf.read_text().endswith(LINE + "\n")


def test_uninstall_restores_both_files_byte_for_byte_and_leaves_nothing(live):
    before = tree(live.home)
    stat = (live.conf.stat().st_ino, live.conf.stat().st_mode)
    dstat = (live.desktop.stat().st_ino, live.desktop.stat().st_mode)
    live.run("install.sh")
    os.utime(live.conf)  # nothing depends on times
    proc = live.run("uninstall.sh", "--purge")
    assert "our line removed" in proc.stdout
    after = tree(live.home)
    backups = [k for k in after if ".bak-" in k]
    assert len(backups) == 1  # the dated copy is the user's
    del after[backups[0]]
    assert after == before  # zero own files, both files byte-identical
    assert (live.conf.stat().st_ino, live.conf.stat().st_mode) == stat
    assert (live.desktop.stat().st_ino, live.desktop.stat().st_mode) == dstat
    calls = live.calls()
    tail = calls[calls.index(next(c for c in calls if "Activate quit" in c)):]
    assert [c for c in tail if c.startswith("hyprctl")] == [
        "hyprctl dispatch submap reset", "hyprctl reload", "hyprctl configerrors"]


def test_uninstall_without_purge_keeps_history_only(live):
    live.run("install.sh")
    (live.home / ".local/state/settings-hub/history.jsonl").write_text("{}\n")
    live.run("uninstall.sh")
    state = sorted(p.name for p in (live.home / ".local/state/settings-hub").iterdir())
    assert state == ["app.log", "history.jsonl"] or state == ["history.jsonl"]


def test_dry_runs_change_nothing_and_call_nothing(live):
    before = tree(live.home)
    proc = live.run("install.sh", "--dry-run")
    assert "would append to" in proc.stdout and "would write" in proc.stdout
    assert tree(live.home) == before and live.calls() == []
    live.run("install.sh")
    installed = tree(live.home)
    calls = len(live.calls())
    proc = live.run("uninstall.sh", "--dry-run", "--purge")
    assert "would remove from" in proc.stdout
    assert tree(live.home) == installed and len(live.calls()) == calls
    again = live.run("install.sh", "--dry-run").stdout  # everything is in place already
    changes = [line for line in again.splitlines() if line.startswith("   would ")
               and "install-manifest" not in line and "would run:" not in line
               and "would restart" not in line]
    assert changes == []


def test_damaged_binds_block_stops_before_anything_changes(live):
    live.own.write_text("# >>> settings-hub binds\nbind = SUPER, E, exec, x\n")  # no end marker
    before = tree(live.home)
    proc = live.run("install.sh", rc=2)
    assert "markers are damaged" in proc.stderr
    assert tree(live.home) == before and live.calls() == []


def test_a_lua_config_stops_the_install(live):
    (live.conf.parent / "hyprland.lua").write_text("-- lua\n")
    before = tree(live.home)
    assert "hyprland.lua" in live.run("install.sh", rc=2).stderr
    assert tree(live.home) == before


@pytest.mark.parametrize("desktop", [
    DESKTOP + "NoDisplay=false\n",  # its own line: not ours to change
    DESKTOP + "[Desktop Action new]\nName=New\nExec=x\n",  # would land in the action
])
def test_desktop_files_we_must_not_touch(live, desktop):
    live.desktop.write_text(desktop)
    live.run("install.sh")
    assert live.desktop.read_text() == desktop
    assert f"line\t{live.desktop}\t" not in live.manifest.read_text()
    live.run("uninstall.sh", "--purge")
    assert live.desktop.read_text() == desktop


def test_desktop_without_final_newline_comes_back_byte_for_byte(live):
    live.desktop.write_text(DESKTOP.rstrip("\n"))
    live.run("install.sh")
    assert live.desktop.read_text() == DESKTOP + "NoDisplay=true\n"
    live.run("uninstall.sh", "--purge")
    assert live.desktop.read_text() == DESKTOP.rstrip("\n")


def test_a_rewritten_desktop_file_is_left_alone_by_uninstall(live):
    """screen-sleep's installer rewrites its .desktop file, dropping our line."""
    live.run("install.sh")
    live.desktop.write_text(DESKTOP)
    proc = live.run("uninstall.sh", "--purge")
    assert "occurs 0 times" in proc.stdout
    assert live.desktop.read_text() == DESKTOP


def test_without_hyprland_conf_nothing_happens(tmp_path):
    live = Live(tmp_path, FIXTURES / "hypr" / "hyprland.conf")
    live.conf.unlink()
    before = tree(live.home)
    assert "hyprland.conf" in live.run("install.sh", rc=2).stderr
    live.run("uninstall.sh")  # no manifest: nothing to remove
    assert tree(live.home) == before and live.calls() == []


@pytest.mark.live
def test_hyprland_itself_accepts_the_installed_config(tmp_path):
    """Hyprland's own parser (--verify-config, no compositor) on the copy of the
    real config with our line and settings-hub.conf: no errors."""
    live = Live(tmp_path, REAL_CONF)
    anim = REAL_CONF.parent / "animations.conf"
    if anim.exists():
        (live.conf.parent / "animations.conf").write_bytes(anim.read_bytes())
    live.run("install.sh")
    proc = subprocess.run(["Hyprland", "--verify-config", "-c", str(live.conf)],
                          env={"PATH": "/usr/bin:/bin", "HOME": str(live.home),
                               "XDG_RUNTIME_DIR": str(tmp_path)},
                          capture_output=True, text=True, timeout=60)
    result = proc.stdout.split("Config parsing result:")[-1]
    assert result.strip() == "config ok", result
