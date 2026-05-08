from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .run_export_retrieval import verify_run_export_retrieval
from .schema_validation import SchemaValidationError, validate_payload


RUN_EXPORT_UPLOAD_PROOF_SCHEMA = "run-export-upload-proof.schema.json"
RUN_EXPORT_UPLOAD_PROOF_VERSION = "mesh.run_export_upload_proof.v1"
RUN_EXPORT_UPLOAD_VERIFICATION_VERSION = "mesh.run_export_upload_verification.v1"
DURABLE_RUN_EXPORT_URI_SCHEMES = frozenset({"s3", "gs", "az", "azblob", "r2", "https"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_run_export_upload_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(RUN_EXPORT_UPLOAD_PROOF_SCHEMA, payload)
    return payload


def verify_run_export_upload_proof(
    *,
    package_path: str | Path | None,
    archive_path: str | Path | None,
    proof_path: str | Path | None,
) -> dict[str, Any]:
    package_file = Path(package_path) if package_path else None
    archive_file = Path(archive_path) if archive_path else None
    proof_file = Path(proof_path) if proof_path else None
    errors: list[str] = []
    try:
        proof = load_run_export_upload_proof(proof_file)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        errors.append(f"proof_load_failed:{exc}")

    retrieval = verify_run_export_retrieval(package_path=package_file, archive_path=archive_file)
    package = _load_json(package_file, errors)
    checks = _checks(
        proof=proof,
        package=package,
        package_file=package_file,
        archive_file=archive_file,
        retrieval=retrieval,
    )
    payload = {
        "schema_version": RUN_EXPORT_UPLOAD_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) and not errors else "fail",
        "run_id": package.get("run_id") if package else None,
        "package_path": str(package_file) if package_file else None,
        "archive_path": str(archive_file) if archive_file else None,
        "proof_path": str(proof_file) if proof_file else None,
        "checks": checks,
        "retrieval": {
            "status": retrieval.get("status"),
            "checks": retrieval.get("checks", {}),
        },
        "errors": errors,
    }
    return payload


def _checks(
    *,
    proof: dict[str, Any] | None,
    package: dict[str, Any] | None,
    package_file: Path | None,
    archive_file: Path | None,
    retrieval: dict[str, Any],
) -> dict[str, bool]:
    package_upload = _upload(proof, "package")
    archive_upload = _upload(proof, "archive")
    provider = str(proof.get("provider") or "").strip() if proof is not None else ""
    return {
        "retrieval_verified": retrieval.get("status") == "pass",
        "proof_present": proof is not None,
        "proof_schema_valid": proof is not None,
        "run_id_matches": proof is not None and package is not None and proof.get("run_id") == package.get("run_id"),
        "export_id_matches": proof is not None and package is not None and proof.get("export_id") == package.get("export_id"),
        "provider_present": proof is not None and bool(provider),
        "restore_tested": proof is not None and proof.get("restore_tested") is True,
        "restore_ref_present": proof is not None and bool(str(proof.get("restore_ref") or "").strip()),
        "package_upload_present": package_upload is not None,
        "archive_upload_present": archive_upload is not None,
        "package_provider_matches": bool(provider)
        and package_upload is not None
        and str(package_upload.get("provider") or "").strip() == provider,
        "archive_provider_matches": bool(provider)
        and archive_upload is not None
        and str(archive_upload.get("provider") or "").strip() == provider,
        "package_uri_durable": _durable_uri(str(package_upload.get("blob_uri") or "")) if package_upload else False,
        "archive_uri_durable": _durable_uri(str(archive_upload.get("blob_uri") or "")) if archive_upload else False,
        "package_sha256_matches": _upload_matches_file(package_upload, package_file),
        "archive_sha256_matches": _upload_matches_file(archive_upload, archive_file),
        "package_byte_count_matches": _byte_count_matches(package_upload, package_file),
        "archive_byte_count_matches": _byte_count_matches(archive_upload, archive_file),
        "package_content_type_json": package_upload is not None and package_upload.get("content_type") == "application/json",
        "archive_content_type_zip": archive_upload is not None and archive_upload.get("content_type") == "application/zip",
        "retention_present": package is not None
        and isinstance(package.get("retention"), dict)
        and bool((package.get("retention") or {}).get("delete_after")),
    }


def _load_json(path: Path | None, errors: list[str]) -> dict[str, Any] | None:
    if path is None:
        errors.append("package_path_missing")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"package_load_failed:{exc}")
        return None
    return payload if isinstance(payload, dict) else None


def _upload(proof: dict[str, Any] | None, artifact_type: str) -> dict[str, Any] | None:
    if not isinstance(proof, dict):
        return None
    uploads = proof.get("uploads")
    if not isinstance(uploads, list):
        return None
    for upload in uploads:
        if isinstance(upload, dict) and upload.get("artifact_type") == artifact_type:
            return upload
    return None


def _upload_matches_file(upload: dict[str, Any] | None, path: Path | None) -> bool:
    if upload is None or path is None or not path.is_file():
        return False
    expected = str(upload.get("sha256") or "")
    return bool(_SHA256_RE.match(expected)) and _file_sha256(path) == expected


def _byte_count_matches(upload: dict[str, Any] | None, path: Path | None) -> bool:
    if upload is None or path is None or not path.is_file():
        return False
    return upload.get("byte_count") == path.stat().st_size


def _durable_uri(raw: str) -> bool:
    parsed = urlparse(raw.strip())
    return parsed.scheme in DURABLE_RUN_EXPORT_URI_SCHEMES and bool(parsed.netloc)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
