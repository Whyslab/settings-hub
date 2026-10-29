"""An isolated screen-sleep world for tests (plan section 4), without GTK.

* HOME and the XDG dirs point into a temporary directory; WAYLAND_DISPLAY and
  HYPRLAND_INSTANCE_SIGNATURE are removed, so nothing can reach the session.
* screen-sleep's modules are copies (anonymised fixtures, or the installed ones
  for `live` tests) under $HOME/.local/share/screen-sleep; config.json is a
  fixture copy; hypridle.conf is generated in $HOME/.config/hypr.
* Stubs come first in PATH and log their arguments to calls.log: hyprctl
  (remembers the hyprsunset temperature), pkill, pgrep (says hypridle runs),
  systemctl (says the daemon is active), notify-send, systemd-inhibit (stays
  alive like the real one, until killed).
* idle.py calls /usr/bin/pkill and /usr/bin/pgrep by absolute path, which no
  PATH stub can catch. The loaded modules' `subprocess` is therefore wrapped:
  an absolute program is redirected to the stub of the same name, and a test
  fails outright if there is no such stub. The real hypridle is never touched.
* GTK's main loop is replaced by `Loop`: worker results are queued and run on
  the test thread by pump(), the way GLib.idle_add runs them on the GTK thread.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import time
from pathlib import Path

from conftest import FIXTURES

from settings_hub import history as history_mod
from settings_hub.backends import screen_sleep as backend_mod
from settings_hub.workers import Workers

SS_FIXTURES = FIXTURES / "screen_sleep"
MODULES = ("common", "idle", "night")
GENERAL = "general {\n    lock_cmd = pidof hyprlock || hyprlock\n}\n"

STUBS = {
    "hyprctl": """
