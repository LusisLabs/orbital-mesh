from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from shared.mesh_runtime import SchemaValidationError, load_schema, validate_payload


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "perennial"

SCHEMA_BY_RECORD = {
    "agent_action_record": "perennial/agent-action-record.schema.json",
    "sensitive_reservoir": "perennial/sensitive-reservoir.schema.json",
    "epistemic_state": "perennial/epistemic-state.schema.json",
    "ontological_state": "perennial/ontological-state.schema.json",
    "governance_commit": "perennial/governance-commit.schema.json",
    "proof_envelope": "perennial/proof-envelope.schema.json",
    "pilot_scope": "perennial/pilot-scope.schema.json",
    "darkharness_pilot_packet": "perennial/darkharness-pilot-packet.schema.json",
}

EXPECTED_CONTRACT_TITLES = {
    "agent_action_record": "AgentActionRecord",
    "sensitive_reservoir": "SensitiveReservoir",
    "epistemic_state": "EpistemicState",
    "ontological_state": "OntologicalState",
    "governance_commit": "GovernanceCommit",
    "proof_envelope": "ProofEnvelope",
    "pilot_scope": "PilotScope",
    "darkharness_pilot_packet": "DarkharnessPilotPacket",
}

PERENNIAL_FIXTURES = [
    "allowed_action.json",
    "denied_action.json",
    "reservoir_denial.json",
    "pilot_packet_boundary.json",
]


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class PerennialContractValidationTests(unittest.TestCase):
    def test_perennial_contract_schemas_are_loadable(self) -> None:
        for record_name, schema_name in SCHEMA_BY_RECORD.items():
            with self.subTest(record_name=record_name):
                schema = load_schema(schema_name)
                self.assertEqual(schema["title"], EXPECTED_CONTRACT_TITLES[record_name])

    def test_perennial_fixtures_validate_present_contract_records(self) -> None:
        observed_records: set[str] = set()

        for fixture_name in PERENNIAL_FIXTURES:
            fixture = _load_fixture(fixture_name)
            contracts = fixture["contracts"]
            self.assertTrue(contracts, fixture_name)

            for record_name, payload in contracts.items():
                with self.subTest(fixture=fixture_name, record_name=record_name):
                    validate_payload(SCHEMA_BY_RECORD[record_name], payload)
                    observed_records.add(record_name)

        self.assertGreaterEqual(observed_records, set(SCHEMA_BY_RECORD))

    def test_agent_action_record_rejects_missing_boundary(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["agent_action_record"]
        invalid = copy.deepcopy(payload)
        invalid.pop("boundary")

        with self.assertRaisesRegex(SchemaValidationError, "missing required field 'boundary'"):
            validate_payload(SCHEMA_BY_RECORD["agent_action_record"], invalid)

    def test_sensitive_reservoir_rejects_missing_owner(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["sensitive_reservoir"]
        invalid = copy.deepcopy(payload)
        invalid.pop("owner")

        with self.assertRaisesRegex(SchemaValidationError, "missing required field 'owner'"):
            validate_payload(SCHEMA_BY_RECORD["sensitive_reservoir"], invalid)

    def test_sensitive_reservoir_rejects_external_egress_default_allow(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["sensitive_reservoir"]
        invalid = copy.deepcopy(payload)
        invalid["locality"]["external_egress_default"] = "allow"

        with self.assertRaisesRegex(SchemaValidationError, "external_egress_default"):
            validate_payload(SCHEMA_BY_RECORD["sensitive_reservoir"], invalid)

    def test_governance_commit_rejects_missing_authority(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["governance_commit"]
        invalid = copy.deepcopy(payload)
        invalid.pop("authority")

        with self.assertRaisesRegex(SchemaValidationError, "missing required field 'authority'"):
            validate_payload(SCHEMA_BY_RECORD["governance_commit"], invalid)

    def test_governance_commit_rejects_missing_proof(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["governance_commit"]
        invalid = copy.deepcopy(payload)
        invalid.pop("proof")

        with self.assertRaisesRegex(SchemaValidationError, "missing required field 'proof'"):
            validate_payload(SCHEMA_BY_RECORD["governance_commit"], invalid)

    def test_proof_envelope_rejects_raw_sensitive_data_in_default_pilot(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["proof_envelope"]
        invalid = copy.deepcopy(payload)
        invalid["disclosure"]["raw_sensitive_data_included"] = True

        with self.assertRaisesRegex(SchemaValidationError, "raw_sensitive_data_included"):
            validate_payload(SCHEMA_BY_RECORD["proof_envelope"], invalid)

    def test_pilot_scope_rejects_production_actions_without_approval(self) -> None:
        payload = _load_fixture("allowed_action.json")["contracts"]["pilot_scope"]
        invalid = copy.deepcopy(payload)
        invalid["authority"]["production_actions_approval_required"] = False

        with self.assertRaisesRegex(SchemaValidationError, "production_actions_approval_required"):
            validate_payload(SCHEMA_BY_RECORD["pilot_scope"], invalid)

    def test_pilot_packet_rejects_missing_claim_boundary(self) -> None:
        payload = _load_fixture("pilot_packet_boundary.json")["contracts"]["darkharness_pilot_packet"]
        invalid = copy.deepcopy(payload)
        invalid.pop("claim_boundary")

        with self.assertRaisesRegex(SchemaValidationError, "missing required field 'claim_boundary'"):
            validate_payload(SCHEMA_BY_RECORD["darkharness_pilot_packet"], invalid)

    def test_pilot_packet_rejects_disabled_production_approval_boundary(self) -> None:
        payload = _load_fixture("pilot_packet_boundary.json")["contracts"]["darkharness_pilot_packet"]
        invalid = copy.deepcopy(payload)
        invalid["boundaries"]["production_actions_approval_required"] = False

        with self.assertRaisesRegex(SchemaValidationError, "production_actions_approval_required"):
            validate_payload(SCHEMA_BY_RECORD["darkharness_pilot_packet"], invalid)


if __name__ == "__main__":
    unittest.main()
