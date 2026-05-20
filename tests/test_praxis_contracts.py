from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from shared.mesh_runtime.schema_validation import SchemaValidationError, load_schema, validate_payload

FIXTURE_PATH = Path("fixtures/praxis/p1_contracts.json")
CONTRACT_SCHEMAS = {
    "mcp_generation_request": "praxis/mcp-generation-request.schema.json",
    "source_bundle": "praxis/source-bundle.schema.json",
    "generated_mcp_contract": "praxis/generated-mcp-contract.schema.json",
    "akto_security_evidence": "praxis/akto-security-evidence.schema.json",
    "acp_agent_session": "praxis/acp-agent-session.schema.json",
    "certification_binding": "praxis/certification-binding.schema.json",
}


class PraxisContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_praxis_schema_titles_are_loadable(self) -> None:
        titles = {
            "mcp_generation_request": "PraxisMcpGenerationRequest",
            "source_bundle": "PraxisSourceBundle",
            "generated_mcp_contract": "PraxisGeneratedMcpContract",
            "akto_security_evidence": "PraxisAktoSecurityEvidence",
            "acp_agent_session": "PraxisAcpAgentSession",
            "certification_binding": "PraxisCertificationBinding",
        }

        for fixture_key, schema_name in CONTRACT_SCHEMAS.items():
            with self.subTest(schema_name=schema_name):
                self.assertEqual(load_schema(schema_name)["title"], titles[fixture_key])

    def test_p1_fixture_validates_against_all_praxis_schemas(self) -> None:
        for fixture_key, schema_name in CONTRACT_SCHEMAS.items():
            with self.subTest(schema_name=schema_name):
                validate_payload(schema_name, self.fixture[fixture_key])

    def test_generation_request_rejects_raw_credential_fields(self) -> None:
        request = copy.deepcopy(self.fixture["mcp_generation_request"])
        request["auth_declarations"][0]["token"] = "do-not-store"

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["mcp_generation_request"], request)

    def test_source_bundle_rejects_raw_payload_storage(self) -> None:
        bundle = copy.deepcopy(self.fixture["source_bundle"])
        bundle["redaction"]["raw_payload_stored"] = True

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["source_bundle"], bundle)

    def test_generated_tools_require_mutation_class_and_source_evidence(self) -> None:
        contract = copy.deepcopy(self.fixture["generated_mcp_contract"])
        del contract["tool_candidates"][0]["mutation_class"]

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["generated_mcp_contract"], contract)

        contract = copy.deepcopy(self.fixture["generated_mcp_contract"])
        del contract["tool_candidates"][0]["source_evidence_refs"]

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["generated_mcp_contract"], contract)

    def test_akto_evidence_cannot_grant_authority(self) -> None:
        evidence = copy.deepcopy(self.fixture["akto_security_evidence"])
        evidence["authority"]["grants_certification"] = True

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["akto_security_evidence"], evidence)

    def test_acp_session_cannot_grant_runtime_authority(self) -> None:
        session = copy.deepcopy(self.fixture["acp_agent_session"])
        session["authority"]["grants_runtime_authority"] = True

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["acp_agent_session"], session)

    def test_certification_binding_keeps_mesh_authoritative_and_revocable(self) -> None:
        binding = copy.deepcopy(self.fixture["certification_binding"])
        binding["authority"]["mesh_owns_revocation"] = False

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["certification_binding"], binding)

        binding = copy.deepcopy(self.fixture["certification_binding"])
        binding["revocation"]["revocable"] = False

        with self.assertRaises(SchemaValidationError):
            validate_payload(CONTRACT_SCHEMAS["certification_binding"], binding)


if __name__ == "__main__":
    unittest.main()
