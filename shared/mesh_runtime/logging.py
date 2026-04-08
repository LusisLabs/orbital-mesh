from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def log_runtime_event(event_type: str, **fields: Any) -> None:
    if os.getenv("MESH_STRUCTURED_LOGS", "").lower() not in {"1", "true", "yes"}:
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **fields,
    }
    sys.stderr.write(json.dumps(payload, sort_keys=True) + "\n")
