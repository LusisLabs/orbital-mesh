from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schema_validation import SchemaValidationError, validate_payload


PRODUCTION_TARGET_PROOF_SCHEMA = "production-target-proof.schema.json"
PRODUCTION_TARGET_PROOF_VERSION = "mesh.production_target_proof.v1"
PRODUCTION_TARGET_VERIFICATION_VERSION = "mesh.production_target_verification.v1"

_PRODUCTION_LIKE_ENVIRONMENTS = {"staging", "pilot", "production", "prod", "expansion"}


def load_production_target_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(PRODUCTION_TARGET_PROOF_SCHEMA, payload)
    return payload


def verify_production_target_proof(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_production_target_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof, expected_environment=expected_environment, require_live=require_live)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": PRODUCTION_TARGET_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "evidence_level": proof.get("evidence_level") if proof else None,
        "target_ref": proof.get("target_ref") if proof else None,
        "run_id": _section(proof, "run").get("run_id") if proof else None,
        "run_export_ref": _section(proof, "run").get("run_export_ref") if proof else None,
        "timeline_ref": _section(proof, "audit").get("timeline_ref") if proof else None,
        "merkle_ref": _section(proof, "audit").get("merkle_ref") if proof else None,
        "third_party_replay_ref": _section(proof, "audit").get("third_party_replay_ref") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    *,
    expected_environment: str | None,
    require_live: bool,
) -> dict[str, bool]:
    expected_environment = (expected_environment or "").strip()
    if proof is None:
        checks = {
            "proof_present": False,
            "schema_valid": False,
            "production_like_environment": False,
            "live_evidence_required": not require_live,
            "target_ref_present": False,
            "ingress_authenticated": False,
            "operator_identity_recorded": False,
            "telemetry_verified": False,
            "secrets_protected": False,
            "rollback_rehearsed": False,
            "approval_audited": False,
            "run_artifacts_complete": False,
            "governance_refs_complete": False,
            "audit_chain_complete": False,
            "audit_explains_action": False,
            "postmortem_exported": False,
            "secret_redaction_verified": False,
            "third_party_replayable": False,
            "live_artifact_refs_present": not require_live,
        }
        if expected_environment:
            checks["environment_matches_expected"] = False
        return checks

    environment = str(proof.get("environment") or "").strip()
    ingress = _section(proof, "ingress")
    identity = _section(proof, "identity")
    telemetry = _section(proof, "telemetry")
    secrets = _section(proof, "secrets")
    rollback = _section(proof, "rollback")
    approval = _section(proof, "approval")
    run = _section(proof, "run")
    governance = _section(proof, "governance")
    audit = _section(proof, "audit")

    checks = {
        "proof_present": True,
        "schema_valid": True,
        "production_like_environment": environment in _PRODUCTION_LIKE_ENVIRONMENTS,
        "live_evidence_required": (proof.get("evidence_level") == "live") if require_live else True,
        "target_ref_present": bool(str(proof.get("target_ref") or "").strip()),
        "ingress_authenticated": _ingress_authenticated(ingress),
        "operator_identity_recorded": _operator_identity_recorded(identity),
        "telemetry_verified": _telemetry_verified(telemetry),
        "secrets_protected": _secrets_protected(secrets),
        "rollback_rehearsed": _rollback_rehearsed(rollback),
        "approval_audited": _approval_audited(approval),
        "run_artifacts_complete": _run_artifacts_complete(run),
        "governance_refs_complete": _governance_refs_complete(governance),
        "audit_chain_complete": _audit_chain_complete(audit),
        "audit_explains_action": _audit_explains_action(audit),
        "postmortem_exported": bool(str(run.get("postmortem_export_ref") or "").strip())
        and bool(str(governance.get("incident_review_ref") or "").strip()),
        "secret_redaction_verified": audit.get("secret_redaction_verified") is True
        and secrets.get("secret_redaction_verified") is True
        and secrets.get("raw_secret_material_present") is False,
        "third_party_replayable": bool(str(audit.get("third_party_replay_ref") or "").strip()),
        "live_artifact_refs_present": bool(_strings(proof.get("live_artifact_refs"))) if require_live else True,
    }
    if expected_environment:
        checks["environment_matches_expected"] = environment == expected_environment
    return checks


