#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hsai_bridge import load_hsai_formal_backend_run_metadata, local_hsai_allow_decision
from shared.mesh_runtime.schema_validation import validate_payload


def main() -> int:
    try:
        request = _read_request()
        validate_payload("hsai-admission-request.schema.json", request)
        formal_bundle_path = os.getenv("MESH_HSAI_FORMAL_BACKEND_RUN_BUNDLE_PATH", "").strip()
        formal_metadata = (
            load_hsai_formal_backend_run_metadata(formal_bundle_path)
            if formal_bundle_path
            else None
        )
        decision = local_hsai_allow_decision(request, formal_backend_metadata=formal_metadata)
        sys.stdout.write(json.dumps(decision, sort_keys=True, separators=(",", ":")))
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}, sort_keys=True))
        sys.stderr.write("\n")
        return 2


def _read_request() -> dict[str, Any]:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError("HSAI admission request must be a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
