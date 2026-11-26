"""Sound devices through pactl (PipeWire's PulseAudio interface). No GTK.

Everything is a command that already controls the sound: `pactl -f json list
sinks|sources` for the list, `pactl get-default-sink|source` for what is used,
`set-default-*`, `set-*-volume`, `set-*-mute` for changes. No audio is opened
here and no volume is kept in memory: every page show asks pactl again.

History: one item per key -- "default.sink", "default.source",
"volume.<kind>.<name>" (percent) and "mute.<kind>.<name>".

Programs (the mixer): every stream a program plays (`list sink-inputs`) is
grouped by the program's name, so the three Firefox tabs that play are one row
and one slider. Their keys are "app.volume.<program>" and "app.mute.<program>";
undoing one sets all of that program's streams that exist now (a program that
was closed meanwhile cannot be undone, and says so). Who records from a
microphone is read from `list source-outputs` (monitor sources do not count:
they are a visualiser listening to the speakers).
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import strings
from ..workers import Workers

log = logging.getLogger(__name__)

BACKEND = "audio"
WORKER = "audio"
READ_WORKER = "audio-read"
KINDS = ("sink", "source")
DEFAULT_KEYS = {"sink": "default.sink", "source": "default.source"}
TIMEOUT_S = 5

Result = tuple[int, str, str]
Runner = Callable[[list[str]], Result]


def _run(argv: list[str]) -> Result:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


@dataclass(frozen=True)
class Device:
    name: str
    description: str
    volume: int  # percent, the loudest channel
    mute: bool
    monitor: bool = False  # a source that repeats what a sink plays, not a microphone
    index: int = -1


@dataclass
class Audio:
    sinks: list[Device] = field(default_factory=list)
    sources: list[Device] = field(default_factory=list)
    default_sink: str = ""
    default_source: str = ""
    apps: list[App] = field(default_factory=list)
    recorders: list[str] = field(default_factory=list)  # programs using a microphone

    def devices(self, kind: str) -> list[Device]:
        return self.sinks if kind == "sink" else self.sources

    def default(self, kind: str) -> str:
        return self.default_sink if kind == "sink" else self.default_source


def is_monitor(item: dict) -> bool:
    """A source that only repeats what a sink plays: not a microphone."""
    properties = item.get("properties") or {}
    return (properties.get("device.class") == "monitor"
            or str(item.get("name", "")).endswith(".monitor"))


def parse_devices(text: str) -> list[Device]:
    """pactl -f json list sinks/sources -> devices; volumes are per channel."""
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    out: list[Device] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        percents = []
        for channel in (item.get("volume") or {}).values():
            value = str(channel.get("value_percent", "")).rstrip("%")
            try:
                percents.append(int(value))
            except ValueError:
                continue
        out.append(Device(
            name=str(item["name"]),
            description=str(item.get("description") or item["name"]),
            volume=max(percents) if percents else 0,
            mute=bool(item.get("mute")),
            monitor=is_monitor(item),
            index=int(item.get("index", -1)) if str(item.get("index", "")).isdigit() else -1,
        ))
    return out


HIDDEN_APPS = {"speech-dispatcher", "speech-dispatcher-dummy"}  # silent helpers
APP_KEYS = ("app.volume.", "app.mute.")


@dataclass(frozen=True)
class App:
    """One program and all the streams it plays now."""

    name: str
    streams: tuple[int, ...]
    volume: int  # percent, the loudest stream
    mute: bool  # all of its streams are muted
    playing: str  # what plays (media names of streams not paused), may be ""
    icon: str = ""


def _percent(volume) -> int:
    percents = []
    for channel in (volume.values() if isinstance(volume, dict) else ()):
        if not isinstance(channel, dict):
            continue
        try:
            percents.append(int(str(channel.get("value_percent", "")).rstrip("%")))
        except ValueError:
            continue
    return max(percents) if percents else 0


def _app_name(properties: dict) -> str:
    return str(properties.get("application.name") or properties.get(
        "application.process.binary") or "")


def parse_apps(text: str) -> list[App]:
    """pactl -f json list sink-inputs -> programs, alphabetically."""
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    if not isinstance(raw, list):
        return []
    grouped: dict[str, list[dict]] = {}
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("index", "")).isdigit():
            continue
        properties = item.get("properties")
        if not isinstance(properties, dict):
            continue
        name = _app_name(properties)
        if (not name or name in HIDDEN_APPS or properties.get("stream.monitor") == "true"
                or properties.get("media.role") == "event"):  # a click or a notification blip
            continue
        grouped.setdefault(name, []).append(item)
    out = []
    for name, items in grouped.items():
        playing = [str((i.get("properties") or {}).get("media.name") or "")
                   for i in items if not i.get("corked")]
        icon = next((str((i.get("properties") or {}).get("application.icon_name"))
                     for i in items if (i.get("properties") or {}).get("application.icon_name")),
                    "")
        out.append(App(
            name=name,
            streams=tuple(int(i["index"]) for i in items),
            volume=max(_percent(i.get("volume")) for i in items),
            mute=all(bool(i.get("mute")) for i in items),
            playing=" · ".join(p for p in playing if p),
            icon=icon,
        ))
    return sorted(out, key=lambda a: a.name.lower())


def parse_recorders(text: str, monitors: set[int]) -> list[str]:
    """pactl -f json list source-outputs -> names of programs using a microphone."""
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    names: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("source") in monitors:
            continue
        properties = item.get("properties")
        if not isinstance(properties, dict) or properties.get("stream.monitor") == "true":
            continue
        name = _app_name(properties)
        if name and name not in HIDDEN_APPS and name not in names:
            names.append(name)
    return names


def key_app_volume(app: str) -> str:
    return f"app.volume.{app}"


def key_app_mute(app: str) -> str:
    return f"app.mute.{app}"


def key_volume(kind: str, name: str) -> str:
    return f"volume.{kind}.{name}"


def key_mute(kind: str, name: str) -> str:
    return f"mute.{kind}.{name}"


class Backend:
    def __init__(self, workers: Workers, runner: Runner | None = None) -> None:
        self.workers = workers
        self.run = runner or _run

    # ---- reading ---------------------------------------------------------

    def probe(self) -> Audio:
        audio = Audio()
        monitors: set[int] = set()
        for kind in KINDS:
            code, out, _err = self.run(["pactl", "-f", "json", "list", f"{kind}s"])
            devices = parse_devices(out) if code == 0 else []
            code, out, _err = self.run(["pactl", f"get-default-{kind}"])
            default = out.strip() if code == 0 else ""
            if kind == "sink":
                audio.sinks = devices
                audio.default_sink = default
            else:
                # Monitors are not offered, except one already in use: it has to
                # be seen, and a real microphone has to be selectable instead.
                audio.sources = [d for d in devices if not d.monitor or d.name == default]
                audio.default_source = default
                monitors = {d.index for d in devices if d.monitor}
        audio.apps = self.probe_apps()
        code, out, _err = self.run(["pactl", "-f", "json", "list", "source-outputs"])
        audio.recorders = parse_recorders(out, monitors) if code == 0 else []
        return audio

    def probe_apps(self) -> list[App]:
        code, out, _err = self.run(["pactl", "-f", "json", "list", "sink-inputs"])
        return parse_apps(out) if code == 0 else []

    def queue_apps(self, on_done: Callable[[list[App], BaseException | None], None]) -> None:
        self.workers.submit(READ_WORKER, self.probe_apps, on_done, key="apps")

    def _app(self, name: str) -> App | None:
        return next((a for a in self.probe_apps() if a.name == name), None)

    def set_app_volume(self, name: str, percent: int) -> tuple[bool, str]:
        """Every stream of the program now; False when it plays nothing any more."""
        app = self._app(name)
        if app is None:
            return False, strings.AUDIO_APP_GONE.format(app=name)
        percent = max(0, min(150, int(percent)))
        for index in app.streams:
            ok, message = self._ok(["pactl", "set-sink-input-volume", str(index), f"{percent}%"])
            if not ok:
                return ok, message
        return True, ""

    def set_app_mute(self, name: str, mute: bool) -> tuple[bool, str]:
        app = self._app(name)
        if app is None:
            return False, strings.AUDIO_APP_GONE.format(app=name)
        for index in app.streams:
            ok, message = self._ok(["pactl", "set-sink-input-mute", str(index),
                                    "1" if mute else "0"])
            if not ok:
                return ok, message
        return True, ""

    def queue_probe(self, on_done: Callable[[Audio, BaseException | None], None]) -> None:
        self.workers.submit(READ_WORKER, self.probe, on_done)

    # ---- changing --------------------------------------------------------

    def set_default(self, kind: str, name: str) -> tuple[bool, str]:
        return self._ok(["pactl", f"set-default-{kind}", name])

    def set_volume(self, kind: str, name: str, percent: int) -> tuple[bool, str]:
        percent = max(0, min(150, int(percent)))
        return self._ok(["pactl", f"set-{kind}-volume", name, f"{percent}%"])

    def set_mute(self, kind: str, name: str, mute: bool) -> tuple[bool, str]:
        return self._ok(["pactl", f"set-{kind}-mute", name, "1" if mute else "0"])

    def _ok(self, argv: list[str]) -> tuple[bool, str]:
        code, out, err = self.run(argv)
        text = (out + err).strip()
        return code == 0, "" if code == 0 else (text or f"exit {code}")

    # ---- History's view --------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        audio = self.probe()
        out: dict[str, Any] = {}
        for key in keys:
            if key.startswith(APP_KEYS):
                name = key.split(".", 2)[2]
                app = next((a for a in audio.apps if a.name == name), None)
                if app is not None:
                    out[key] = app.mute if key.startswith("app.mute.") else app.volume
                continue
            if key in DEFAULT_KEYS.values():
                kind = "sink" if key == DEFAULT_KEYS["sink"] else "source"
                out[key] = audio.default(kind)
                continue
            kind, name = _split_key(key)
            device = next((d for d in audio.devices(kind) if d.name == name), None)
            if device is None:
                continue
            out[key] = device.mute if key.startswith("mute.") else device.volume
        return out

    def apply(self, values: dict[str, Any]) -> None:
        errors: list[str] = []
        for key in sorted(values):
            value = values[key]
            if key == DEFAULT_KEYS["sink"]:
                ok, message = self.set_default("sink", str(value))
            elif key == DEFAULT_KEYS["source"]:
                ok, message = self.set_default("source", str(value))
            elif key.startswith("app.volume."):
                ok, message = self.set_app_volume(key.split(".", 2)[2], int(value))
            elif key.startswith("app.mute."):
                ok, message = self.set_app_mute(key.split(".", 2)[2], bool(value))
            else:
                kind, name = _split_key(key)
                if key.startswith("mute."):
                    ok, message = self.set_mute(kind, name, bool(value))
                else:
                    ok, message = self.set_volume(kind, name, int(value))
            if not ok:
                errors.append(f"{key}: {message}")
        if errors:
            raise RuntimeError("; ".join(errors))


def _split_key(key: str) -> tuple[str, str]:
    """'volume.sink.NAME' -> ('sink', 'NAME'); the name may contain dots."""
    parts = key.split(".", 2)
    return (parts[1], parts[2] if len(parts) > 2 else "")


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
