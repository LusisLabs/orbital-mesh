#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.repeatability import REPEATABILITY_VERIFICATION_VERSION, verify_repeatability_proof


EXPECTED_REPEATABILITY_VERIFICATION_SCHEMA = "mesh.repeatability_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mesh repeatability proof.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.repeatability_proof.v1 packet.")
    parser.add_argument("--expected-head", default="", help="Require repo_head to match this commit.")
    parser.add_argument(
        "--allow-dirty-env",
        action="store_true",
        help="Do not require working_tree_clean, clean_env_recreated, and fresh_image_built.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_repeatability_proof(
        args.proof,
        expected_head=args.expected_head or None,
        require_clean_env=not args.allow_dirty_env,
        repo_root=REPO_ROOT,
    )
    if payload.get("schema_version") != REPEATABILITY_VERIFICATION_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if payload.get("schema_version") != EXPECTED_REPEATABILITY_VERIFICATION_SCHEMA:
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
