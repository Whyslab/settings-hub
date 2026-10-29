"""An isolated Hyprland config for the binds tests (plan section 4).

* HOME, XDG_CONFIG_HOME and XDG_RUNTIME_DIR point into a temporary directory;
  WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE are removed.
* $HOME/.config/hypr/hyprland.conf is a copy (the anonymised fixture, or this
  machine's config for `live` tests); with sourced=True the installer's line
  `source = ~/.config/hypr/settings-hub.conf` is appended to the copy.
* hyprctl is a stub first in PATH that logs its arguments to calls.log:
  `binds -j` prints binds.json (Hyprland's live list), `configerrors` prints an
  error while settings-hub.conf contains the text in $T/bad (if any) plus
  whatever is in $T/old-errors, `submap` prints $T/submap, `dispatch submap X`
  writes it, `reload` only logs.
* The backend's `subprocess` is wrapped (step3_env.Guard): any program that is
  not a stub fails the test, so the real hyprctl can never run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import FIXTURES
from screen_sleep_env import Loop
from step3_env import Guard, make_stub

from settings_hub import history as history_mod
from settings_hub.backends import binds as bb

HYPR_FIXTURES = FIXTURES / "hypr"
CONF = HYPR_FIXTURES / "hyprland.conf"
LIVE = HYPR_FIXTURES / "binds.json"
SOURCE_LINE = "source = ~/.config/hypr/settings-hub.conf  # settings-hub"

HYPRCTL = r"""
case "$1" in
    binds) cat "$T/binds.json" ;;
    configerrors)
        cat "$T/old-errors" 2>/dev/null
        own="$HOME/.config/hypr/settings-hub.conf"
        if [ -s "$T/bad" ] && grep -qF "$(cat "$T/bad")" "$own" 2>/dev/null; then
            echo "Config error in file $own: invalid key"
        fi ;;
    submap) cat "$T/submap" ;;
    dispatch)
        if [ "$2" = submap ]; then
            if [ "$3" = reset ]; then echo default >"$T/submap"; else echo "$3" >"$T/submap"; fi
        fi ;;
esac
exit 0
"""


class World:
    def __init__(self, root: Path, monkeypatch, conf: Path = CONF, live: Path = LIVE,
                 sourced: bool = True, capture_ready: bool = False) -> None:
        """capture_ready: Hyprland's live list has the capture submap's bind (as it
        will once settings-hub.conf is sourced), so key capture may use the submap."""
        self.root = root
        self.home = root / "home"
        self.hypr = self.home / ".config" / "hypr"
        self.stubs = root / "stubs"
        self.calls = root / "calls.log"
        self.run = root / "run"
        for d in (self.hypr, self.stubs, self.run, self.home / ".local" / "state"):
            d.mkdir(parents=True, exist_ok=True)
        self.run.chmod(0o700)
        self.conf = self.hypr / "hyprland.conf"
        text = conf.read_text(encoding="utf-8")
        if sourced:
            text = text.rstrip("\n") + "\n" + SOURCE_LINE + "\n"
        self.conf.write_text(text, encoding="utf-8")
        (self.hypr / "animations.conf").write_text("# animations\n")
        theme = self.home / ".local" / "state" / "wallpaper-theme"
        theme.mkdir(parents=True, exist_ok=True)
        (theme / "hyprland.conf").write_text("# wallpaper-theme\n")
        self.own = self.hypr / "settings-hub.conf"
        self.lua = self.hypr / "hyprland.lua"
        items = json.loads(live.read_text(encoding="utf-8"))
        if capture_ready:
            items.append(dict(items[0], modmask=77, key="Escape", dispatcher="submap",
                              arg="reset", submap="settings-hub-capture"))
        (root / "binds.json").write_text(json.dumps(items))
        (root / "submap").write_text("default\n")
        make_stub(self.stubs / "hyprctl", root, "hyprctl", HYPRCTL)

        for var in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "SETTINGS_HUB_HYPR_CONF",
                    "SETTINGS_HUB_BINDS_CONF", "SETTINGS_HUB_HYPR_LUA"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(self.home / ".config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(self.home / ".local" / "state"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(self.run))
        monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        monkeypatch.setenv("PATH", f"{self.stubs}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setattr(bb, "subprocess", Guard(root, self.stubs))

        self.loop = Loop()
        self.backend = bb.Backend(self.loop.workers, dispatch=self.loop.queue.put)
        self.history = history_mod.History(root / "history.jsonl")
        bb.register(self.history, self.backend)

    def calls_of(self, program: str = "hyprctl") -> list[str]:
        try:
            lines = self.calls.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [line for line in lines if line.split(" ", 1)[0] == program]

    def clear_calls(self) -> None:
        self.calls.unlink(missing_ok=True)

    def block(self) -> list[str]:
        text = self.own.read_text(encoding="utf-8")
        start = text.index("# >>> settings-hub binds")
        end = text.index("# <<< settings-hub binds")
        return [line for line in text[start:end].splitlines()[1:] if line.strip()]

    def close(self) -> None:
        self.loop.workers.stop_all(2)
