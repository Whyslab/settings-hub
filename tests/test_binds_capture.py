"""Key capture's submap fallback and its watchdog. No GTK.

The watchdog is the exact shell command the window hands to `hyprctl dispatch
exec`; here it runs under sh with the stub hyprctl (binds_env) and no sleep.
"""

import os
import stat
import subprocess

import pytest
from binds_env import World

from settings_hub.binds import capture


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, capture_ready=True)
    yield w
    w.close()


def submap(world) -> str:
    return (world.root / "submap").read_text().strip()


def test_fallback_switches_submap_and_starts_a_watchdog_through_hyprland(world):
    fb = capture.SubmapFallback(world.backend.hyprctl)
    assert fb.start() is True
    calls = world.calls_of()
    assert calls[:2] == ["hyprctl binds -j", "hyprctl dispatch submap settings-hub-capture"]
    assert calls[2].startswith("hyprctl dispatch exec sleep 15; ")
    assert fb.token in calls[2] and str(fb.path) in calls[2]
    assert fb.path == world.run / "settings-hub-capture"
    assert fb.path.read_text().strip() == fb.token
    assert stat.S_IMODE(fb.path.stat().st_mode) == 0o600
    assert submap(world) == capture.SUBMAP
    fb.stop()
    assert not fb.path.exists() and submap(world) == "default"
    assert world.calls_of()[-1] == "hyprctl dispatch submap reset"


def test_no_submap_without_its_way_out(tmp_path, monkeypatch):
    """Before settings-hub.conf is loaded Hyprland has no such submap: stay out of it."""
    w = World(tmp_path, monkeypatch, capture_ready=False)
    try:
        fb = capture.SubmapFallback(w.backend.hyprctl)
        assert fb.start() is False and fb.active is False
        assert w.calls_of() == ["hyprctl binds -j"] and not fb.path.exists()
        fb.stop()
        assert w.calls_of() == ["hyprctl binds -j"]
    finally:
        w.close()


def test_a_new_capture_gets_a_new_token(world):
    a = capture.SubmapFallback(world.backend.hyprctl)
    a.start()
    first = a.token
    a.stop()
    a.start()
    assert a.token != first
    a.stop()


def run_watchdog(world, token: str) -> list[str]:
    path = capture.token_path(world.run)
    world.clear_calls()
    subprocess.run(["sh", "-c", capture.watchdog_command(path, token, 0)], check=False,
                   env=dict(os.environ), timeout=10)
    return world.calls_of()


def test_watchdog_resets_a_capture_left_behind(world):
    fb = capture.SubmapFallback(world.backend.hyprctl)
    fb.start()
    fb.token = None  # the window "crashed": it never stops the capture itself
    token = fb.path.read_text().strip()
    assert run_watchdog(world, token) == ["hyprctl submap", "hyprctl dispatch submap reset"]
    assert submap(world) == "default"


def test_old_watchdog_ignores_a_newer_capture(world):
    fb = capture.SubmapFallback(world.backend.hyprctl)
    fb.start()
    old = fb.token
    fb.stop()
    fb.start()  # a new capture: new token, submap on again
    assert run_watchdog(world, old) == []  # token differs: not even `hyprctl submap`
    assert submap(world) == capture.SUBMAP
    fb.stop()


def test_watchdog_leaves_a_foreign_submap_alone(world):
    fb = capture.SubmapFallback(world.backend.hyprctl)
    fb.start()
    (world.root / "submap").write_text("resize\n")  # the user went into another submap
    assert run_watchdog(world, fb.token) == ["hyprctl submap"]
    assert submap(world) == "resize"


def test_startup_resets_only_our_own_submap(world):
    assert capture.reset_if_stuck(world.backend.hyprctl) is False
    assert world.calls_of() == ["hyprctl submap"]
    (world.root / "submap").write_text(capture.SUBMAP + "\n")
    assert capture.reset_if_stuck(world.backend.hyprctl) is True
    assert world.calls_of()[-1] == "hyprctl dispatch submap reset"
    assert submap(world) == "default"


def test_backend_startup_reset_runs_on_the_worker(world):
    (world.root / "submap").write_text(capture.SUBMAP + "\n")
    world.backend.reset_submap()
    world.loop.pump()
    assert world.calls_of() == ["hyprctl submap", "hyprctl dispatch submap reset"]
