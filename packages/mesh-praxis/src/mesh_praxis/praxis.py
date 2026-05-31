from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .json_store import LockedJsonFile
from .schema_validation import SchemaValidationError, validate_payload


PRAXIS_SOURCE_BUNDLE_SCHEMA = "praxis/source-bundle.schema.json"
PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA = "praxis/generated-mcp-contract.schema.json"
PRAXIS_AKTO_SECURITY_EVIDENCE_SCHEMA = "praxis/akto-security-evidence.schema.json"
PRAXIS_CERTIFICATION_BINDING_SCHEMA = "praxis/certification-binding.schema.json"
PRAXIS_E2E_PROOF_PACKET_SCHEMA = "praxis/e2e-proof-packet.schema.json"
PRAXIS_SOURCE_BUNDLE_VERSION = "praxis.source_bundle.v1"
PRAXIS_GENERATED_MCP_CONTRACT_VERSION = "praxis.generated_mcp_contract.v1"
PRAXIS_AKTO_SECURITY_EVIDENCE_VERSION = "praxis.akto_security_evidence.v1"
PRAXIS_CERTIFICATION_BINDING_VERSION = "praxis.certification_binding.v1"
PRAXIS_E2E_PROOF_PACKET_VERSION = "praxis.e2e_proof_packet.v1"
PRAXIS_MANAGED_DRY_RUN_RUNTIME_VERSION = "praxis.managed_dry_run_runtime.v1"
PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE = "praxis.managed-dry-run-runtime.v1"
PRAXIS_DOCKER_DYNAMIC_MCP_BRIDGE_VERSION = "praxis.docker_dynamic_mcp_bridge.v1"
DOCKER_DYNAMIC_MCP_DOC_URL = "https://docs.docker.com/ai/mcp-catalog-and-toolkit/dynamic-mcp/"
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_RAW_SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|client[_-]?secret|cookie|kubeconfig|password|private[_-]?key|token)", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"(Bearer\s+(?!REDACTED)[A-Za-z0-9._~+/=-]{12,}|sk-[A-Za-z0-9]{12,})")
_DOCKER_DYNAMIC_MCP_MANAGEMENT_TOOLS = (
    "mcp-find",
    "mcp-add",
    "mcp-config-set",
    "mcp-remove",
    "mcp-exec",
    "code-mode",
)
_DOCKER_DYNAMIC_MCP_ALLOWED_TOOLS = ("mcp-find",)
_DOCKER_DYNAMIC_MCP_BLOCKED_TOOLS = (
    "mcp-add",
    "mcp-config-set",
    "mcp-remove",
    "mcp-exec",
    "code-mode",
)


def build_praxis_source_bundle(
    *,
    bundle_id: str,
    tenant_id: str,
    sources: list[dict[str, str]],
    created_at: str | None = None,
) -> dict[str, Any]:
    packets = [_source_packet(index=index, source=source) for index, source in enumerate(sources, start=1)]
    bundle = {
        "schema_version": PRAXIS_SOURCE_BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "created_at": created_at or _timestamp(),
        "tenant_id": tenant_id,
        "source_packets": packets,
        "redaction": {
            "status": "redacted",
            "raw_payload_stored": False,
            "secret_material_refs": [],
        },
    }
    validate_payload(PRAXIS_SOURCE_BUNDLE_SCHEMA, bundle)
    return bundle


def load_praxis_source_bundle_fixture() -> dict[str, Any]:
    return build_praxis_source_bundle(
        bundle_id="praxis-source-bundle-demo-001",
        tenant_id="tenant_demo",
        created_at="2026-05-20T05:00:05Z",
        sources=[
            {
                "source_type": "openapi",
                "source_ref": "fixtures/praxis/demo-openapi.redacted.json",
            },
            {
                "source_type": "postman_json",
                "source_ref": "fixtures/praxis/demo-postman.redacted.json",
            },
            {
                "source_type": "sop_markdown",
                "source_ref": "fixtures/praxis/demo-sop.redacted.md",
            },
            {
                "source_type": "redacted_traffic_ref",
                "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json",
            },
        ],
    )


def generate_praxis_mcp_contract(
    *,
    source_bundle: dict[str, Any],
    contract_id: str,
    generated_at: str | None = None,
    generator_version: str = "praxis-contract-builder-p3",
) -> dict[str, Any]:
    validate_payload(PRAXIS_SOURCE_BUNDLE_SCHEMA, source_bundle)
    openapi_packet = _first_packet(source_bundle, "openapi")
    if openapi_packet is None:
        raise SchemaValidationError("$.source_packets: openapi source packet is required for P3 generation")
    openapi = json.loads(_resolve_package_path(str(openapi_packet["source_ref"])).read_text(encoding="utf-8"))
    sop_hints = _sop_workflow_hints(source_bundle)
    candidates = [
        _tool_candidate_from_openapi_endpoint(openapi_packet=openapi_packet, path=path, method=method, operation=operation, sop_hints=sop_hints)
        for path, methods in sorted(openapi.get("paths", {}).items())
        if isinstance(methods, dict)
        for method, operation in sorted(methods.items())
        if isinstance(operation, dict)
    ]
    contract = {
        "schema_version": PRAXIS_GENERATED_MCP_CONTRACT_VERSION,
        "contract_id": contract_id,
        "source_bundle_id": source_bundle["bundle_id"],
        "generated_at": generated_at or _timestamp(),
        "generator_version": generator_version,
        "tool_candidates": candidates,
    }
    validate_payload(PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA, contract)
    return contract


