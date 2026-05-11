#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mesh_brain.artifact_registry import verify_artifact_upload_registry

PROOF_SCHEMA_VERSION = "mesh.mesh_brain_artifact_registry_proof.v1"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Verify Mesh Brain production artifact refs and optional object-storage upload proofs ({PROOF_SCHEMA_VERSION})."
    )
    parser.add_argument(
        "--artifacts-json",
        required=True,
        help="Path to state-store artifacts JSON. Accepts {'artifacts': [...]} or a raw list.",
    )
    parser.add_argument(
        "--proof-manifest",
        help="Path to mesh.artifact_upload_proof.v1 manifest with uploaded blob proof records.",
    )
    parser.add_argument(
        "--require-upload-proof",
        action="store_true",
        help="Fail unless every production artifact has matching upload proof.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    try:
        payload = verify_artifact_upload_registry(
            artifacts_json=Path(args.artifacts_json),
            proof_manifest=Path(args.proof_manifest) if args.proof_manifest else None,
            require_upload_proof=args.require_upload_proof,
        )
    except Exception as exc:  # noqa: BLE001 - release verifier should report a structured failure.
        payload = {"status": "failed", "error": str(exc)}
        _emit(payload, json_mode=args.json)
        return 1
    _emit(payload, json_mode=args.json)
    return 0 if payload["status"] == "pass" else 1


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload["status"])
        for key, value in payload.items():
            if key != "status":
                print(f"{key}: {value}")


if __name__ == "__main__":
    sys.exit(main())
