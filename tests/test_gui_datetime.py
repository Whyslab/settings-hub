"""The Date, time and language page in the real window (gui_datetime.py on Xvfb).

System changes go through the (fake) timedatectl/localectl only after a
choice, a refused password changes nothing, Ctrl+Z puts a change back; the
session's layouts go through the Hyprland variables.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name


@pytest.mark.live
def test_datetime_page(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1", LANG="C.UTF-8", LC_ALL="C.UTF-8")
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_datetime.py"), str(ROOT), str(state), str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == [], r["errors"]
    assert r["read"] and r["missing_rows"] == [] and r["history_on_open"] == 0
    assert r["now"] and r["zone"] == "Europe/Oslo · UTC+01:00", r["zone"]
    assert r["ntp"] and "точное" in r["ntp_hint"]
    assert r["locale"] == "Русский"
    assert r["layouts"] == ["Английская (США) (us)", "Русская (ru)", "Норвежская (no)"]
    assert r["switch"] == "Win+Пробел"
    assert "ru, us" in r["login_hint"] and "Оба Shift" in r["login_hint"]
    assert r["login_sensitive"]
    assert r["add_first"] == "Украинская (ua)"  # known names first, "custom" left out
    assert r["zone_after"].startswith("America/New_York"), r["zone_after"]
    assert r["now_tooltip_after"] == "UTC-05:00", r["now_tooltip_after"]
    assert r["pick_kept"] == "ua"
    assert r["zone_status"] == "Часовой пояс: America/New_York"
    assert r["zone_history"] == [["timelang", "timezone", "Europe/Oslo", "America/New_York"]]
    assert "пароль не введён" in r["denied_status"]
    assert r["ntp_after_deny"] is True and r["history_after_deny"] == 1
    assert r["zone_undone"] == "Europe/Oslo" and r["undo_recorded"] == "Europe/Oslo"
    assert r["undo_returned_s"] < 0.5, r["undo_returned_s"]  # not waiting for the password
    assert "спросят пароль" in r["undo_status"]
    assert r["second_undo_status"].startswith("Подождите")
    assert r["mixed_main_thread"] == [True], r["mixed_main_thread"]
    assert r["mixed_zone"] == "Europe/Kyiv" and r["mixed_k"] == 1  # the page's pick came last
    assert r["mixed_recorded"] == ["thread-check", "timelang"], r["mixed_recorded"]
    assert r["dialogs_at_once"] == 1
    assert r["locale_call"] == ["/usr/bin/localectl", "set-locale", "LANG=en_US.UTF-8",
                                "LC_TIME=en_US.UTF-8"]
    assert r["login_call"] == ["/usr/bin/localectl", "--no-convert", "set-x11-keymap",
                               "us,ru,no", "pc105", "",  # the old ",": other layouts
                               "terminate:ctrl_alt_bksp,grp:win_space_toggle"]
    assert r["login_hint_after"] == "Сейчас: как в этом сеансе"
    assert not r["login_sensitive_after"]
    assert r["after_up"] == ["Русская (ru)", "Английская (США) (us)", "Норвежская (no)"]
    assert r["after_add"] == "ru,us,no"  # the removed one is first to add again
    assert r["options_after"] == "grp:alt_shift_toggle"
    assert r["layout_history"][:3] == ["ru,us,no", "ru,us", "ru,us,no"]
    assert r["last_removable"] is False
    assert r["unsafe_login_sensitive"] is False and "нельзя" in r["unsafe_login_hint"]
    assert r["down_errors"] == []
    assert r["down_ntp_hint"].startswith("Не удалось прочитать"), r["down_ntp_hint"]
    assert r["down_login_hint"] == "Не удалось прочитать"
    assert r["down_zone_sensitive"] is False and r["down_locale"] is None
    assert [c[1:3] for c in r["commands"]][:2] == [["set-timezone", "America/New_York"],
                                                   ["set-ntp", "false"]]
