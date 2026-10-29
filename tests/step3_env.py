"""An isolated world for the wallpaper and animations pages (plan section 4).

* HOME and the XDG dirs point into a temporary directory; WAYLAND_DISPLAY and
  HYPRLAND_INSTANCE_SIGNATURE are removed.
* $HOME/.config/hypr/scripts/wallpaper.sh is a stub that does what the real
  script does to its state files (set -> <target>.path and random off; random
  on -> a "random" picture), never awww, magick or SDDM. wallpaper-theme,
  magick, hyprctl and notify-send are stubs first in PATH. Every stub logs its
  arguments to calls.log.
* rofi-launcher's animations module is a copy (anonymised fixtures, or the
  installed one for `live` tests) under $tmp/rofi, with a stub
  bin/anim-preview.sh that logs its arguments and ANIM_PREVIEW_REOPEN.
* The backends' `subprocess` is wrapped: a program must be a stub, or a file
  inside the temporary directory, or the test fails ("a real program would
  run"). The real wallpaper.sh, wallpaper-theme, anim-preview.sh and
  `hyprctl reload` can never run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from conftest import FIXTURES
from screen_sleep_env import Loop

from settings_hub import history as history_mod
from settings_hub.backends import animations as an_mod
from settings_hub.backends import wallpaper as wp_mod

ROFI_FIXTURE = FIXTURES / "rofi"
WALLPAPERS = FIXTURES / "wallpapers"

WALLPAPER_SH = r"""
S="$HOME/.local/state/hypr-wallpaper"
mkdir -p "$S"
rand_set() {
    for u in desktop lock sddm; do
        if [ "$u" = "$1" ]; then echo "$u=$2"
        elif grep -qx "$u=on" "$S/random.conf" 2>/dev/null; then echo "$u=on"
        else echo "$u=off"; fi
    done >"$S/random.conf.new"
    mv "$S/random.conf.new" "$S/random.conf"
}
case "$1" in
    set)
        [ -r "$3" ] || { echo "file not found: $3" >&2; exit 1; }
        [ -e "$T/fail-set" ] && { echo "awww failed" >&2; exit 1; }
        img=$(realpath "$3")
        case "$2" in
            all) ts="desktop lock sddm" ;;
            desktop|lock|sddm) ts=$2 ;;
            *) echo "unknown target: $2" >&2; exit 1 ;;
        esac
        for t in $ts; do
            grep -qx "$t=on" "$S/random.conf" 2>/dev/null && rand_set "$t" off
            echo "$img" >"$S/$t.path"
        done ;;
    random)
        rand_set "$2" "$3"
        [ "$3" = on ] && cat "$T/random-pick" >"$S/$2.path" ;;
    current) cat "$S/${2:-desktop}.path" 2>/dev/null ;;
    pick) ;;
    *) exit 1 ;;
esac
exit 0
"""

STUBS = {
    "wallpaper-theme": """
case "$1" in
    status) sed "s/MODE/$(cat "$T/theme-mode")/" "$T/status.txt" ;;
    mode) case "$2" in off|vivid|tinted) echo "$2" >"$T/theme-mode" ;;
          *) echo "bad mode" >&2; exit 1 ;; esac ;;
esac
exit 0
""",
    # The picker's command line: the output file is the last argument.
    "magick": """
