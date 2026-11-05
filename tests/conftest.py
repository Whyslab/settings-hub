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
    """A hyprland.conf as it was before install.sh appended our line."""
    line = (OUR_SOURCE_LINE + "\n").encode()
    return data[:-len(line)] if data.endswith(line) else data
