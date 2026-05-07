from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from shared.mesh_runtime import validate_payload
from shared.mesh_runtime.perennial import (
    build_darkharness_pilot_packet,
    materialize_agent_action_record,
    materialize_epistemic_state,
    materialize_governance_commit,
    materialize_ontological_state,
    materialize_proof_envelope,
)

from tests.test_perennial_materialization import _decision, _evaluation, _event, _ownership_metadata, _run_export, _scenario_analysis


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "perennial"


class DarkharnessPacketTests(unittest.TestCase):
    def test_packet_builder_wraps_allowed_and_denied_shadow_records(self) -> None:
        allowed = _record_set("run_packet_allowed", "evt_packet_allowed", "execution_recorded", "execute", [])
        denied = _record_set(
            "run_packet_denied",
            "evt_packet_denied",
            "steering_rejected",
            "reject",
            ["production-impacting action requires operator approval"],
        )
        pilot_scope = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]["pilot_scope"]
        reservoir = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]["sensitive_reservoir"]

        packet = build_darkharness_pilot_packet(
            pilot_scope=pilot_scope,
            readiness={"status": "ready"},
            go_no_go={"packet_version": "pilot.go_no_go.v1", "final_release_decision": "pass"},
            run_exports=[allowed["run_export"], denied["run_export"]],
            sensitive_reservoirs=[reservoir],
            agent_action_records=[allowed["action_record"], denied["action_record"]],
            epistemic_states=[allowed["epistemic_state"], denied["epistemic_state"]],
            ontological_states=[allowed["ontological_state"]],
            governance_commits=[allowed["governance_commit"], denied["governance_commit"]],
            proof_envelopes=[allowed["proof_envelope"], denied["proof_envelope"]],
            generated_at="2026-05-05T17:00:00Z",
        )

        self.assertEqual(packet["packet"], "darkharness.pilot_packet.v1")
        self.assertEqual(packet["boundaries"]["raw_reservoir_egress"], "deny")
        self.assertEqual(packet["boundaries"]["external_model_calls"], "deny")
        self.assertTrue(packet["boundaries"]["production_actions_approval_required"])
        self.assertEqual(len(packet["implemented_evidence"]["allowed_action_proofs"]), 1)
        self.assertEqual(len(packet["implemented_evidence"]["denied_action_proofs"]), 1)
        self.assertIn("runtime_wiring", packet["claim_boundary"]["not_implemented"])

        validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)


def _record_set(
    run_id: str,
    event_id: str,
    event_type: str,
    recommendation: str,
    blocking_reasons: list[str],
) -> dict[str, Any]:
    event = _event(
        event_id,
        run_id,
        event_type,
        {
            "operator_id": "operator.launcher" if recommendation == "execute" else None,
            "action_type": "restart_deployment",
            "service": "checkout-api",
            "namespace": "payments-pilot",
            "resource_ref": "deployment/checkout-api",
            "production_impact": "possible",
            "denial_reasons": blocking_reasons,
        },
        status="executed" if recommendation == "execute" else "denied",
    )
    run_export = _run_export(
        run_id=run_id,
        event=event,
        decision=_decision(f"dec_{run_id}", autonomy_tier="approval_required"),
        evaluation=_evaluation(f"eval_{run_id}", final_recommendation=recommendation, blocking_reasons=blocking_reasons),
        approvals=[{"event_id": f"approval_{run_id}", "operator_id": "operator.launcher"}] if recommendation == "execute" else [],
    )
    action_record = materialize_agent_action_record(
        run_export["timeline_json"][0],
        run=run_export["session"],
        decision=run_export["decision_record"],
        evaluation=run_export["evaluation_record"],
        tenant_id="customer-a",
        reservoir_refs=["reservoir_checkout_events"],
    )
    epistemic_state = materialize_epistemic_state(_scenario_analysis(), run_id=run_id)
    ontological_state = materialize_ontological_state(_ownership_metadata())
    proof_envelope = materialize_proof_envelope(run_export, subject_refs=[run_id, action_record["action_record_id"]])
    governance_commit = materialize_governance_commit(
        run_export=run_export,
        epistemic_state=epistemic_state,
        ontological_state=ontological_state,
        proof_envelope=proof_envelope,
        action_record=action_record,
        readiness={"status": "ready"},
        trust_ladder_ref="trust://checkout-api/pilot",
    )
    return {
        "run_export": run_export,
        "action_record": action_record,
        "epistemic_state": epistemic_state,
        "ontological_state": ontological_state,
        "proof_envelope": proof_envelope,
        "governance_commit": governance_commit,
    }


if __name__ == "__main__":
    unittest.main()
