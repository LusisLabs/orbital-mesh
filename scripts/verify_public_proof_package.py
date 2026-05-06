#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.public_proof import (
    PUBLIC_PROOF_VERIFICATION_VERSION,
    verify_public_proof_package,
)


EXPECTED_PUBLIC_PROOF_VERIFICATION_SCHEMA = "mesh.public_proof_package_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Orbital Mesh public proof package manifest.")
    parser.add_argument(
        "--package",
        default="config/public-proof.package.json",
        help="Path to a mesh.public_proof_package.v1 manifest.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_public_proof_package(args.package)
    if (
        payload.get("schema_version") != PUBLIC_PROOF_VERIFICATION_VERSION
        or payload.get("schema_version") != EXPECTED_PUBLIC_PROOF_VERIFICATION_SCHEMA
    ):
        payload = {**payload, "status": "fail", "errors": [*payload.get("errors", []), "unexpected schema version"]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            print(f"{'pass' if passed else 'fail'} {name}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
