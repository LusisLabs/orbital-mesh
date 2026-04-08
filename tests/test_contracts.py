from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import Decision, Trigger, load_fixture, load_schema, validate_payload


class ContractValidationTests(unittest.TestCase):
    def test_trigger_schema_is_loadable(self) -> None:
        schema = load_schema("trigger.schema.json")
        self.assertEqual(schema["title"], "Trigger")

    def test_trigger_payload_validates(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        payload = {
            "trigger_id": "trg_test",
            "trigger_type": "feature_flag_performance_regression",
            "triggered_at": signal["observed_at"],
            "environment": signal["environment"],
            "service": signal["service"],
            "endpoint": signal["endpoint"],
            "flag_key": signal["feature_flag"]["flag_key"],
            "current_rollout_pct": signal["feature_flag"]["current_rollout_pct"],
            "comparison_window": signal["comparison_window"],
            "segment": signal["segment"],
            "metrics": {
                "baseline_p95_latency_ms": signal["request_telemetry"]["baseline"]["p95_latency_ms"],
                "observed_p95_latency_ms": signal["request_telemetry"]["observed"]["p95_latency_ms"],
                "baseline_error_rate": signal["request_telemetry"]["baseline"]["error_rate"],
                "observed_error_rate": signal["request_telemetry"]["observed"]["error_rate"],
                "baseline_timeout_rate": signal["request_telemetry"]["baseline"]["timeout_rate"],
                "observed_timeout_rate": signal["request_telemetry"]["observed"]["timeout_rate"],
                "sample_size": signal["request_telemetry"]["sample_size"],
            },
            "related_context": {
                "release_id": signal["deployment"]["release_id"],
                "active_incidents": signal["related_context"]["active_incidents"],
                "similar_prior_cases": signal["related_context"]["similar_prior_cases"],
            },
        }
        validate_payload("trigger.schema.json", payload)
        model = Trigger.from_dict(payload)
        self.assertEqual(model.trigger_type, "feature_flag_performance_regression")

    def test_high_risk_decision_is_a_valid_contract(self) -> None:
        payload = load_fixture("decisions", "high_risk_decision.json")
        decision = Decision.from_dict(payload)
        self.assertEqual(decision.risk["level"], "high")

    def test_code_patch_decision_is_a_valid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            payload = {
                "decision_id": "dec_patch_test",
                "trigger_id": "trg_patch_test",
                "decision_type": "investigate_and_patch",
                "autonomy_tier": "autonomous",
                "summary": "Apply a bounded patch to the search parser.",
                "reasoning": {
                    "primary_hypothesis": "A parser timeout constant is forcing the degraded path.",
                    "evidence": ["p95 latency and timeout rate regressed after rollout"],
                    "evidence_pack": {"suspected_file": "app/search.py"},
                    "alternatives_considered": ["reduce rollout to 10%", "disable feature flag fully"],
                },
                "expected_outcome": {
                    "target_metrics": {
                        "p95_latency_ms": "<= 470",
                        "error_rate": "<= 0.015",
                    },
                    "time_to_effect": "10m",
                },
                "risk": {
                    "level": "medium",
                    "blast_radius": "single_repo_single_file",
                    "customer_impact_if_wrong": "temporary service instability from an incorrect bounded patch",
                },
                "confidence": 0.78,
                "execution_plan": {
                    "system": "repo_patch_service",
                    "action": "investigate_and_patch",
                    "parameters": {
                        "repo_path": str(repo_path),
                        "allowed_paths": ["app/search.py"],
                        "suspected_file": "app/search.py",
                        "test_commands": ["python3 -m unittest discover -s tests"],
                        "patch_template": {
                            "target_file": "app/search.py",
                            "find": "old",
                            "replace": "new",
                        },
                    },
                    "rollback_plan": "restore previous file contents from backup",
                },
            }
            decision = Decision.from_dict(payload)
        self.assertEqual(decision.execution_plan["system"], "repo_patch_service")


if __name__ == "__main__":
    unittest.main()
