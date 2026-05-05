from __future__ import annotations

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


def _durable_uri_ok(uri: str) -> bool:
    try:
        validate_durable_artifact_uri(uri)
    except ValueError:
        return False
    return True
