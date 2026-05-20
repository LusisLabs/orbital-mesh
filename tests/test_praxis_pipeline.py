from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.praxis import (
    build_praxis_certification_binding,
    build_praxis_demo_proof_packet,
    build_praxis_e2e_proof_packet,
    build_praxis_source_bundle,
    generate_praxis_mcp_contract,
    import_praxis_akto_security_evidence,
    load_praxis_source_bundle_fixture,
)
from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload


class PraxisSourceIngestTests(unittest.TestCase):
    def test_source_ingest_normalizes_openapi_postman_sop_and_traffic_refs(self) -> None:
        bundle = load_praxis_source_bundle_fixture()

        validate_payload("praxis/source-bundle.schema.json", bundle)
        self.assertEqual(bundle["schema_version"], "praxis.source_bundle.v1")
        self.assertEqual(
            [packet["source_type"] for packet in bundle["source_packets"]],
            ["openapi", "postman_json", "sop_markdown", "redacted_traffic_ref"],
        )
        self.assertTrue(all(packet["citation_refs"] for packet in bundle["source_packets"]))
        self.assertTrue(all(packet["secret_scan"]["raw_credentials_present"] is False for packet in bundle["source_packets"]))
        self.assertFalse(bundle["redaction"]["raw_payload_stored"])

    def test_source_ingest_rejects_unredacted_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "bad-openapi.json"
            source_path.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "paths": {},
                        "components": {
                            "securitySchemes": {
                                "apiKeyAuth": {
                                    "type": "apiKey",
                                    "name": "Authorization",
                                    "value": "Bearer abcdefghijklmnopqrstuvwxyz",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SchemaValidationError):
                build_praxis_source_bundle(
                    bundle_id="bad",
                    tenant_id="tenant_demo",
                    created_at="2026-05-20T05:00:05Z",
                    sources=[
                        {
                            "source_type": "openapi",
                            "source_ref": str(source_path),
                        }
                    ],
                )


class PraxisGeneratedMcpContractTests(unittest.TestCase):
    def test_generator_emits_candidate_tools_with_fail_closed_mutation_defaults(self) -> None:
        source_bundle = load_praxis_source_bundle_fixture()
        contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-generated-contract-demo-001",
            generated_at="2026-05-20T05:00:10Z",
        )

        validate_payload("praxis/generated-mcp-contract.schema.json", contract)
        tools = {tool["tool_id"]: tool for tool in contract["tool_candidates"]}

        self.assertEqual(tools["tool.listorders"]["mutation_class"], "read_only")
        self.assertEqual(tools["tool.listorders"]["approval_posture"], "read_only")
        self.assertEqual(tools["tool.listorders"]["auth_scope"]["allowed_scopes"], ["orders.read"])
        self.assertIn("source://openapi/fixtures/praxis/demo-openapi.redacted.json#paths./orders.get", tools["tool.listorders"]["source_evidence_refs"])

        cancel_tool = tools["tool.cancelorder"]
        self.assertEqual(cancel_tool["mutation_class"], "mutation")
        self.assertEqual(cancel_tool["approval_posture"], "denied")
        self.assertEqual(cancel_tool["auth_scope"]["allowed_scopes"], [])
        self.assertIn("mutation_scope_not_certified", cancel_tool["blockers"])
        self.assertIn("operator_approval_missing", cancel_tool["blockers"])


class PraxisAktoSecurityEvidenceTests(unittest.TestCase):
    def test_akto_fixture_imports_as_advisory_security_evidence(self) -> None:
        source_bundle = load_praxis_source_bundle_fixture()
        contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-generated-contract-demo-001",
            generated_at="2026-05-20T05:00:10Z",
        )
        evidence = import_praxis_akto_security_evidence(
            akto_result_path="fixtures/praxis/demo-akto-results.json",
            generated_contract=contract,
            evidence_id="praxis-akto-evidence-demo-001",
            imported_at="2026-05-20T05:00:15Z",
        )

        validate_payload("praxis/akto-security-evidence.schema.json", evidence)
        self.assertFalse(evidence["live_dast_executed"])
        self.assertFalse(evidence["raw_traffic_stored"])
        self.assertTrue(evidence["authority"]["advisory_only"])
        self.assertFalse(evidence["authority"]["grants_certification"])
        self.assertEqual(evidence["findings"][0]["tool_candidate_ids"], ["tool.cancelorder"])

    def test_akto_import_rejects_live_dast_by_default(self) -> None:
        source_bundle = load_praxis_source_bundle_fixture()
        contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-generated-contract-demo-001",
            generated_at="2026-05-20T05:00:10Z",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = Path(tmp_dir) / "akto-live.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "source": "akto_fixture",
                        "scan_status": "imported",
                        "live_dast_executed": True,
                        "raw_traffic_stored": False,
                        "inventory": [],
                        "findings": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SchemaValidationError):
                import_praxis_akto_security_evidence(
                    akto_result_path=fixture_path,
                    generated_contract=contract,
                    evidence_id="bad",
                    imported_at="2026-05-20T05:00:15Z",
                )


