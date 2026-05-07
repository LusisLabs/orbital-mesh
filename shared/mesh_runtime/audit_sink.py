from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schema_validation import SchemaValidationError, validate_payload


AUDIT_SINK_PROOF_SCHEMA = "audit-sink-proof.schema.json"
AUDIT_SINK_PROOF_VERSION = "mesh.audit_sink_proof.v1"
AUDIT_SINK_VERIFICATION_VERSION = "mesh.audit_sink_contract_verification.v1"
DURABLE_AUDIT_URI_SCHEMES = frozenset({"s3", "gs", "az", "azblob", "r2", "https"})
EXTERNAL_AUDIT_STATES = frozenset({"pilot-ready", "production-ready"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_audit_sink_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(AUDIT_SINK_PROOF_SCHEMA, payload)
    return payload


def audit_sink_proof_ready(path: str | Path | None) -> bool:
    return verify_audit_sink_proof(path)["status"] == "pass"


def verify_audit_sink_proof(path: str | Path | None) -> dict[str, Any]:
    proof: dict[str, Any] | None = None
    load_error: str | None = None
    proof_path = Path(path) if path else None
    try:
        proof = load_audit_sink_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        load_error = str(exc)

    checks = _proof_checks(proof)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False

    status = "pass" if all(checks.values()) else "fail"
    return {
        "schema_version": AUDIT_SINK_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": status,
        "proof_path": str(proof_path) if proof_path else None,
        "sink_id": proof.get("sink_id") if proof else None,
        "destination_uri": proof.get("destination_uri") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "connector_id_audit_sink": False,
            "sink_state_certified": False,
            "destination_uri_durable": False,
            "append_only": False,
            "receipt_present": False,
            "event_count_positive": False,
            "run_export_sha256_valid": False,
            "merkle_root_valid": False,
            "credential_boundary_runtime_secret": False,
            "no_production_actuator_credentials": False,
            "no_repo_write_credentials": False,
            "rotation_evidence_present": False,
            "break_glass_recording_rehearsed": False,
            "retention_positive": False,
        }
    credential_boundary = proof.get("credential_boundary") if isinstance(proof.get("credential_boundary"), dict) else {}
    receipt = proof.get("receipt") if isinstance(proof.get("receipt"), dict) else {}
    return {
        "proof_present": True,
        "schema_valid": True,
        "connector_id_audit_sink": proof.get("connector_id") == "audit_sink",
        "sink_state_certified": proof.get("sink_state") in EXTERNAL_AUDIT_STATES,
        "destination_uri_durable": _durable_uri(str(proof.get("destination_uri") or "")),
        "append_only": proof.get("append_only") is True,
        "receipt_present": all(
            bool(str(receipt.get(field) or "").strip())
            for field in ("receipt_id", "received_at")
        )
        and isinstance(receipt.get("sink_sequence"), int)
        and receipt.get("sink_sequence", 0) >= 0,
        "event_count_positive": isinstance(proof.get("event_count"), int) and proof.get("event_count", 0) > 0,
        "run_export_sha256_valid": _valid_sha256(str(proof.get("run_export_sha256") or "")),
        "merkle_root_valid": _valid_sha256(str(proof.get("merkle_root") or "")),
        "credential_boundary_runtime_secret": (
            credential_boundary.get("credential_mode") == "runtime-secret"
            and credential_boundary.get("runtime_secret_mount_required") is True
            and bool(str(credential_boundary.get("service_account_ref") or "").strip())
        ),
        "no_production_actuator_credentials": (
            credential_boundary.get("production_actuator_credentials_allowed") is False
        ),
        "no_repo_write_credentials": credential_boundary.get("repo_write_credentials_allowed") is False,
        "rotation_evidence_present": bool(str(proof.get("rotation_evidence_ref") or "").strip()),
        "break_glass_recording_rehearsed": (
            proof.get("break_glass_recording_required") is True
            and proof.get("break_glass_drill_recorded") is True
        ),
        "retention_positive": isinstance(proof.get("retention_days"), int) and proof.get("retention_days", 0) > 0,
    }


def _durable_uri(raw: str) -> bool:
    parsed = urlparse(raw.strip())
    return parsed.scheme in DURABLE_AUDIT_URI_SCHEMES and bool(parsed.netloc)


def _valid_sha256(raw: str) -> bool:
    return bool(_SHA256_RE.match(raw.strip()))


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
