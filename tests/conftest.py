import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


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
