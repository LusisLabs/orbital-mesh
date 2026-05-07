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

from mesh_brain.artifact_registry import verify_production_artifact_record


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mesh Brain production artifact refs and optional object-storage upload proofs.")
    parser.add_argument("--artifacts-json", required=True, help="Path to state-store artifacts JSON. Accepts {'artifacts': [...]} or a raw list.")
    parser.add_argument("--proof-manifest", help="Path to mesh.artifact_upload_proof.v1 manifest with uploaded blob proof records.")
    parser.add_argument("--require-upload-proof", action="store_true", help="Fail unless every production artifact has matching upload proof.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    try:
        payload = verify_registry(
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


def verify_registry(
    *,
    artifacts_json: Path,
    proof_manifest: Path | None = None,
    require_upload_proof: bool = False,
) -> dict[str, Any]:
    records = _load_artifact_records(artifacts_json)
    production_records = [_normalize_record(record) for record in records if _is_mesh_brain_production_record(record)]
    proofs = _load_upload_proofs(proof_manifest) if proof_manifest else {}
    results = [
        _verify_record(record, proofs=proofs, require_upload_proof=require_upload_proof)
        for record in production_records
    ]
    checks = {
        "production_artifacts_present": bool(production_records),
        "production_artifact_records_valid": bool(production_records) and all(result["registry"]["status"] == "pass" for result in results),
        "upload_proofs_present": not require_upload_proof or (bool(production_records) and all(result["upload_proof"]["status"] == "pass" for result in results)),
    }
    return {
        "schema_version": "mesh.mesh_brain_artifact_registry_proof.v1",
        "status": "pass" if all(checks.values()) else "fail",
        "artifact_count": len(production_records),
        "checks": checks,
        "records": results,
    }


def _load_artifact_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_records = payload.get("artifacts") if isinstance(payload, dict) else payload
    if not isinstance(raw_records, list):
        raise ValueError("artifacts JSON must contain an artifacts list or be a list")
    return [dict(record) for record in raw_records if isinstance(record, dict)]


def _load_upload_proofs(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_uploads = payload.get("uploads") if isinstance(payload, dict) else payload
    if not isinstance(raw_uploads, list):
        raise ValueError("upload proof manifest must contain an uploads list or be a list")
    proofs: dict[str, dict[str, Any]] = {}
    for upload in raw_uploads:
        if not isinstance(upload, dict):
            continue
        blob_uri = str(upload.get("blob_uri") or upload.get("uri") or "").strip()
        if blob_uri:
            proofs[blob_uri] = dict(upload)
    return proofs


def _is_mesh_brain_production_record(record: dict[str, Any]) -> bool:
    artifact_key = str(record.get("artifact_key") or "")
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return artifact_key.startswith("mesh_brain_") and isinstance(metadata.get("production_artifact"), dict)


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": record.get("run_id"),
        "event_id": record.get("event_id"),
        "artifact_key": record.get("artifact_key"),
        "uri": record.get("uri"),
        "path": record.get("path"),
        "content_hash": record.get("content_hash"),
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
    }


def _verify_record(
    record: dict[str, Any],
    *,
    proofs: dict[str, dict[str, Any]],
    require_upload_proof: bool,
) -> dict[str, Any]:
    registry = verify_production_artifact_record(record)
    uri = str(record.get("uri") or "")
    proof = proofs.get(uri)
    upload_status = _verify_upload_proof(record, proof) if require_upload_proof else {"status": "skipped", "checks": {}}
    return {
        "artifact_key": record.get("artifact_key"),
        "uri": uri,
        "registry": registry,
        "upload_proof": upload_status,
    }


def _verify_upload_proof(record: dict[str, Any], proof: dict[str, Any] | None) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    production = metadata.get("production_artifact") if isinstance(metadata.get("production_artifact"), dict) else {}
    expected_byte_count = production.get("byte_count")
    checks = {
        "proof_present": isinstance(proof, dict),
        "sha256_matches": isinstance(proof, dict) and proof.get("sha256") == record.get("content_hash"),
        "byte_count_matches": isinstance(proof, dict)
        and (expected_byte_count is None or proof.get("byte_count") == expected_byte_count),
        "provider_present": isinstance(proof, dict) and bool(str(proof.get("provider") or "").strip()),
        "uploaded_at_present": isinstance(proof, dict) and bool(str(proof.get("uploaded_at") or "").strip()),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
    }


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
