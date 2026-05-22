from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
TRIGGER_WEB_SOURCE_PROVENANCE_SCHEMA = "trigger-web-source-provenance.schema.json"
TRIGGER_WEB_SOURCE_PROVENANCE_VERSION = "mesh.trigger_web_source_provenance.v1"
TRIGGER_WEB_SOURCE_VERIFICATION_VERSION = "mesh.trigger_web_source_provenance_verification.v1"
REQUIRED_SOURCE_PATHS = frozenset(
    {
        "apps/webapp",
        "apps/webapp/app/components/layout",
        "apps/webapp/app/components/navigation",
        "apps/webapp/app/components/primitives",
        "apps/webapp/app/routes/storybook.table",
        "apps/webapp/app/routes/_app.orgs.$organizationSlug.projects.$projectParam.env.$envParam.runs",
    }
)
REQUIRED_AUTHORITY_GATES = frozenset(
    {
        "mesh.runtime_state",
        "mesh.contracts",
        "mesh.policy",
        "mesh.approvals",
        "mesh.evidence",
        "mesh.merkle",
        "mesh.vault",
        "mesh.operator_ui",
    }
)
FORBIDDEN_IMPORTS = frozenset(
    {
        "trigger_database_authority",
        "trigger_prisma_models",
        "trigger_clickhouse_runtime",
        "trigger_run_engine_authority",
        "trigger_billing_runtime",
        "trigger_org_auth_authority",
        "trigger_deployment_runtime",
        "trigger_sdk_internals",
    }
)


def load_trigger_web_source_provenance(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    provenance_path = _resolve_path(path)
    if not provenance_path.exists():
        return None
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    validate_payload(TRIGGER_WEB_SOURCE_PROVENANCE_SCHEMA, payload)
    return payload


def verify_trigger_web_source_provenance(path: str | Path | None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        provenance = load_trigger_web_source_provenance(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        provenance = None
        errors.append(f"provenance_invalid:{type(exc).__name__}")
    if provenance is None:
        errors.append("provenance_missing")
        source_entries: list[dict[str, Any]] = []
    else:
        source_entries = [entry for entry in provenance.get("source_paths", []) if isinstance(entry, dict)]

    source_root = _resolve_source_root(str(provenance.get("source_root") or "")) if provenance else None
    source_paths = [_normalize_source_path(str(entry.get("path") or ""), source_root) for entry in source_entries]
    duplicate_paths = sorted({item for item in source_paths if source_paths.count(item) > 1})
    missing_source_paths = sorted(REQUIRED_SOURCE_PATHS - set(source_paths))
    source_root_available = bool(source_root and source_root.exists())
    missing_existing_paths = sorted(
        path for path in source_paths if source_root_available and not _resolve_source_path(path, source_root).exists()
    )
    missing_import_value = _missing_text(source_entries, "import_value")
    missing_fork_posture = _missing_text(source_entries, "fork_posture")
    missing_adaptation = _missing_text(source_entries, "orbital_mesh_adaptation")
    imported_paths = sorted(
        imported_path
        for entry in source_entries
        for imported_path in entry.get("imported_paths", [])
        if str(imported_path).strip()
    )
    disallowed_imported_paths = sorted(
        imported_path
        for entry in source_entries
        for imported_path in entry.get("imported_paths", [])
        if str(imported_path).strip()
        and str(imported_path).strip() not in set(str(path) for path in entry.get("allowed_imported_paths", []))
    )
    missing_allowed_imports = sorted(
        str(entry.get("path"))
        for entry in source_entries
        if not entry.get("allowed_imported_paths")
    )
    missing_gates = sorted(REQUIRED_AUTHORITY_GATES - set(provenance.get("required_authority_gates", []) if provenance else []))
    missing_forbidden_imports = sorted(FORBIDDEN_IMPORTS - set(provenance.get("forbidden_imports", []) if provenance else []))
    license_path = _resolve_source_path(str(provenance.get("license_path") or ""), source_root) if provenance else None
    license_valid = bool(
        provenance
        and provenance.get("license") == "Apache-2.0"
        and (
            not source_root_available
            or (
                license_path
                and license_path.exists()
                and "Apache License" in license_path.read_text(encoding="utf-8", errors="ignore")[:200]
            )
        )
    )
    remotes = provenance.get("remotes", {}) if provenance else {}
    remotes_valid = bool(
        remotes.get("origin") == "https://github.com/LusisLabs/lusistrigger.dev.git"
        and remotes.get("upstream") == "https://github.com/triggerdotdev/trigger.dev.git"
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
    if missing_allowed_imports:
        errors.append("allowed_imported_paths_missing")
    if disallowed_imported_paths:
        errors.append("imported_paths_outside_allowed_targets")
    if provenance and provenance.get("active_runtime") is not False:
        errors.append("active_runtime_enabled")
    if provenance and provenance.get("wholesale_copy_allowed") is not False:
        errors.append("wholesale_copy_allowed")
    if provenance and provenance.get("comparative_claims_allowed") is not False:
        errors.append("comparative_claims_allowed")
    if missing_gates:
        errors.append("authority_gates_missing")
    if missing_forbidden_imports:
        errors.append("forbidden_imports_missing")
    if not license_valid:
        errors.append("apache_license_not_verified")
    if not remotes_valid:
        errors.append("remotes_not_verified")

    return {
        "schema_version": TRIGGER_WEB_SOURCE_VERIFICATION_VERSION,
        "status": "pass" if not errors else "fail",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "provenance_path": str(_resolve_path(path)) if path else None,
        "provenance_version": provenance.get("version") if provenance else None,
        "source_root": provenance.get("source_root") if provenance else None,
        "source_root_available": source_root_available,
        "source_commit": provenance.get("source_commit") if provenance else None,
        "source_commit_status": provenance.get("source_commit_status") if provenance else None,
        "license_valid": license_valid,
        "remotes_valid": remotes_valid,
        "source_path_count": len(source_entries),
        "missing_source_paths": missing_source_paths,
        "missing_existing_paths": missing_existing_paths,
        "duplicate_paths": duplicate_paths,
        "missing_import_value": missing_import_value,
        "missing_fork_posture": missing_fork_posture,
        "missing_adaptation": missing_adaptation,
        "missing_allowed_imports": missing_allowed_imports,
        "imported_paths": imported_paths,
        "disallowed_imported_paths": disallowed_imported_paths,
        "missing_gates": missing_gates,
        "missing_forbidden_imports": missing_forbidden_imports,
        "errors": errors,
    }


def trigger_web_source_provenance_ready(path: str | Path | None) -> bool:
    return verify_trigger_web_source_provenance(path)["status"] == "pass"


def _missing_text(entries: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(str(entry.get("path")) for entry in entries if not str(entry.get(field) or "").strip())


def _resolve_source_root(configured_source_root: str) -> Path:
    override = os.environ.get("MESH_TRIGGER_WEB_SOURCE_ROOT", "").strip()
    return _resolve_path(override or configured_source_root)


def _normalize_source_path(path: str, source_root: Path | None) -> str:
    candidate = Path(path)
    if candidate.is_absolute() and source_root:
        try:
            return candidate.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix().lstrip("./")


def _resolve_source_path(path: str, source_root: Path | None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if source_root:
        return (source_root / candidate).resolve()
    return _resolve_path(candidate)


def _resolve_path(path: str | Path | None) -> Path:
    p = Path(path or "")
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()
