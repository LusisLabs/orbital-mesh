from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICIES_DIR = Path(__file__).resolve().parents[2] / "policies"


@lru_cache(maxsize=None)
def load_policy(name: str) -> dict[str, Any]:
    path = POLICIES_DIR / name
    with path.open() as handle:
        return json.load(handle)
