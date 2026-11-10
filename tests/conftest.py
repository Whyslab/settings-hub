import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _private_home(request, tmp_path_factory, monkeypatch):
    """Nothing but a `live` test may reach this machine's files or session.

    A default path (History(), Settings(), the variables files) then lands in a
    temporary home, not in the person's journal.
    """
    # No test may send a real "mouse battery low" notification (live ones too).
    monkeypatch.setenv("SETTINGS_HUB_NO_BATTERY_ALERTS", "1")
    if request.node.get_closest_marker("live"):
        return
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for name, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_STATE_HOME", ".local/state"),
                      ("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache")):
        monkeypatch.setenv(name, str(home / sub))
    for name in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


OUR_SOURCE_LINE = "source = ~/.config/hypr/settings-hub.conf  # settings-hub"


def before_install(data: bytes) -> bytes:
    """A hyprland.conf as it was before install.sh appended our line.

    The line is dropped wherever it is: other installers (wallpaper-theme) append
    their own lines after it, and install.sh finds it anywhere (grep -Fx)."""
    line = OUR_SOURCE_LINE.encode()
    lines = data.splitlines(keepends=True)
    return b"".join(x for x in lines if x.rstrip(b"\r\n") != line)
