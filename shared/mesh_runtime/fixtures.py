from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def load_fixture(*parts: str) -> dict[str, Any]:
    path = FIXTURES_DIR.joinpath(*parts)
    with path.open() as handle:
        return json.load(handle)
