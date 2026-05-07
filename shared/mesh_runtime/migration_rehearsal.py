from __future__ import annotations

import json
import hashlib
import re
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


MIGRATION_REHEARSAL_SCHEMA = "migration-rehearsal.schema.json"
MIGRATION_REHEARSAL_VERSION = "mesh.migration_rehearsal.v1"
MIGRATION_REHEARSAL_VERIFICATION_VERSION = "mesh.migration_rehearsal_verification.v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_migration_rehearsal(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(MIGRATION_REHEARSAL_SCHEMA, payload)
    return payload


def verify_migration_rehearsal(
    path: str | Path | None,
    *,
    expected_migration_version: str | None = None,
    expected_migration_combined_sha256: str | None = None,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_migration_rehearsal(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)
    checks = _proof_checks(
        proof,
        expected_migration_version=expected_migration_version,
        expected_migration_combined_sha256=expected_migration_combined_sha256,
    )
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": MIGRATION_REHEARSAL_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "rehearsal_id": proof.get("rehearsal_id") if proof else None,
        "migration_version": proof.get("migration_version") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def build_migration_rehearsal_packet(
    *,
    operator_id: str,
    environment: str,
    rollback_ref: str,
    pre_migration_snapshot_ref: str,
    post_migration_validation_ref: str,
    applied_migration_count: int,
    measured_apply_seconds: float,
    measured_rollback_seconds: float,
    rolled_back: bool,
    destructive_changes_reviewed: bool,
    migration_directory: str | Path = "migrations/postgres",
    repo_root: str | Path | None = None,
    rehearsal_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    inventory = migration_rehearsal_inventory(migration_directory, repo_root=repo_root)
    packet = {
        "schema_version": MIGRATION_REHEARSAL_VERSION,
        "rehearsal_id": rehearsal_id or f"migration_rehearsal_{_timestamp().replace('-', '').replace(':', '')}",
        "generated_at": generated_at or _timestamp(),
        "operator_id": operator_id,
        "environment": environment,
        "database_engine": "postgres",
        "migration_directory": inventory["migration_directory"],
        "migration_version": inventory["migration_version"],
        "migration_combined_sha256": inventory["combined_sha256"],
        "applied_migration_count": applied_migration_count,
        "rolled_back": rolled_back,
        "rollback_ref": rollback_ref,
        "pre_migration_snapshot_ref": pre_migration_snapshot_ref,
        "post_migration_validation_ref": post_migration_validation_ref,
        "destructive_changes_reviewed": destructive_changes_reviewed,
        "measured_apply_seconds": measured_apply_seconds,
        "measured_rollback_seconds": measured_rollback_seconds,
    }
    validate_payload(MIGRATION_REHEARSAL_SCHEMA, packet)
    return packet


def migration_rehearsal_inventory(
    migration_directory: str | Path = "migrations/postgres",
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    directory = Path(migration_directory)
    if not directory.is_absolute():
        directory = root / directory
    records = _migration_hash_records(directory, root)
    if not records:
        raise FileNotFoundError(f"no migration SQL files found in {directory}")
    return {
        "migration_directory": _display_path(directory, root),
        "migration_version": Path(records[-1]["path"]).stem,
        "combined_sha256": _combined_hash(records),
        "hashes": records,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    *,
    expected_migration_version: str | None,
    expected_migration_combined_sha256: str | None,
) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "operator_present": False,
            "database_engine_postgres": False,
            "migration_directory_postgres": False,
            "migration_version_present": False,
            "migration_version_matches": False,
            "migration_combined_sha256_valid": False,
            "migration_combined_sha256_matches": False,
            "applied_migration_count_positive": False,
            "rolled_back": False,
            "rollback_ref_present": False,
            "snapshot_ref_present": False,
            "post_validation_ref_present": False,
            "destructive_changes_reviewed": False,
            "timings_present": False,
        }
    migration_version = str(proof.get("migration_version") or "").strip()
    migration_sha = str(proof.get("migration_combined_sha256") or "").strip()
    expected_version = (expected_migration_version or "").strip()
    expected_sha = (expected_migration_combined_sha256 or "").strip()
    return {
        "proof_present": True,
        "schema_valid": True,
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "database_engine_postgres": proof.get("database_engine") == "postgres",
        "migration_directory_postgres": proof.get("migration_directory") == "migrations/postgres",
        "migration_version_present": bool(migration_version),
        "migration_version_matches": not expected_version or migration_version == expected_version,
        "migration_combined_sha256_valid": bool(_SHA256_RE.match(migration_sha)),
        "migration_combined_sha256_matches": not expected_sha or migration_sha == expected_sha,
        "applied_migration_count_positive": (
            isinstance(proof.get("applied_migration_count"), int)
            and proof.get("applied_migration_count", 0) > 0
        ),
        "rolled_back": proof.get("rolled_back") is True,
        "rollback_ref_present": bool(str(proof.get("rollback_ref") or "").strip()),
        "snapshot_ref_present": bool(str(proof.get("pre_migration_snapshot_ref") or "").strip()),
        "post_validation_ref_present": bool(str(proof.get("post_migration_validation_ref") or "").strip()),
        "destructive_changes_reviewed": proof.get("destructive_changes_reviewed") is True,
        "timings_present": isinstance(proof.get("measured_apply_seconds"), (int, float))
        and isinstance(proof.get("measured_rollback_seconds"), (int, float)),
    }


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _migration_hash_records(directory: Path, root: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.sql")):
        records.append({"path": _display_path(path, root), "sha256": _sha256(path)})
    return records


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _combined_hash(records: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
