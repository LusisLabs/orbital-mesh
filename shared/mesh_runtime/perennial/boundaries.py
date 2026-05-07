from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.mesh_runtime.schema_validation import SchemaValidationError

from ._utils import stable_id, timestamp, validate


def materialize_sensitive_reservoir(
    *,
    reservoir_id: str,
    name: str,
    owner: dict[str, Any],
    classification: dict[str, Any],
    locality: dict[str, Any],
    access_policy: dict[str, Any],
    projection: dict[str, Any],
    crypto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "contract": "perennial.sensitive_reservoir.v1",
        "reservoir_id": reservoir_id,
        "name": name,
        "owner": {
            "team": owner["team"],
            "service_owner": owner["service_owner"],
            "data_steward": owner["data_steward"],
        },
        "classification": {
            "data_classes": list(classification["data_classes"]),
            "sensitivity": classification["sensitivity"],
            "trainable": classification["trainable"],
        },
        "locality": {
            "boundary": locality.get("boundary", "on_prem"),
            "region": locality["region"],
            "storage_ref": locality["storage_ref"],
            "external_egress_default": locality.get("external_egress_default", "deny"),
        },
        "access_policy": {
            "allowed_purposes": list(access_policy["allowed_purposes"]),
            "allowed_compute_modes": list(access_policy["allowed_compute_modes"]),
            "approval_required": bool(access_policy.get("approval_required", True)),
            "retention_days": int(access_policy["retention_days"]),
        },
        "projection": {
            "redaction_profile": projection["redaction_profile"],
            "max_snippet_chars": int(projection.get("max_snippet_chars", 0)),
            "hash_algorithm": projection.get("hash_algorithm", "sha256"),
            "allowed_index_fields": list(projection.get("allowed_index_fields", [])),
        },
        "crypto": {
            "encryption_profile": (crypto or {}).get("encryption_profile", "customer-managed-aes256"),
            "signing_profile": (crypto or {}).get("signing_profile"),
            "pqc_profile": (crypto or {}).get("pqc_profile"),
        },
    }
    return assert_reservoir_default_deny(payload)


def assert_reservoir_default_deny(reservoir: dict[str, Any]) -> dict[str, Any]:
    payload = validate("perennial/sensitive-reservoir.schema.json", dict(reservoir))
    locality = payload["locality"]
    if locality.get("boundary") != "on_prem":
        raise SchemaValidationError("$.locality.boundary: reservoir must remain on_prem")
    if locality.get("external_egress_default") != "deny":
        raise SchemaValidationError("$.locality.external_egress_default: raw reservoir egress must default deny")
    if payload["classification"].get("trainable") == "allowed":
        raise SchemaValidationError("$.classification.trainable: use opt_in or allowed_redacted, never raw allowed")
    return payload


def assert_pilot_scope_boundaries(pilot_scope: dict[str, Any]) -> dict[str, Any]:
    payload = validate("perennial/pilot-scope.schema.json", dict(pilot_scope))
    if payload["authority"].get("production_actions_approval_required") is not True:
        raise SchemaValidationError("$.authority.production_actions_approval_required: must remain true for v1")
    if payload["data_boundary"].get("raw_reservoir_egress") != "deny":
        raise SchemaValidationError("$.data_boundary.raw_reservoir_egress: must remain deny for v1")
    if payload["data_boundary"].get("external_model_calls") != "deny_by_default":
        raise SchemaValidationError("$.data_boundary.external_model_calls: must remain deny_by_default for v1")
    return payload


