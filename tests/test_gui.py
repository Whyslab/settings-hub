"""The real GTK page, on a private Xvfb display (live: needs this machine's GTK4).

Isolation as in plan section 4: Xvfb on :99 or higher (killed by its pid), a
private D-Bus session without service activation, a temporary HOME with copies
of screen-sleep's modules and stub programs. The page is driven in-process by
gui_screen_sleep.py; no synthetic input is sent anywhere.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest import ROOT
from screen_sleep_env import World

from settings_hub import loader

BUS = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:tmpdir=/tmp</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


def free_display() -> int:
    n = 99
    while Path(f"/tmp/.X{n}-lock").exists() or Path(f"/tmp/.X11-unix/X{n}").exists():
        n += 1
    return n


@pytest.fixture
def xvfb(tmp_path):
    n = free_display()
    proc = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "920x900x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if Path(f"/tmp/.X11-unix/X{n}").exists():
                break
            time.sleep(0.05)
        assert proc.poll() is None, "Xvfb did not start"
        yield f":{n}"
    finally:
        proc.terminate()  # our own Xvfb, by pid
        proc.wait(5)


def run_page(world: World, display: str, tmp_path: Path) -> dict:
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    out = tmp_path / "gui.json"
    env = dict(os.environ, DISPLAY=display, GDK_BACKEND="x11", GSK_RENDERER="cairo",
               NO_AT_BRIDGE="1", GTK_A11Y="none", PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_screen_sleep.py"), str(ROOT), str(world.ss_dir),
         str(world.stubs), str(tmp_path / "history.jsonl"), str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-3000:]
    return json.loads(out.read_text())


def check(r: dict) -> None:
    assert r["missing_widgets"] == []
    assert r["missing_rows"] == []
    i = r["initial"]
    assert i["ac_dim"] == 60 and i["target"] == 2700 and i["slider"] == 4300
    assert i["ac_suspend_on"] is False and i["ac_suspend_spin_sensitive"] is False
    assert i["schedule_on"] is True
    assert i["label"] == "4300 K" and i["on_hour_text"] == "21"
    assert i["ac_heading"] != i["battery_heading"]  # the active set is marked
    assert i["setup_visible"] is False
    assert (r["dim_after_1s"], r["dim_after_2s"]) == (5, 9)
    assert r["pkill_calls"] == []  # on AC: the battery set is not applied
    assert r["lock_shown_after_reread"] == 33  # the re-read did not overwrite it
    assert r["target_shown_after_reread"] == 3000  # but showed the rest fresh
    assert r["lock_written"] == 33
    if r["dpms_focused"]:
        assert r["dpms_shown_while_focused"] == 80
    else:  # a window without a window manager may not get keyboard focus
        assert r["window_active"] is False
    assert r["dpms_shown_after_focus_left"] == 55
    assert r["schedule_right_after_move"] is False
    assert r["temp_applied"] is True
    assert r["override_before_600ms"] is False and r["override_after_600ms"] is True
    assert r["slider_group"] == ["night.current_temp", "night.manual_override"]
    assert r["slider_groups_added"] == 1
    assert r["released_groups_added"] == 1 and r["released_temp"] is True
    assert r["focus_out_groups_added"] == 1
    assert r["override_after_schedule_on"] is False
    assert r["ac_after_movie"] == [False] * 4 == r["ac_switches_after_movie"]
    assert r["movie_group_size"] == 3  # suspend was already off
    assert r["ac_after_undo"] == [True, True, True, False] == r["ac_switches_after_undo"]
    assert r["caffeine_pid_file"] is True and r["caffeine_pid_file_after_off"] is False
    assert r["missing_setup_visible"] is True and r["missing_main_visible"] is False
    assert r["missing_config_created"] is False


@pytest.mark.live
def test_page_on_fixture_modules(tmp_path, monkeypatch, xvfb):
    world = World(tmp_path, monkeypatch)
    try:
        check(run_page(world, xvfb, tmp_path))
    finally:
        world.close()


@pytest.mark.live
def test_page_on_installed_modules(tmp_path, monkeypatch, xvfb):
    """The same, on copies of the modules installed on this machine."""
    installed = loader.screen_sleep_dir()  # read before HOME is replaced
    copy = tmp_path / "installed"
    copy.mkdir()
    for name in ("common", "idle", "night"):
        shutil.copy(installed / f"{name}.py", copy / f"{name}.py")
    world = World(tmp_path / "w", monkeypatch, source=copy)
    try:
        check(run_page(world, xvfb, tmp_path))
    finally:
        world.close()
