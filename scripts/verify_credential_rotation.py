#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY_PATH
from shared.mesh_runtime.credential_rotation import (
    CREDENTIAL_ROTATION_VERIFICATION_VERSION,
    verify_credential_rotation_proof,
)


EXPECTED_VERIFICATION_SCHEMA_VERSION = "mesh.credential_rotation_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify connector credential rotation evidence against the certification registry.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.credential_rotation_proof.v1 packet.")
    parser.add_argument("--connector-id", required=True, help="Connector id from config/connector-certification.registry.json.")
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY_PATH),
        help="Connector certification registry path.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_credential_rotation_proof(
        proof_path=args.proof,
        registry_path=args.registry,
        connector_id=args.connector_id,
    )
    if (
        payload.get("schema_version") != CREDENTIAL_ROTATION_VERIFICATION_VERSION
        or payload.get("schema_version") != EXPECTED_VERIFICATION_SCHEMA_VERSION
    ):
        payload = {**payload, "status": "fail", "error": "unexpected verification schema version"}
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
