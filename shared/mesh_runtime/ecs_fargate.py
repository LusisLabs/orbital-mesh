from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


ECS_FARGATE_PROMOTION_PROOF_SCHEMA = "ecs-fargate-promotion-proof.schema.json"
ECS_FARGATE_PROMOTION_PROOF_VERSION = "mesh.ecs_fargate_promotion_proof.v1"
ECS_FARGATE_PROMOTION_VERIFICATION_VERSION = "mesh.ecs_fargate_promotion_verification.v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARN_RE = re.compile(r"^arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:.+")
_SECRET_REF_PREFIXES = ("arn:aws:secretsmanager:", "arn:aws:ssm:", "secretsmanager:", "ssm:")


def load_ecs_fargate_promotion_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(ECS_FARGATE_PROMOTION_PROOF_SCHEMA, payload)
    return payload


def verify_ecs_fargate_promotion_proof(path: str | Path | None) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_ecs_fargate_promotion_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": ECS_FARGATE_PROMOTION_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "target_id": proof.get("target_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "target_ecs_fargate": False,
            "operator_present": False,
            "nonlocal_environment": False,
            "aws_boundary_complete": False,
            "secret_refs_scoped": False,
            "no_raw_secret_material": False,
            "image_digest_valid": False,
            "release_provenance_complete": False,
            "health_passed": False,
            "readiness_passed": False,
            "ingress_identity_proved": False,
            "postgres_persistence_proved": False,
            "feedback_proved": False,
            "audit_proved": False,
            "rollback_proved": False,
        }
    return {
        "proof_present": True,
        "schema_valid": True,
        "target_ecs_fargate": proof.get("target_id") == "ecs_fargate",
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "nonlocal_environment": str(proof.get("environment") or "").strip() in {"staging", "pilot", "production"},
        "aws_boundary_complete": _aws_boundary_complete(_section(proof, "aws_account_boundary")),
        "secret_refs_scoped": _secret_refs_scoped(_section(proof, "aws_account_boundary")),
        "no_raw_secret_material": _section(proof, "aws_account_boundary").get("raw_secret_material_present") is False,
        "image_digest_valid": _valid_digest(str(_section(proof, "image").get("digest") or "")),
        "release_provenance_complete": _release_provenance_complete(_section(proof, "release_provenance")),
        "health_passed": _status_passed(_section(proof, "health")),
        "readiness_passed": _readiness_passed(_section(proof, "readiness")),
        "ingress_identity_proved": _ingress_identity_proved(_section(proof, "ingress_identity")),
        "postgres_persistence_proved": _postgres_persistence_proved(_section(proof, "persistence")),
        "feedback_proved": _status_passed(_section(proof, "feedback")),
        "audit_proved": _status_passed(_section(proof, "audit")),
        "rollback_proved": _status_passed(_section(proof, "rollback")),
    }


def _section(proof: dict[str, Any], name: str) -> dict[str, Any]:
    value = proof.get(name)
    return value if isinstance(value, dict) else {}


def _aws_boundary_complete(boundary: dict[str, Any]) -> bool:
    arn_fields = (
        "cluster_arn",
        "service_arn",
        "task_definition_arn",
        "execution_role_arn",
        "task_role_arn",
    )
    return (
        bool(str(boundary.get("account_id") or "").strip())
        and bool(str(boundary.get("region") or "").strip())
        and all(_valid_arn(str(boundary.get(field) or "")) for field in arn_fields)
    )


def _secret_refs_scoped(boundary: dict[str, Any]) -> bool:
    refs = boundary.get("secret_refs")
    if not isinstance(refs, list):
        return False
    return bool(refs) and all(
        isinstance(ref, str)
        and ref.strip()
        and ref.strip().startswith(_SECRET_REF_PREFIXES)
        for ref in refs
    )


def _release_provenance_complete(record: dict[str, Any]) -> bool:
    return (
        record.get("status") == "complete"
        and _valid_sha256(str(record.get("packet_sha256") or ""))
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _readiness_passed(record: dict[str, Any]) -> bool:
    blockers = record.get("blockers")
    return (
        _status_passed(record)
        and isinstance(blockers, list)
        and not blockers
    )


def _ingress_identity_proved(record: dict[str, Any]) -> bool:
    return (
        record.get("tls_terminated") is True
        and record.get("sso_enforced") is True
        and record.get("mesh_headers_stripped") is True
        and record.get("operator_headers_stamped") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _postgres_persistence_proved(record: dict[str, Any]) -> bool:
    return (
        record.get("state_backend") == "postgres"
        and bool(str(record.get("database_secret_ref") or "").strip())
        and bool(str(record.get("restart_proof_ref") or "").strip())
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _status_passed(record: dict[str, Any]) -> bool:
    return record.get("status") == "pass" and bool(str(record.get("evidence_ref") or "").strip())


def _valid_arn(raw: str) -> bool:
    return bool(_ARN_RE.match(raw.strip()))


def _valid_digest(raw: str) -> bool:
    return bool(_DIGEST_RE.match(raw.strip()))


def _valid_sha256(raw: str) -> bool:
    return bool(_SHA256_RE.match(raw.strip()))


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
