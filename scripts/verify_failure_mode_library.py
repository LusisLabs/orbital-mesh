#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.failure_modes import build_failure_mode_library_packet


EXPECTED_FAILURE_MODE_LIBRARY_SCHEMA = "mesh.failure_mode_library.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh failure-mode library.")
    parser.add_argument("--library", default="", help="Path to a mesh.failure_mode_library.registry.v1 file.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = build_failure_mode_library_packet(args.library or None)
    if payload.get("schema_version") != EXPECTED_FAILURE_MODE_LIBRARY_SCHEMA:
        payload = {**payload, "status": "incomplete", "blockers": [*payload.get("blockers", []), "unexpected_schema_version"]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
        for blocker in payload["blockers"]:
            print(f"blocker {blocker}")
    return 0 if payload["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
