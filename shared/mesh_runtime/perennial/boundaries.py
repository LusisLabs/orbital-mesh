from __future__ import annotations

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
