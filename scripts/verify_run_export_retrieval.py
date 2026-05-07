#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.run_export_retrieval import RUN_EXPORT_RETRIEVAL_VERSION, verify_run_export_retrieval


EXPECTED_RETRIEVAL_SCHEMA_VERSION = "mesh.run_export_retrieval.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Mesh run export package and optional archive for audit retrieval.")
    parser.add_argument("--package", required=True, help="Path to a mesh.run_export.v1 JSON package.")
    parser.add_argument("--archive", help="Path to a mesh.run_export_archive.v1 zip archive.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_run_export_retrieval(package_path=args.package, archive_path=args.archive)
    if (
        payload.get("schema_version") != RUN_EXPORT_RETRIEVAL_VERSION
        or payload.get("schema_version") != EXPECTED_RETRIEVAL_SCHEMA_VERSION
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