class PraxisCertificationBridgeTests(unittest.TestCase):
    def test_certification_binding_admits_read_only_and_denies_unsafe_mutation(self) -> None:
        source_bundle = load_praxis_source_bundle_fixture()
        contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-generated-contract-demo-001",
            generated_at="2026-05-20T05:00:10Z",
        )
        evidence = import_praxis_akto_security_evidence(
            akto_result_path="fixtures/praxis/demo-akto-results.json",
            generated_contract=contract,
            evidence_id="praxis-akto-evidence-demo-001",
            imported_at="2026-05-20T05:00:15Z",
        )

        binding = build_praxis_certification_binding(
            generated_contract=contract,
            akto_evidence=evidence,
            binding_id="praxis-certification-binding-demo-001",
            connector_id="praxis-demo-generated-mcp",
            acp_session_id="praxis-acp-session-demo-001",
            created_at="2026-05-20T05:00:25Z",
        )

        validate_payload("praxis/certification-binding.schema.json", binding)
        bindings = {item["tool_candidate_id"]: item for item in binding["tool_bindings"]}
        self.assertEqual(bindings["tool.listorders"]["certification_result"], "read_only")
        self.assertEqual(bindings["tool.listorders"]["allowed_scopes"], ["orders.read"])
        self.assertEqual(bindings["tool.cancelorder"]["certification_result"], "denied")
        self.assertIn("akto_high_or_critical_finding_open", bindings["tool.cancelorder"]["readiness_blockers"])
        self.assertTrue(binding["authority"]["mesh_owns_certification"])
        self.assertFalse(binding["authority"]["akto_grants_authority"])
        self.assertTrue(binding["revocation"]["revocable"])


class PraxisProofPacketTests(unittest.TestCase):
    def test_demo_proof_packet_binds_vertical_slice_without_runtime_authority(self) -> None:
        packet = build_praxis_demo_proof_packet()

        validate_payload("praxis/e2e-proof-packet.schema.json", packet)
        self.assertEqual(packet["status"], "complete")
        self.assertTrue(packet["checks"]["source_bundle_bound"])
        self.assertTrue(packet["checks"]["read_only_tool_certified"])
        self.assertTrue(packet["checks"]["unsafe_mutation_denied"])
        self.assertEqual(packet["mcp_readiness"]["status"], "dry_run_ready")
        self.assertEqual(packet["mcp_readiness"]["certified_tool_ids"], ["tool.listorders"])
        self.assertEqual(packet["mcp_readiness"]["denied_tool_ids"], ["tool.cancelorder"])
        self.assertFalse(packet["authority"]["managed_runtime_deployed"])
        self.assertTrue(packet["authority"]["mesh_owns_revocation"])

    def test_proof_packet_blocks_when_source_contract_binding_is_broken(self) -> None:
        source_bundle = load_praxis_source_bundle_fixture()
        generated_contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-generated-contract-demo-001",
            generated_at="2026-05-20T05:00:10Z",
        )
        akto_evidence = import_praxis_akto_security_evidence(
            akto_result_path="fixtures/praxis/demo-akto-results.json",
            generated_contract=generated_contract,
            evidence_id="praxis-akto-evidence-demo-001",
            imported_at="2026-05-20T05:00:15Z",
        )
        binding = build_praxis_certification_binding(
            generated_contract=generated_contract,
            akto_evidence=akto_evidence,
            binding_id="praxis-certification-binding-demo-001",
            connector_id="praxis-demo-generated-mcp",
            acp_session_id="praxis-acp-session-demo-001",
            created_at="2026-05-20T05:00:25Z",
        )
        generated_contract["source_bundle_id"] = "wrong-source"

        packet = build_praxis_e2e_proof_packet(
            source_bundle=source_bundle,
            generated_contract=generated_contract,
            akto_evidence=akto_evidence,
            certification_binding=binding,
            packet_id="blocked",
            generated_at="2026-05-20T05:00:30Z",
        )

        self.assertEqual(packet["status"], "blocked")
        self.assertFalse(packet["checks"]["source_bundle_bound"])


if __name__ == "__main__":
    unittest.main()
