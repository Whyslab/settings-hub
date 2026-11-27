"""Backups: status.json, archives.txt and systemd read without root; start through systemd."""

import json
import subprocess
from datetime import datetime

import pytest

from settings_hub.backends import backups as bk

STATUS = {
    "updated": "2026-11-27T02:22:15Z", "archive": "bm-t1-20261127_032032",
    "start": "2026-11-27T03:20:33.000000", "size": "32,9 GB", "added": "149,4 MB",
    "repo": "16,1 GB", "count": 7, "checked": "2026-11-23T03:06:23Z",
    "drilled": "2026-11-01T17:26:22Z",
}
ARCHIVES = ("bm-t1-20261127_032032\t2026-11-27T03:20:33.000000\n"
            "bm-full-20261122_113411\t2026-11-22T11:34:11.000000\n")
SHOW = """Id=bm-backup.service
LoadState=loaded
ActiveState=inactive
Result=success
Job=

Id=bm-full.service
ActiveState=inactive
Result=success

Id=bm-check.service
ActiveState=failed
Result=exit-code

Id=bm-drill.service
ActiveState=inactive
Result=success

Id=bm-backup.timer
ActiveState=active
NextElapseUSecRealtime=@1764296783

Id=bm-full.timer
ActiveState=active
NextElapseUSecRealtime=@1764384065
"""


class Run:
    def __init__(self, show=SHOW, start_rc=0, start_err=""):
        self.calls = []
        self.show, self.start_rc, self.start_err = show, start_rc, start_err

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1] == "show":
            return subprocess.CompletedProcess(argv, 0, self.show, "")
        return subprocess.CompletedProcess(argv, self.start_rc, "", self.start_err)


@pytest.fixture
def state(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps(STATUS))
    (tmp_path / "archives.txt").write_text(ARCHIVES)
    return tmp_path


def backend(state, run=None, now=datetime(2026, 11, 27, 13, 0)):
    return bk.Backend(None, state_dir=state, run=run or Run(), now=lambda: now)


def test_probe_reads_everything(state):
    info = backend(state).probe()
    assert info.configured and info.last == datetime(2026, 11, 27, 3, 20, 33)
    assert (info.size, info.added, info.repo, info.count) == ("32,9 GB", "149,4 MB",
                                                              "16,1 GB", 7)
    assert info.checked is not None and info.checked.tzinfo is None  # UTC turned local
    assert info.next_backup == datetime.fromtimestamp(1764296783)
    assert info.failed == ("check",) and info.running == () and not info.stale
    assert [(a.full, a.start.day) for a in info.archives] == [(False, 27), (True, 22)]


def test_running_and_stale(state):
    show = SHOW.replace("loaded\nActiveState=inactive",
                        "loaded\nActiveState=activating")
    info = backend(state, Run(show), now=datetime(2026, 11, 29, 9, 0)).probe()
    assert info.running == ("backup",) and info.stale


def test_no_status_and_no_unit_means_not_configured(tmp_path):
    show = SHOW.replace("LoadState=loaded", "LoadState=not-found")
    info = backend(tmp_path, Run(show)).probe()
    assert not info.configured and info.status == "missing"


def test_no_copy_yet_still_offers_the_buttons(tmp_path):
    info = backend(tmp_path).probe()  # the unit is installed, status.json not yet written
    assert info.configured and info.status == "missing" and not info.stale


def test_unreadable_status_is_not_hidden(state):
    (state / "status.json").write_text('{"start": "2026-11-27T03:2')  # cut short
    info = backend(state).probe()
    assert info.configured and info.status == "unreadable" and not info.stale
    (state / "status.json").write_text("[1, 2]")
    assert backend(state).probe().status == "unreadable"


def test_queued_job_and_stopped_timer(state):
    show = SHOW.replace("Job=\n", "Job=1234\n", 1).replace(
        "Id=bm-backup.timer\nActiveState=active", "Id=bm-backup.timer\nActiveState=inactive")
    info = backend(state, Run(show)).probe()
    assert info.running == ("backup",) and info.schedule_off
    assert not backend(state).probe().schedule_off


def test_odd_values_do_not_break_the_page(state):
    (state / "status.json").write_text(json.dumps({"start": "yesterday", "count": True,
                                                   "size": 5, "checked": None}))
    (state / "archives.txt").write_text("\n\tno-name\nbm-t1-x\tnot a date\n")
    info = backend(state, Run(show="")).probe()
    assert info.last is None and info.count == 0 and info.size == "" and info.stale
    assert [a.name for a in info.archives] == ["bm-t1-x"] and info.archives[0].start is None


def test_systemctl_missing_is_said(state):
    def broken(argv, **kwargs):
        raise FileNotFoundError("systemctl")
    info = backend(state, broken).probe()
    assert info.configured and not info.units and info.next_backup is None


