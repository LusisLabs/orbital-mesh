from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


BACKUP_RESTORE_REHEARSAL_SCHEMA = "backup-restore-rehearsal.schema.json"
BACKUP_RESTORE_REHEARSAL_VERSION = "mesh.backup_restore_rehearsal.v1"
BACKUP_RESTORE_VERIFICATION_VERSION = "mesh.backup_restore_verification.v1"
BACKUP_RESTORE_COMPONENTS = frozenset(
    {
        "state_store",
        "vault",
        "merkle_proofs",
        "integrations_config",
        "research_artifacts",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_backup_restore_rehearsal(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(BACKUP_RESTORE_REHEARSAL_SCHEMA, payload)
    return payload


def backup_restore_rehearsal_ready(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
    expected_state_backend: str | None = None,
) -> bool:
    return (
        verify_backup_restore_rehearsal(
            path,
            expected_environment=expected_environment,
            expected_state_backend=expected_state_backend,
        )["status"]
        == "pass"
    )


def verify_backup_restore_rehearsal(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
    expected_state_backend: str | None = None,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_backup_restore_rehearsal(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(
        proof,
        expected_environment=expected_environment,
        expected_state_backend=expected_state_backend,
    )
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": BACKUP_RESTORE_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "rehearsal_id": proof.get("rehearsal_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    *,
    expected_environment: str | None = None,
    expected_state_backend: str | None = None,
) -> dict[str, bool]:
    expected_environment = (expected_environment or "").strip()
    expected_state_backend = (expected_state_backend or "").strip()
    if proof is None:
        checks = {
            "proof_present": False,
            "schema_valid": False,
            "rehearsal_id_present": False,
            "environment_present": False,
            "operator_present": False,
            "backup_ref_present": False,
            "restore_ref_present": False,
            "rpo_non_negative": False,
            "rto_positive": False,
            "restore_within_rto": False,
            "required_components_present": False,
            "all_components_restored": False,
            "component_hashes_match": False,
            "component_hashes_valid": False,
            "component_backup_refs_present": False,
        }
        if expected_environment:
            checks["environment_matches_expected"] = False
        if expected_state_backend:
            checks["state_backend_matches_expected"] = False
        return checks
    components = proof.get("components") if isinstance(proof.get("components"), list) else []
    component_names = {component.get("component") for component in components if isinstance(component, dict)}
    environment = str(proof.get("environment") or "").strip()
    state_backend = str(proof.get("state_backend") or "").strip()
    checks = {
        "proof_present": True,
        "schema_valid": True,
        "rehearsal_id_present": bool(str(proof.get("rehearsal_id") or "").strip()),
        "environment_present": bool(environment),
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "backup_ref_present": bool(str(proof.get("backup_ref") or "").strip()),
        "restore_ref_present": bool(str(proof.get("restore_ref") or "").strip()),
        "rpo_non_negative": isinstance(proof.get("rpo_seconds"), int) and proof.get("rpo_seconds", -1) >= 0,
        "rto_positive": isinstance(proof.get("rto_seconds"), int) and proof.get("rto_seconds", 0) > 0,
        "restore_within_rto": _restore_within_rto(proof),
        "required_components_present": BACKUP_RESTORE_COMPONENTS.issubset(component_names),
        "all_components_restored": bool(components) and all(
            isinstance(component, dict) and component.get("restored") is True for component in components
        ),
        "component_hashes_match": bool(components) and all(
            isinstance(component, dict) and component.get("sha256_before") == component.get("sha256_after")
            for component in components
        ),
        "component_hashes_valid": bool(components) and all(
            isinstance(component, dict)
            and _valid_sha256(str(component.get("sha256_before") or ""))
            and _valid_sha256(str(component.get("sha256_after") or ""))
            for component in components
        ),
        "component_backup_refs_present": bool(components) and all(
            isinstance(component, dict) and bool(str(component.get("backup_uri") or "").strip())
            for component in components
        ),
    }
    if expected_environment:
        checks["environment_matches_expected"] = environment == expected_environment
    if expected_state_backend:
        checks["state_backend_matches_expected"] = state_backend == expected_state_backend
    return checks


def _restore_within_rto(proof: dict[str, Any]) -> bool:
    measured = proof.get("measured_restore_seconds")
    rto = proof.get("rto_seconds")
    return isinstance(measured, (int, float)) and isinstance(rto, int) and measured <= rto


def _valid_sha256(raw: str) -> bool:
    return bool(_SHA256_RE.match(raw.strip()))


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
