from __future__ import annotations

import copy
import unittest
from typing import Any

from shared.mesh_runtime import RunEvent, RunSession, build_merkle_proof, build_merkle_snapshot, validate_payload
from shared.mesh_runtime.perennial import (
    materialize_agent_action_record,
    materialize_epistemic_state,
    materialize_governance_commit,
    materialize_ontological_state,
    materialize_proof_envelope,
    verify_hmac_signature_proof,
)


class PerennialMaterializationTests(unittest.TestCase):
    def test_allowed_run_materializes_shadow_governance_records(self) -> None:
        run_export = _run_export(
            run_id="run_allowed_shadow",
            event=_event(
                "evt_execute_allowed",
                "run_allowed_shadow",
                "execution_recorded",
                {
                    "operator_id": "operator.launcher",
                    "action_type": "restart_deployment",
                    "service": "checkout-api",
                    "namespace": "payments-pilot",
                    "resource_ref": "deployment/checkout-api",
                    "production_impact": "possible",
                    "operator_authority_refs": ["operator-approval://evt_approve_allowed"],
                },
                status="executed",
            ),
            decision=_decision("dec_allowed_restart", autonomy_tier="approval_required"),
            evaluation=_evaluation("eval_allowed_restart", final_recommendation="execute", blocking_reasons=[]),
            approvals=[{"event_id": "evt_approve_allowed", "operator_id": "operator.launcher"}],
        )
        before = copy.deepcopy(run_export)

        action_record = materialize_agent_action_record(
            run_export["timeline_json"][0],
            run=run_export["session"],
            decision=run_export["decision_record"],
            evaluation=run_export["evaluation_record"],
            tenant_id="customer-a",
            proof_refs=["proof://allowed"],
            reservoir_refs=["reservoir_checkout_events"],
        )
        epistemic_state = materialize_epistemic_state(_scenario_analysis(), run_id=run_export["run_id"])
        ontological_state = materialize_ontological_state(_ownership_metadata())
        proof_envelope = materialize_proof_envelope(run_export, subject_refs=[run_export["run_id"], action_record["action_record_id"]])
        governance_commit = materialize_governance_commit(
            run_export=run_export,
            epistemic_state=epistemic_state,
            ontological_state=ontological_state,
            proof_envelope=proof_envelope,
            action_record=action_record,
            readiness={"status": "ready"},
            trust_ladder_ref="trust://checkout-api/pilot",
        )

        self.assertEqual(action_record["action"]["action_class"], "execute")
        self.assertEqual(action_record["outcome"]["status"], "executed")
        self.assertEqual(epistemic_state["governance_use"]["review_required"], True)
        self.assertIn("owner.checkout", governance_commit["authority"]["service_owner_refs"])
        self.assertEqual(governance_commit["outcome"]["gate_result"], "allowed")
        self.assertIn("operator-approval://evt_approve_allowed", governance_commit["authority"]["operator_approval_refs"])
        self.assertIn("artifact://remediation_safety", governance_commit["inputs"]["evidence_refs"])
        self.assertIn("artifact://integration_readiness", governance_commit["inputs"]["evidence_refs"])
        self.assertIn("mesh_brain://model-kernel/mb_kernel_1", governance_commit["inputs"]["evidence_refs"])
        self.assertIn("mesh_brain://live-serving/mb_live_1", governance_commit["inputs"]["evidence_refs"])
        self.assertIn("mesh_brain://rollback-drill/mb_rollback_1", governance_commit["inputs"]["evidence_refs"])
        self.assertIn("rollback://checkout-api/restart", governance_commit["inputs"]["evidence_refs"])
        self.assertEqual(proof_envelope["implemented_proofs"]["merkle"]["run_id"], "run_allowed_shadow")
        self.assertEqual(run_export, before)

        validate_payload("perennial/agent-action-record.schema.json", action_record)
        validate_payload("perennial/epistemic-state.schema.json", epistemic_state)
        validate_payload("perennial/ontological-state.schema.json", ontological_state)
        validate_payload("perennial/proof-envelope.schema.json", proof_envelope)
        validate_payload("perennial/governance-commit.schema.json", governance_commit)

    def test_denied_run_materializes_denial_reason_and_commit(self) -> None:
        run_export = _run_export(
            run_id="run_denied_shadow",
            event=_event(
                "evt_denied_scale",
                "run_denied_shadow",
                "steering_rejected",
                {
                    "actor": {
                        "actor_type": "agent",
                        "actor_id": "mesh-agent.autoremediate",
                        "display_name": "Mesh autoremediation agent",
                        "authority_source": "service_account",
                    },
                    "action_type": "scale_deployment",
                    "service": "checkout-api",
                    "namespace": "payments-pilot",
                    "resource_ref": "deployment/checkout-api",
                    "production_impact": "direct",
                    "denial_reasons": ["production-impacting action requires operator approval"],
                },
                status="denied",
            ),
            decision=_decision("dec_denied_scale", autonomy_tier="approval_required"),
            evaluation=_evaluation(
                "eval_denied_scale",
                final_recommendation="reject",
                blocking_reasons=["production-impacting action requires operator approval"],
            ),
            approvals=[],
        )

        action_record = materialize_agent_action_record(
            run_export["timeline_json"][0],
            run=run_export["session"],
            decision=run_export["decision_record"],
            evaluation=run_export["evaluation_record"],
            tenant_id="customer-a",
        )
        epistemic_state = materialize_epistemic_state(_scenario_analysis(), run_id=run_export["run_id"])
        ontological_state = materialize_ontological_state(_ownership_metadata())
        proof_envelope = materialize_proof_envelope(run_export, subject_refs=[run_export["run_id"], action_record["action_record_id"]])
        governance_commit = materialize_governance_commit(
            run_export=run_export,
            epistemic_state=epistemic_state,
            ontological_state=ontological_state,
            proof_envelope=proof_envelope,
            action_record=action_record,
            readiness={"status": "ready"},
            trust_ladder_ref="trust://checkout-api/pilot",
        )

        self.assertEqual(action_record["action"]["action_class"], "deny")
        self.assertEqual(action_record["outcome"]["status"], "denied")
        self.assertEqual(action_record["outcome"]["denial_reasons"], ["production-impacting action requires operator approval"])
        self.assertEqual(governance_commit["commit_type"], "deny_action")
        self.assertEqual(governance_commit["outcome"]["gate_result"], "denied")
        self.assertEqual(governance_commit["authority"]["operator_approval_refs"], [])

    def test_proof_envelope_can_include_configured_hmac_signature(self) -> None:
        run_export = _run_export(
            run_id="run_signed_shadow",
            event=_event(
                "evt_signed_execute",
                "run_signed_shadow",
                "execution_recorded",
                {
                    "operator_id": "operator.launcher",
                    "action_type": "restart_deployment",
                    "service": "checkout-api",
                    "namespace": "payments-pilot",
                    "resource_ref": "deployment/checkout-api",
                    "production_impact": "possible",
                },
                status="executed",
            ),
            decision=_decision("dec_signed_restart", autonomy_tier="approval_required"),
            evaluation=_evaluation("eval_signed_restart", final_recommendation="execute", blocking_reasons=[]),
            approvals=[{"event_id": "evt_signed_approval", "operator_id": "operator.launcher"}],
        )
        action_record = materialize_agent_action_record(
            run_export["timeline_json"][0],
            run=run_export["session"],
            decision=run_export["decision_record"],
            evaluation=run_export["evaluation_record"],
            tenant_id="customer-a",
        )
        epistemic_state = materialize_epistemic_state(_scenario_analysis(), run_id=run_export["run_id"])
        ontological_state = materialize_ontological_state(_ownership_metadata())
        proof_envelope = materialize_proof_envelope(
            run_export,
            subject_refs=[run_export["run_id"], action_record["action_record_id"]],
            signing_key="test-darkharness-signing-secret",
            signing_key_id="test-key",
        )
        signature = proof_envelope["implemented_proofs"]["signature"]
        governance_commit = materialize_governance_commit(
            run_export=run_export,
            epistemic_state=epistemic_state,
            ontological_state=ontological_state,
            proof_envelope=proof_envelope,
            action_record=action_record,
            readiness={"status": "ready"},
            trust_ladder_ref="trust://checkout-api/pilot",
        )

        signature_payload = {
            "run_id": run_export["run_id"],
            "subject_refs": [run_export["run_id"], action_record["action_record_id"]],
            "merkle_root": run_export["merkle"]["snapshot"]["root_hash"],
            "leaf_event_ids": run_export["merkle"]["snapshot"]["event_ids"],
            "redaction_profile": "darkharness-pilot-redacted",
        }
        self.assertEqual(signature["algorithm"], "hmac-sha256")
        self.assertEqual(signature["status"], "verified")
        self.assertTrue(
            verify_hmac_signature_proof(
                signature_payload,
                signature,
                secret="test-darkharness-signing-secret",
            )
        )
        self.assertEqual(
            governance_commit["proof"]["signature_ref"],
            f"signature://test-key/{signature['payload_sha256']}",
        )
        validate_payload("perennial/proof-envelope.schema.json", proof_envelope)
        validate_payload("perennial/governance-commit.schema.json", governance_commit)


