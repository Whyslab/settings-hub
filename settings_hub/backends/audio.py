"""Sound devices through pactl (PipeWire's PulseAudio interface). No GTK.

Everything is a command that already controls the sound: `pactl -f json list
sinks|sources` for the list, `pactl get-default-sink|source` for what is used,
`set-default-*`, `set-*-volume`, `set-*-mute` for changes. No audio is opened
here and no volume is kept in memory: every page show asks pactl again.

History: one item per key -- "default.sink", "default.source",
"volume.<kind>.<name>" (percent) and "mute.<kind>.<name>".
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class Audio:
    sinks: list[Device] = field(default_factory=list)
    sources: list[Device] = field(default_factory=list)
    default_sink: str = ""
    default_source: str = ""

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
        ))
    return out


def key_volume(kind: str, name: str) -> str:
    return f"volume.{kind}.{name}"


def key_mute(kind: str, name: str) -> str:
    return f"mute.{kind}.{name}"


class Backend:
    def __init__(self, workers: Workers, runner: Runner | None = None) -> None:
        self.workers = workers
        self.run = runner or _run

    # ---- reading ---------------------------------------------------------

    def _cmd(self, kind: str, verb: str) -> str:
        return {"sink": "get-default-sink", "source": "get-default-source"}[kind] \
            if verb == "default" else ""

    def probe(self) -> Audio:
        audio = Audio()
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
        return audio

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
