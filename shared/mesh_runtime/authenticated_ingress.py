from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schema_validation import SchemaValidationError, validate_payload


AUTHENTICATED_INGRESS_DEPLOYMENT_PROOF_SCHEMA = "authenticated-ingress-deployment-proof.schema.json"
AUTHENTICATED_INGRESS_DEPLOYMENT_PROOF_VERSION = "mesh.authenticated_ingress_deployment_proof.v1"
AUTHENTICATED_INGRESS_DEPLOYMENT_VERIFICATION_VERSION = "mesh.authenticated_ingress_deployment_verification.v1"
AUTHENTICATED_INGRESS_REHEARSAL_VERSION = "mesh.authenticated_ingress_rehearsal.v1"
_NONLOCAL_ENVIRONMENTS = frozenset({"staging", "pilot", "production"})
_IDENTITY_PROVIDER_TYPES = frozenset({"oidc", "saml", "sso", "oauth2", "identity-aware-proxy"})
_TLS_MINIMUM_VERSIONS = frozenset({"TLSv1.2", "TLSv1.3"})


def load_authenticated_ingress_deployment_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(AUTHENTICATED_INGRESS_DEPLOYMENT_PROOF_SCHEMA, payload)
    return payload


def authenticated_ingress_deployment_ready(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
) -> bool:
    return (
        verify_authenticated_ingress_deployment_proof(path, expected_environment=expected_environment)["status"]
        == "pass"
    )


def verify_authenticated_ingress_deployment_proof(
    path: str | Path | None,
    *,
    expected_environment: str | None = None,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_authenticated_ingress_deployment_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    checks = _proof_checks(proof, expected_environment=expected_environment)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": AUTHENTICATED_INGRESS_DEPLOYMENT_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "environment": proof.get("environment") if proof else None,
        "ingress_url": proof.get("ingress_url") if proof else None,
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(proof: dict[str, Any] | None, *, expected_environment: str | None = None) -> dict[str, bool]:
    expected_environment = (expected_environment or "").strip()
    if proof is None:
        checks = {
            "proof_present": False,
            "schema_valid": False,
            "nonlocal_environment": False,
            "operator_present": False,
            "ingress_url_https": False,
            "tls_terminated": False,
            "identity_provider_enforced": False,
            "mesh_headers_sanitized": False,
            "role_mapping_complete": False,
            "network_boundary_private": False,
            "app_rehearsal_passed": False,
            "audit_identity_recorded": False,
            "no_raw_secret_material": False,
        }
        if expected_environment:
            checks["environment_matches_expected"] = False
        return checks
    environment = str(proof.get("environment") or "").strip()
    checks = {
        "proof_present": True,
        "schema_valid": True,
        "nonlocal_environment": environment in _NONLOCAL_ENVIRONMENTS,
        "operator_present": bool(str(proof.get("operator_id") or "").strip()),
        "ingress_url_https": _https_url(str(proof.get("ingress_url") or "")),
        "tls_terminated": _tls_terminated(_section(proof, "tls")),
        "identity_provider_enforced": _identity_provider_enforced(_section(proof, "identity_provider")),
        "mesh_headers_sanitized": _mesh_headers_sanitized(_section(proof, "header_sanitization")),
        "role_mapping_complete": _role_mapping_complete(_section(proof, "role_mapping")),
        "network_boundary_private": _network_boundary_private(_section(proof, "network_boundary")),
        "app_rehearsal_passed": _app_rehearsal_passed(_section(proof, "app_rehearsal")),
        "audit_identity_recorded": _audit_identity_recorded(_section(proof, "audit")),
        "no_raw_secret_material": proof.get("raw_secret_material_present") is False,
    }
    if expected_environment:
        checks["environment_matches_expected"] = environment == expected_environment
    return checks


def _section(proof: dict[str, Any], name: str) -> dict[str, Any]:
    value = proof.get(name)
    return value if isinstance(value, dict) else {}


def _tls_terminated(record: dict[str, Any]) -> bool:
    return (
        record.get("terminated") is True
        and record.get("public_listener") is True
        and record.get("minimum_version") in _TLS_MINIMUM_VERSIONS
        and bool(str(record.get("certificate_ref") or "").strip())
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _identity_provider_enforced(record: dict[str, Any]) -> bool:
    return (
        str(record.get("type") or "").strip() in _IDENTITY_PROVIDER_TYPES
        and record.get("sso_enforced") is True
        and bool(str(record.get("identity_claim") or "").strip())
        and bool(str(record.get("roles_claim") or "").strip())
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _mesh_headers_sanitized(record: dict[str, Any]) -> bool:
    return (
        record.get("client_mesh_operator_header_stripped") is True
        and record.get("client_mesh_roles_header_stripped") is True
        and record.get("proxy_operator_header_stamped") is True
        and record.get("proxy_roles_header_stamped") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _role_mapping_complete(record: dict[str, Any]) -> bool:
    return all(bool(str(record.get(role) or "").strip()) for role in ("viewer", "launcher", "approver", "admin")) and bool(
        str(record.get("evidence_ref") or "").strip()
    )


def _network_boundary_private(record: dict[str, Any]) -> bool:
    return (
        record.get("raw_service_publicly_reachable") is False
        and record.get("upstream_private") is True
        and bool(str(record.get("allowed_proxy_ref") or "").strip())
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _app_rehearsal_passed(record: dict[str, Any]) -> bool:
    return (
        record.get("schema_version") == AUTHENTICATED_INGRESS_REHEARSAL_VERSION
        and record.get("status") == "passed"
        and bool(str(record.get("run_id") or "").strip())
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _audit_identity_recorded(record: dict[str, Any]) -> bool:
    return (
        record.get("source_ip_or_proxy_identity_recorded") is True
        and record.get("operator_identity_recorded") is True
        and bool(str(record.get("evidence_ref") or "").strip())
    )


def _https_url(raw: str) -> bool:
    parsed = urlparse(raw.strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