def _event(event_id: str, run_id: str, event_type: str, payload: dict[str, Any], *, status: str) -> RunEvent:
    return RunEvent(
        event_id=event_id,
        run_id=run_id,
        sequence=1,
        stage="executing",
        event_type=event_type,
        recorded_at="2026-05-05T15:00:00Z",
        payload=payload,
        summary={"status": status},
        artifact_key=None,
        integration_name="control_plane",
        status=status,
    )


def _run_export(
    run_id: str,
    event: RunEvent,
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    approvals: list[dict[str, Any]],
) -> dict[str, Any]:
    session = RunSession(
        run_id=run_id,
        created_at="2026-05-05T14:59:00Z",
        updated_at="2026-05-05T15:00:00Z",
        goal_id="goal_darkharness",
        scenario_key="checkout_latency",
        stage="completed",
        status="completed",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=["before_execute"],
        pending_pause_stage=None,
        evaluation_mode="pilot",
        orchestration_mode="shadow",
        latest_event_id=event.event_id,
        latest_event_sequence=event.sequence,
        latest_merkle_root=None,
        artifacts={
            "decision": decision,
            "evaluation": evaluation,
            "approvals": approvals,
            "remediation_safety": {"score": 0.91},
            "trust_ladder": {"level": "approval_required"},
            "integration_readiness": {"status": "ready"},
            "mesh_brain_model_kernel_run_record": {"run_id": "mb_kernel_1"},
            "mesh_brain_live_serving_run_record": {"run_id": "mb_live_1"},
            "mesh_brain_rollback_drill_run_record": {"run_id": "mb_rollback_1"},
        },
    )
    snapshot = build_merkle_snapshot(run_id, [event]).to_dict()
    proof = build_merkle_proof(run_id, [event], event.event_id)
    return {
        "package_version": "mesh.run_export.v1",
        "generated_at": "2026-05-05T15:00:05Z",
        "run_id": run_id,
        "session": session.to_dict(),
        "timeline_json": [event.to_dict()],
        "evidence_artifacts": [{"artifact_key": "scenario_analysis", "uri": f"artifact://{run_id}/scenario"}],
        "decision_record": decision,
        "evaluation_record": evaluation,
        "execution_record": None,
        "feedback_record": None,
        "approval_records": approvals,
        "operator_notes": [],
        "merkle": {
            "snapshot": snapshot,
            "latest_event_proof": proof.to_dict() if proof else None,
        },
        "checks": {
            "timeline_present": True,
            "merkle_root_present": True,
            "merkle_proof_valid": True,
        },
        "export_id": f"export_{run_id}",
        "package_sha256": f"sha256:{run_id}",
    }


