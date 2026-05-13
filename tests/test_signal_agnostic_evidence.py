from __future__ import annotations

import tempfile
import unittest

from services.runtime import MeshRuntimeEngine
from services.signal_profiles._shared_strategies import HarnessDrivenRcaBuilder
from shared.mesh_runtime import Decision, RuntimeConfig, Trigger, load_fixture


def _runtime() -> MeshRuntimeEngine:
    tmp = tempfile.TemporaryDirectory()
    engine = MeshRuntimeEngine(
        RuntimeConfig(
            evaluation_mode="native",
            orchestration_mode="dry_run",
            state_directory=tmp.name,
        )
    )
    engine._test_tmp = tmp  # type: ignore[attr-defined]
    return engine


def _event_by_artifact(result: dict, artifact_key: str) -> dict:
    for event in result["run_events"]:
        if event.get("artifact_key") == artifact_key:
            return event
    raise AssertionError(f"missing artifact event {artifact_key}")


def _trigger() -> Trigger:
    return Trigger(
        trigger_id="trg_test",
        trigger_type="generic_signal_firing",
        triggered_at="2026-05-13T12:00:00Z",
        environment="prod",
        service="api",
        endpoint="/",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window=None,
        segment={"customer_tier": "standard"},
        metrics={
            "baseline_p95_latency_ms": None,
            "observed_p95_latency_ms": None,
            "baseline_error_rate": None,
            "observed_error_rate": None,
            "sample_size": None,
        },
        related_context={"release_id": None, "active_incidents": 0, "similar_prior_cases": 0},
    )


def _decision(reasoning: dict) -> Decision:
    return Decision(
        decision_id="dec_test",
        trigger_id="trg_test",
        summary="test",
        decision_type="escalate",
        autonomy_tier="escalated",
        reasoning=reasoning,
        expected_outcome={"target_metrics": {"p95_latency_ms": "unknown", "error_rate": "unknown"}, "time_to_effect": "operator_dependent"},
        risk={"level": "high", "blast_radius": "unknown", "customer_impact_if_wrong": "unknown"},
        confidence=0.5,
        execution_plan={"system": "incident_service", "action": "open_incident", "parameters": {}, "rollback_plan": "no_op"},
    )


class SignalAgnosticEvidenceRuntimeTests(unittest.TestCase):
    def test_feature_flag_uses_structured_feature_flag_evidence(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        self.assertNotIn("signal_type", signal)

        result = _runtime().run_sync(signal, "feature_flag_profile_resolution")
        evidence_event = _event_by_artifact(result, "evidence_pack")

        self.assertEqual(result["normalized_event"]["payload"]["signal_type"], "feature_flag")
        self.assertEqual(result["decision"]["decision_type"], "disable_flag")
        self.assertEqual(_event_by_artifact(result, "investigation_plan")["integration_name"], "feature_flag_planner")
        self.assertEqual(evidence_event["payload"]["source"], "feature_flag_structured_signal")
        self.assertTrue(evidence_event["payload"]["sufficient"])
        self.assertEqual(_event_by_artifact(result, "rca_report")["integration_name"], "feature_flag_rca")

    def test_unknown_signal_type_reaches_generic_insufficient_evidence_and_escalates(self) -> None:
        result = _runtime().run_sync(
            {
                "signal_id": "aws-1",
                "observed_at": "2026-05-13T12:00:00Z",
                "signal_type": "aws_cloudwatch_alarm",
                "environment": "prod",
                "service": "api",
                "endpoint": "/",
                "segment": {"customer_tier": "standard"},
                "related_context": {},
            },
            "unknown_signal_profile_resolution",
        )
        evidence_event = _event_by_artifact(result, "evidence_pack")

        self.assertEqual(result["trigger"]["trigger_type"], "generic_signal_firing")
        self.assertEqual(result["decision"]["decision_type"], "escalate")
        self.assertEqual(evidence_event["payload"]["source"], "generic_signal_type")
        self.assertFalse(evidence_event["payload"]["sufficient"])
        self.assertIn("related_context.severity", evidence_event["payload"]["missing_fields"])

    def test_unknown_signal_with_identity_still_escalates(self) -> None:
        result = _runtime().run_sync(
            {
                "signal_id": "aws-2",
                "observed_at": "2026-05-13T12:00:00Z",
                "signal_type": "aws_cloudwatch_alarm",
                "environment": "prod",
                "service": "api",
                "endpoint": "/",
                "severity": "critical",
                "segment": {"customer_tier": "standard"},
                "related_context": {"severity": "critical"},
            },
            "unknown_signal_strong",
        )
        evidence_event = _event_by_artifact(result, "evidence_pack")

        self.assertEqual(result["decision"]["decision_type"], "escalate")
        self.assertFalse(evidence_event["payload"]["sufficient"])
        self.assertEqual(evidence_event["payload"]["missing_fields"], ["no_profile_registered"])


class HarnessDrivenRcaBuilderSourceTests(unittest.TestCase):
    def test_uses_attached_investigation_root_cause_candidates(self) -> None:
        report = HarnessDrivenRcaBuilder().build(
            trigger=_trigger(),
            decision=_decision(
                {
                    "evidence_pack": {
                        "investigation_report": {
                            "root_cause_candidates": [
                                {
                                    "root_cause": "missing_secret_binding",
                                    "confidence": 0.66,
                                    "matched_patterns": ["secret not found"],
                                }
                            ]
                        }
                    }
                }
            ),
            evidence_pack={"probe_results": [], "sufficient": False, "missing_fields": ["no_profile_registered"]},
        )

        self.assertEqual(report.likely_cause, "missing_secret_binding")
        self.assertAlmostEqual(report.confidence, 0.66)
        self.assertIn("matched_patterns=secret not found", report.supporting_evidence)


if __name__ == "__main__":
    unittest.main()
