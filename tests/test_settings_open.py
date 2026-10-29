"""bin/settings-open, every branch, on stub gdbus/python3/notify-send.

The stubs share a directory: `owner` exists while the fake app owns its D-Bus
name, `hung` makes the running copy ignore calls, `mode` says what a started
`python3 app.py --daemon` does (ok: takes the name after a delay; hang: never
does; crash: exits). Every stub call is appended to calls.log. flock, sleep and
the shell are real.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest
from conftest import ROOT

SCRIPT = ROOT / "bin" / "settings-open"

GDBUS = r"""#!/bin/sh
d=$STUB_DIR
case "$*" in
    *NameHasOwner*)
        echo "has-owner" >>"$d/calls.log"
        if [ -f "$d/owner" ]; then echo "(true,)"; else echo "(false,)"; fi
        ;;
    *Activate*)
        page=
        for a; do case $a in "[<"*) page=$a ;; esac; done
        echo "activate $page" >>"$d/calls.log"
        if [ -f "$d/hung" ]; then sleep 1; echo "Error: Timeout was reached" >&2; exit 1; fi
        [ -f "$d/owner" ] || { echo "Error: not owned" >&2; exit 1; }
        echo "()"
        ;;
    *) echo "gdbus $*" >>"$d/calls.log"; exit 1 ;;
esac
"""

PYTHON = r"""#!/bin/sh
d=$STUB_DIR
echo "python3 $*" >>"$d/calls.log"
case "$*" in
    *--daemon*)
        echo $$ >>"$d/daemon.pids"
        case $(cat "$d/mode" 2>/dev/null) in
            hang) exec sleep 30 ;;
            crash) exit 1 ;;
            *) sleep "${STUB_START_DELAY:-0.3}"; : >"$d/owner"; exec sleep 30 ;;
        esac
        ;;