def _decision(decision_id: str, *, autonomy_tier: str) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "trigger_id": "trg_checkout_latency",
        "decision_type": "restart_deployment",
        "autonomy_tier": autonomy_tier,
        "summary": "Restart checkout deployment after bounded RCA.",
        "reasoning": {
            "primary_hypothesis": "Stuck rollout degraded checkout latency.",
            "evidence": ["otel p95 regression", "deployment rollout stalled"],
            "alternatives_considered": ["open incident only", "rollback deployment"],
        },
        "expected_outcome": {
            "target_metrics": {"p95_latency_ms": "<= 500", "error_rate": "<= 0.02"},
            "time_to_effect": "10m",
        },
        "risk": {
            "level": "medium",
            "blast_radius": "payments-pilot checkout-api",
            "customer_impact_if_wrong": "temporary checkout latency remains elevated",
        },
        "confidence": 0.77,
        "execution_plan": {
            "system": "kubernetes_service",
            "action": "restart_deployment",
            "parameters": {
                "service": "checkout-api",
                "namespace": "payments-pilot",
                "resource_ref": "deployment/checkout-api",
                "production_impact": "possible",
            },
            "rollback_plan": "rollback://checkout-api/restart",
        },
    }


def _evaluation(evaluation_id: str, *, final_recommendation: str, blocking_reasons: list[str]) -> dict[str, Any]:
    return {
        "evaluation_id": evaluation_id,
        "decision_id": "dec_allowed_restart",
        "passed": final_recommendation == "execute",
        "final_recommendation": final_recommendation,
        "stage_results": {
            "schema_validation": {},
            "policy_validation": {},
            "contract_checks": {},
            "trajectory_quality": {},
            "behavioral_scores": {},
            "verifier": {},
            "business_rules": {},
            "execution_readiness": {},
        },
        "blocking_reasons": blocking_reasons,
    }


