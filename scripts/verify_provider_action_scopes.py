#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.provider_action_scope import (
    PROVIDER_ACTION_SCOPE_VERIFICATION_VERSION,
    verify_provider_action_scope_proof,
)


EXPECTED_PROVIDER_ACTION_SCOPE_VERIFICATION_SCHEMA = "mesh.provider_action_scope_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify provider action scopes against connector certification.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.provider_action_scope_proof.v1 packet.")
    parser.add_argument(
        "--registry",
        default="config/connector-certification.registry.json",
        help="Connector certification registry path.",
    )
    parser.add_argument("--require-live", action="store_true", help="Require evidence_level=live and per-action live refs.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_provider_action_scope_proof(
        args.proof,
        registry_path=args.registry,
        require_live=args.require_live,
    )
    if payload.get("schema_version") != PROVIDER_ACTION_SCOPE_VERIFICATION_VERSION:
        payload = {**payload, "status": "fail", "error": "unexpected_schema_version"}
    if payload.get("schema_version") != EXPECTED_PROVIDER_ACTION_SCOPE_VERIFICATION_SCHEMA:
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