esac
exit 0
"""

LOGGER = """#!/bin/sh
echo "{name} $*" >>"$STUB_DIR/calls.log"
"""


def alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.stub = tmp / "stub"
        self.bin = tmp / "bin"
        self.data = tmp / "home" / ".local" / "share"
        self.state = tmp / "home" / ".local" / "state"
        self.run_dir = tmp / "run"
        for d in (self.stub, self.bin, self.data, self.state, self.run_dir):
            d.mkdir(parents=True)
        self._write(self.bin / "gdbus", GDBUS)
        self._write(self.bin / "python3", PYTHON)
        self._write(self.bin / "notify-send", LOGGER.format(name="notify-send"))
        # the old windows that settings-open falls back to
        (self.data / "screen-sleep").mkdir()
        (self.data / "screen-sleep" / "gui.py").write_text("")
        (self.data / "rofi-launcher" / "bin").mkdir(parents=True)
        for name in ("hub-wallpaper.sh", "hub-animations.sh"):
            self._write(self.data / "rofi-launcher" / "bin" / name, LOGGER.format(name=name))
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(tmp / "home"),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.state),
            "XDG_RUNTIME_DIR": str(self.run_dir),
            "SETTINGS_HUB_APP": str(tmp / "app.py"),
            "SETTINGS_HUB_START_WAIT": "1",
            "STUB_DIR": str(self.stub),
        }

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)

    def set(self, name: str, value: str = "") -> None:
        (self.stub / name).write_text(value)

    def start(self, page: str = "", **extra) -> subprocess.Popen:
        return subprocess.Popen([str(SCRIPT), *([page] if page else [])],
                                env={**self.env, **extra},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def run(self, page: str = "", **extra) -> int:
        proc = self.start(page, **extra)
        proc.communicate(timeout=20)
        return proc.returncode

    def calls(self) -> list[str]:
        log = self.stub / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def wait_call(self, pred, timeout: float = 2.0) -> list[str]:
        """Background children (old windows, notify-send) log a moment later."""
        deadline = time.monotonic() + timeout
        while not any(pred(c) for c in self.calls()) and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.calls()

    def daemons(self) -> list[int]:
        f = self.stub / "daemon.pids"
        return [int(x) for x in f.read_text().split()] if f.exists() else []

    def open_log(self) -> str:
        return (self.state / "settings-hub" / "open.log").read_text()

    def lock_is_free(self) -> bool:
        lock = self.run_dir / "settings-hub-start.lock"
        return subprocess.run(["flock", "-n", str(lock), "true"]).returncode == 0

    def cleanup(self) -> None:
        for pid in self.daemons():
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.cleanup()


def daemon_starts(calls):
    return [c for c in calls if c.startswith("python3") and "--daemon" in c]


def test_running_copy_gets_the_page(env):
    env.set("owner")
    assert env.run("history") == 0
    assert env.calls() == ["has-owner", "activate [<'history'>]"]
    log = env.open_log()
    assert log.startswith("call ") and " history running" in log
    call_ns = int(log.split()[1])
    assert abs(call_ns - time.time_ns()) < 60 * 10**9  # nanoseconds since the epoch


def test_no_page_sends_empty_string(env):
    env.set("owner")
    assert env.run() == 0
    assert "activate [<''>]" in env.calls()


def test_cold_start_starts_one_daemon_then_opens(env):
    assert env.run("history") == 0
    calls = env.calls()
    assert len(daemon_starts(calls)) == 1
    assert daemon_starts(calls)[0] == f"python3 {env.tmp / 'app.py'} --daemon"
    assert calls[-1] == "activate [<'history'>]"
    pid = env.daemons()[0]
    assert alive(pid)  # the background copy keeps running after settings-open exits
    assert env.lock_is_free()  # and it did not inherit the start lock
    assert f"pid={pid}" in env.open_log()


def test_timeout_kills_exactly_the_started_pid_and_opens_old_window(env):
    env.set("mode", "hang")
    decoy = subprocess.Popen(["sleep", "30"])  # same command as the hung stub
    try:
        started = time.monotonic()
        assert env.run("screen-sleep") == 1
        assert time.monotonic() - started < 5
        pid = env.daemons()[0]
        deadline = time.monotonic() + 2
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not alive(pid)
        assert alive(decoy.pid)
        gui = f"python3 {env.data / 'screen-sleep' / 'gui.py'}"
        calls = env.wait_call(lambda c: c == gui)
        assert len(daemon_starts(calls)) == 1
        assert gui in calls
        assert not any(c.startswith("activate") for c in calls)
        assert env.lock_is_free()
        assert f"killed pid={pid}" in env.open_log()
    finally:
        decoy.kill()
        decoy.wait()


def test_crashing_app_falls_back(env):
    env.set("mode", "crash")
    assert env.run("wallpaper") == 1
    calls = env.wait_call(lambda c: c.startswith("hub-wallpaper.sh"))
    assert len(daemon_starts(calls)) == 1
    assert "hub-wallpaper.sh " in calls


def test_second_press_during_start_waits_and_sends_its_page(env):
    first = env.start("screen-sleep", STUB_START_DELAY="0.8", SETTINGS_HUB_START_WAIT="3")
    time.sleep(0.25)  # the first press holds the lock and is waiting for the name
    second = env.start("wallpaper", STUB_START_DELAY="0.8", SETTINGS_HUB_START_WAIT="3")
    first.communicate(timeout=20)
    second.communicate(timeout=20)
    assert (first.returncode, second.returncode) == (0, 0)
    calls = env.calls()
    assert len(daemon_starts(calls)) == 1
    activates = [c for c in calls if c.startswith("activate")]
    assert sorted(activates) == ["activate [<'screen-sleep'>]", "activate [<'wallpaper'>]"]
    assert " wallpaper waited" in env.open_log()


def test_hung_running_copy_does_not_start_another(env):
    env.set("owner")
    env.set("hung")
    assert env.run("history") == 1
    calls = env.wait_call(lambda c: c.startswith("notify-send"))
    assert daemon_starts(calls) == []
    assert calls.count("activate [<'history'>]") == 1
    assert any(c.startswith("notify-send") for c in calls)
    assert "no answer" in env.open_log()


def test_fallback_message_comes_from_installed_text(env):
    (env.data / "settings-hub").mkdir()
    (env.data / "settings-hub" / "open-failed.txt").write_text("custom message\n")
    env.set("owner")
    env.set("hung")
    env.run("binds")
    calls = env.wait_call(lambda c: c.startswith("notify-send"))
    assert "notify-send -a settings-hub custom message" in calls


@pytest.mark.parametrize("page,old", [
    ("wallpaper", "hub-wallpaper.sh "),
    ("animations", "hub-animations.sh "),
])
def test_old_windows_for_each_page(env, page, old):
    env.set("owner")
    env.set("hung")
    assert env.run(page) == 1
    assert old in env.wait_call(lambda c: c == old)


def test_missing_old_window_notifies(env):
    (env.data / "screen-sleep" / "gui.py").unlink()
    env.set("owner")
    env.set("hung")
    env.run("screen-sleep")
    calls = env.wait_call(lambda c: c.startswith("notify-send"))
    assert any(c.startswith("notify-send") for c in calls)
    assert not any("gui.py" in c for c in calls)


@pytest.mark.parametrize("page", ["../x", "a b", "X", "$(id)", "a'b"])
def test_bad_page_names_are_refused(env, page):
    assert env.run(page) == 2
    assert env.calls() == []


def test_open_log_is_trimmed(env):
    log = env.state / "settings-hub" / "open.log"
    log.parent.mkdir(parents=True)
    log.write_text("".join(f"call {i} x \n" for i in range(30000)))
    env.set("owner")
    assert env.run("history") == 0
    lines = log.read_text().splitlines()
    assert len(lines) == 1002  # the last 1000 kept, then this call's two lines
    assert lines[0] == "call 29000 x "
