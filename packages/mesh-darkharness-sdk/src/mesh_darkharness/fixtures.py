from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def load_fixture(domain: str, name: str) -> dict[str, Any]:
    path = PACKAGE_ROOT / "fixtures" / domain / name
    return json.loads(path.read_text(encoding="utf-8"))
