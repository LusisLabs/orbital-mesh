from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import SchemaValidationError
from shared.mesh_runtime.perennial import (
    assert_pilot_scope_boundaries,
    assert_reservoir_default_deny,
    load_darkharness_registry,
    materialize_sensitive_reservoir,
    project_reservoir_access,
)
from shared.mesh_runtime.perennial.boundaries import reservoir_denial_record


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "perennial"


class SensitiveReservoirBoundaryTests(unittest.TestCase):
    def test_materialized_reservoir_defaults_to_on_prem_deny(self) -> None:
        reservoir = materialize_sensitive_reservoir(
            reservoir_id="reservoir_security_findings",
            name="Security findings",
            owner={
                "team": "security",
                "service_owner": "owner.security",
                "data_steward": "steward.security",
            },
            classification={
                "data_classes": ["security", "secret_adjacent"],
                "sensitivity": "restricted",
                "trainable": "prohibited",
            },
            locality={
                "region": "customer-a-dc1",
                "storage_ref": "postgres://mesh/security_findings",
            },
            access_policy={
                "allowed_purposes": ["rca", "audit", "policy_check"],
                "allowed_compute_modes": ["in_place", "hash_only", "aggregate_only"],
                "retention_days": 90,
            },
            projection={
                "redaction_profile": "security-no-snippets",
                "allowed_index_fields": ["finding_type", "severity", "hash"],
            },
        )

        self.assertEqual(reservoir["locality"]["boundary"], "on_prem")
        self.assertEqual(reservoir["locality"]["external_egress_default"], "deny")
        self.assertEqual(reservoir["projection"]["max_snippet_chars"], 0)

    def test_reservoir_boundary_rejects_egress_allow(self) -> None:
        reservoir = json.loads((FIXTURE_DIR / "reservoir_denial.json").read_text())["contracts"]["sensitive_reservoir"]
        invalid = copy.deepcopy(reservoir)
        invalid["locality"]["external_egress_default"] = "allow"

        with self.assertRaisesRegex(SchemaValidationError, "external_egress_default"):
            assert_reservoir_default_deny(invalid)

    def test_pilot_scope_rejects_relaxed_production_authority(self) -> None:
        scope = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]["pilot_scope"]
        invalid = copy.deepcopy(scope)
        invalid["authority"]["production_actions_approval_required"] = False

        with self.assertRaisesRegex(SchemaValidationError, "production_actions_approval_required"):
            assert_pilot_scope_boundaries(invalid)

    def test_pilot_scope_rejects_raw_reservoir_egress(self) -> None:
        scope = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]["pilot_scope"]
        invalid = copy.deepcopy(scope)
        invalid["data_boundary"]["raw_reservoir_egress"] = "approved_exception"

        with self.assertRaisesRegex(SchemaValidationError, "raw_reservoir_egress"):
            assert_pilot_scope_boundaries(invalid)

    def test_reservoir_denial_record_is_valid_agent_action_record(self) -> None:
        record = reservoir_denial_record(
            reservoir_id="reservoir_security_findings",
            actor_id="external-llm.request",
            tenant_id="customer-a",
            run_id="run_reservoir_denial",
            observed_at="2026-05-05T16:00:00Z",
        )

        self.assertEqual(record["action"]["action_class"], "deny")
        self.assertEqual(record["outcome"]["status"], "denied")
        self.assertEqual(record["boundary"]["data_boundary"], "on_prem")

    def test_hash_projection_excludes_raw_reservoir_value(self) -> None:
        reservoir = json.loads((FIXTURE_DIR / "reservoir_denial.json").read_text())["contracts"]["sensitive_reservoir"]

        result = project_reservoir_access(
            reservoir=reservoir,
            value={"finding": "secret-adjacent stack trace", "severity": "high"},
            purpose="audit",
            compute_mode="hash_only",
            actor_id="darkharness.packet-export",
            tenant_id="customer-a",
            run_id="run_projection",
            observed_at="2026-05-05T16:05:00Z",
        )

        self.assertEqual(result["status"], "allowed")
        self.assertFalse(result["raw_sensitive_data_included"])
        self.assertEqual(result["projection"]["mode"], "hash_only")
        self.assertIn("content_hash", result["projection"])
        self.assertNotIn("secret-adjacent stack trace", json.dumps(result))
        self.assertEqual(result["action_record"]["action"]["action_type"], "reservoir_hash_only")

    def test_aggregate_projection_returns_shape_not_raw_values(self) -> None:
        reservoir = json.loads((FIXTURE_DIR / "reservoir_denial.json").read_text())["contracts"]["sensitive_reservoir"]

        result = project_reservoir_access(
            reservoir=reservoir,
            value=[1, 2, {"customer": "private"}],
            purpose="audit",
            compute_mode="aggregate_only",
            actor_id="darkharness.packet-export",
            tenant_id="customer-a",
        )

        self.assertEqual(result["projection"]["summary"]["shape"], "array")
        self.assertEqual(result["projection"]["summary"]["item_count"], 3)
        self.assertNotIn("private", json.dumps(result))

    def test_disallowed_projection_mode_returns_denial_without_raw_value(self) -> None:
        reservoir = json.loads((FIXTURE_DIR / "reservoir_denial.json").read_text())["contracts"]["sensitive_reservoir"]

        result = project_reservoir_access(
            reservoir=reservoir,
            value={"raw": "do-not-export"},
            purpose="audit",
            compute_mode="redacted_projection",
            actor_id="external-model.request",
            tenant_id="customer-a",
            run_id="run_projection_denied",
        )

        self.assertEqual(result["status"], "denied")
        self.assertFalse(result["raw_sensitive_data_included"])
        self.assertIn("compute mode", result["denial_reasons"][0])
        self.assertNotIn("do-not-export", json.dumps(result))
        self.assertEqual(result["action_record"]["outcome"]["status"], "denied")

    def test_registry_loader_validates_configured_scope_and_reservoirs(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "darkharness-registry.json"
            path.write_text(
                json.dumps(
                    {
                        "registry": "darkharness.registry.v1",
                        "tenant_id": "customer-a",
                        "pilot_scope": fixture["pilot_scope"],
                        "sensitive_reservoirs": [fixture["sensitive_reservoir"]],
                        "trust_ladder_ref": "trust://checkout-api/pilot",
                        "owner_registry_ref": "registry://owners/checkout-api",
                        "policy_refs": ["policy://darkharness/pilot/approval-required"],
                    }
                ),
                encoding="utf-8",
            )

            registry = load_darkharness_registry(path)

        self.assertEqual(registry.tenant_id, "customer-a")
        self.assertEqual(registry.source_path, str(path))
        self.assertEqual(registry.sensitive_reservoirs[0]["reservoir_id"], "reservoir_checkout_events")

    def test_registry_loader_rejects_relaxed_reservoir_boundary(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "allowed_action.json").read_text())["contracts"]
        invalid_reservoir = copy.deepcopy(fixture["sensitive_reservoir"])
        invalid_reservoir["locality"]["external_egress_default"] = "allow"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "darkharness-registry.json"
            path.write_text(
                json.dumps(
                    {
                        "pilot_scope": fixture["pilot_scope"],
                        "sensitive_reservoirs": [invalid_reservoir],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SchemaValidationError, "external_egress_default"):
                load_darkharness_registry(path)


if __name__ == "__main__":
    unittest.main()
