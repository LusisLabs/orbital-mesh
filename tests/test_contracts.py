from __future__ import annotations

import unittest

from shared.mesh_runtime import RemediationPlan, Trigger, load_fixture, load_schema, validate_payload


class ContractValidationTests(unittest.TestCase):
    def test_trigger_schema_is_loadable(self) -> None:
        schema = load_schema("trigger.schema.json")
        self.assertEqual(schema["title"], "Trigger")

    def test_trigger_payload_validates(self) -> None:
        signal = load_fixture("signals", "search_latency_regression.json")
        payload = {
            "trigger_id": "trg_test",
            "trigger_type": "performance_regression",
            "triggered_at": signal["observed_at"],
            "scope": {
                "environment": signal["environment"],
                "service": signal["service"],
                "endpoint": signal["endpoint"],
                "segment": signal["segment"],
            },
            "symptoms": [
                {
                    "metric": "p95_latency_ms",
                    "baseline": signal["baseline"]["p95_latency_ms"],
                    "observed": signal["observed"]["p95_latency_ms"],
                    "delta_pct": 46.4,
                }
            ],
            "related_changes": signal["related_changes"],
            "evidence_quality": signal["evidence_quality"],
            "dedupe_key": "prod:api-gateway:POST/search:enterprise_us",
        }
        validate_payload("trigger.schema.json", payload)
        model = Trigger.from_dict(payload)
        self.assertEqual(model.trigger_type, "performance_regression")

    def test_high_risk_plan_is_a_valid_contract(self) -> None:
        payload = load_fixture("plans", "high_risk_plan.json")
        plan = RemediationPlan.from_dict(payload)
        self.assertEqual(plan.risk["level"], "high")


if __name__ == "__main__":
    unittest.main()