def import_praxis_akto_security_evidence(
    *,
    akto_result_path: str | Path,
    generated_contract: dict[str, Any],
    evidence_id: str,
    imported_at: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(_resolve_package_path(str(akto_result_path)).read_text(encoding="utf-8"))
    return import_praxis_akto_security_evidence_payload(
        akto_result_payload=payload,
        generated_contract=generated_contract,
        evidence_id=evidence_id,
        imported_at=imported_at,
    )


def import_praxis_akto_security_evidence_payload(
    *,
    akto_result_payload: dict[str, Any],
    generated_contract: dict[str, Any],
    evidence_id: str,
    imported_at: str | None = None,
) -> dict[str, Any]:
    validate_payload(PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA, generated_contract)
    payload = akto_result_payload
    _reject_raw_secret_values(json.dumps(payload, sort_keys=True), evidence_id)
    if payload.get("live_dast_executed") is True:
        raise SchemaValidationError("$.live_dast_executed: live Akto scans are not allowed by default")
    if payload.get("raw_traffic_stored") is True:
        raise SchemaValidationError("$.raw_traffic_stored: raw traffic storage is forbidden")
    tool_ids_by_endpoint = _tool_ids_by_endpoint(generated_contract)
    evidence = {
        "schema_version": PRAXIS_AKTO_SECURITY_EVIDENCE_VERSION,
        "evidence_id": evidence_id,
        "imported_at": imported_at or _timestamp(),
        "source": str(payload.get("source") or "akto_fixture"),
        "scan_status": str(payload.get("scan_status") or "imported"),
        "live_dast_executed": False,
        "raw_traffic_stored": False,
        "inventory": [
            _akto_inventory_record(item, tool_ids_by_endpoint)
            for item in payload.get("inventory", [])
            if isinstance(item, dict)
        ],
        "findings": [
            _akto_finding_record(item, tool_ids_by_endpoint)
            for item in payload.get("findings", [])
            if isinstance(item, dict)
        ],
        "authority": {
            "advisory_only": True,
            "grants_policy_authority": False,
            "grants_certification": False,
        },
    }
    validate_payload(PRAXIS_AKTO_SECURITY_EVIDENCE_SCHEMA, evidence)
    return evidence


def build_praxis_certification_binding(
    *,
    generated_contract: dict[str, Any],
    akto_evidence: dict[str, Any],
    binding_id: str,
    connector_id: str,
    acp_session_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    validate_payload(PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA, generated_contract)
    validate_payload(PRAXIS_AKTO_SECURITY_EVIDENCE_SCHEMA, akto_evidence)
    finding_index = _open_findings_by_tool(akto_evidence)
    tool_bindings = [_tool_certification_binding(tool, finding_index.get(str(tool["tool_id"]), [])) for tool in generated_contract["tool_candidates"]]
    binding = {
        "schema_version": PRAXIS_CERTIFICATION_BINDING_VERSION,
        "binding_id": binding_id,
        "created_at": created_at or _timestamp(),
        "generated_contract_id": generated_contract["contract_id"],
        "security_evidence_id": akto_evidence["evidence_id"],
        "acp_session_id": acp_session_id,
        "mesh_connector_certification_version": "mesh.connector_certification.v1",
        "connector_id": connector_id,
        "tool_bindings": tool_bindings,
        "authority": {
            "mesh_owns_policy": True,
            "mesh_owns_certification": True,
            "mesh_owns_approval": True,
            "mesh_owns_audit": True,
            "mesh_owns_bounded_execution": True,
            "mesh_owns_revocation": True,
            "akto_grants_authority": False,
            "acp_grants_runtime_authority": False,
            "generated_mcp_is_candidate_until_certified": True,
        },
        "revocation": {
            "revocable": True,
            "deactivation_required": True,
            "revocation_ref": f"mesh-revocation://{connector_id}",
        },
    }
    validate_payload(PRAXIS_CERTIFICATION_BINDING_SCHEMA, binding)
    return binding


def build_praxis_e2e_proof_packet(
    *,
    source_bundle: dict[str, Any],
    generated_contract: dict[str, Any],
    akto_evidence: dict[str, Any],
    certification_binding: dict[str, Any],
    packet_id: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_payload(PRAXIS_SOURCE_BUNDLE_SCHEMA, source_bundle)
    validate_payload(PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA, generated_contract)
    validate_payload(PRAXIS_AKTO_SECURITY_EVIDENCE_SCHEMA, akto_evidence)
    validate_payload(PRAXIS_CERTIFICATION_BINDING_SCHEMA, certification_binding)

    bindings = certification_binding["tool_bindings"]
    certified_tool_ids = sorted(
        binding["tool_candidate_id"]
        for binding in bindings
        if binding["certification_result"] in {"read_only", "staging_ready"}
    )
    denied_tool_ids = sorted(binding["tool_candidate_id"] for binding in bindings if binding["certification_result"] == "denied")
    blockers = sorted({blocker for binding in bindings for blocker in binding["readiness_blockers"]})
    checks = {
        "source_bundle_bound": source_bundle.get("bundle_id") == generated_contract.get("source_bundle_id"),
        "generated_contract_bound": generated_contract.get("contract_id") == certification_binding.get("generated_contract_id"),
        "security_evidence_bound": akto_evidence.get("evidence_id") == certification_binding.get("security_evidence_id"),
        "certification_binding_bound": bool(certification_binding.get("binding_id")),
        "read_only_tool_certified": bool(certified_tool_ids),
        "unsafe_mutation_denied": bool(denied_tool_ids),
        "operator_decision_bound": bool(denied_tool_ids and certified_tool_ids),
        "dry_run_mcp_readiness_bound": bool(certified_tool_ids),
    }
    packet = {
        "schema_version": PRAXIS_E2E_PROOF_PACKET_VERSION,
        "packet_id": packet_id,
        "generated_at": generated_at or _timestamp(),
        "state_slice": "praxis.e2e-proof-packet.v1",
        "status": "complete" if all(checks.values()) else "blocked",
        "source_bundle": {
            "bundle_id": source_bundle["bundle_id"],
            "sha256": _canonical_sha256(source_bundle),
            "source_packet_count": len(source_bundle["source_packets"]),
        },
        "generated_contract": {
            "contract_id": generated_contract["contract_id"],
            "sha256": _canonical_sha256(generated_contract),
            "tool_candidate_count": len(generated_contract["tool_candidates"]),
        },
        "security_evidence": {
            "evidence_id": akto_evidence["evidence_id"],
            "sha256": _canonical_sha256(akto_evidence),
            "finding_count": len(akto_evidence["findings"]),
            "critical_or_high_open_count": sum(
                1
                for finding in akto_evidence["findings"]
                if finding["severity"] in {"high", "critical"} and finding["status"] == "open"
            ),
        },
        "certification_binding": {
            "binding_id": certification_binding["binding_id"],
            "sha256": _canonical_sha256(certification_binding),
            "connector_id": certification_binding["connector_id"],
        },
        "mcp_readiness": {
            "status": "dry_run_ready" if certified_tool_ids else "blocked",
            "dry_run_only": True,
            "certified_tool_ids": certified_tool_ids,
            "denied_tool_ids": denied_tool_ids,
            "readiness_blockers": blockers,
        },
        "operator_decision": {
            "decision": "approve_read_only_deny_mutation" if certified_tool_ids and denied_tool_ids else "blocked",
            "decision_refs": ["mesh-approval://praxis-demo/read-only-approved", "mesh-approval://praxis-demo/mutation-denied"],
            "evidence_refs": [
                generated_contract["contract_id"],
                akto_evidence["evidence_id"],
                certification_binding["binding_id"],
            ],
        },
        "authority": {
            "akto_advisory_only": True,
            "acp_grants_runtime_authority": False,
            "mesh_owns_certification": True,
            "mesh_owns_revocation": True,
            "managed_runtime_deployed": False,
        },
        "checks": checks,
    }
    validate_payload(PRAXIS_E2E_PROOF_PACKET_SCHEMA, packet)
    return packet


def build_praxis_demo_proof_packet() -> dict[str, Any]:
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
    certification_binding = build_praxis_certification_binding(
        generated_contract=generated_contract,
        akto_evidence=akto_evidence,
        binding_id="praxis-certification-binding-demo-001",
        connector_id="praxis-demo-generated-mcp",
        acp_session_id="praxis-acp-session-demo-001",
        created_at="2026-05-20T05:00:25Z",
    )
    return build_praxis_e2e_proof_packet(
        source_bundle=source_bundle,
        generated_contract=generated_contract,
        akto_evidence=akto_evidence,
        certification_binding=certification_binding,
        packet_id="praxis-proof-packet-demo-001",
        generated_at="2026-05-20T05:00:30Z",
    )


def build_praxis_product_dashboard() -> dict[str, Any]:
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
    certification_binding = build_praxis_certification_binding(
        generated_contract=generated_contract,
        akto_evidence=akto_evidence,
        binding_id="praxis-certification-binding-demo-001",
        connector_id="praxis-demo-generated-mcp",
        acp_session_id="praxis-acp-session-demo-001",
        created_at="2026-05-20T05:00:25Z",
    )
    proof_packet = build_praxis_e2e_proof_packet(
        source_bundle=source_bundle,
        generated_contract=generated_contract,
        akto_evidence=akto_evidence,
        certification_binding=certification_binding,
        packet_id="praxis-proof-packet-demo-001",
        generated_at="2026-05-20T05:00:30Z",
    )
    bindings_by_tool = {
        str(binding["tool_candidate_id"]): binding
        for binding in certification_binding["tool_bindings"]
    }
    findings_by_tool = _open_findings_by_tool(akto_evidence)
    tool_rows = []
    for tool in generated_contract["tool_candidates"]:
        binding = bindings_by_tool.get(str(tool["tool_id"]), {})
        findings = findings_by_tool.get(str(tool["tool_id"]), [])
        tool_rows.append(
            {
                "tool_id": tool["tool_id"],
                "name": tool["name"],
                "description": tool["description"],
                "method": tool["endpoint"]["method"],
                "path": tool["endpoint"]["path"],
                "mutation_class": tool["mutation_class"],
                "approval_posture": tool["approval_posture"],
                "certification_result": binding.get("certification_result", "candidate"),
                "allowed_scopes": binding.get("allowed_scopes", []),
                "readiness_blockers": binding.get("readiness_blockers", tool.get("blockers", [])),
                "finding_count": len(findings),
                "source_evidence_refs": tool["source_evidence_refs"],
            }
        )
    return {
        "schema_version": "praxis.product_dashboard.v1",
        "state_slice": "praxis.pilot-runtime.v1",
        "status": "bounded_dry_run_ready" if proof_packet["status"] == "complete" else "blocked",
        "product_entrypoint": "meshapp.home.praxis",
        "summary": {
            "source_packets": len(source_bundle["source_packets"]),
            "tool_candidates": len(generated_contract["tool_candidates"]),
            "akto_findings": len(akto_evidence["findings"]),
            "certified_read_only_tools": len(proof_packet["mcp_readiness"]["certified_tool_ids"]),
            "denied_tools": len(proof_packet["mcp_readiness"]["denied_tool_ids"]),
        },
        "proof_packet": proof_packet,
        "source_bundle": {
            "bundle_id": source_bundle["bundle_id"],
            "redaction_status": source_bundle["redaction"]["status"],
            "raw_payload_stored": source_bundle["redaction"]["raw_payload_stored"],
            "packets": [
                {
                    "packet_id": packet["packet_id"],
                    "source_type": packet["source_type"],
                    "source_ref": packet["source_ref"],
                    "evidence_gaps": packet["evidence_gaps"],
                    "raw_credentials_present": packet["secret_scan"]["raw_credentials_present"],
                }
                for packet in source_bundle["source_packets"]
            ],
        },
        "generated_contract": {
            "contract_id": generated_contract["contract_id"],
            "generator_version": generated_contract["generator_version"],
            "tools": tool_rows,
        },
        "security_evidence": {
            "evidence_id": akto_evidence["evidence_id"],
            "source": akto_evidence["source"],
            "scan_status": akto_evidence["scan_status"],
            "live_dast_executed": akto_evidence["live_dast_executed"],
            "raw_traffic_stored": akto_evidence["raw_traffic_stored"],
            "findings": akto_evidence["findings"],
            "authority": akto_evidence["authority"],
        },
        "pilot_runtime": {
            "runtime_id": "praxis-demo-generated-mcp-dry-run",
            "connector_id": certification_binding["connector_id"],
            "status": proof_packet["mcp_readiness"]["status"],
            "dry_run_only": True,
            "managed_runtime_deployed": proof_packet["authority"]["managed_runtime_deployed"],
            "mcp_endpoint_ref": "mcp-dry-run://praxis-demo-generated-mcp",
            "credential_boundary": "runtime-secret://praxis/generated-mcp",
            "revocation_ref": certification_binding["revocation"]["revocation_ref"],
            "docker_dynamic_mcp_bridge": _docker_dynamic_mcp_bridge(
                runtime_status="running",
                connector_id=certification_binding["connector_id"],
            ),
            "controls": [
                {
                    "control_id": "start_dry_run",
                    "label": "Start dry-run MCP endpoint",
                    "state": "ready",
                    "requires_mesh_approval": False,
                },
                {
                    "control_id": "revoke_runtime",
                    "label": "Revoke generated connector",
                    "state": "ready",
                    "requires_mesh_approval": True,
                },
                {
                    "control_id": "deploy_managed_runtime",
                    "label": "Deploy managed pilot runtime",
                    "state": "blocked",
                    "requires_mesh_approval": True,
                    "reason": "Managed runtime deployment stays blocked until production-like proof, live target ownership, and credential rotation evidence exist.",
                },
            ],
        },
        "authority": {
            "mesh_owns_certification": True,
            "mesh_owns_approval": True,
            "mesh_owns_revocation": True,
            "akto_advisory_only": True,
            "acp_grants_runtime_authority": False,
            "generated_tools_are_candidates_until_certified": True,
        },
    }


class PraxisManagedRuntimeStore:
    """File-backed Praxis generation and dry-run runtime state."""

    def __init__(self, state_path: str | Path):
        self.path = Path(state_path)
        self.source_root = self.path.parent / "sources"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.source_root.mkdir(parents=True, exist_ok=True)

    def list_records(self, *, scope: dict[str, str] | None = None) -> dict[str, Any]:
        with LockedJsonFile(self.path) as payload:
            store = _managed_runtime_store(payload)
            records = []
            for record in store["records"].values():
                if not _record_in_scope(record, scope):
                    continue
                _ensure_docker_dynamic_mcp_bridge(record)
                records.append(_record_copy(record))
        records.sort(key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""), reverse=True)
        return {
            "schema_version": PRAXIS_MANAGED_DRY_RUN_RUNTIME_VERSION,
            "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
            "runs": [_record_summary(record) for record in records],
        }

    def get_record(self, request_id: str, *, scope: dict[str, str] | None = None) -> dict[str, Any] | None:
        with LockedJsonFile(self.path) as payload:
            store = _managed_runtime_store(payload)
            record = store["records"].get(request_id)
            if not record or not _record_in_scope(record, scope):
                return None
            _ensure_docker_dynamic_mcp_bridge(record)
            return _record_copy(record)

    def build_product_dashboard(self, *, scope: dict[str, str] | None = None) -> dict[str, Any]:
        with LockedJsonFile(self.path) as payload:
            store = _managed_runtime_store(payload)
            records = []
            for record in store["records"].values():
                if not _record_in_scope(record, scope):
                    continue
                _ensure_docker_dynamic_mcp_bridge(record)
                records.append(_record_copy(record))
        records.sort(key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""), reverse=True)
        latest = records[0] if records else None
        if latest is None:
            return _empty_product_dashboard(records=[])
        return _record_product_dashboard(latest, records=records)

    def create_generation_request(
        self,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        sources = payload.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("sources must be a non-empty list")
        now = _timestamp()
        request_id = _request_id(payload.get("request_id"))
        bundle_id = str(payload.get("bundle_id") or f"{request_id}-source-bundle")
        contract_id = str(payload.get("contract_id") or f"{request_id}-generated-contract")
        materialized_sources = self._materialize_sources(
            request_id=request_id,
            scope=scope,
            sources=sources,
        )
        source_bundle = build_praxis_source_bundle(
            bundle_id=bundle_id,
            tenant_id=scope["scope_id"],
            sources=materialized_sources,
            created_at=now,
        )
        generated_contract = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id=contract_id,
            generated_at=now,
            generator_version=str(payload.get("generator_version") or "praxis-contract-builder-product"),
        )
        record = {
            "schema_version": PRAXIS_MANAGED_DRY_RUN_RUNTIME_VERSION,
            "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
            "request_id": request_id,
            "created_at": now,
            "updated_at": now,
            "status": "candidate_generated",
            "owner_scope": dict(scope),
            "operator": _operator_ref(operator),
            "source_bundle": source_bundle,
            "generated_contract": generated_contract,
            "akto_evidence": None,
            "certification_binding": None,
            "proof_packet": None,
            "p10_proof_packet": None,
            "dry_run_runtime": _initial_dry_run_runtime(),
            "audit_events": [],
        }
        _append_praxis_event(
            record,
            event_type="praxis.generation_request_created",
            operator=operator,
            details={
                "source_bundle_id": source_bundle["bundle_id"],
                "generated_contract_id": generated_contract["contract_id"],
                "source_packet_count": len(source_bundle["source_packets"]),
            },
        )
        _refresh_p10_proof(record)
        with LockedJsonFile(self.path) as payload_data:
            store = _managed_runtime_store(payload_data)
            if request_id in store["records"]:
                raise ValueError(f"Praxis generation request already exists: {request_id}")
            store["records"][request_id] = record
        return _record_copy(record)

    def import_akto_evidence(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            evidence_id = str(payload.get("evidence_id") or f"{request_id}-akto-evidence")
            if isinstance(payload.get("akto_result"), dict):
                evidence = import_praxis_akto_security_evidence_payload(
                    akto_result_payload=payload["akto_result"],
                    generated_contract=record["generated_contract"],
                    evidence_id=evidence_id,
                    imported_at=_timestamp(),
                )
            else:
                akto_result_path = payload.get("akto_result_path")
                if not akto_result_path:
                    raise ValueError("akto_result_path or akto_result is required")
                evidence = import_praxis_akto_security_evidence(
                    akto_result_path=str(akto_result_path),
                    generated_contract=record["generated_contract"],
                    evidence_id=evidence_id,
                    imported_at=_timestamp(),
                )
            record["akto_evidence"] = evidence
            record["status"] = "security_evidence_imported"
            _append_praxis_event(
                record,
                event_type="praxis.akto_evidence_imported",
                operator=operator,
                details={
                    "evidence_id": evidence["evidence_id"],
                    "finding_count": len(evidence["findings"]),
                    "akto_advisory_only": True,
                },
            )

        return self._mutate_record(request_id, scope=scope, mutate=mutate)

    def build_certification_binding(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            evidence = record.get("akto_evidence")
            if not isinstance(evidence, dict):
                raise ValueError("Akto evidence must be imported before certification binding")
            binding = build_praxis_certification_binding(
                generated_contract=record["generated_contract"],
                akto_evidence=evidence,
                binding_id=str(payload.get("binding_id") or f"{request_id}-certification-binding"),
                connector_id=str(payload.get("connector_id") or f"{request_id}-generated-mcp"),
                acp_session_id=str(payload.get("acp_session_id") or f"{request_id}-operator-review"),
                created_at=_timestamp(),
            )
            record["certification_binding"] = binding
            record["proof_packet"] = build_praxis_e2e_proof_packet(
                source_bundle=record["source_bundle"],
                generated_contract=record["generated_contract"],
                akto_evidence=evidence,
                certification_binding=binding,
                packet_id=str(payload.get("packet_id") or f"{request_id}-certification-proof"),
                generated_at=_timestamp(),
            )
            record["dry_run_runtime"] = _dry_run_runtime_for_binding(binding, status="dry_run_ready")
            record["status"] = "certification_bound"
            _append_praxis_event(
                record,
                event_type="praxis.certification_binding_built",
                operator=operator,
                details={
                    "binding_id": binding["binding_id"],
                    "connector_id": binding["connector_id"],
                    "managed_runtime_deployed": False,
                },
            )

        return self._mutate_record(request_id, scope=scope, mutate=mutate)

    def start_dry_run_endpoint(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            binding = record.get("certification_binding")
            if not isinstance(binding, dict):
                raise ValueError("certification binding is required before dry-run start")
            certified = _certified_tool_ids(binding)
            if not certified:
                raise ValueError("at least one read-only certified tool is required before dry-run start")
            bridge_payload = payload.get("docker_dynamic_mcp_bridge")
            if bridge_payload is not None and not isinstance(bridge_payload, dict):
                raise ValueError("docker_dynamic_mcp_bridge must be an object")
            runtime = _dry_run_runtime_for_binding(binding, status="running")
            runtime["started_at"] = _timestamp()
            runtime["mcp_endpoint_ref"] = _dry_run_mcp_endpoint_ref(
                payload.get("mcp_endpoint_ref"),
                connector_id=str(binding["connector_id"]),
            )
            if payload.get("docker_dynamic_mcp_gateway_ref"):
                runtime["docker_dynamic_mcp_bridge"]["gateway_ref"] = _docker_dynamic_mcp_gateway_ref(
                    payload["docker_dynamic_mcp_gateway_ref"]
                )
            if isinstance(bridge_payload, dict):
                runtime["docker_dynamic_mcp_bridge"] = _validated_docker_dynamic_mcp_bridge_payload(
                    bridge_payload,
                    runtime_status="running",
                    connector_id=str(binding["connector_id"]),
                )
            record["dry_run_runtime"] = runtime
            record["status"] = "dry_run_running"
            _append_praxis_event(
                record,
                event_type="praxis.dry_run_endpoint_started",
                operator=operator,
                details={
                    "runtime_id": runtime["runtime_id"],
                    "mcp_endpoint_ref": runtime["mcp_endpoint_ref"],
                    "certified_tool_ids": certified,
                    "managed_runtime_deployed": False,
                },
            )

        return self._mutate_record(request_id, scope=scope, mutate=mutate)

    def call_dry_run_tool(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        call_result: dict[str, Any] = {}

        def mutate(record: dict[str, Any]) -> None:
            runtime = record.get("dry_run_runtime")
            if not isinstance(runtime, dict) or runtime.get("status") != "running":
                raise ValueError("dry-run endpoint is not running")
            tool_id = str(payload.get("tool_id") or "")
            if not tool_id:
                raise ValueError("tool_id is required")
            binding = _binding_for_tool(record.get("certification_binding"), tool_id)
            if binding is None:
                raise ValueError(f"tool not found in certification binding: {tool_id}")
            details = {
                "tool_id": tool_id,
                "arguments_sha256": _canonical_sha256(payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}),
                "side_effects_executed": False,
            }
            if binding["certification_result"] != "read_only":
                event = _append_praxis_event(
                    record,
                    event_type="praxis.dry_run_tool_call_denied",
                    operator=operator,
                    details={**details, "reason": "tool is not certified read-only"},
                )
                call_result.update(
                    {
                        "schema_version": "praxis.dry_run_tool_call.v1",
                        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
                        "request_id": request_id,
                        "tool_id": tool_id,
                        "status": "denied",
                        "allowed": False,
                        "reason": "tool is not certified read-only",
                        "audit_event_id": event["event_id"],
                        "side_effects_executed": False,
                    }
                )
                return
            event = _append_praxis_event(
                record,
                event_type="praxis.dry_run_tool_called",
                operator=operator,
                details={**details, "result_ref": f"dry-run-result://{request_id}/{tool_id}"},
            )
            call_result.update(
                {
                    "schema_version": "praxis.dry_run_tool_call.v1",
                    "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
                    "request_id": request_id,
                    "tool_id": tool_id,
                    "status": "simulated",
                    "allowed": True,
                    "result": {
                        "mode": "dry_run",
                        "endpoint": _tool_endpoint(record["generated_contract"], tool_id),
                        "side_effects_executed": False,
                    },
                    "audit_event_id": event["event_id"],
                    "side_effects_executed": False,
                }
            )

        self._mutate_record(request_id, scope=scope, mutate=mutate)
        return call_result

    def mcp_json_rpc(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        rpc_id = payload.get("id")
        method = str(payload.get("method") or "")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if payload.get("jsonrpc") != "2.0":
            return _mcp_error(rpc_id, -32600, "JSON-RPC 2.0 envelope is required")
        if method == "initialize":
            self._append_mcp_runtime_event(
                request_id,
                event_type="praxis.mcp_initialize",
                operator=operator,
                scope=scope,
                details={"protocol_version": str(params.get("protocolVersion") or "unknown")},
            )
            return _mcp_result(
                rpc_id,
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "praxis-managed-dry-run-runtime",
                        "version": PRAXIS_MANAGED_DRY_RUN_RUNTIME_VERSION,
                    },
                },
            )
        if method == "tools/list":
            record = self._running_mcp_record(request_id, scope=scope)
            self._append_mcp_runtime_event(
                request_id,
                event_type="praxis.mcp_tools_listed",
                operator=operator,
                scope=scope,
                details={"certified_tool_count": len(_certified_tool_ids(record["certification_binding"]))},
            )
            return _mcp_result(rpc_id, {"tools": _mcp_tools_for_record(record)})
        if method == "tools/call":
            tool_name = str(params.get("name") or params.get("tool_id") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            result = self.call_dry_run_tool(
                request_id,
                {"tool_id": tool_name, "arguments": arguments},
                operator=operator,
                scope=scope,
            )
            return _mcp_result(
                rpc_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}],
                    "isError": result.get("allowed") is not True,
                },
            )
        return _mcp_error(rpc_id, -32601, f"Unsupported Praxis MCP method: {method}")

    def revoke_generated_connector(
        self,
        request_id: str,
        payload: dict[str, Any],
        *,
        operator: dict[str, Any],
        scope: dict[str, str],
    ) -> dict[str, Any]:
        def mutate(record: dict[str, Any]) -> None:
            binding = record.get("certification_binding")
            if not isinstance(binding, dict):
                raise ValueError("certification binding is required before revocation")
            runtime = dict(record.get("dry_run_runtime") or _dry_run_runtime_for_binding(binding, status="dry_run_ready"))
            existing_bridge = runtime.get("docker_dynamic_mcp_bridge") if isinstance(runtime.get("docker_dynamic_mcp_bridge"), dict) else {}
            revoked_bridge = _docker_dynamic_mcp_bridge(runtime_status="revoked", connector_id=str(binding["connector_id"]))
            if existing_bridge.get("gateway_ref"):
                revoked_bridge["gateway_ref"] = existing_bridge["gateway_ref"]
            if existing_bridge.get("catalog_ref"):
                revoked_bridge["catalog_ref"] = existing_bridge["catalog_ref"]
            runtime.update(
                {
                    "status": "revoked",
                    "revoked_at": _timestamp(),
                    "revocation_reason": str(payload.get("reason") or "operator_revocation"),
                    "mcp_endpoint_ref": None,
                    "managed_runtime_deployed": False,
                    "docker_dynamic_mcp_bridge": revoked_bridge,
                    "controls": _dry_run_controls(status="revoked", connector_id=str(binding["connector_id"])),
                }
            )
            record["dry_run_runtime"] = runtime
            record["status"] = "revoked"
            _append_praxis_event(
                record,
                event_type="praxis.generated_connector_revoked",
                operator=operator,
                details={
                    "connector_id": binding["connector_id"],
                    "revocation_ref": binding["revocation"]["revocation_ref"],
                    "reason": runtime["revocation_reason"],
                },
            )

        return self._mutate_record(request_id, scope=scope, mutate=mutate)

    def export_p10_proof_packet(self, request_id: str, *, scope: dict[str, str]) -> dict[str, Any]:
        record = self.get_record(request_id, scope=scope)
        if record is None:
            raise KeyError(request_id)
        packet = record.get("p10_proof_packet")
        if not isinstance(packet, dict):
            raise ValueError("P10 proof packet has not been materialized")
        return _record_copy(packet)

    def _running_mcp_record(self, request_id: str, *, scope: dict[str, str]) -> dict[str, Any]:
        record = self.get_record(request_id, scope=scope)
        if record is None:
            raise KeyError(request_id)
        runtime = record.get("dry_run_runtime")
        if not isinstance(runtime, dict) or runtime.get("status") != "running":
            raise ValueError("dry-run MCP endpoint is not running")
        if not isinstance(record.get("certification_binding"), dict):
            raise ValueError("certification binding is required before MCP serving")
        return record

    def _append_mcp_runtime_event(
        self,
        request_id: str,
        *,
        event_type: str,
        operator: dict[str, Any],
        scope: dict[str, str],
        details: dict[str, Any],
    ) -> None:
        def mutate(record: dict[str, Any]) -> None:
            runtime = record.get("dry_run_runtime")
            if not isinstance(runtime, dict) or runtime.get("status") != "running":
                raise ValueError("dry-run MCP endpoint is not running")
            _append_praxis_event(record, event_type=event_type, operator=operator, details=details)

        self._mutate_record(request_id, scope=scope, mutate=mutate)

    def _mutate_record(
        self,
        request_id: str,
        *,
        scope: dict[str, str],
        mutate,
    ) -> dict[str, Any]:
        with LockedJsonFile(self.path) as payload:
            store = _managed_runtime_store(payload)
            record = store["records"].get(request_id)
            if not record or not _record_in_scope(record, scope):
                raise KeyError(request_id)
            mutate(record)
            record["updated_at"] = _timestamp()
            _ensure_docker_dynamic_mcp_bridge(record)
            _refresh_p10_proof(record)
            return _record_copy(record)

    def _materialize_sources(
        self,
        *,
        request_id: str,
        scope: dict[str, str],
        sources: list[Any],
    ) -> list[dict[str, str]]:
        materialized = []
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                raise ValueError("each source must be an object")
            source_type = str(source.get("source_type") or "").strip()
            if not source_type:
                raise ValueError("source_type is required")
            if source.get("source_ref"):
                materialized.append({"source_type": source_type, "source_ref": str(source["source_ref"])})
                continue
            if "content" not in source:
                raise ValueError("source_ref or content is required for each source")
            text = _source_content_text(source["content"])
            _reject_raw_secret_material(text, f"{request_id}:{source_type}")
            target = self._source_content_path(
                request_id=request_id,
                scope=scope,
                index=index,
                source_type=source_type,
                filename=str(source.get("filename") or source_type),
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            materialized.append({"source_type": source_type, "source_ref": str(target)})
        return materialized

    def _source_content_path(
        self,
        *,
        request_id: str,
        scope: dict[str, str],
        index: int,
        source_type: str,
        filename: str,
    ) -> Path:
        source_name = Path(filename).name
        stem = _slug(Path(source_name).stem or source_type) or _slug(source_type)
        suffix = Path(source_name).suffix or _source_suffix(source_type)
        return self.source_root / _slug(scope["scope_id"]) / _slug(request_id) / f"{index:02d}-{stem}{suffix}"


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _managed_runtime_store(payload: dict[str, Any]) -> dict[str, Any]:
    payload["schema_version"] = PRAXIS_MANAGED_DRY_RUN_RUNTIME_VERSION
    payload["state_slice"] = PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE
    if not isinstance(payload.get("records"), dict):
        payload["records"] = {}
    return payload


def _record_copy(record: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(record))


def _record_in_scope(record: dict[str, Any], scope: dict[str, str] | None) -> bool:
    if scope is None:
        return True
    owner_scope = record.get("owner_scope")
    return isinstance(owner_scope, dict) and owner_scope.get("scope_id") == scope.get("scope_id")


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    runtime = record.get("dry_run_runtime") if isinstance(record.get("dry_run_runtime"), dict) else {}
    proof = record.get("p10_proof_packet") if isinstance(record.get("p10_proof_packet"), dict) else {}
    contract = record.get("generated_contract") if isinstance(record.get("generated_contract"), dict) else {}
    bundle = record.get("source_bundle") if isinstance(record.get("source_bundle"), dict) else {}
    binding = record.get("certification_binding") if isinstance(record.get("certification_binding"), dict) else {}
    return {
        "request_id": record.get("request_id"),
        "state_slice": record.get("state_slice"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "owner_scope": record.get("owner_scope"),
        "source_bundle_id": bundle.get("bundle_id"),
        "generated_contract_id": contract.get("contract_id"),
        "connector_id": binding.get("connector_id") or runtime.get("connector_id"),
        "dry_run_status": runtime.get("status"),
        "mcp_endpoint_ref": runtime.get("mcp_endpoint_ref"),
        "managed_runtime_deployed": runtime.get("managed_runtime_deployed") is True,
        "certified_tool_count": len(runtime.get("certified_tool_ids") or []),
        "denied_tool_count": len(runtime.get("denied_tool_ids") or []),
        "audit_event_count": len(record.get("audit_events") or []),
        "p10_status": proof.get("status", "blocked"),
    }


def _empty_product_dashboard(*, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "praxis.product_dashboard.v1",
        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
        "status": "no_runs",
        "product_entrypoint": "meshapp.home.praxis",
        "summary": {
            "runs": len(records),
            "source_packets": 0,
            "tool_candidates": 0,
            "akto_findings": 0,
            "certified_read_only_tools": 0,
            "denied_tools": 0,
            "audit_events": 0,
        },
        "runs": [_record_summary(record) for record in records],
        "proof_packet": {"status": "not_started", "checks": {}},
        "p10_proof_packet": {"status": "not_started", "checks": {}},
        "source_bundle": {
            "bundle_id": None,
            "redaction_status": "not_started",
            "raw_payload_stored": False,
            "packets": [],
        },
        "generated_contract": {
            "contract_id": None,
            "generator_version": None,
            "tools": [],
        },
        "security_evidence": {
            "evidence_id": None,
            "source": None,
            "scan_status": "not_run",
            "live_dast_executed": False,
            "raw_traffic_stored": False,
            "findings": [],
            "authority": {
                "advisory_only": True,
                "grants_policy_authority": False,
                "grants_certification": False,
            },
        },
        "pilot_runtime": _initial_dry_run_runtime(),
        "authority": _product_authority(),
    }


def _record_product_dashboard(record: dict[str, Any], *, records: list[dict[str, Any]]) -> dict[str, Any]:
    source_bundle = record["source_bundle"]
    generated_contract = record["generated_contract"]
    akto_evidence = record.get("akto_evidence") if isinstance(record.get("akto_evidence"), dict) else None
    proof_packet = record.get("proof_packet") if isinstance(record.get("proof_packet"), dict) else {"status": "not_ready", "checks": {}}
    runtime = record.get("dry_run_runtime") if isinstance(record.get("dry_run_runtime"), dict) else _initial_dry_run_runtime()
    tools = _dashboard_tool_rows(generated_contract, record.get("certification_binding"), akto_evidence)
    return {
        "schema_version": "praxis.product_dashboard.v1",
        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
        "status": record.get("status", "unknown"),
        "product_entrypoint": "meshapp.home.praxis",
        "summary": {
            "runs": len(records),
            "source_packets": len(source_bundle["source_packets"]),
            "tool_candidates": len(generated_contract["tool_candidates"]),
            "akto_findings": len(akto_evidence["findings"]) if akto_evidence else 0,
            "certified_read_only_tools": len(runtime.get("certified_tool_ids") or []),
            "denied_tools": len(runtime.get("denied_tool_ids") or []),
            "audit_events": len(record.get("audit_events") or []),
        },
        "runs": [_record_summary(item) for item in records],
        "proof_packet": proof_packet,
        "p10_proof_packet": record.get("p10_proof_packet") or {"status": "blocked", "checks": {}},
        "source_bundle": {
            "bundle_id": source_bundle["bundle_id"],
            "redaction_status": source_bundle["redaction"]["status"],
            "raw_payload_stored": source_bundle["redaction"]["raw_payload_stored"],
            "packets": [
                {
                    "packet_id": packet["packet_id"],
                    "source_type": packet["source_type"],
                    "source_ref": packet["source_ref"],
                    "evidence_gaps": packet["evidence_gaps"],
                    "raw_credentials_present": packet["secret_scan"]["raw_credentials_present"],
                }
                for packet in source_bundle["source_packets"]
            ],
        },
        "generated_contract": {
            "contract_id": generated_contract["contract_id"],
            "generator_version": generated_contract["generator_version"],
            "tools": tools,
        },
        "security_evidence": {
            "evidence_id": akto_evidence["evidence_id"] if akto_evidence else None,
            "source": akto_evidence["source"] if akto_evidence else None,
            "scan_status": akto_evidence["scan_status"] if akto_evidence else "not_run",
            "live_dast_executed": False,
            "raw_traffic_stored": False,
            "findings": akto_evidence["findings"] if akto_evidence else [],
            "authority": akto_evidence["authority"] if akto_evidence else {
                "advisory_only": True,
                "grants_policy_authority": False,
                "grants_certification": False,
            },
        },
        "pilot_runtime": runtime,
        "authority": _product_authority(),
    }


def _dashboard_tool_rows(
    generated_contract: dict[str, Any],
    certification_binding: Any,
    akto_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    bindings_by_tool = {}
    if isinstance(certification_binding, dict):
        bindings_by_tool = {
            str(binding["tool_candidate_id"]): binding
            for binding in certification_binding.get("tool_bindings", [])
            if isinstance(binding, dict)
        }
    findings_by_tool = _open_findings_by_tool(akto_evidence or {})
    rows = []
    for tool in generated_contract.get("tool_candidates", []):
        binding = bindings_by_tool.get(str(tool["tool_id"]), {})
        findings = findings_by_tool.get(str(tool["tool_id"]), [])
        rows.append(
            {
                "tool_id": tool["tool_id"],
                "name": tool["name"],
                "description": tool["description"],
                "method": tool["endpoint"]["method"],
                "path": tool["endpoint"]["path"],
                "mutation_class": tool["mutation_class"],
                "approval_posture": tool["approval_posture"],
                "certification_result": binding.get("certification_result", "candidate"),
                "allowed_scopes": binding.get("allowed_scopes", []),
                "readiness_blockers": binding.get("readiness_blockers", tool.get("blockers", [])),
                "finding_count": len(findings),
                "source_evidence_refs": tool["source_evidence_refs"],
            }
        )
    return rows


def _product_authority() -> dict[str, bool]:
    return {
        "mesh_owns_certification": True,
        "mesh_owns_approval": True,
        "mesh_owns_revocation": True,
        "akto_advisory_only": True,
        "acp_grants_runtime_authority": False,
        "generated_tools_are_candidates_until_certified": True,
    }


def _request_id(raw: Any) -> str:
    if raw:
        cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(raw)).strip("-")
        if cleaned:
            return cleaned
    return f"praxis-request-{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def _operator_ref(operator: dict[str, Any]) -> dict[str, Any]:
    return {
        "operator_id": operator.get("operator_id") or "unknown",
        "user_id": operator.get("user_id"),
        "team_id": operator.get("team_id"),
        "roles": sorted(operator.get("roles") or []),
        "source": operator.get("source") or "unknown",
    }


def _append_praxis_event(
    record: dict[str, Any],
    *,
    event_type: str,
    operator: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    events = record.setdefault("audit_events", [])
    event = {
        "event_id": f"praxis-event-{len(events) + 1:06d}",
        "timestamp": _timestamp(),
        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
        "request_id": record.get("request_id"),
        "event_type": event_type,
        "operator": _operator_ref(operator),
        "details": details,
    }
    events.append(event)
    return event


def _refresh_p10_proof(record: dict[str, Any]) -> None:
    events = record.get("audit_events") or []
    event_types = {event.get("event_type") for event in events if isinstance(event, dict)}
    runtime = record.get("dry_run_runtime") if isinstance(record.get("dry_run_runtime"), dict) else {}
    bridge = runtime.get("docker_dynamic_mcp_bridge") if isinstance(runtime.get("docker_dynamic_mcp_bridge"), dict) else {}
    checks = {
        "source_upload_bound": isinstance(record.get("source_bundle"), dict),
        "generated_tools_bound": bool((record.get("generated_contract") or {}).get("tool_candidates")),
        "security_evidence_bound": isinstance(record.get("akto_evidence"), dict),
        "certification_binding_bound": isinstance(record.get("certification_binding"), dict),
        "dry_run_mcp_endpoint_started": "praxis.dry_run_endpoint_started" in event_types,
        "dry_run_endpoint_ref_bound": (
            runtime.get("mcp_endpoint_ref") is None
            or str(runtime.get("mcp_endpoint_ref") or "").startswith("mcp-dry-run://")
        ),
        "tool_call_audit_event_bound": "praxis.dry_run_tool_called" in event_types,
        "revocation_bound": "praxis.generated_connector_revoked" in event_types,
        "managed_runtime_deploy_blocked": runtime.get("managed_runtime_deployed") is False,
        "docker_dynamic_mcp_bridge_bound": _docker_dynamic_mcp_bridge_is_bound(bridge),
        "docker_gateway_ref_bound": str(bridge.get("gateway_ref") or "").startswith("docker-mcp-gateway://"),
        "dynamic_servers_session_scoped": bridge.get("session_only") is True,
        "dynamic_profile_persistence_blocked": bridge.get("profile_persisted") is False,
        "docker_code_mode_blocked": bridge.get("code_mode_enabled") is False and "code-mode" in set(bridge.get("blocked_management_tools") or []),
        "bridge_catalog_allowlist_bound": bool(bridge.get("allowed_server_ids")),
    }
    record["p10_proof_packet"] = {
        "schema_version": "praxis.managed_dry_run_proof_packet.v1",
        "packet_id": f"{record.get('request_id')}-p10-proof-packet",
        "generated_at": _timestamp(),
        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
        "status": "complete" if all(checks.values()) else "blocked",
        "request_id": record.get("request_id"),
        "source_bundle_id": (record.get("source_bundle") or {}).get("bundle_id"),
        "generated_contract_id": (record.get("generated_contract") or {}).get("contract_id"),
        "akto_evidence_id": (record.get("akto_evidence") or {}).get("evidence_id"),
        "certification_binding_id": (record.get("certification_binding") or {}).get("binding_id"),
        "dry_run_runtime": runtime,
        "audit_event_ids": [event.get("event_id") for event in events if isinstance(event, dict)],
        "checks": checks,
        "authority": {
            "akto_advisory_only": True,
            "mesh_owns_certification": True,
            "mesh_owns_revocation": True,
            "managed_runtime_deployed": runtime.get("managed_runtime_deployed") is True,
        },
    }


def _initial_dry_run_runtime() -> dict[str, Any]:
    return {
        "runtime_id": None,
        "connector_id": None,
        "status": "not_started",
        "dry_run_only": True,
        "managed_runtime_deployed": False,
        "mcp_endpoint_ref": None,
        "credential_boundary": "runtime-secret://praxis/generated-mcp",
        "revocation_ref": None,
        "certified_tool_ids": [],
        "denied_tool_ids": [],
        "approval_required_tool_ids": [],
        "docker_dynamic_mcp_bridge": _docker_dynamic_mcp_bridge(runtime_status="not_started", connector_id=None),
        "controls": _dry_run_controls(status="not_started", connector_id=None),
    }


def _dry_run_runtime_for_binding(certification_binding: dict[str, Any], *, status: str) -> dict[str, Any]:
    connector_id = str(certification_binding["connector_id"])
    return {
        "runtime_id": f"{connector_id}-dry-run",
        "connector_id": connector_id,
        "status": status,
        "dry_run_only": True,
        "managed_runtime_deployed": False,
        "mcp_endpoint_ref": f"mcp-dry-run://{connector_id}" if status == "running" else None,
        "credential_boundary": "runtime-secret://praxis/generated-mcp",
        "revocation_ref": certification_binding["revocation"]["revocation_ref"],
        "certified_tool_ids": _certified_tool_ids(certification_binding),
        "denied_tool_ids": _denied_tool_ids(certification_binding),
        "approval_required_tool_ids": _approval_required_tool_ids(certification_binding),
        "docker_dynamic_mcp_bridge": _docker_dynamic_mcp_bridge(runtime_status=status, connector_id=connector_id),
        "controls": _dry_run_controls(status=status, connector_id=connector_id),
    }


def _docker_dynamic_mcp_bridge(*, runtime_status: str, connector_id: str | None) -> dict[str, Any]:
    bridge_status = "not_started"
    if runtime_status == "dry_run_ready":
        bridge_status = "ready"
    elif runtime_status == "running":
        bridge_status = "active"
    elif runtime_status == "revoked":
        bridge_status = "revoked"
    allowed_server_ids = [connector_id] if connector_id else []
    return {
        "schema_version": PRAXIS_DOCKER_DYNAMIC_MCP_BRIDGE_VERSION,
        "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
        "status": bridge_status,
        "provider": "docker_mcp_toolkit",
        "catalog": "docker_mcp_catalog",
        "catalog_ref": "docker-mcp-catalog://default",
        "documentation_ref": DOCKER_DYNAMIC_MCP_DOC_URL,
        "gateway_ref": "docker-mcp-gateway://current-session",
        "session_only": True,
        "profile_persisted": False,
        "connector_ref": connector_id,
        "allowed_server_ids": allowed_server_ids,
        "allowed_management_tools": list(_DOCKER_DYNAMIC_MCP_ALLOWED_TOOLS),
        "blocked_management_tools": list(_DOCKER_DYNAMIC_MCP_BLOCKED_TOOLS),
        "code_mode_enabled": False,
        "credentials_boundary": "docker-mcp-gateway://credentials",
        "side_effects_executed": False,
        "management_tools": [
            {
                "name": tool_name,
                "scope": "session_management" if tool_name != "code-mode" else "sandboxed_composition",
                "enabled": tool_name in _DOCKER_DYNAMIC_MCP_ALLOWED_TOOLS,
            }
            for tool_name in _DOCKER_DYNAMIC_MCP_MANAGEMENT_TOOLS
        ],
        "prerequisites": [
            "Docker Desktop 4.50 or later",
            "Docker MCP Toolkit enabled",
            "MCP client connected to the Docker MCP Gateway",
            "dynamic-tools feature enabled",
        ],
        "security": {
            "catalog_servers_built_signed_maintained_by_docker": True,
            "servers_run_in_isolated_containers": True,
            "restricted_container_resources": True,
            "gateway_managed_credentials": True,
            "code_mode_isolated_sandbox": True,
        },
        "authority": {
            "mesh_owns_certification": True,
            "mesh_owns_revocation": True,
            "docker_dynamic_mcp_grants_runtime_authority": False,
            "dynamically_added_servers_are_candidates_until_certified": True,
        },
    }


def _dry_run_mcp_endpoint_ref(value: Any, *, connector_id: str) -> str:
    endpoint_ref = str(value or f"mcp-dry-run://{connector_id}")
    if not endpoint_ref.startswith("mcp-dry-run://"):
        raise ValueError("mcp_endpoint_ref must use mcp-dry-run://")
    return endpoint_ref


def _docker_dynamic_mcp_gateway_ref(value: Any) -> str:
    gateway_ref = str(value or "")
    if not gateway_ref.startswith("docker-mcp-gateway://"):
        raise ValueError("docker_dynamic_mcp_gateway_ref must use docker-mcp-gateway://")
    return gateway_ref


def _validated_docker_dynamic_mcp_bridge_payload(
    payload: dict[str, Any],
    *,
    runtime_status: str,
    connector_id: str,
) -> dict[str, Any]:
    bridge = _docker_dynamic_mcp_bridge(runtime_status=runtime_status, connector_id=connector_id)
    if payload.get("session_only") is False:
        raise ValueError("Docker Dynamic MCP bridge must be session scoped")
    if payload.get("profile_persisted") is True or payload.get("persists_to_profile") is True:
        raise ValueError("Docker Dynamic MCP bridge must not persist dynamic servers to a profile")
    if payload.get("code_mode_enabled") is True:
        raise ValueError("Docker Dynamic MCP code-mode is blocked for Praxis dry-run runtime")
    if payload.get("gateway_ref"):
        gateway_ref = str(payload["gateway_ref"])
        if not gateway_ref.startswith("docker-mcp-gateway://"):
            raise ValueError("docker_dynamic_mcp_bridge.gateway_ref must use docker-mcp-gateway://")
        bridge["gateway_ref"] = gateway_ref
    if payload.get("catalog_ref"):
        catalog_ref = str(payload["catalog_ref"])
        if not catalog_ref.startswith("docker-mcp-catalog://"):
            raise ValueError("docker_dynamic_mcp_bridge.catalog_ref must use docker-mcp-catalog://")
        bridge["catalog_ref"] = catalog_ref
    if "allowed_server_ids" in payload:
        allowed = payload["allowed_server_ids"]
        if not isinstance(allowed, list) or any(not isinstance(item, str) or not item for item in allowed):
            raise ValueError("docker_dynamic_mcp_bridge.allowed_server_ids must be a list of strings")
        if connector_id not in set(allowed):
            raise ValueError("Docker Dynamic MCP bridge must allowlist the generated connector id")
        bridge["allowed_server_ids"] = sorted(set(allowed))
    return bridge


def _ensure_docker_dynamic_mcp_bridge(record: dict[str, Any]) -> None:
    runtime = record.get("dry_run_runtime")
    if not isinstance(runtime, dict):
        return
    bridge = runtime.get("docker_dynamic_mcp_bridge")
    if isinstance(bridge, dict) and _docker_dynamic_mcp_bridge_is_bound(bridge):
        return
    runtime["docker_dynamic_mcp_bridge"] = _docker_dynamic_mcp_bridge(
        runtime_status=str(runtime.get("status") or "not_started"),
        connector_id=runtime.get("connector_id") if runtime.get("connector_id") else None,
    )


def _docker_dynamic_mcp_bridge_is_bound(bridge: dict[str, Any]) -> bool:
    authority = bridge.get("authority") if isinstance(bridge.get("authority"), dict) else {}
    tools = bridge.get("management_tools") if isinstance(bridge.get("management_tools"), list) else []
    tool_names = {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
    blocked = set(bridge.get("blocked_management_tools") if isinstance(bridge.get("blocked_management_tools"), list) else [])
    return (
        bridge.get("schema_version") == PRAXIS_DOCKER_DYNAMIC_MCP_BRIDGE_VERSION
        and bridge.get("state_slice") == PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE
        and bridge.get("provider") == "docker_mcp_toolkit"
        and bridge.get("session_only") is True
        and bridge.get("profile_persisted") is False
        and bridge.get("code_mode_enabled") is False
        and set(_DOCKER_DYNAMIC_MCP_MANAGEMENT_TOOLS).issubset(tool_names)
        and set(_DOCKER_DYNAMIC_MCP_BLOCKED_TOOLS).issubset(blocked)
        and authority.get("docker_dynamic_mcp_grants_runtime_authority") is False
    )


def _dry_run_controls(*, status: str, connector_id: str | None) -> list[dict[str, Any]]:
    start_state = "blocked"
    start_reason = "Certification binding is required before dry-run start."
    if status == "dry_run_ready":
        start_state = "ready"
        start_reason = "Read-only certification is bound; local MCP dry-run can start."
    elif status == "running":
        start_state = "running"
        start_reason = "Local dry-run MCP endpoint is active."
    elif status == "revoked":
        start_reason = "Generated connector has been revoked."
    revoke_state = "blocked"
    revoke_reason = "No generated connector is bound."
    if connector_id and status in {"dry_run_ready", "running"}:
        revoke_state = "ready"
        revoke_reason = "Mesh can revoke the generated connector and deactivate the endpoint."
    elif connector_id and status == "revoked":
        revoke_state = "complete"
        revoke_reason = "Generated connector has been revoked."
    return [
        {
            "control_id": "start_dry_run",
            "label": "Start dry-run MCP endpoint",
            "state": start_state,
            "requires_mesh_approval": False,
            "reason": start_reason,
        },
        {
            "control_id": "revoke_runtime",
            "label": "Revoke generated connector",
            "state": revoke_state,
            "requires_mesh_approval": True,
            "reason": revoke_reason,
        },
        {
            "control_id": "deploy_managed_runtime",
            "label": "Deploy managed pilot runtime",
            "state": "blocked",
            "requires_mesh_approval": True,
            "reason": "Managed runtime deployment stays blocked until production-like proof, live target ownership, and credential rotation evidence exist.",
        },
    ]


def _certified_tool_ids(certification_binding: dict[str, Any]) -> list[str]:
    return sorted(
        str(binding["tool_candidate_id"])
        for binding in certification_binding.get("tool_bindings", [])
        if isinstance(binding, dict) and binding.get("certification_result") == "read_only"
    )


def _denied_tool_ids(certification_binding: dict[str, Any]) -> list[str]:
    return sorted(
        str(binding["tool_candidate_id"])
        for binding in certification_binding.get("tool_bindings", [])
        if isinstance(binding, dict) and binding.get("certification_result") == "denied"
    )


def _approval_required_tool_ids(certification_binding: dict[str, Any]) -> list[str]:
    return sorted(
        str(binding["tool_candidate_id"])
        for binding in certification_binding.get("tool_bindings", [])
        if isinstance(binding, dict) and binding.get("certification_result") == "approval_required"
    )


def _binding_for_tool(certification_binding: Any, tool_id: str) -> dict[str, Any] | None:
    if not isinstance(certification_binding, dict):
        return None
    for binding in certification_binding.get("tool_bindings", []):
        if isinstance(binding, dict) and binding.get("tool_candidate_id") == tool_id:
            return binding
    return None


def _tool_endpoint(generated_contract: dict[str, Any], tool_id: str) -> dict[str, Any]:
    for tool in generated_contract.get("tool_candidates", []):
        if isinstance(tool, dict) and tool.get("tool_id") == tool_id:
            return {
                "method": tool["endpoint"]["method"],
                "path": tool["endpoint"]["path"],
                "mutation_class": tool["mutation_class"],
            }
    return {}


def _mcp_result(rpc_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _mcp_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _mcp_tools_for_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    certified = set(_certified_tool_ids(record["certification_binding"]))
    tools = []
    for tool in record["generated_contract"].get("tool_candidates", []):
        if not isinstance(tool, dict) or str(tool.get("tool_id")) not in certified:
            continue
        endpoint = tool.get("endpoint") if isinstance(tool.get("endpoint"), dict) else {}
        tools.append(
            {
                "name": str(tool["tool_id"]),
                "description": str(tool.get("description") or tool.get("name") or tool["tool_id"]),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "dry_run_reason": {
                            "type": "string",
                            "description": "Operator reason for exercising this certified dry-run tool.",
                        }
                    },
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                    "title": str(tool.get("name") or tool["tool_id"]),
                },
                "praxis": {
                    "method": str(endpoint.get("method") or "GET"),
                    "path": str(endpoint.get("path") or "/"),
                    "state_slice": PRAXIS_MANAGED_DRY_RUN_RUNTIME_STATE_SLICE,
                },
            }
        )
    return tools


def _source_content_text(content: Any) -> str:
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2, sort_keys=True) + "\n"
    return str(content)


def _source_suffix(source_type: str) -> str:
    if source_type == "sop_markdown":
        return ".md"
    return ".json"


def _tool_certification_binding(tool: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    mutation_class = str(tool["mutation_class"])
    high_or_critical = [finding for finding in findings if finding["severity"] in {"high", "critical"} and finding["status"] == "open"]
    blockers = list(tool.get("blockers", []))
    if high_or_critical:
        blockers.append("akto_high_or_critical_finding_open")
    if mutation_class == "read_only" and not high_or_critical:
        result = "read_only"
        allowed_scopes = list(tool["auth_scope"]["allowed_scopes"])
        blockers = [blocker for blocker in blockers if blocker not in {"connector_certification_missing"}]
    elif mutation_class == "read_only":
        result = "denied"
        allowed_scopes = []
    elif high_or_critical:
        result = "denied"
        allowed_scopes = []
    else:
        result = "approval_required"
        allowed_scopes = []
        blockers.append("operator_approval_required_before_execution")
    return {
        "tool_candidate_id": str(tool["tool_id"]),
        "requested_scope": str(tool["auth_scope"]["scope_id"]),
        "mutation_class": mutation_class,
        "certification_result": result,
        "allowed_scopes": allowed_scopes,
        "readiness_blockers": sorted(set(blockers)),
        "evidence_refs": list(tool["source_evidence_refs"]),
    }


def _open_findings_by_tool(akto_evidence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    findings: dict[str, list[dict[str, Any]]] = {}
    for finding in akto_evidence.get("findings", []):
        if not isinstance(finding, dict) or finding.get("status") != "open":
            continue
        for tool_id in finding.get("tool_candidate_ids", []):
            findings.setdefault(str(tool_id), []).append(finding)
    return findings


def _akto_inventory_record(item: dict[str, Any], tool_ids_by_endpoint: dict[tuple[str, str], list[str]]) -> dict[str, Any]:
    method = str(item["method"]).upper()
    path = str(item["path"])
    return {
        "endpoint_id": str(item["endpoint_id"]),
        "method": method,
        "path": path,
        "source_packet_id": str(item["source_packet_id"]),
        "tool_candidate_ids": tool_ids_by_endpoint.get((method, path), []),
    }


def _akto_finding_record(item: dict[str, Any], tool_ids_by_endpoint: dict[tuple[str, str], list[str]]) -> dict[str, Any]:
    endpoint_ids = [str(endpoint_id) for endpoint_id in item.get("affected_endpoint_ids", [])]
    tool_ids = [str(tool_id) for tool_id in item.get("tool_candidate_ids", [])]
    if not tool_ids:
        for endpoint in item.get("affected_endpoints", []):
            if isinstance(endpoint, dict):
                tool_ids.extend(tool_ids_by_endpoint.get((str(endpoint.get("method", "")).upper(), str(endpoint.get("path", ""))), []))
    return {
        "finding_id": str(item["finding_id"]),
        "severity": str(item["severity"]),
        "status": str(item["status"]),
        "summary": str(item["summary"]),
        "affected_endpoint_ids": endpoint_ids,
        "tool_candidate_ids": sorted(set(tool_ids)),
        "evidence_ref": str(item["evidence_ref"]),
        "remediation_ref": item.get("remediation_ref"),
    }


def _tool_ids_by_endpoint(generated_contract: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    mapping: dict[tuple[str, str], list[str]] = {}
    for tool in generated_contract.get("tool_candidates", []):
        if not isinstance(tool, dict):
            continue
        endpoint = tool.get("endpoint", {})
        if not isinstance(endpoint, dict):
            continue
        key = (str(endpoint.get("method", "")).upper(), str(endpoint.get("path", "")))
        mapping.setdefault(key, []).append(str(tool["tool_id"]))
    return mapping


def _tool_candidate_from_openapi_endpoint(
    *,
    openapi_packet: dict[str, Any],
    path: str,
    method: str,
    operation: dict[str, Any],
    sop_hints: list[str],
) -> dict[str, Any]:
    http_method = method.upper()
    mutation_class = _mutation_class(http_method)
    approval_posture = "read_only" if mutation_class == "read_only" else "denied"
    operation_id = str(operation.get("operationId") or f"{method}_{path.strip('/').replace('/', '_')}")
    source_ref = str(openapi_packet["source_ref"])
    source_evidence_ref = f"source://openapi/{source_ref}#paths.{path}.{method}"
    tool_id = f"tool.{_slug(operation_id)}"
    blockers = ["connector_certification_missing"]
    if mutation_class != "read_only":
        blockers.extend(["mutation_scope_not_certified", "operator_approval_missing"])
    return {
        "tool_id": tool_id,
        "name": _slug(operation_id).replace("-", "_"),
        "description": str(operation.get("summary") or operation_id),
        "endpoint": {
            "method": http_method,
            "path": path,
            "source_packet_id": str(openapi_packet["packet_id"]),
        },
        "args_schema": _args_schema_from_operation(operation),
        "auth_scope": {
            "scope_id": _scope_id(path, mutation_class),
            "credential_ref": "runtime-secret://praxis/generated-mcp",
            "allowed_scopes": [_scope_id(path, mutation_class)] if mutation_class == "read_only" else [],
            "raw_credentials_present": False,
        },
        "mutation_class": mutation_class,
        "approval_posture": approval_posture,
        "workflow_hints": _workflow_hints(path=path, mutation_class=mutation_class, sop_hints=sop_hints),
        "test_plan": {
            "fixture_refs": [
                "fixtures/praxis/demo-openapi.redacted.json",
                "fixtures/praxis/demo-postman.redacted.json",
                "fixtures/praxis/demo-sop.redacted.md",
                "fixtures/praxis/demo-traffic-ref.redacted.json",
            ],
            "negative_cases": _negative_cases(mutation_class),
            "requires_live_target": False,
        },
        "source_evidence_refs": [source_evidence_ref],
        "certification_state": "candidate",
        "blockers": blockers,
    }


def _args_schema_from_operation(operation: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name") or "")
        if not name:
            continue
        schema = parameter.get("schema") if isinstance(parameter.get("schema"), dict) else {"type": "string"}
        properties[name] = schema
        if parameter.get("required") is True:
            required.append(name)
    args_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        args_schema["required"] = required
    return args_schema


def _first_packet(source_bundle: dict[str, Any], source_type: str) -> dict[str, Any] | None:
    for packet in source_bundle.get("source_packets", []):
        if isinstance(packet, dict) and packet.get("source_type") == source_type:
            return packet
    return None


def _mutation_class(method: str) -> str:
    if method == "GET":
        return "read_only"
    if method in {"PUT", "PATCH"}:
        return "idempotent_write"
    if method == "DELETE":
        return "destructive_mutation"
    return "mutation"


def _scope_id(path: str, mutation_class: str) -> str:
    resource = path.strip("/").split("/", 1)[0] or "root"
    suffix = "read" if mutation_class == "read_only" else "write"
    return f"{resource}.{suffix}"


def _workflow_hints(*, path: str, mutation_class: str, sop_hints: list[str]) -> list[str]:
    hints = ["generated_from_openapi", "source_evidence_required"]
    if mutation_class != "read_only":
        hints.extend(["requires_mesh_connector_certification", "requires_operator_approval"])
    if any(path in hint for hint in sop_hints):
        hints.append("sop_mentions_endpoint")
    return hints


def _negative_cases(mutation_class: str) -> list[str]:
    cases = ["reject_raw_credentials", "block_missing_source_evidence"]
    if mutation_class != "read_only":
        cases.append("mutation_defaults_denied")
    return cases


def _sop_workflow_hints(source_bundle: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for packet in source_bundle.get("source_packets", []):
        if not isinstance(packet, dict) or packet.get("source_type") != "sop_markdown":
            continue
        text = _resolve_package_path(str(packet["source_ref"])).read_text(encoding="utf-8")
        hints.extend(line.strip() for line in text.splitlines() if line.strip())
    return hints


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _source_packet(*, index: int, source: dict[str, str]) -> dict[str, Any]:
    source_type = str(source["source_type"])
    source_ref = str(source["source_ref"])
    path = _resolve_package_path(source_ref)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    _reject_raw_secret_material(text, source_ref)
    redacted_fields = _redacted_fields_for_source(source_type, text)
    packet = {
        "packet_id": f"src-{source_type.replace('_', '-')}-{index}",
        "source_type": source_type,
        "source_ref": source_ref,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "citation_refs": _citation_refs(source_type, source_ref, text),
        "extracted_at": "2026-05-20T05:00:05Z",
        "evidence_gaps": _evidence_gaps(source_type, text),
        "secret_scan": {
            "status": "pass",
            "raw_credentials_present": False,
            "redacted_fields": redacted_fields,
        },
    }
    return packet


def _citation_refs(source_type: str, source_ref: str, text: str) -> list[str]:
    if source_type == "openapi":
        payload = json.loads(text)
        refs = []
        for path, methods in sorted(payload.get("paths", {}).items()):
            if isinstance(methods, dict):
                refs.extend(f"source://openapi/{source_ref}#paths.{path}.{method}" for method in sorted(methods))
        return refs
    if source_type == "postman_json":
        payload = json.loads(text)
        return [
            f"source://postman/{source_ref}#item.{index}.{item.get('name', 'request')}"
            for index, item in enumerate(payload.get("item", []))
            if isinstance(item, dict)
        ]
    if source_type == "sop_markdown":
        headings = [line.lstrip("# ").strip().replace(" ", "-").lower() for line in text.splitlines() if line.startswith("#")]
        return [f"source://sop/{source_ref}#{heading}" for heading in headings] or [f"source://sop/{source_ref}"]
    if source_type == "redacted_traffic_ref":
        payload = json.loads(text)
        return [f"source://traffic/{source_ref}#{payload.get('capture_id', 'capture')}"]
    return [f"source://{source_type}/{source_ref}"]


def _evidence_gaps(source_type: str, text: str) -> list[str]:
    if source_type == "sop_markdown":
        return ["sop_is_policy_context_not_behavior_proof"]
    if source_type == "redacted_traffic_ref" and json.loads(text).get("raw_traffic_stored") is False:
        return ["raw_traffic_not_stored_by_design"]
    return []


def _redacted_fields_for_source(source_type: str, text: str) -> list[str]:
    redacted_fields: set[str] = set()
    if "Authorization: REDACTED" in text or '"key": "Authorization"' in text:
        redacted_fields.add("Authorization")
    if "Cookie" in text:
        redacted_fields.add("Cookie")
    if source_type == "redacted_traffic_ref":
        payload = json.loads(text)
        redacted_fields.update(str(field) for field in payload.get("redacted_fields", []))
    return sorted(redacted_fields)


def _reject_raw_secret_material(text: str, source_ref: str) -> None:
    if _SECRET_VALUE_RE.search(text):
        raise SchemaValidationError(f"{source_ref}: raw secret-like value is forbidden")
    for match in _RAW_SECRET_KEY_RE.finditer(text):
        prefix = text[max(0, match.start() - 80) : match.start()]
        window = text[match.end() : match.end() + 80]
        if "redacted_fields" in prefix:
            continue
        if "REDACTED" not in window and "env" not in window.lower() and "environment variable" not in window.lower():
            raise SchemaValidationError(f"{source_ref}: possible unredacted credential field near {match.group(0)!r}")


def _reject_raw_secret_values(text: str, source_ref: str) -> None:
    if _SECRET_VALUE_RE.search(text):
        raise SchemaValidationError(f"{source_ref}: raw secret-like value is forbidden")


def _resolve_package_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    package_candidate = _PACKAGE_ROOT / candidate
    if package_candidate.exists():
        return package_candidate
    return Path(__file__).resolve().parents[3] / candidate


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
