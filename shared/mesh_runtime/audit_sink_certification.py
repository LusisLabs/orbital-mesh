from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .audit_sink import EXTERNAL_AUDIT_STATES, load_audit_sink_proof, verify_audit_sink_proof
from .connector_certification import load_connector_certification_registry
from .schema_validation import SchemaValidationError, validate_payload


AUDIT_SINK_CERTIFICATION_SCHEMA = "audit-sink-certification.schema.json"
AUDIT_SINK_CERTIFICATION_VERSION = "mesh.audit_sink_certification.v1"
AUDIT_SINK_CERTIFICATION_VERIFICATION_VERSION = "mesh.audit_sink_certification_verification.v1"
_LOCAL_ENVIRONMENTS = frozenset({"", "local", "dev", "development", "test", "ci"})


def load_audit_sink_certification(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    certification_path = Path(path)
    if not certification_path.exists():
        return None
    payload = json.loads(certification_path.read_text(encoding="utf-8"))
    validate_payload(AUDIT_SINK_CERTIFICATION_SCHEMA, payload)
    return payload


def audit_sink_certification_ready(
    path: str | Path | None,
    *,
    proof_path: str | Path | None,
    registry_path: str | Path | None,
) -> bool:
    return (
        verify_audit_sink_certification(
            path,
            proof_path=proof_path,
            registry_path=registry_path,
        )["status"]
        == "pass"
    )


def verify_audit_sink_certification(
    path: str | Path | None,
    *,
    proof_path: str | Path | None,
    registry_path: str | Path | None,
) -> dict[str, Any]:
    certification: dict[str, Any] | None = None
    proof: dict[str, Any] | None = None
    registry_record: dict[str, Any] | None = None
    load_error: str | None = None
    certification_path = Path(path) if path else None
    resolved_proof_path = Path(proof_path) if proof_path else None
    resolved_registry_path = Path(registry_path) if registry_path else None
    try:
        certification = load_audit_sink_certification(certification_path)
        proof = load_audit_sink_proof(resolved_proof_path)
        registry = load_connector_certification_registry(str(resolved_registry_path) if resolved_registry_path else None)
        registry_record = _audit_sink_record(registry)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        load_error = str(exc)

    proof_verification = verify_audit_sink_proof(resolved_proof_path)
    checks = _certification_checks(
        certification=certification,
        proof=proof,
        proof_path=resolved_proof_path,
        registry_record=registry_record,
        proof_verification=proof_verification,
    )
    if certification is None:
        checks["certification_present"] = False
    if load_error:
        checks["schema_valid"] = False

    status = "pass" if all(checks.values()) else "fail"
    return {
        "schema_version": AUDIT_SINK_CERTIFICATION_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": status,
        "certification_path": str(certification_path) if certification_path else None,
        "proof_path": str(resolved_proof_path) if resolved_proof_path else None,
        "registry_path": str(resolved_registry_path) if resolved_registry_path else None,
        "certification_id": certification.get("certification_id") if certification else None,
        "sink_id": certification.get("sink_id") if certification else None,
        "checks": checks,
        "proof_verification_status": proof_verification.get("status"),
        "error": load_error,
    }


def _certification_checks(
    *,
    certification: dict[str, Any] | None,
    proof: dict[str, Any] | None,
    proof_path: Path | None,
    registry_record: dict[str, Any] | None,
    proof_verification: dict[str, Any],
) -> dict[str, bool]:
    if certification is None:
        return {
            "certification_present": False,
            "schema_valid": False,
            "connector_id_audit_sink": False,
            "state_certified": False,
            "environment_production_like": False,
            "review_present": False,
            "registry_present": False,
            "registry_record_certified": False,
            "registry_state_matches_certification": False,
            "registry_blockers_empty": False,
            "registry_evidence_refs_present": False,
            "proof_verification_passed": False,
            "proof_sha256_matches": False,
            "sink_matches_proof": False,
            "state_matches_proof": False,
            "authority_boundary_matches_proof": False,
            "required_artifacts_present": False,
            "compliance_reliance_allowed": False,
            "raw_secret_material_absent": False,
            "blockers_empty": False,
        }
    registry_state = str(registry_record.get("state") or "") if registry_record else ""
    registry_blockers = registry_record.get("blockers") if registry_record else []
    registry_evidence_refs = registry_record.get("evidence_refs") if registry_record else []
    proof_boundary = proof.get("credential_boundary") if isinstance(proof, dict) else {}
    certification_boundary = certification.get("authority_boundary")
    if not isinstance(proof_boundary, dict):
        proof_boundary = {}
    if not isinstance(certification_boundary, dict):
        certification_boundary = {}
    return {
        "certification_present": True,
        "schema_valid": True,
        "connector_id_audit_sink": certification.get("connector_id") == "audit_sink",
        "state_certified": certification.get("sink_state") in EXTERNAL_AUDIT_STATES,
        "environment_production_like": str(certification.get("environment") or "").strip().lower()
        not in _LOCAL_ENVIRONMENTS,
        "review_present": _present(certification.get("reviewed_by")) and _present(certification.get("approved_at")),
        "registry_present": registry_record is not None,
        "registry_record_certified": registry_state in EXTERNAL_AUDIT_STATES,
        "registry_state_matches_certification": registry_state == certification.get("registry_state"),
        "registry_blockers_empty": isinstance(registry_blockers, list) and not registry_blockers,
        "registry_evidence_refs_present": isinstance(registry_evidence_refs, list) and bool(registry_evidence_refs),
        "proof_verification_passed": proof_verification.get("status") == "pass",
        "proof_sha256_matches": (
            proof_path is not None
            and proof_path.exists()
            and certification.get("audit_sink_proof_sha256") == _sha256(proof_path)
        ),
        "sink_matches_proof": bool(proof) and certification.get("sink_id") == proof.get("sink_id"),
        "state_matches_proof": bool(proof) and certification.get("sink_state") == proof.get("sink_state"),
        "authority_boundary_matches_proof": _authority_boundary_matches(
            certification_boundary,
            proof_boundary,
        ),
        "required_artifacts_present": _required_artifacts_present(certification.get("required_artifacts")),
        "compliance_reliance_allowed": certification.get("compliance_reliance_allowed") is True,
        "raw_secret_material_absent": certification.get("raw_secret_material_present") is False,
        "blockers_empty": isinstance(certification.get("blockers"), list) and not certification.get("blockers"),
    }


def _audit_sink_record(registry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not registry:
        return None
    for record in registry.get("connectors", []):
        if isinstance(record, dict) and record.get("connector_id") == "audit_sink":
            return record
    return None


def _authority_boundary_matches(certification: dict[str, Any], proof: dict[str, Any]) -> bool:
    expected_fields = (
        "service_account_ref",
        "credential_mode",
        "runtime_secret_mount_required",
        "production_actuator_credentials_allowed",
        "repo_write_credentials_allowed",
    )
    return all(certification.get(field) == proof.get(field) for field in expected_fields)


def _required_artifacts_present(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    required_fields = (
        "append_only_receipt_ref",
        "run_export_ref",
        "merkle_proof_ref",
        "rotation_evidence_ref",
        "break_glass_recording_ref",
        "retention_policy_ref",
    )
    return all(_present(raw.get(field)) for field in required_fields)


def _present(raw: Any) -> bool:
    return bool(str(raw or "").strip())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
