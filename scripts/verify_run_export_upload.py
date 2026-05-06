#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.run_export_upload import (
    RUN_EXPORT_UPLOAD_VERIFICATION_VERSION,
    verify_run_export_upload_proof,
)


EXPECTED_UPLOAD_VERIFICATION_SCHEMA = "mesh.run_export_upload_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify durable upload proof for a Mesh run export package and archive.")
    parser.add_argument("--package", required=True, help="Path to a mesh.run_export.v1 JSON package.")
    parser.add_argument("--archive", required=True, help="Path to a mesh.run_export_archive.v1 zip archive.")
    parser.add_argument("--proof", required=True, help="Path to a mesh.run_export_upload_proof.v1 manifest.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_run_export_upload_proof(
        package_path=args.package,
        archive_path=args.archive,
        proof_path=args.proof,
    )
    if (
        payload.get("schema_version") != RUN_EXPORT_UPLOAD_VERIFICATION_VERSION
        or payload.get("schema_version") != EXPECTED_UPLOAD_VERIFICATION_SCHEMA
    ):
        payload = {**payload, "status": "fail", "errors": [*payload.get("errors", []), "unexpected_schema_version"]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
        for error in payload["errors"]:
            print(error, file=sys.stderr)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