if [ "$1" = hyprsunset ] && [ "$2" = temperature ]; then
    if [ $# -ge 3 ]; then echo "$3" >"$T/temperature"; else cat "$T/temperature"; fi
fi
exit 0
""",
    "pkill": "exit 0\n",
    "pgrep": "exit 0\n",
    "systemctl": 'case " $* " in *" is-active "*) echo active ;; esac\nexit 0\n',
    "notify-send": "exit 0\n",
    "systemd-inhibit": "trap 'exit 0' TERM INT\nwhile :; do sleep 1; done\n",
}


class Redirect:
    """Stands in for the `subprocess` module inside the loaded modules."""

    def __init__(self, stubs: Path) -> None:
        self._stubs = stubs

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def _fix(self, cmd):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]).startswith("/"):
            stub = self._stubs / Path(cmd[0]).name
            if not stub.exists():
                raise AssertionError(f"a real program would run: {cmd}")
            return [str(stub), *cmd[1:]]
        return cmd

    def run(self, cmd, *args, **kwargs):
        return subprocess.run(self._fix(cmd), *args, **kwargs)

    def Popen(self, cmd, *args, **kwargs):  # noqa: N802 -- mirrors subprocess.Popen
        return subprocess.Popen(self._fix(cmd), *args, **kwargs)


class Loop:
    """Worker results run on the test thread, like GLib.idle_add."""

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue()
        self.workers = Workers(self.queue.put)

    def pump(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.queue.get(timeout=0.01)()
                continue
            except queue.Empty:
                pass
            if self.workers.wait_idle(0) and self.queue.empty():
                return
            if time.monotonic() > deadline:
                raise AssertionError("workers did not finish")


class FakeTimers:
    def __init__(self) -> None:
        self.t = 1000.0
        self._timers: list[list] = []  # [due, seq, fn, alive]
        self._seq = 0

    def now(self) -> float:
        return self.t

    def after(self, ms, fn):
        self._seq += 1
        timer = [self.t + ms / 1000, self._seq, fn, True]
        self._timers.append(timer)
        return timer

    def cancel(self, handle) -> None:
        if handle is not None:
            handle[3] = False

    def advance(self, seconds: float, loop: Loop | None = None) -> None:
        end = self.t + seconds
        while True:
            due = sorted((t for t in self._timers if t[3] and t[0] <= end),
                         key=lambda t: (t[0], t[1]))
            if not due:
                break
            timer = due[0]
            timer[3] = False
            self.t = max(self.t, timer[0])
            timer[2]()
            if loop is not None:
                loop.pump()
        self.t = end


class FakeView:
    def __init__(self) -> None:
        self.values: dict = {}
        self.shows: list = []
        self.focus: set[str] = set()
        self.order: dict = {}
        self.probes: list = []
        self.setup: tuple | None = None
        self.statuses: list[str] = []

    def show(self, key, value):
        self.values[key] = value
        self.shows.append((key, value))

    def focused(self, key):
        return key in self.focus

    def show_order(self, profile, bad):
        self.order[profile] = bad

    def show_probe(self, probe):
        self.probes.append(probe)

    def show_setup(self, state, detail):
        self.setup = (state, detail)

    def status(self, text):
        self.statuses.append(text)


class World:
    def __init__(self, root: Path, monkeypatch, source: Path = SS_FIXTURES,
                 power: str = "ac", config: bool = True) -> None:
        self.root = root
        self.home = root / "home"
        self.stubs = root / "stubs"
        self.calls = root / "calls.log"
        self.ss_dir = self.home / ".local" / "share" / "screen-sleep"
        self.config = self.home / ".config" / "screen-sleep" / "config.json"
        self.hypridle = self.home / ".config" / "hypr" / "hypridle.conf"
        self.state_dir = self.home / ".local" / "state" / "screen-sleep"
        for d in (self.stubs, self.ss_dir, self.config.parent, self.hypridle.parent,
                  self.home / ".local" / "state", self.home / ".cache", root / "run"):
            d.mkdir(parents=True, exist_ok=True)
        (root / "run").chmod(0o700)
        for name, body in STUBS.items():
            path = self.stubs / name
            path.write_text(f'#!/bin/sh\nT="{root}"\necho "{name} $*" >>"$T/calls.log"\n'
                            + body.lstrip("\n"))
            path.chmod(0o755)
        (root / "temperature").write_text("4300\n")
        for name in MODULES:
            shutil.copy(source / f"{name}.py", self.ss_dir / f"{name}.py")
        if config:
            shutil.copy(SS_FIXTURES / "config.json", self.config)

        for var in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(self.home / ".config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(self.home / ".local" / "state"))
        monkeypatch.setenv("XDG_DATA_HOME", str(self.home / ".local" / "share"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(self.home / ".cache"))
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(root / "run"))
        monkeypatch.setenv("PATH", f"{self.stubs}{os.pathsep}{os.environ['PATH']}")

        self.loop = Loop()
        self.backend = backend_mod.Backend(self.loop.workers, self.ss_dir,
                                           dispatch=self.loop.queue.put)
        self.ss = self.backend.ss  # loaded now, with HOME already pointing here
        for module in (self.ss.idle, self.ss.night):
            monkeypatch.setattr(module, "subprocess", Redirect(self.stubs))
        self.power = {"ac": power == "ac"}
        monkeypatch.setattr(self.ss.idle, "on_ac", lambda: self.power["ac"])
        assert str(self.ss.common.CONFIG_FILE) == str(self.config)
        assert str(self.ss.idle.HYPRIDLE_CONF) == str(self.hypridle)

        if config:
            cfg = self.ss.common.load_config()
            self.hypridle.write_text(self.ss.idle.render(GENERAL, cfg["idle"][power], power))
        self.history = history_mod.History(root / "history.jsonl")
        backend_mod.register(self.history, self.backend)

    # ---- helpers --------------------------------------------------------

    def cfg(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def write_cfg(self, cfg: dict) -> None:
        """What the daemon does: rewrite config.json behind the window's back."""
        self.ss.common.save_config(cfg)

    def calls_of(self, program: str) -> list[str]:
        try:
            lines = self.calls.read_text().splitlines()
        except FileNotFoundError:
            return []
        return [line for line in lines if line.split(" ", 1)[0] == program]

    def block(self) -> str:
        text = self.hypridle.read_text()
        start = text.index(self.ss.idle.MARK_START)
        end = text.index(self.ss.idle.MARK_END) + len(self.ss.idle.MARK_END)
        return text[start:end]

    def close(self) -> None:
        self.loop.workers.stop_all(2)
        pid_file = self.state_dir / "caffeine.pid"
        try:
            pid = int(pid_file.read_text())
        except (OSError, ValueError):
            return
        try:
            os.killpg(pid, 15)
        except OSError:
            pass