def _scenario_analysis() -> dict[str, Any]:
    return {
        "analysis_id": "analysis_checkout_latency",
        "trigger_id": "trg_checkout_latency",
        "created_at": "2026-05-05T14:58:00Z",
        "suggested_decision_type": "restart_deployment",
        "confidence": 0.77,
        "risk_level": "medium",
        "autonomy_tier_hint": "approval_required",
        "required_review_reasons": ["production-impacting action requires approval"],
        "evidence_refs": ["event://evt_execute_allowed"],
        "subdecisions": [
            {
                "subdecision_id": "sub_restart",
                "analyzer": "scenario-analysis",
                "recommendation": "restart_deployment",
                "confidence": 0.77,
                "risk_level": "medium",
                "reasons": ["rollout stuck"],
                "evidence_refs": ["event://evt_execute_allowed"],
                "requires_review": True,
            },
            {
                "subdecision_id": "sub_database",
                "analyzer": "scenario-analysis",
                "recommendation": "investigate_database",
                "confidence": 0.34,
                "risk_level": "high",
                "reasons": ["database pressure remains possible"],
                "evidence_refs": ["otel://db/p95"],
                "requires_review": True,
            },
        ],
        "evidence_nodes": [
            {
                "evidence_id": "ev_rollout_stalled",
                "run_id": "run_allowed_shadow",
                "analyzer": "kubernetes",
                "kind": "deployment",
                "summary": "Checkout rollout is stalled.",
                "payload": {},
                "source_event_ids": ["evt_execute_allowed"],
                "confidence": 0.82,
                "trusted": True,
            }
        ],
    }


def _ownership_metadata() -> dict[str, Any]:
    return {
        "namespace": "payments-pilot",
        "service": "checkout-api",
        "owner": {
            "owner_id": "owner.checkout",
            "team": "platform-reliability",
            "source_refs": ["registry://owners/checkout"],
        },
        "reservoir_ids": ["reservoir_checkout_events"],
        "policy_refs": ["policy://darkharness/pilot/approval-required"],
    }


if __name__ == "__main__":
    unittest.main()
