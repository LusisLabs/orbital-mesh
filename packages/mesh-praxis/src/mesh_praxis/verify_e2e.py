from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from mesh_praxis.praxis import (
    PraxisManagedRuntimeStore,
    build_praxis_demo_proof_packet,
    load_praxis_source_bundle_fixture,
)
from mesh_praxis.schema_validation import SchemaValidationError, validate_payload

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PACKAGE_ROOT / "fixtures" / "praxis"
P8_PROOF_PACKET_PATH = FIXTURES_DIR / "p8_proof_packet.json"
P1_CONTRACTS_PATH = FIXTURES_DIR / "p1_contracts.json"
CONTRACT_SCHEMAS = {
    "mcp_generation_request": "praxis/mcp-generation-request.schema.json",
    "source_bundle": "praxis/source-bundle.schema.json",
    "generated_mcp_contract": "praxis/generated-mcp-contract.schema.json",
    "akto_security_evidence": "praxis/akto-security-evidence.schema.json",
    "acp_agent_session": "praxis/acp-agent-session.schema.json",
    "certification_binding": "praxis/certification-binding.schema.json",
}
FORBIDDEN_RAW_CREDENTIAL_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "cookie",
    "kubeconfig",
    "password",
    "private_key",
    "raw_credentials",
    "raw_secret",
    "raw_value",
    "secret_value",
    "token",
}


