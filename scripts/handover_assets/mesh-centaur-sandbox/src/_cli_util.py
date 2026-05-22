from __future__ import annotations

import json
import sys
from typing import Any


def emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"{payload.get('status', 'unknown')}: {payload.get('summary', '')}".strip())
    for blocker in payload.get("blockers", []):
        print(f"  blocker: {blocker}", file=sys.stderr)


def exit_code(payload: dict[str, Any]) -> int:
    return 0 if payload.get("status") == "pass" else 1
