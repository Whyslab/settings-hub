"""Disk space on the System page in the real window (gui_disk_space.py on Xvfb).

du counts a temporary home; emptying the Trash asks first and touches only that
home's Trash; a nearly full disk is marked.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name


@pytest.mark.live
def test_disk_space_part(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    (home / "Videos").mkdir()
    (home / "Videos" / "film.mkv").write_bytes(os.urandom(3_000_000))
    trash = home / ".local" / "share" / "Trash"
    (trash / "files").mkdir(parents=True)
    (trash / "info").mkdir()
    (trash / "files" / "old.iso").write_bytes(os.urandom(2_000_000))
    (trash / "info" / "old.iso.trashinfo").write_text("[Trash Info]\n")
    apps = home / ".local" / "share" / "Steam" / "steamapps"
    apps.mkdir(parents=True)
    (apps / "appmanifest_570.acf").write_text('"name" "Dota 2"\n"SizeOnDisk" "77000000000"\n')
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (home / "pacman.conf").write_text(f"[options]\nCacheDir = {pkg}/\n")
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items()
           if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_STATE_HOME=str(home / ".local" / "state"),
               XDG_CACHE_HOME=str(home / ".cache"), DISPLAY=xvfb, GDK_BACKEND="x11",
               GSK_RENDERER="cairo", NO_AT_BRIDGE="1", GTK_A11Y="none",
               PYTHONDONTWRITEBYTECODE="1")
    bus = tmp_path / "bus.conf"
    bus.write_text(BUS)
    done = subprocess.run(
        ["dbus-run-session", f"--config-file={bus}", "--", "/usr/bin/python3",
         str(ROOT / "tests" / "gui_disk_space.py"), str(ROOT), str(state), str(home),
         str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == [], r["errors"]
    assert r["counted"] and r["missing_rows"] == []
    assert r["mount_titles"] and r["mount_titles"][0] == "Системный диск", r["mount_titles"]
    assert r["disk_row_is_first_mount"]
    assert r["folders"][:1] == ["Видео"] and "Данные программ" in r["folders"], r["folders"]
    assert "~/Videos" in r["folder_paths"]
    assert r["opened"] == [str(home / "Videos")]
    assert r["pages_opened"] == ["updates#cache"]  # cleaning is on the Updates page
    assert "файлов и папок: 1" in r["trash_hint"] and r["trash_sensitive"]
    assert r["games_visible"] and "Dota 2 (71.7 ГБ)" in r["games_hint"], r["games_hint"]
    assert "сами раз в неделю" in r["packages_hint"]
    assert r["asked"][0] == "Очистить корзину?" and "навсегда" in r["asked"][1]
    assert "(1 шт." in r["asked"][1], r["asked"]
    assert "сетевых дисков (" in r["asked"][1] and "/nas)" in r["asked"][1]
    assert r["asked_times"] == 1 and r["sensitive_after_no"]
    assert "(2 шт." in r["asked_fresh"], r["asked_fresh"]  # counted again before asking
    assert r["gio_after_no"] == 0
    assert r["gio_after_yes"] == [["/usr/bin/gio", "trash", "--empty"]]
    assert r["emptied_before_count"]  # the race really happened
    assert r["trash_after"] == "Пусто" and not r["trash_sensitive_after"]  # after the slow count
    assert r["status_after"] == "Корзина очищена"
    assert r["recounted_on_show"] == 0 and r["recounted_on_click"] >= 1
    assert r["low_hint"].startswith("Почти заполнен") and r["low_marked"]
    assert r["low_value"] == "95%"
