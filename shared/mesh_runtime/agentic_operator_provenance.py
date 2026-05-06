from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTIC_OPERATOR_SOURCE_PROVENANCE_SCHEMA = "agentic-operator-source-provenance.schema.json"
AGENTIC_OPERATOR_SOURCE_PROVENANCE_VERSION = "mesh.agentic_operator_source_provenance.v1"
AGENTIC_OPERATOR_SOURCE_VERIFICATION_VERSION = "mesh.agentic_operator_source_provenance_verification.v1"
REQUIRED_SOURCE_PATHS = frozenset(
    {
        "agentic-operator-core-main/api/v1alpha1/agentworkload_types.go",
        "agentic-operator-core-main/api/v1alpha1/tenant_types.go",
        "agentic-operator-core-main/internal/controller",
        "agentic-operator-core-main/pkg/argo",
        "agentic-operator-core-main/pkg/multitenancy",
        "agentic-operator-core-main/pkg/finops",
        "agentic-operator-core-main/pkg/llm",
        "agentic-operator-core-main/pkg/mcp",
        "agentic-operator-core-main/charts",
        "agentic-operator-core-main/config/crd",
        "agentic-operator-core-main/config/rbac",
        "agentic-operator-core-main/config/policies",
        "agentic-operator-core-main/cmd/agentctl",
    }
)
REQUIRED_AUTHORITY_GATES = frozenset(
    {
        "ownership_boundary",
        "tenant_boundary",
        "policy_lifecycle",
        "evidence_sufficiency",
        "operator_approval",
        "rollback_authority",
        "timeline_proof",
        "release_provenance",
    }
)
FORBIDDEN_CREDENTIALS = frozenset(
    {
        "production_actuator_credentials",
        "production_kubeconfig",
        "repository_write_credentials",
    }
)


def load_agentic_operator_source_provenance(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    provenance_path = _resolve_path(path)
    if not provenance_path.exists():
        return None
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    validate_payload(AGENTIC_OPERATOR_SOURCE_PROVENANCE_SCHEMA, payload)
    return payload


def verify_agentic_operator_source_provenance(path: str | Path | None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        provenance = load_agentic_operator_source_provenance(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        provenance = None
        errors.append(f"provenance_invalid:{type(exc).__name__}")
    if provenance is None:
        errors.append("provenance_missing")
        source_entries: list[dict[str, Any]] = []
    else:
        source_entries = [
            entry
            for entry in provenance.get("source_paths", [])
            if isinstance(entry, dict)
        ]

    source_paths = [str(entry.get("path") or "") for entry in source_entries]
    duplicate_paths = sorted({item for item in source_paths if source_paths.count(item) > 1})
    missing_source_paths = sorted(REQUIRED_SOURCE_PATHS - set(source_paths))
    missing_existing_paths = sorted(path for path in source_paths if not _resolve_path(path).exists())
    missing_import_value = _missing_text(source_entries, "import_value")
    missing_fork_posture = _missing_text(source_entries, "fork_posture")
    missing_adaptation = _missing_text(source_entries, "orbital_mesh_adaptation")
    copied_paths = sorted(
        imported_path
        for entry in source_entries
        for imported_path in entry.get("imported_paths", [])
        if str(imported_path).strip()
    )
    missing_gates = sorted(REQUIRED_AUTHORITY_GATES - set(provenance.get("required_authority_gates", []) if provenance else []))
    missing_forbidden_credentials = sorted(
        FORBIDDEN_CREDENTIALS - set(provenance.get("forbidden_credentials", []) if provenance else [])
    )
    license_path = _resolve_path(str(provenance.get("license_path") or "")) if provenance else None
    license_valid = bool(
        provenance
        and provenance.get("license") == "Apache-2.0"
        and license_path
        and license_path.exists()
        and "Apache License" in license_path.read_text(encoding="utf-8", errors="ignore")[:200]
    )
    source_root = _resolve_path(str(provenance.get("source_root") or "")) if provenance else None
    snapshot_sha = _snapshot_sha256(source_root) if source_root and source_root.exists() else None
    snapshot_matches = bool(provenance and snapshot_sha == provenance.get("source_snapshot_sha256"))
    source_commit_recorded = bool(provenance and provenance.get("source_commit_status") == "recorded" and provenance.get("source_commit"))
    source_commit_unavailable_but_snapshotted = bool(
        provenance
        and provenance.get("source_commit_status") == "unavailable_import_snapshot"
        and not provenance.get("source_commit")
        and snapshot_matches
    )

    if not source_entries:
        errors.append("source_paths_missing")
    if duplicate_paths:
        errors.append("duplicate_source_paths")
    if missing_source_paths:
        errors.append("required_source_paths_missing")
    if missing_existing_paths:
        errors.append("source_paths_not_found")
    if missing_import_value:
        errors.append("import_value_missing")
    if missing_fork_posture:
        errors.append("fork_posture_missing")
    if missing_adaptation:
        errors.append("orbital_mesh_adaptation_missing")
    if copied_paths:
        errors.append("imported_paths_present_before_fork_gate")
    if provenance and provenance.get("active_runtime") is not False:
        errors.append("active_runtime_enabled")
    if provenance and provenance.get("wholesale_copy_allowed") is not False:
        errors.append("wholesale_copy_allowed")
    if provenance and provenance.get("comparative_claims_allowed") is not False:
        errors.append("comparative_claims_allowed")
    if missing_gates:
        errors.append("authority_gates_missing")
    if missing_forbidden_credentials:
        errors.append("forbidden_credentials_missing")
    if not license_valid:
        errors.append("apache_license_not_verified")
    if provenance and not (source_commit_recorded or source_commit_unavailable_but_snapshotted):
        errors.append("source_commit_or_snapshot_not_verified")

    return {
        "schema_version": AGENTIC_OPERATOR_SOURCE_VERIFICATION_VERSION,
        "status": "pass" if not errors else "fail",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "provenance_path": str(_resolve_path(path)) if path else None,
        "provenance_version": provenance.get("version") if provenance else None,
        "source_root": provenance.get("source_root") if provenance else None,
        "source_commit_status": provenance.get("source_commit_status") if provenance else None,
        "source_commit_recorded": source_commit_recorded,
        "source_snapshot_sha256": snapshot_sha,
        "source_snapshot_matches": snapshot_matches,
        "license_valid": license_valid,
        "source_path_count": len(source_entries),
        "missing_source_paths": missing_source_paths,
        "missing_existing_paths": missing_existing_paths,
        "duplicate_paths": duplicate_paths,
        "missing_import_value": missing_import_value,
        "missing_fork_posture": missing_fork_posture,
        "missing_adaptation": missing_adaptation,
        "copied_paths": copied_paths,
        "missing_gates": missing_gates,
        "missing_forbidden_credentials": missing_forbidden_credentials,
        "errors": errors,
    }


def agentic_operator_source_provenance_ready(path: str | Path | None) -> bool:
    return verify_agentic_operator_source_provenance(path)["status"] == "pass"


def _missing_text(entries: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        str(entry.get("path"))
        for entry in entries
        if not str(entry.get(field) or "").strip()
    )


def _resolve_path(path: str | Path | None) -> Path:
    p = Path(path or "")
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


def _snapshot_sha256(source_root: Path) -> str:
    files = sorted(path for path in source_root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(REPO_ROOT).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{file_hash}  {relative}\n".encode("utf-8"))
    return digest.hexdigest()
