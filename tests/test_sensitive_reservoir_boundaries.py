from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from shared.mesh_runtime import SchemaValidationError
from shared.mesh_runtime.perennial import (
    assert_pilot_scope_boundaries,
    assert_reservoir_default_deny,
    materialize_sensitive_reservoir,
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


if __name__ == "__main__":
    unittest.main()