def _ingress_authenticated(ingress: dict[str, Any]) -> bool:
    return (
        bool(str(ingress.get("proof_ref") or "").strip())
        and _https_url(str(ingress.get("ingress_url") or ""))
        and ingress.get("authenticated") is True
        and ingress.get("tls_terminated") is True
        and ingress.get("identity_enforced") is True
    )


def _operator_identity_recorded(identity: dict[str, Any]) -> bool:
    return (
        bool(str(identity.get("operator_id") or "").strip())
        and bool(str(identity.get("source_identity_ref") or "").strip())
        and identity.get("mutation_identity_recorded") is True
        and bool(str(identity.get("evidence_ref") or "").strip())
    )


def _telemetry_verified(telemetry: dict[str, Any]) -> bool:
    return (
        bool(str(telemetry.get("signal_source_ref") or "").strip())
        and bool(str(telemetry.get("metrics_ref") or "").strip())
        and bool(str(telemetry.get("feedback_source_ref") or "").strip())
        and telemetry.get("target_feedback_verified") is True
    )


def _secrets_protected(secrets: dict[str, Any]) -> bool:
    return (
        bool(_strings(secrets.get("runtime_secret_refs")))
        and bool(str(secrets.get("credential_rotation_ref") or "").strip())
        and secrets.get("raw_secret_material_present") is False
        and secrets.get("secret_redaction_verified") is True
    )


def _rollback_rehearsed(rollback: dict[str, Any]) -> bool:
    return (
        bool(str(rollback.get("rollback_ref") or "").strip())
        and rollback.get("rollback_rehearsed") is True
        and bool(str(rollback.get("rollback_artifact_ref") or "").strip())
    )


def _approval_audited(approval: dict[str, Any]) -> bool:
    return (
        approval.get("approval_required") is True
        and bool(str(approval.get("approval_ref") or "").strip())
        and bool(str(approval.get("approver_identity_ref") or "").strip())
        and bool(str(approval.get("approval_audit_ref") or "").strip())
    )


def _run_artifacts_complete(run: dict[str, Any]) -> bool:
    return all(
        bool(str(run.get(name) or "").strip())
        for name in (
            "run_id",
            "decision_ref",
            "evaluation_ref",
            "execution_ref",
            "feedback_ref",
            "run_export_ref",
            "postmortem_export_ref",
        )
    )


def _governance_refs_complete(governance: dict[str, Any]) -> bool:
    return all(
        bool(str(governance.get(name) or "").strip())
        for name in (
            "on_call_ref",
            "escalation_ref",
            "break_glass_ref",
            "incident_review_ref",
            "retention_ref",
            "deletion_ref",
        )
    )


def _audit_chain_complete(audit: dict[str, Any]) -> bool:
    return (
        bool(str(audit.get("timeline_ref") or "").strip())
        and bool(str(audit.get("merkle_ref") or "").strip())
        and bool(_strings(audit.get("policy_refs")))
        and bool(_strings(audit.get("evidence_refs")))
    )


def _audit_explains_action(audit: dict[str, Any]) -> bool:
    return (
        bool(str(audit.get("decision_reason_ref") or "").strip())
        and bool(str(audit.get("change_record_ref") or "").strip())
        and bool(str(audit.get("recovery_result_ref") or "").strip())
    )


def _section(proof: dict[str, Any] | None, name: str) -> dict[str, Any]:
    value = (proof or {}).get(name)
    return value if isinstance(value, dict) else {}


def _strings(raw: Any) -> list[str]:
    return [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _https_url(raw: str) -> bool:
    parsed = urlparse(raw.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
