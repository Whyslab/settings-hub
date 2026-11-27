"""The Backups page in the real window (gui_backups.py on Xvfb).

Opening it starts nothing; a refused password is said and the buttons come
back; a started copy is shown as running until the unit ends.
"""

import json
import os
import subprocess

import pytest
from conftest import ROOT
from test_backups import ARCHIVES, STATUS
from test_gui import BUS, xvfb  # noqa: F401 -- the fixture is used by name


@pytest.mark.live
def test_backups_page(tmp_path, xvfb):  # noqa: F811
    home = tmp_path / "home"
    state = home / ".local" / "state" / "settings-hub"
    state.mkdir(parents=True)
    data = tmp_path / "bm"
    data.mkdir()
    (data / "status.json").write_text(json.dumps(STATUS))
    (data / "archives.txt").write_text(ARCHIVES)
    ctrl = tmp_path / "ctrl"
    ctrl.mkdir()
    log = tmp_path / "calls.log"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    systemctl = stubs / "systemctl"
    systemctl.write_text(f"""#!/bin/sh
# settings-hub stub
echo "systemctl $*" >>"{log}"
case "$1" in
  show)
    state=inactive; [ -e "{ctrl}/running" ] && state=activating
    printf 'Id=bm-backup.service\\nLoadState=loaded\\n'
    printf 'ActiveState=%s\\nResult=success\\n' "$state"
    if [ -e "{ctrl}/skipped" ]; then
      printf 'ConditionResult=no\\nConditionTimestamp=@%s\\n' "$(cat "{ctrl}/skipped")"
    fi
    printf '\\n'
    printf 'Id=bm-backup.timer\\nActiveState=active\\nNextElapseUSecRealtime=@1764296783\\n\\n'
    printf 'Id=bm-full.timer\\nActiveState=active\\nNextElapseUSecRealtime=@1764384065\\n'
    exit 0 ;;
  start)
    rc=$(cat "{ctrl}/start-rc")
    # like --no-block: the unit shows as running only a moment later
    if [ "$rc" = 0 ]; then (sleep 1.5; : >"{ctrl}/running") >/dev/null 2>&1 & exit 0; fi
    if [ "$rc" = skip ]; then date +%s >"{ctrl}/skipped"; exit 0; fi
    echo "Failed to start: Access denied" >&2; exit "$rc" ;;
esac
exit 0
""")
    systemctl.chmod(0o755)
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
         str(ROOT / "tests" / "gui_backups.py"), str(ROOT), str(state), str(ctrl), str(data),
         str(systemctl), str(out)],
        env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    r = json.loads(out.read_text())
    assert r["errors"] == [], r["errors"]
    assert "Всё хорошо" in r["opened"] and "7 · 16,1 GB на диске" in r["opened"], r["opened"]
    assert "Полная" in r["opened"] and "Обычная" in r["opened"], r["opened"]
    starts = [line for line in log.read_text().splitlines() if " start " in f"{line} "]
    assert starts == ["systemctl start --no-block bm-backup.service",
                      "systemctl start --no-block bm-full.service",
                      "systemctl start --no-block bm-backup.service"], starts
    assert "пароль не введён" in r["denied"] and r["sensitive_after_denied"]
    assert "Копия началась" in r["started"] and r["unit_seen"]
    assert not r["sensitive_while_running"]
    assert r["ended"] and r["sensitive_after"]
    assert r["poll_after_leave"] == 0
    assert r["skipped_soon"], r["skipped_texts"]  # said at once, not after the 20 s wait
