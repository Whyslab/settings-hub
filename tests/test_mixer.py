"""The Sound page's programs: grouping streams, who records, per-program changes."""

import json

from settings_hub import strings
from settings_hub.backends import audio as aud


def stream(index, app, volume=100, mute=False, corked=False, media="", **props):
    return {"index": index, "mute": mute, "corked": corked,
            "volume": {"front-left": {"value_percent": f"{volume}%"},
                       "front-right": {"value_percent": f"{volume - 10}%"}},
            "properties": {"application.name": app, "media.name": media, **props}}


STREAMS = json.dumps([
    stream(1, "Firefox", 100, media="local-Spotify"),
    stream(2, "Firefox", 60, corked=True, media="YouTube"),
    stream(3, "speech-dispatcher-dummy", 100),
    stream(4, "Telegram", 40, mute=True),
    stream(5, "cava", 100, **{"stream.monitor": "true"}),
])


def test_streams_of_one_program_are_one_row():
    apps = aud.parse_apps(STREAMS)
    assert [a.name for a in apps] == ["Firefox", "Telegram"]
    firefox = apps[0]
    assert firefox.streams == (1, 2)
    assert firefox.volume == 100  # the loudest stream, the loudest channel
    assert firefox.playing == "local-Spotify"  # the paused tab is not "playing"
    assert not firefox.mute
    assert apps[1].mute


def test_broken_json_is_no_programs():
    assert aud.parse_apps("not json") == []
    assert aud.parse_apps("{}") == []


def test_recorders_skip_monitor_sources():
    outputs = json.dumps([
        {"index": 9, "source": 57, "properties": {"application.name": "cava"}},
        {"index": 10, "source": 58, "properties": {"application.name": "Firefox"}},
        {"index": 11, "source": 58, "properties": {"application.name": "Firefox"}},
    ])
    assert aud.parse_recorders(outputs, monitors={57}) == ["Firefox"]


class FakePactl:
    def __init__(self, text=STREAMS):
        self.text = text
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[-1] == "sink-inputs":
            return 0, self.text, ""
        return 0, "", ""


def test_program_volume_reaches_every_stream():
    run = FakePactl()
    backend = aud.Backend(None, runner=run)
    assert backend.set_app_volume("Firefox", 55) == (True, "")
    sets = [c for c in run.calls if c[1] == "set-sink-input-volume"]
    assert sets == [["pactl", "set-sink-input-volume", "1", "55%"],
                    ["pactl", "set-sink-input-volume", "2", "55%"]]


def test_a_closed_program_says_so():
    backend = aud.Backend(None, runner=FakePactl("[]"))
    ok, message = backend.set_app_mute("Firefox", True)
    assert not ok and message == strings.AUDIO_APP_GONE.format(app="Firefox")


def test_history_reads_and_applies_program_keys():
    run = FakePactl()
    backend = aud.Backend(None, runner=run)
    key = aud.key_app_volume("Telegram")
    assert backend.read([key, aud.key_app_mute("Telegram")]) == {
        key: 40, aud.key_app_mute("Telegram"): True}
    backend.apply({aud.key_app_mute("Telegram"): False})
    assert ["pactl", "set-sink-input-mute", "4", "0"] in run.calls