def test_start_runs_the_unit_without_waiting_for_the_copy(state):
    run = Run()
    backend(state, run).start("full")
    assert run.calls[-1] == ["/usr/bin/systemctl", "start", "--no-block", "bm-full.service"]


def test_start_refuses_anything_else(state):
    run = Run()
    for kind in ("check", "drill", "bm-backup.service; reboot", ""):
        with pytest.raises(ValueError):
            backend(state, run).start(kind)
    assert run.calls == []


def test_an_unanswered_password_dialog_is_a_timeout(state):
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    with pytest.raises(TimeoutError):
        backend(state, slow).start("backup")


def test_no_password_is_a_permission_error(state):
    run = Run(start_rc=4, start_err="Failed to start bm-backup.service: Access denied\n")
    with pytest.raises(PermissionError):
        backend(state, run).start("backup")
    run = Run(start_rc=1, start_err="Unit bm-backup.service not found.\n")
    with pytest.raises(RuntimeError, match="not found"):
        backend(state, run).start("backup")


def test_systemctl_is_never_looked_up_in_path(state):
    run = Run()
    backend(state, run).probe()
    assert run.calls and all(argv[0] == "/usr/bin/systemctl" for argv in run.calls)


def test_a_start_skipped_by_a_condition_is_seen(state):
    show = SHOW.replace("Id=bm-full.service\n",
                        "Id=bm-full.service\nConditionResult=no\n"
                        "ConditionTimestamp=@1764296000\n").replace(
        "Id=bm-drill.service\n", "Id=bm-drill.service\nConditionResult=no\nConditionTimestamp=\n")
    info = backend(state, Run(show)).probe()
    assert info.skipped == ("full",)  # drill: never started since boot, not skipped
    assert info.skipped_at == {"full": datetime.fromtimestamp(1764296000)}


def test_without_systemctl_and_status_the_page_still_shows(tmp_path):
    def broken(argv, **kwargs):
        raise FileNotFoundError("systemctl")
    info = backend(tmp_path, broken).probe()
    assert info.configured and not info.units and info.status == "missing"


def test_a_stopped_full_timer_is_seen(state):
    show = SHOW.replace("Id=bm-full.timer\nActiveState=active",
                        "Id=bm-full.timer\nActiveState=inactive")
    assert show != SHOW and backend(state, Run(show)).probe().schedule_off
    assert not backend(state).probe().schedule_off


def test_an_old_or_missing_check_is_seen(state):
    assert not backend(state).probe().check_old
    assert backend(state, now=datetime(2026, 12, 20)).probe().check_old
    (state / "status.json").write_text(json.dumps({**STATUS, "checked": ""}))
    assert backend(state).probe().check_old


def test_the_state_row_never_says_fine_when_it_is_not(state):
    pytest.importorskip("gi")
    from settings_hub import strings
    from settings_hub.pages.backups import BackupsPage

    base = backend(state).probe()
    ok = bk.Info(**{**base.__dict__, "failed": ()})
    verdict = BackupsPage.verdict
    assert verdict(ok, "")[0] == strings.BK_OK
    cases = {
        "units": ({"units": False}, strings.BK_UNKNOWN),
        "failed": ({"failed": ("check",)}, strings.BK_FAILED.format(kinds="проверка копий")),
        "unreadable": ({"status": "unreadable"}, strings.BK_UNREADABLE),
        "schedule": ({"schedule_off": True}, strings.BK_SCHEDULE_OFF),
        "stale": ({"stale": True}, strings.BK_STALE),
        "first": ({"status": "missing"}, strings.BK_FIRST),
        "skipped": ({"skipped": ("backup",)}, strings.BK_SKIPPED.format(kinds="копия")),
        "check": ({"check_old": True}, strings.BK_CHECK_OLD),
    }
    for name, (change, title) in cases.items():
        got = verdict(bk.Info(**{**ok.__dict__, **change}), "")
        assert got[0] == title, name
        assert got[2] or name == "first", name  # marked, except "no copy yet"
    # a failure stays first while another kind runs; a rerun of the same kind clears it
    other = bk.Info(**{**ok.__dict__, "running": ("check",), "failed": ("backup",)})
    assert verdict(other, "")[0] == strings.BK_FAILED.format(kinds="копия")
    rerun = bk.Info(**{**ok.__dict__, "running": ("backup",), "failed": ("backup",)})
    assert verdict(rerun, "")[0] == strings.BK_RUNNING["backup"]
    failed = bk.Info(**{**ok.__dict__, "failed": ("full",), "skipped": ("full",)})
    assert verdict(failed, "full")[0] == strings.BK_RUNNING["full"]  # just pressed
    assert verdict(failed, "")[0] == strings.BK_FAILED.format(kinds="полная копия")
    off = bk.Info(**{**ok.__dict__, "units": False, "failed": ("backup",)})
    assert verdict(off, "")[0] == strings.BK_UNKNOWN