for out; do :; done
[ -e "$T/fail-magick" ] && exit 1
printf 'thumb of %s\\n' "$2" >"$out"
exit 0
""",
    "hyprctl": "exit 0\n",
    "notify-send": "exit 0\n",
}

ANIM_PREVIEW = 'echo "reopen ${ANIM_PREVIEW_REOPEN-unset}" >>"$T/calls.log"\n'


class Guard:
    """Stands in for `subprocess` inside the backends: stubs and $tmp only."""

    def __init__(self, root: Path, stubs: Path) -> None:
        self._root, self._stubs = str(root), stubs

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def _check(self, cmd):
        program = str(cmd[0])
        if program == "bash":  # bash <script>: the script must be ours
            program = str(cmd[1])
        if "/" not in program:
            if not (self._stubs / program).exists():
                raise AssertionError(f"a real program would run: {cmd}")
        elif not os.path.realpath(program).startswith(self._root + os.sep):
            raise AssertionError(f"a real program would run: {cmd}")
        return cmd

    def run(self, cmd, *args, **kwargs):
        return subprocess.run(self._check(cmd), *args, **kwargs)

    def Popen(self, cmd, *args, **kwargs):  # noqa: N802 -- mirrors subprocess.Popen
        return subprocess.Popen(self._check(cmd), *args, **kwargs)


def make_stub(path: Path, root: Path, name: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nT="{root}"\necho "{name} $*" >>"$T/calls.log"\n'
                    + body.lstrip("\n"))
    path.chmod(0o755)


class World:
    def __init__(self, root: Path, monkeypatch, rofi_source: Path = ROFI_FIXTURE,
                 wallpaper_script: bool = True, theme: bool = True,
                 animations: bool = True) -> None:
        self.root = root
        self.home = root / "home"
        self.stubs = root / "stubs"
        self.calls = root / "calls.log"
        self.library = self.home / ".config" / "hypr" / "wallpapers"
        self.state = self.home / ".local" / "state" / "hypr-wallpaper"
        self.thumbs = self.home / ".cache" / "wallpaper-thumbs"
        self.script = self.home / ".config" / "hypr" / "scripts" / "wallpaper.sh"
        self.rofi = root / "rofi"
        self.cfg = self.home / ".config" / "rofi-launcher"
        self.hypr = self.home / ".config" / "hypr"
        for d in (self.stubs, self.library, self.state, self.home / ".cache", root / "run",
                  self.cfg):
            d.mkdir(parents=True, exist_ok=True)
        for image in sorted(WALLPAPERS.iterdir()):
            shutil.copy(image, self.library / image.name)
        (root / "random-pick").write_text(str(self.library / "plasma.jpg") + "\n")
        (root / "theme-mode").write_text("off\n")
        shutil.copy(FIXTURES / "wallpaper_theme_status.txt", root / "status.txt")
        for name, body in STUBS.items():
            if name == "wallpaper-theme" and not theme:
                continue
            make_stub(self.stubs / name, root, name, body)
        if wallpaper_script:
            make_stub(self.script, root, "wallpaper.sh", WALLPAPER_SH)
        ignore = shutil.ignore_patterns("__pycache__")
        shutil.copytree(rofi_source / "rofi_hub", self.rofi / "rofi_hub", ignore=ignore)
        shutil.copytree(rofi_source / "data", self.rofi / "data", ignore=ignore)
        make_stub(self.rofi / "bin" / "anim-preview.sh", root, "anim-preview.sh",
                  ANIM_PREVIEW)
        if animations:
            for name in ("animation-preset", "animation-tuning.json"):
                shutil.copy(FIXTURES / "animations" / name, self.cfg / name)

        for var in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "ANIM_PREVIEW_REOPEN",
                    "SETTINGS_HUB_WALLPAPER_SH", "SETTINGS_HUB_WALLPAPER_DIR",
                    "SETTINGS_HUB_WALLPAPER_STATE", "SETTINGS_HUB_WALLPAPER_THUMBS",
                    "SETTINGS_HUB_WALLPAPER_THEME"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(self.home / ".config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(self.home / ".local" / "state"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(self.home / ".cache"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root / "run"))
        monkeypatch.setenv("SETTINGS_HUB_ROFI_DIR", str(self.rofi))
        monkeypatch.setenv("LANG", "C")  # the module must be Russian anyway
        monkeypatch.setenv("LC_MESSAGES", "C")
        monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        path = os.environ["PATH"]
        if not theme:  # no wallpaper-theme anywhere on PATH
            path = os.pathsep.join(p for p in path.split(os.pathsep)
                                   if not (Path(p) / "wallpaper-theme").exists())
        monkeypatch.setenv("PATH", f"{self.stubs}{os.pathsep}{path}")
        guard = Guard(root, self.stubs)
        monkeypatch.setattr(wp_mod, "subprocess", guard)
        monkeypatch.setattr(an_mod, "subprocess", guard)

        self.loop = Loop()
        self.wallpaper = wp_mod.Backend(self.loop.workers, dispatch=self.loop.queue.put)
        self.animations = an_mod.Backend(self.loop.workers, self.rofi,
                                         dispatch=self.loop.queue.put)
        self.history = history_mod.History(root / "history.jsonl")
        wp_mod.register(self.history, self.wallpaper)
        an_mod.register(self.history, self.animations)

    def image(self, name: str):
        return next(i for i in self.wallpaper.images() if i.name == name)

    def calls_of(self, program: str) -> list[str]:
        try:
            lines = self.calls.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [line for line in lines if line.split(" ", 1)[0] == program]

    def close(self) -> None:
        self.loop.workers.stop_all(2)
