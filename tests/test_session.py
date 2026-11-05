"""The window asks to be moved into the user manager only when it must."""

from settings_hub import session

HYPR = {"HYPRLAND_INSTANCE_SIGNATURE": "x"}


def test_the_root_cgroup_of_hyprland_needs_a_scope():
    assert session.needs_scope(HYPR, "/")


def test_a_terminal_or_a_login_does_not():
    kitty = "/user.slice/user-1000.slice/user@1000.service/app.slice/kitty.scope"
    assert not session.needs_scope(HYPR, kitty)
    assert not session.needs_scope(HYPR, "/user.slice/user-1000.slice/session-8.scope")


def test_never_outside_hyprland():
    assert not session.needs_scope({}, "/")  # tests, other desktops


def test_the_unified_path_is_read():
    assert session.cgroup_path("0::/\n") == "/"
    assert session.cgroup_path("1:name=systemd:/x\n0::/user.slice/a\n") == "/user.slice/a"


def test_the_call_moves_this_very_process():
    argv = session.scope_call(42)
    assert argv[:3] == ["busctl", "--user", "--timeout=2"]
    assert "settings-hub-42.scope" in argv and argv[argv.index("PIDs") + 3] == "42"
    assert argv[-1] == "0"


def test_any_failure_carries_on(monkeypatch):
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "x")
    monkeypatch.setattr(session, "_read_cgroup", lambda: "/")
    monkeypatch.setattr(session.shutil, "which", lambda _n: "/usr/bin/busctl")

    def hung(*_a, **_k):
        raise session.subprocess.TimeoutExpired("busctl", 3)

    monkeypatch.setattr(session.subprocess, "run", hung)
    assert session.move_into_scope() is False
