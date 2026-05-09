#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.incident_coverage import (
    INCIDENT_COVERAGE_VERIFICATION_VERSION,
    verify_incident_coverage_proof,
)


EXPECTED_INCIDENT_COVERAGE_VERIFICATION_SCHEMA = "mesh.incident_coverage_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mesh incident-class coverage proof.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.incident_coverage_proof.v1 packet.")
    parser.add_argument("--require-live", action="store_true", help="Require live evidence refs and run ids.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_incident_coverage_proof(args.proof, require_live=args.require_live)
    if payload.get("schema_version") != INCIDENT_COVERAGE_VERIFICATION_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if payload.get("schema_version") != EXPECTED_INCIDENT_COVERAGE_VERIFICATION_SCHEMA:
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
