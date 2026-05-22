from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.praxis import (
    PraxisManagedRuntimeStore,
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


class PraxisManagedDryRunRuntimeTests(unittest.TestCase):
    def test_managed_runtime_persists_generation_to_revocation_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = PraxisManagedRuntimeStore(Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json")
            scope = {"kind": "team", "id": "team_demo", "scope_id": "team:team_demo"}
            operator = {"operator_id": "operator@example.com", "roles": ["admin"], "user_id": "usr_demo", "team_id": "team_demo"}

            record = store.create_generation_request(
                {
                    "request_id": "praxis-request-runtime-001",
                    "sources": [
                        {"source_type": "openapi", "source_ref": "fixtures/praxis/demo-openapi.redacted.json"},
                        {"source_type": "postman_json", "source_ref": "fixtures/praxis/demo-postman.redacted.json"},
                        {"source_type": "sop_markdown", "source_ref": "fixtures/praxis/demo-sop.redacted.md"},
                        {"source_type": "redacted_traffic_ref", "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json"},
                    ],
                },
                operator=operator,
                scope=scope,
            )
            self.assertEqual(record["state_slice"], "praxis.managed-dry-run-runtime.v1")
            self.assertEqual(record["status"], "candidate_generated")
            self.assertTrue((Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json").exists())

            record = store.import_akto_evidence(
                "praxis-request-runtime-001",
                {
                    "evidence_id": "praxis-akto-runtime-001",
                    "akto_result_path": "fixtures/praxis/demo-akto-results.json",
                },
                operator=operator,
                scope=scope,
            )
            self.assertEqual(record["akto_evidence"]["authority"]["grants_certification"], False)

            record = store.build_certification_binding(
                "praxis-request-runtime-001",
                {
                    "binding_id": "praxis-binding-runtime-001",
                    "connector_id": "praxis-runtime-generated-mcp",
                    "acp_session_id": "praxis-acp-runtime-001",
                },
                operator=operator,
                scope=scope,
            )
            self.assertEqual(record["dry_run_runtime"]["status"], "dry_run_ready")
            self.assertFalse(record["dry_run_runtime"]["managed_runtime_deployed"])
            self.assertEqual(record["dry_run_runtime"]["certified_tool_ids"], ["tool.listorders"])

            record = store.start_dry_run_endpoint(
                "praxis-request-runtime-001",
                {
                    "docker_dynamic_mcp_bridge": {
                        "gateway_ref": "docker-mcp-gateway://praxis-runtime-test",
                        "allowed_server_ids": ["praxis-runtime-generated-mcp"],
                        "session_only": True,
                        "profile_persisted": False,
                        "code_mode_enabled": False,
                    }
                },
                operator=operator,
                scope=scope,
            )
            self.assertEqual(record["dry_run_runtime"]["status"], "running")
            self.assertEqual(record["dry_run_runtime"]["mcp_endpoint_ref"], "mcp-dry-run://praxis-runtime-generated-mcp")
            bridge = record["dry_run_runtime"]["docker_dynamic_mcp_bridge"]
            self.assertEqual(bridge["schema_version"], "praxis.docker_dynamic_mcp_bridge.v1")
            self.assertEqual(bridge["gateway_ref"], "docker-mcp-gateway://praxis-runtime-test")
            self.assertEqual(bridge["allowed_server_ids"], ["praxis-runtime-generated-mcp"])
            self.assertEqual(bridge["allowed_management_tools"], ["mcp-find"])
            self.assertIn("mcp-add", bridge["blocked_management_tools"])
            self.assertFalse(bridge["code_mode_enabled"])
            self.assertFalse(bridge["profile_persisted"])
            self.assertTrue(bridge["session_only"])

            allowed_call = store.call_dry_run_tool(
                "praxis-request-runtime-001",
                {"tool_id": "tool.listorders", "arguments": {}},
                operator=operator,
                scope=scope,
            )
            self.assertTrue(allowed_call["allowed"])
            self.assertFalse(allowed_call["side_effects_executed"])

            denied_call = store.call_dry_run_tool(
                "praxis-request-runtime-001",
                {"tool_id": "tool.cancelorder", "arguments": {"order_id": "ord_demo"}},
                operator=operator,
                scope=scope,
            )
            self.assertFalse(denied_call["allowed"])
            self.assertEqual(denied_call["status"], "denied")

            record = store.revoke_generated_connector(
                "praxis-request-runtime-001",
                {"reason": "runtime test complete"},
                operator=operator,
                scope=scope,
            )
            self.assertEqual(record["dry_run_runtime"]["status"], "revoked")
            self.assertEqual(record["p10_proof_packet"]["status"], "complete")
            self.assertTrue(record["p10_proof_packet"]["checks"]["revocation_bound"])
            self.assertTrue(record["p10_proof_packet"]["checks"]["docker_dynamic_mcp_bridge_bound"])
            self.assertTrue(record["p10_proof_packet"]["checks"]["dynamic_servers_session_scoped"])
            self.assertTrue(record["p10_proof_packet"]["checks"]["dynamic_profile_persistence_blocked"])
            self.assertTrue(record["p10_proof_packet"]["checks"]["docker_code_mode_blocked"])
            self.assertTrue(record["p10_proof_packet"]["checks"]["bridge_catalog_allowlist_bound"])

            dashboard = store.build_product_dashboard(scope=scope)
            self.assertEqual(dashboard["state_slice"], "praxis.managed-dry-run-runtime.v1")
            self.assertEqual(dashboard["summary"]["runs"], 1)
            self.assertEqual(dashboard["pilot_runtime"]["status"], "revoked")
            self.assertEqual(dashboard["pilot_runtime"]["docker_dynamic_mcp_bridge"]["status"], "revoked")

    def test_managed_runtime_rejects_unsafe_docker_dynamic_mcp_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = PraxisManagedRuntimeStore(Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json")
            scope = {"kind": "team", "id": "team_demo", "scope_id": "team:team_demo"}
            operator = {"operator_id": "operator@example.com", "roles": ["admin"], "user_id": "usr_demo", "team_id": "team_demo"}

            store.create_generation_request(
                {
                    "request_id": "praxis-request-bridge-policy-001",
                    "sources": [
                        {"source_type": "openapi", "source_ref": "fixtures/praxis/demo-openapi.redacted.json"},
                        {"source_type": "postman_json", "source_ref": "fixtures/praxis/demo-postman.redacted.json"},
                        {"source_type": "sop_markdown", "source_ref": "fixtures/praxis/demo-sop.redacted.md"},
                        {"source_type": "redacted_traffic_ref", "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json"},
                    ],
                },
                operator=operator,
                scope=scope,
            )
            store.import_akto_evidence(
                "praxis-request-bridge-policy-001",
                {"evidence_id": "praxis-akto-bridge-policy-001", "akto_result_path": "fixtures/praxis/demo-akto-results.json"},
                operator=operator,
                scope=scope,
            )
            store.build_certification_binding(
                "praxis-request-bridge-policy-001",
                {
                    "binding_id": "praxis-binding-bridge-policy-001",
                    "connector_id": "praxis-bridge-policy-generated-mcp",
                    "acp_session_id": "praxis-acp-bridge-policy-001",
                },
                operator=operator,
                scope=scope,
            )

            with self.assertRaises(ValueError):
                store.start_dry_run_endpoint(
                    "praxis-request-bridge-policy-001",
                    {
                        "docker_dynamic_mcp_bridge": {
                            "allowed_server_ids": ["praxis-bridge-policy-generated-mcp"],
                            "session_only": True,
                            "profile_persisted": False,
                            "code_mode_enabled": True,
                        }
                    },
                    operator=operator,
                    scope=scope,
                )

    def test_mcp_json_rpc_lists_and_calls_only_certified_read_only_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = PraxisManagedRuntimeStore(Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json")
            scope = {"kind": "team", "id": "team_demo", "scope_id": "team:team_demo"}
            operator = {"operator_id": "operator@example.com", "roles": ["admin"], "user_id": "usr_demo", "team_id": "team_demo"}

            store.create_generation_request(
                {
                    "request_id": "praxis-request-mcp-rpc-001",
                    "sources": [
                        {"source_type": "openapi", "source_ref": "fixtures/praxis/demo-openapi.redacted.json"},
                        {"source_type": "postman_json", "source_ref": "fixtures/praxis/demo-postman.redacted.json"},
                        {"source_type": "sop_markdown", "source_ref": "fixtures/praxis/demo-sop.redacted.md"},
                        {"source_type": "redacted_traffic_ref", "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json"},
                    ],
                },
                operator=operator,
                scope=scope,
            )
            store.import_akto_evidence(
                "praxis-request-mcp-rpc-001",
                {"evidence_id": "praxis-akto-mcp-rpc-001", "akto_result_path": "fixtures/praxis/demo-akto-results.json"},
                operator=operator,
                scope=scope,
            )
            store.build_certification_binding(
                "praxis-request-mcp-rpc-001",
                {
                    "binding_id": "praxis-binding-mcp-rpc-001",
                    "connector_id": "praxis-mcp-rpc-generated-mcp",
                    "acp_session_id": "praxis-acp-mcp-rpc-001",
                },
                operator=operator,
                scope=scope,
            )
            store.start_dry_run_endpoint("praxis-request-mcp-rpc-001", {}, operator=operator, scope=scope)

            initialized = store.mcp_json_rpc(
                "praxis-request-mcp-rpc-001",
                {"jsonrpc": "2.0", "id": "init", "method": "initialize"},
                operator=operator,
                scope=scope,
            )
            self.assertEqual(initialized["result"]["serverInfo"]["name"], "praxis-managed-dry-run-runtime")

            listed = store.mcp_json_rpc(
                "praxis-request-mcp-rpc-001",
                {"jsonrpc": "2.0", "id": "list", "method": "tools/list"},
                operator=operator,
                scope=scope,
            )
            self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["tool.listorders"])

            called = store.mcp_json_rpc(
                "praxis-request-mcp-rpc-001",
                {
                    "jsonrpc": "2.0",
                    "id": "call",
                    "method": "tools/call",
                    "params": {"name": "tool.listorders", "arguments": {"dry_run_reason": "unit test"}},
                },
                operator=operator,
                scope=scope,
            )
            self.assertFalse(called["result"]["isError"])
            self.assertIn('"side_effects_executed": false', called["result"]["content"][0]["text"])

    def test_managed_runtime_rejects_raw_secret_source_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = PraxisManagedRuntimeStore(Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json")
            scope = {"kind": "team", "id": "team_demo", "scope_id": "team:team_demo"}
            operator = {"operator_id": "operator@example.com", "roles": ["admin"], "user_id": "usr_demo", "team_id": "team_demo"}

            with self.assertRaises(SchemaValidationError):
                store.create_generation_request(
                    {
                        "request_id": "praxis-request-secret-001",
                        "sources": [
                            {
                                "source_type": "openapi",
                                "filename": "bad-openapi.json",
                                "content": {
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
                                },
                            }
                        ],
                    },
                    operator=operator,
                    scope=scope,
                )


if __name__ == "__main__":
    unittest.main()
