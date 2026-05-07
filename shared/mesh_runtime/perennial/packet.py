from __future__ import annotations

from typing import Any

from ._utils import stable_id, timestamp, validate
from .boundaries import assert_pilot_scope_boundaries, assert_reservoir_default_deny


def build_darkharness_pilot_packet(
    *,
    pilot_scope: dict[str, Any],
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
    run_exports: list[dict[str, Any]],
    sensitive_reservoirs: list[dict[str, Any]],
    agent_action_records: list[dict[str, Any]],
    epistemic_states: list[dict[str, Any]],
    ontological_states: list[dict[str, Any]],
    governance_commits: list[dict[str, Any]],
    proof_envelopes: list[dict[str, Any]],
    generated_at: str | None = None,
    claim_boundary: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    scope = assert_pilot_scope_boundaries(pilot_scope)
    reservoirs = [assert_reservoir_default_deny(reservoir) for reservoir in sensitive_reservoirs]
    packet_generated_at = generated_at or timestamp()
    allowed_commits = [commit for commit in governance_commits if commit.get("outcome", {}).get("gate_result") == "allowed"]
    denied_commits = [commit for commit in governance_commits if commit.get("outcome", {}).get("gate_result") == "denied"]
    packet = {
        "packet": "darkharness.pilot_packet.v1",
        "packet_id": stable_id("dh_packet", scope["pilot_scope_id"], packet_generated_at, [export.get("run_id") for export in run_exports]),
        "generated_at": packet_generated_at,
        "customer_boundary": scope["customer_boundary"],
        "pilot_scope_id": scope["pilot_scope_id"],
        "implemented_evidence": {
            "readiness": readiness,
            "go_no_go": go_no_go,
            "run_exports": [
                {
                    "run_id": export.get("run_id"),
                    "export_id": export.get("export_id"),
                    "package_sha256": export.get("package_sha256"),
                }
                for export in run_exports
            ],
            "merkle_proofs": [
                envelope["implemented_proofs"]["merkle"]
                for envelope in proof_envelopes
            ],
            "denied_action_proofs": [
                {
                    "governance_commit_id": commit["governance_commit_id"],
                    "proof_envelope_id": commit["proof"]["proof_envelope_id"],
                }
                for commit in denied_commits
            ],
            "allowed_action_proofs": [
                {
                    "governance_commit_id": commit["governance_commit_id"],
                    "proof_envelope_id": commit["proof"]["proof_envelope_id"],
                }
                for commit in allowed_commits
            ],
            "postgres_restart_proof": go_no_go.get("postgres_restart_proof"),
        },
        "perennial_records": {
            "sensitive_reservoirs": reservoirs,
            "agent_action_records": list(agent_action_records),
            "epistemic_states": list(epistemic_states),
            "ontological_states": list(ontological_states),
            "governance_commits": list(governance_commits),
            "proof_envelopes": list(proof_envelopes),
        },
        "boundaries": {
            "raw_reservoir_egress": "deny",
            "external_model_calls": "deny",
            "production_actions_approval_required": True,
        },
        "claim_boundary": claim_boundary
        or {
            "implemented": ["readiness", "go_no_go", "run_export", "merkle_proof"],
            "proposed": ["perennial_shadow_records", "signature", "pqc_signature", "pqc_kem", "selective_disclosure_zk"],
            "not_implemented": ["runtime_wiring", "actuation_changes", "raw_reservoir_egress"],
        },
    }
    return validate("perennial/darkharness-pilot-packet.schema.json", packet)
