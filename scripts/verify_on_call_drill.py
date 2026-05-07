#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.on_call_drill import ON_CALL_DRILL_VERIFICATION_VERSION, verify_on_call_drill


EXPECTED_ON_CALL_DRILL_VERIFICATION_SCHEMA = "mesh.on_call_drill_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Mesh production on-call drill proof packet.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.on_call_drill.v1 packet.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_on_call_drill(args.proof)
    if payload.get("schema_version") != ON_CALL_DRILL_VERIFICATION_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if payload.get("schema_version") != EXPECTED_ON_CALL_DRILL_VERIFICATION_SCHEMA:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
        if payload.get("error"):
            print(payload["error"], file=sys.stderr)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
