"""Wi-Fi joining and the mixer at the controller level (fake backends, no GTK)."""

import json

from settings_hub import strings
from settings_hub.backends import audio as aud
from settings_hub.backends import network as net
from settings_hub.backends import nm_wifi
from settings_hub.controllers import audio as audctl
from settings_hub.controllers import network as netctl
from settings_hub.history import History


class Now:
    """Workers that run a job at once (or hold it, to look at "in progress")."""

    def __init__(self):
        self.held = []
        self.hold = False

    def submit(self, _name, fn, on_done=None, key=None):
        if self.hold:
            self.held.append((fn, on_done))
            return
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        if on_done:
            on_done(result, error)


class NetView:
    def __init__(self):
        self.statuses, self.finished = [], []

    def show_network(self, info):
        pass

    def join_finished(self, ssid, error):
        self.finished.append((ssid, error))

    def status(self, text):
        self.statuses.append(text)

    def refresh_later(self, seconds):
        pass


class NetBackend:
    def __init__(self, outcome):
        self.workers = Now()
        self.outcome = outcome
        self.joins = []

    def queue_probe(self, on_done):
        on_done(net.Network(wifi_on=True), None)

    def join(self, ssid, password, hidden, expect):
        self.joins.append((ssid, hidden, expect))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def net_controller(tmp_path, outcome):
    view = NetView()
    backend = NetBackend(outcome)
    ctl = netctl.Controller(backend, History(tmp_path / "h.jsonl"), view)
    ctl.refresh()
    return ctl, view, backend


def test_join_records_the_connection_and_passes_the_expected_security(tmp_path):
    ctl, view, backend = net_controller(tmp_path, nm_wifi.Joined("Home"))
    ctl.join("Home", "secret-pass", expect=nm_wifi.PERSONAL)
    assert backend.joins == [("Home", False, nm_wifi.PERSONAL)]
    assert view.finished == [("Home", "")]
    entry = ctl.history.groups()[-1].entries[0]
    assert (entry.key, entry.after) == (net.WIFI_CONNECTION, "Home")


def test_a_second_join_while_one_runs_says_so_and_frees_the_page(tmp_path):
    ctl, view, backend = net_controller(tmp_path, nm_wifi.Joined("Home"))
    backend.workers.hold = True
    ctl.join("Home", "secret-pass")
    ctl.join("Cafe", "")
    assert view.finished == [("Cafe", strings.NET_JOIN_BUSY)]


def test_an_unexpected_error_shows_its_type_never_its_arguments(tmp_path):
    ctl, view, _ = net_controller(tmp_path, ValueError("secret-pass leaked?"))
    ctl.join("Home", "secret-pass")
    ssid, error = view.finished[-1]
    assert "secret-pass" not in error and "ValueError" in error
    assert not any("secret-pass" in s for s in view.statuses)


def test_connected_but_not_saved_is_said(tmp_path):
    ctl, view, _ = net_controller(tmp_path, nm_wifi.Joined("Home", saved=False))
    ctl.join("Home", "secret-pass")
    assert strings.NET_JOIN_DONE_UNSAVED.format(name="Home") in view.statuses


# ---- the mixer ------------------------------------------------------------------

APP = "org.mozilla.firefox"  # dots in a program's name survive the History key


class Pactl:
    def __init__(self):
        self.volumes = {"1": 100, "2": 60}
        self.alive = True

    def __call__(self, argv):
        if argv[-1] == "sink-inputs":
            items = [{"index": int(i), "mute": False, "corked": False,
                      "volume": {"fl": {"value_percent": f"{v}%"}},
                      "properties": {"application.name": APP, "media.name": "m"}}
                     for i, v in self.volumes.items()] if self.alive else []
            return 0, json.dumps(items), ""
        if argv[1] == "set-sink-input-volume":
            self.volumes[argv[2]] = int(argv[3].rstrip("%"))
        return 0, "", ""


class AudView:
    def __init__(self):
        self.apps, self.statuses = [], []

    def show_audio(self, audio):
        pass

    def show_volume(self, kind, percent):
        pass

    def show_apps(self, apps, pending):
        self.apps.append(([a.name for a in apps], set(pending)))

    def status(self, text):
        self.statuses.append(text)


def aud_controller(tmp_path):
    pactl = Pactl()
    backend = aud.Backend(Now(), runner=pactl)
    history = History(tmp_path / "h.jsonl")
    aud.register(history, backend)
    view = AudView()
    ctl = audctl.Controller(backend, history, view)
    ctl.refresh()
    return ctl, view, pactl, history


def test_a_drag_is_one_history_item_and_undo_puts_every_stream_back(tmp_path):
    ctl, view, pactl, history = aud_controller(tmp_path)
    for percent in (90, 70, 50):
        ctl.app_volume_moved(APP, percent)
    ctl.commit_app_volume(APP)
    groups = history.groups()
    assert len(groups) == 1
    entry = groups[0].entries[0]
    assert (entry.key, entry.before, entry.after) == (f"app.volume.{APP}", 100, 50)
    assert entry.label == strings.AUDIO_LABEL_APP_VOLUME.format(app=APP)
    assert ctl.pending == set()
    history.execute(history.plan_undo_last())
    assert pactl.volumes == {"1": 100, "2": 100}


def test_a_drag_resumed_after_the_pause_starts_from_where_it_stopped(tmp_path):
    ctl, _view, _pactl, history = aud_controller(tmp_path)
    ctl.app_volume_moved(APP, 80)
    ctl.commit_app_volume(APP)
    ctl.app_volume_moved(APP, 40)  # no poll in between
    ctl.commit_app_volume(APP)
    pairs = [(g.entries[0].before, g.entries[0].after) for g in history.groups()]
    assert pairs == [(100, 80), (80, 40)]


def test_a_program_that_closed_logs_nothing_and_clears_pending(tmp_path):
    ctl, view, pactl, history = aud_controller(tmp_path)
    pactl.alive = False
    ctl.app_volume_moved(APP, 30)
    ctl.commit_app_volume(APP)
    assert history.groups() == []
    assert ctl.pending == set()
    assert strings.AUDIO_APPLY_FAILED.format(
        error=strings.AUDIO_APP_GONE.format(app=APP)) in view.statuses


def test_mute_of_a_program_is_undoable(tmp_path):
    ctl, _view, _pactl, history = aud_controller(tmp_path)
    ctl.set_app_mute(APP, True)
    entry = history.groups()[-1].entries[0]
    assert (entry.key, entry.before, entry.after) == (f"app.mute.{APP}", False, True)


def test_a_poll_read_before_a_commit_does_not_bring_back_the_old_volume(tmp_path):
    ctl, view, pactl, history = aud_controller(tmp_path)
    held = []
    ctl.backend.queue_apps = lambda on_done: held.append(on_done)
    ctl.refresh_apps()  # started now, answers late with the old 100 %
    ctl.app_volume_moved(APP, 40)
    ctl.commit_app_volume(APP)
    stale = [aud.App(APP, (1, 2), 100, False, "m")]
    held[0](stale, None)
    assert next(a for a in ctl.audio.apps if a.name == APP).volume == 40