def _reject_forbidden_raw_credential_keys(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RAW_CREDENTIAL_KEYS:
                raise SchemaValidationError(f"{path}.{key}: raw credential field is forbidden")
            _reject_forbidden_raw_credential_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_raw_credential_keys(child, f"{path}[{index}]")


def _assert_mutating_tools_fail_closed(contract: dict[str, Any]) -> None:
    for tool in contract["tool_candidates"]:
        if tool["mutation_class"] in {"idempotent_write", "mutation", "destructive_mutation"}:
            if tool["approval_posture"] not in {"denied", "approval_required"}:
                raise SchemaValidationError(
                    f"$.generated_mcp_contract.tool_candidates[{tool['tool_id']}].approval_posture: "
                    "mutating tools must default to denied or approval_required"
                )
            if not tool["blockers"]:
                raise SchemaValidationError(
                    f"$.generated_mcp_contract.tool_candidates[{tool['tool_id']}].blockers: "
                    "mutating tools require explicit blockers until certified"
                )


def _verify_p1_contracts() -> dict[str, Any]:
    payloads = json.loads(P1_CONTRACTS_PATH.read_text(encoding="utf-8"))
    for fixture_key, schema_name in CONTRACT_SCHEMAS.items():
        validate_payload(schema_name, payloads[fixture_key])
        _reject_forbidden_raw_credential_keys(payloads[fixture_key], f"$.{fixture_key}")
    _assert_mutating_tools_fail_closed(payloads["generated_mcp_contract"])
    return {"status": "pass", "fixture_keys": list(CONTRACT_SCHEMAS.keys())}


def _verify_p8_proof_packet() -> dict[str, Any]:
    expected = build_praxis_demo_proof_packet()
    actual = json.loads(P8_PROOF_PACKET_PATH.read_text(encoding="utf-8"))
    validate_payload("praxis/e2e-proof-packet.schema.json", actual)
    if actual != expected:
        raise SchemaValidationError(f"{P8_PROOF_PACKET_PATH}: proof packet fixture is stale")
    if actual["status"] != "complete":
        raise SchemaValidationError(f"{P8_PROOF_PACKET_PATH}: proof packet is not complete")
    return {"status": "pass", "packet_id": actual.get("packet_id")}


def _verify_managed_runtime_chain() -> dict[str, Any]:
    scope = {"kind": "team", "id": "team_demo", "scope_id": "team:team_demo"}
    operator = {
        "operator_id": "operator@example.com",
        "roles": ["admin"],
        "user_id": "usr_demo",
        "team_id": "team_demo",
    }
    sources = [
        {"source_type": "openapi", "source_ref": "fixtures/praxis/demo-openapi.redacted.json"},
        {"source_type": "postman_json", "source_ref": "fixtures/praxis/demo-postman.redacted.json"},
        {"source_type": "sop_markdown", "source_ref": "fixtures/praxis/demo-sop.redacted.md"},
        {"source_type": "redacted_traffic_ref", "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json"},
    ]
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = PraxisManagedRuntimeStore(Path(tmp_dir) / "praxis" / "managed-dry-run-runtime.json")
        store.create_generation_request(
            {"request_id": "praxis-request-runtime-001", "sources": sources},
            operator=operator,
            scope=scope,
        )
        store.import_akto_evidence(
            "praxis-request-runtime-001",
            {
                "evidence_id": "praxis-akto-runtime-001",
                "akto_result_path": "fixtures/praxis/demo-akto-results.json",
            },
            operator=operator,
            scope=scope,
        )
        store.build_certification_binding(
            "praxis-request-runtime-001",
            {
                "binding_id": "praxis-binding-runtime-001",
                "connector_id": "praxis-runtime-generated-mcp",
                "acp_session_id": "praxis-acp-runtime-001",
            },
            operator=operator,
            scope=scope,
        )
        store.start_dry_run_endpoint(
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
        allowed_call = store.call_dry_run_tool(
            "praxis-request-runtime-001",
            {"tool_id": "tool.listorders", "arguments": {}},
            operator=operator,
            scope=scope,
        )
        denied_call = store.call_dry_run_tool(
            "praxis-request-runtime-001",
            {"tool_id": "tool.cancelorder", "arguments": {"order_id": "ord_demo"}},
            operator=operator,
            scope=scope,
        )
        record = store.revoke_generated_connector(
            "praxis-request-runtime-001",
            {"reason": "runtime test complete"},
            operator=operator,
            scope=scope,
        )
    return {
        "status": "pass",
        "read_only_call_allowed": allowed_call["allowed"],
        "mutation_call_denied": not denied_call["allowed"],
        "revoked": record["dry_run_runtime"]["status"] == "revoked",
        "revocation_bound": record["p10_proof_packet"]["checks"]["revocation_bound"],
    }


def build_proof_packet() -> dict[str, Any]:
    return build_praxis_demo_proof_packet()


def verify_package_e2e() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    blockers: list[str] = []

    try:
        checks["p1_contracts"] = _verify_p1_contracts()
    except (OSError, json.JSONDecodeError, SchemaValidationError, AssertionError) as exc:
        checks["p1_contracts"] = {"status": "fail", "error": str(exc)}
        blockers.append("p1_contracts_failed")

    try:
        checks["p8_proof_packet"] = _verify_p8_proof_packet()
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        checks["p8_proof_packet"] = {"status": "fail", "error": str(exc)}
        blockers.append("p8_proof_packet_failed")

    try:
        bundle = load_praxis_source_bundle_fixture()
        validate_payload("praxis/source-bundle.schema.json", bundle)
        checks["source_ingest"] = {
            "status": "pass",
            "source_types": [packet["source_type"] for packet in bundle["source_packets"]],
        }
    except (SchemaValidationError, OSError) as exc:
        checks["source_ingest"] = {"status": "fail", "error": str(exc)}
        blockers.append("source_ingest_failed")

    try:
        checks["managed_runtime_chain"] = _verify_managed_runtime_chain()
        if checks["managed_runtime_chain"].get("status") != "pass":
            blockers.append("managed_runtime_chain_failed")
    except (SchemaValidationError, ValueError, OSError) as exc:
        checks["managed_runtime_chain"] = {"status": "fail", "error": str(exc)}
        blockers.append("managed_runtime_chain_failed")

    return {"status": "pass" if not blockers else "fail", "checks": checks, "blockers": blockers}
