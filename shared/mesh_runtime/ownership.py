from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


def load_ownership_registry(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    registry_path = Path(path)
    if not registry_path.exists():
        return None
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_payload("ownership-registry.schema.json", payload)
    return payload


def ownership_registry_ready(path: str | None) -> bool:
    try:
        registry = load_ownership_registry(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError):
        return False
    return bool(registry and registry.get("records"))


def build_ownership_boundary(
    *,
    registry_path: str | None,
    signal_payload: dict[str, Any],
    default_environment: str,
) -> dict[str, Any]:
    service = _first_text(
        signal_payload.get("service"),
        signal_payload.get("deployment_name"),
        _nested(signal_payload, "kubernetes", "deployment_name"),
        "unknown",
    )
    environment = _first_text(signal_payload.get("environment"), default_environment, "local")
    registry = load_ownership_registry(registry_path)
    record = _match_record(registry, service=service, environment=environment) if registry else None
    if record is None:
        boundary = _unresolved_boundary(
            service=service,
            environment=environment,
            registry_path=registry_path,
            blockers=["ownership_record_missing"],
        )
    else:
        boundary = {
            "boundary_version": "ownership.boundary.v1",
            "record_id": str(record["record_id"]),
            "resolved": True,
            "service": str(record["service"]),
            "environment": str(record["environment"]),
            "namespace": str(record["namespace"]),
            "tenant_id": str(record["tenant_id"]),
            "customer_id": str(record["customer_id"]),
            "customer_boundary": str(record["customer_boundary"]),
            "owner": dict(record["owner"]),
            "approver_roles": list(record["approver_roles"]),
            "rollback_authority": dict(record["rollback_authority"]),
            "escalation_route": str(record["escalation_route"]),
            "allowed_action_classes": list(record["allowed_action_classes"]),
            "policy_refs": list(record["policy_refs"]),
            "data_boundary": dict(record["data_boundary"]),
            "source_refs": [f"file://{Path(registry_path).resolve()}"] if registry_path else [],
            "blockers": [],
        }
    validate_payload("ownership-boundary.schema.json", boundary)
    return boundary


def _match_record(registry: dict[str, Any], *, service: str, environment: str) -> dict[str, Any] | None:
    records = registry.get("records") if isinstance(registry.get("records"), list) else []
    candidates = [record for record in records if isinstance(record, dict) and record.get("service") == service]
    if not candidates:
        return None
    for record in candidates:
        if record.get("environment") == environment:
            return record
    for record in candidates:
        if record.get("environment") in {"*", "any"}:
            return record
    return None


def _unresolved_boundary(
    *,
    service: str,
    environment: str,
    registry_path: str | None,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "boundary_version": "ownership.boundary.v1",
        "record_id": "unresolved",
        "resolved": False,
        "service": service,
        "environment": environment,
        "namespace": "unknown",
        "tenant_id": "unknown",
        "customer_id": "unknown",
        "customer_boundary": "unknown",
        "owner": {"owner_id": "unassigned", "source_refs": []},
        "approver_roles": [],
        "rollback_authority": {},
        "escalation_route": "",
        "allowed_action_classes": [],
        "policy_refs": [],
        "data_boundary": {
            "classification": "unknown",
            "export_allowed": False,
            "retention_days": 0,
            "reservoir_refs": [],
            "export_policy": {
                "allowed": False,
                "allowed_destinations": [],
                "redaction_required": True,
            },
            "legal_action_scope": {
                "allowed": False,
                "review_required": True,
                "authority_ref": "unresolved",
            },
        },
        "source_refs": [f"file://{Path(registry_path).resolve()}"] if registry_path else [],
        "blockers": blockers,
    }


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"
