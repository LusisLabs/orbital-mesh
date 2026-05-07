from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .connector_certification import load_connector_certification_registry
from .schema_validation import SchemaValidationError, validate_payload


CREDENTIAL_ROTATION_PROOF_SCHEMA = "credential-rotation-proof.schema.json"
CREDENTIAL_ROTATION_PROOF_VERSION = "mesh.credential_rotation_proof.v1"
CREDENTIAL_ROTATION_VERIFICATION_VERSION = "mesh.credential_rotation_verification.v1"


def load_credential_rotation_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(CREDENTIAL_ROTATION_PROOF_SCHEMA, payload)
    return payload


def verify_credential_rotation_proof(
    *,
    proof_path: str | Path | None,
    registry_path: str | Path | None,
    connector_id: str,
) -> dict[str, Any]:
    proof: dict[str, Any] | None = None
    registry: dict[str, Any] | None = None
    load_error: str | None = None
    try:
        proof = load_credential_rotation_proof(proof_path)
        registry = load_connector_certification_registry(str(registry_path) if registry_path else None)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        load_error = str(exc)

    record = _connector_record(registry, connector_id)
    checks = _checks(proof=proof, record=record, expected_connector_id=connector_id)
    if proof is None:
        checks["proof_present"] = False
    if record is None:
        checks["connector_registry_record_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": CREDENTIAL_ROTATION_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "connector_id": connector_id,
        "proof_path": str(proof_path) if proof_path else None,
        "registry_path": str(registry_path) if registry_path else None,
        "checks": checks,
        "error": load_error,
    }


def _connector_record(registry: dict[str, Any] | None, connector_id: str) -> dict[str, Any] | None:
    if not isinstance(registry, dict):
        return None
    for record in registry.get("connectors", []):
        if isinstance(record, dict) and record.get("connector_id") == connector_id:
            return record
    return None


def _checks(
    *,
    proof: dict[str, Any] | None,
    record: dict[str, Any] | None,
    expected_connector_id: str,
) -> dict[str, bool]:
    if proof is None or record is None:
        return {
            "proof_present": proof is not None,
            "schema_valid": proof is not None,
            "connector_registry_record_present": record is not None,
            "connector_id_matches": False,
            "service_account_ref_matches": False,
            "credential_mode_matches": False,
            "previous_secret_revoked": False,
            "rotation_ticket_present": False,
            "operator_present": False,
            "evidence_refs_present": False,
            "secret_material_absent": False,
            "break_glass_recording_rehearsed": False,
        }
    boundary = record.get("credential_boundary") if isinstance(record.get("credential_boundary"), dict) else {}
    break_glass_required = bool(boundary.get("break_glass_recording_required"))
    return {
        "proof_present": True,
        "schema_valid": True,
        "connector_registry_record_present": True,
        "connector_id_matches": proof.get("connector_id") == expected_connector_id,
        "service_account_ref_matches": proof.get("service_account_ref") == boundary.get("service_account_ref"),
        "credential_mode_matches": proof.get("credential_mode") == boundary.get("credential_mode"),
        "previous_secret_revoked": proof.get("previous_secret_revoked") is True,
        "rotation_ticket_present": bool(str(proof.get("rotation_ticket_ref") or "").strip()),
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "evidence_refs_present": bool(proof.get("evidence_refs")),
        "secret_material_absent": proof.get("secret_material_absent") is True,
        "break_glass_recording_rehearsed": (
            proof.get("break_glass_recorded") is True if break_glass_required else True
        ),
    }


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
