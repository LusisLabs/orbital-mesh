#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.production_target import (
    PRODUCTION_TARGET_VERIFICATION_VERSION,
    verify_production_target_proof,
)


EXPECTED_PRODUCTION_TARGET_VERIFICATION_SCHEMA = "mesh.production_target_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a bounded production-like Mesh target proof.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.production_target_proof.v1 packet.")
    parser.add_argument("--expected-environment", default="", help="Require the proof environment to match this value.")
    parser.add_argument("--require-live", action="store_true", help="Require evidence_level=live and live artifact refs.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_production_target_proof(
        args.proof,
        expected_environment=args.expected_environment,
        require_live=args.require_live,
    )
    if payload.get("schema_version") != PRODUCTION_TARGET_VERIFICATION_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if payload.get("schema_version") != EXPECTED_PRODUCTION_TARGET_VERIFICATION_SCHEMA:
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