def reservoir_denial_record(
    *,
    reservoir_id: str,
    actor_id: str,
    tenant_id: str,
    run_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    return validate(
        "perennial/agent-action-record.schema.json",
        {
            "contract": "perennial.agent_action_record.v1",
            "action_record_id": stable_id("aar", "reservoir_denial", reservoir_id, actor_id, run_id),
            "observed_at": observed_at or timestamp(),
            "actor": {
                "actor_type": "model",
                "actor_id": actor_id,
                "display_name": None,
                "authority_source": "unknown",
            },
            "action": {
                "action_class": "deny",
                "action_type": "raw_reservoir_export",
                "target": {
                    "environment": "pilot",
                    "service": None,
                    "namespace": None,
                    "resource_ref": f"reservoir/{reservoir_id}",
                    "reservoir_id": reservoir_id,
                },
                "production_impact": "none",
            },
            "context": {
                "run_id": run_id,
                "run_event_id": None,
                "decision_id": None,
                "evaluation_id": None,
                "feedback_id": None,
                "source_system": "darkharness-boundary-check",
            },
            "governance": {
                "risk_tier": "unacceptable",
                "autonomy_tier": "no_action",
                "policy_refs": ["policy://darkharness/pilot/raw-egress-deny"],
                "evidence_refs": [f"reservoir://{reservoir_id}/policy"],
                "proof_refs": [],
                "operator_authority_refs": [],
            },
            "outcome": {
                "status": "denied",
                "denial_reasons": ["raw reservoir egress denied by default"],
                "rollback_ref": None,
                "side_effect_refs": [],
            },
            "boundary": {
                "tenant_id": tenant_id,
                "data_boundary": "on_prem",
                "reservoir_refs": [reservoir_id],
            },
        },
    )


def project_reservoir_access(
    *,
    reservoir: dict[str, Any],
    value: Any,
    purpose: str,
    compute_mode: str,
    actor_id: str,
    tenant_id: str,
    run_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    checked = assert_reservoir_default_deny(reservoir)
    allowed_purposes = set(checked["access_policy"]["allowed_purposes"])
    allowed_modes = set(checked["access_policy"]["allowed_compute_modes"])
    if purpose not in allowed_purposes:
        return _reservoir_projection_denied(
            checked,
            actor_id=actor_id,
            tenant_id=tenant_id,
            run_id=run_id,
            observed_at=observed_at,
            denial_reason=f"reservoir purpose {purpose!r} is not allowed",
        )
    if compute_mode not in allowed_modes:
        return _reservoir_projection_denied(
            checked,
            actor_id=actor_id,
            tenant_id=tenant_id,
            run_id=run_id,
            observed_at=observed_at,
            denial_reason=f"reservoir compute mode {compute_mode!r} is not allowed",
        )
    projection = _project_value(checked, value, compute_mode=compute_mode)
    return {
        "status": "allowed",
        "reservoir_id": checked["reservoir_id"],
        "purpose": purpose,
        "compute_mode": compute_mode,
        "raw_sensitive_data_included": False,
        "projection": projection,
        "action_record": _reservoir_projection_record(
            checked,
            actor_id=actor_id,
            tenant_id=tenant_id,
            run_id=run_id,
            observed_at=observed_at,
            purpose=purpose,
            compute_mode=compute_mode,
            evidence_refs=[projection["projection_ref"]],
        ),
    }


def _reservoir_projection_denied(
    reservoir: dict[str, Any],
    *,
    actor_id: str,
    tenant_id: str,
    run_id: str | None,
    observed_at: str | None,
    denial_reason: str,
) -> dict[str, Any]:
    record = reservoir_denial_record(
        reservoir_id=reservoir["reservoir_id"],
        actor_id=actor_id,
        tenant_id=tenant_id,
        run_id=run_id,
        observed_at=observed_at,
    )
    record["outcome"]["denial_reasons"] = [denial_reason]
    return {
        "status": "denied",
        "reservoir_id": reservoir["reservoir_id"],
        "raw_sensitive_data_included": False,
        "projection": None,
        "denial_reasons": [denial_reason],
        "action_record": validate("perennial/agent-action-record.schema.json", record),
    }


def _project_value(reservoir: dict[str, Any], value: Any, *, compute_mode: str) -> dict[str, Any]:
    projection = reservoir["projection"]
    hash_algorithm = projection.get("hash_algorithm", "sha256")
    if hash_algorithm != "sha256":
        raise SchemaValidationError("$.projection.hash_algorithm: only sha256 is supported")
    content_hash = hashlib.sha256(_canonical_bytes(value)).hexdigest()
    projection_ref = f"reservoir://{reservoir['reservoir_id']}/projection/{compute_mode}/{content_hash}"
    if compute_mode == "hash_only":
        return {
            "projection_ref": projection_ref,
            "mode": "hash_only",
            "hash_algorithm": "sha256",
            "content_hash": content_hash,
        }
    if compute_mode == "aggregate_only":
        return {
            "projection_ref": projection_ref,
            "mode": "aggregate_only",
            "hash_algorithm": "sha256",
            "content_hash": content_hash,
            "summary": _aggregate_summary(value),
        }
    if compute_mode == "redacted_projection":
        return {
            "projection_ref": projection_ref,
            "mode": "redacted_projection",
            "hash_algorithm": "sha256",
            "content_hash": content_hash,
            "redaction_profile": projection["redaction_profile"],
            "redacted": _redacted_projection(
                value,
                allowed_index_fields=set(projection.get("allowed_index_fields", [])),
                max_snippet_chars=max(0, int(projection.get("max_snippet_chars", 0))),
            ),
        }
    if compute_mode == "in_place":
        return {
            "projection_ref": projection_ref,
            "mode": "in_place",
            "hash_algorithm": "sha256",
            "content_hash": content_hash,
            "execution_boundary": "reservoir_local_only",
        }
    raise SchemaValidationError(f"$.access_policy.allowed_compute_modes: unsupported compute mode {compute_mode!r}")


def _reservoir_projection_record(
    reservoir: dict[str, Any],
    *,
    actor_id: str,
    tenant_id: str,
    run_id: str | None,
    observed_at: str | None,
    purpose: str,
    compute_mode: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return validate(
        "perennial/agent-action-record.schema.json",
        {
            "contract": "perennial.agent_action_record.v1",
            "action_record_id": stable_id("aar", "reservoir_projection", reservoir["reservoir_id"], purpose, compute_mode, run_id),
            "observed_at": observed_at or timestamp(),
            "actor": {
                "actor_type": "service",
                "actor_id": actor_id,
                "display_name": None,
                "authority_source": "service_account",
            },
            "action": {
                "action_class": "retrieve" if compute_mode != "in_place" else "attest",
                "action_type": f"reservoir_{compute_mode}",
                "target": {
                    "environment": "pilot",
                    "service": None,
                    "namespace": None,
                    "resource_ref": f"reservoir/{reservoir['reservoir_id']}",
                    "reservoir_id": reservoir["reservoir_id"],
                },
                "production_impact": "none",
            },
            "context": {
                "run_id": run_id,
                "run_event_id": None,
                "decision_id": None,
                "evaluation_id": None,
                "feedback_id": None,
                "source_system": "darkharness-reservoir-projection",
            },
            "governance": {
                "risk_tier": "moderate",
                "autonomy_tier": "no_action",
                "policy_refs": [f"policy://darkharness/reservoir/{purpose}/{compute_mode}"],
                "evidence_refs": evidence_refs,
                "proof_refs": [],
                "operator_authority_refs": [],
            },
            "outcome": {
                "status": "observed",
                "denial_reasons": [],
                "rollback_ref": None,
                "side_effect_refs": [],
            },
            "boundary": {
                "tenant_id": tenant_id,
                "data_boundary": "on_prem",
                "reservoir_refs": [reservoir["reservoir_id"]],
            },
        },
    )


def _aggregate_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "shape": "object",
            "field_count": len(value),
            "numeric_field_count": sum(1 for item in value.values() if isinstance(item, int | float) and not isinstance(item, bool)),
        }
    if isinstance(value, list):
        return {
            "shape": "array",
            "item_count": len(value),
            "numeric_item_count": sum(1 for item in value if isinstance(item, int | float) and not isinstance(item, bool)),
        }
    if isinstance(value, str):
        return {"shape": "string", "length": len(value)}
    return {"shape": type(value).__name__}


def _redacted_projection(value: Any, *, allowed_index_fields: set[str], max_snippet_chars: int) -> Any:
    if max_snippet_chars <= 0:
        return None
    if isinstance(value, dict):
        return {
            key: _redacted_projection(raw_value, allowed_index_fields=allowed_index_fields, max_snippet_chars=max_snippet_chars)
            for key, raw_value in value.items()
            if key in allowed_index_fields
        }
    if isinstance(value, list):
        return [
            _redacted_projection(item, allowed_index_fields=allowed_index_fields, max_snippet_chars=max_snippet_chars)
            for item in value[:10]
        ]
    return str(value)[:max_snippet_chars]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
