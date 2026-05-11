from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .runtime import utc_now

DURABLE_ARTIFACT_URI_SCHEMES = frozenset({"s3", "gs", "az", "azblob", "r2", "https"})


@dataclass(frozen=True)
class MeshBrainProductionArtifactRef:
    artifact_key: str
    artifact_type: str
    blob_uri: str
    source_path: str
    sha256: str
    byte_count: int
    content_type: str
    immutable: bool
    registered_at: str
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_production_artifact_ref(
    artifact_ref: dict[str, Any],
    *,
    uri_prefix: str,
    run_id: str,
    artifact_type: str = "mesh_brain_runtime_artifact",
) -> MeshBrainProductionArtifactRef:
    artifact_key = str(artifact_ref.get("artifact_key") or "").strip()
    if not artifact_key:
        raise ValueError("artifact_ref requires artifact_key")
    sha256 = str(artifact_ref.get("sha256") or "").strip()
    if not sha256:
        raise ValueError(f"{artifact_key} requires sha256 before production artifact registration")
    source_path = str(artifact_ref.get("path") or "").strip()
    if not source_path:
        raise ValueError(f"{artifact_key} requires source path before production artifact registration")
    path = Path(source_path)
    if not path.is_file():
        raise ValueError(f"{artifact_key} source artifact is missing: {source_path}")
    blob_uri = production_blob_uri(
        uri_prefix=uri_prefix,
        artifact_key=artifact_key,
        sha256=sha256,
        source_path=path,
    )
    return MeshBrainProductionArtifactRef(
        artifact_key=artifact_key,
        artifact_type=artifact_type,
        blob_uri=blob_uri,
        source_path=str(path),
        sha256=sha256,
        byte_count=path.stat().st_size,
        content_type=str(artifact_ref.get("content_type") or "application/octet-stream"),
        immutable=True,
        registered_at=utc_now(),
        provenance={
            "run_id": run_id,
            "local_path": str(path),
            "source_sha256": sha256,
            "storage_contract": "durable_object_uri_with_content_hash",
        },
    )


def production_blob_uri(*, uri_prefix: str, artifact_key: str, sha256: str, source_path: Path) -> str:
    prefix = uri_prefix.strip().rstrip("/")
    validate_durable_artifact_uri(prefix)
    digest = sha256.strip().lower()
    if len(digest) < 12:
        raise ValueError("sha256 is too short for production artifact URI")
    filename = quote(source_path.name or f"{artifact_key}.artifact", safe="._-")
    key = quote(artifact_key, safe="._-")
    return f"{prefix}/{key}/{digest[:16]}/{filename}"


def validate_durable_artifact_uri(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme not in DURABLE_ARTIFACT_URI_SCHEMES:
        allowed = ", ".join(sorted(DURABLE_ARTIFACT_URI_SCHEMES))
        raise ValueError(f"production artifact URI must use durable object storage scheme ({allowed})")
    if not parsed.netloc:
        raise ValueError("production artifact URI must include a bucket or host")


def verify_production_artifact_record(record: dict[str, Any]) -> dict[str, Any]:
    artifact_key = str(record.get("artifact_key") or "")
    uri = str(record.get("uri") or "")
    content_hash = str(record.get("content_hash") or "")
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    production = metadata.get("production_artifact") if isinstance(metadata.get("production_artifact"), dict) else {}
    checks = {
        "artifact_key_present": bool(artifact_key),
        "content_hash_present": bool(content_hash),
        "durable_uri": _durable_uri_ok(uri),
        "production_metadata_present": bool(production),
        "immutable": production.get("immutable") is True,
        "blob_uri_matches": not production or production.get("blob_uri") == uri,
        "hash_matches": not production or production.get("sha256") == content_hash,
    }
    return {
        "artifact_key": artifact_key,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
    }


def verify_artifact_upload_registry(
    *,
    artifacts_json: str | Path,
    proof_manifest: str | Path | None = None,
    require_upload_proof: bool = False,
) -> dict[str, Any]:
    records = _load_artifact_records(Path(artifacts_json))
    production_records = [_normalize_record(record) for record in records if _is_mesh_brain_production_record(record)]
    proofs = _load_upload_proofs(Path(proof_manifest)) if proof_manifest else {}
    results = [
        _verify_record(record, proofs=proofs, require_upload_proof=require_upload_proof)
        for record in production_records
    ]
    checks = {
        "production_artifacts_present": bool(production_records),
        "production_artifact_records_valid": bool(production_records)
        and all(result["registry"]["status"] == "pass" for result in results),
        "upload_proofs_present": not require_upload_proof
        or (bool(production_records) and all(result["upload_proof"]["status"] == "pass" for result in results)),
    }
    return {
        "schema_version": "mesh.mesh_brain_artifact_registry_proof.v1",
        "status": "pass" if all(checks.values()) else "fail",
        "artifact_count": len(production_records),
        "checks": checks,
        "records": results,
    }


def _durable_uri_ok(uri: str) -> bool:
    try:
        validate_durable_artifact_uri(uri)
    except ValueError:
        return False
    return True


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
