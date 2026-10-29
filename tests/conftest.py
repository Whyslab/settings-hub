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
