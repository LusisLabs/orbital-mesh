from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

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
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RAW_SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|client[_-]?secret|cookie|kubeconfig|password|private[_-]?key|token)", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"(Bearer\s+(?!REDACTED)[A-Za-z0-9._~+/=-]{12,}|sk-[A-Za-z0-9]{12,})")


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
    openapi = json.loads(_resolve_repo_path(str(openapi_packet["source_ref"])).read_text(encoding="utf-8"))
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
    validate_payload(PRAXIS_GENERATED_MCP_CONTRACT_SCHEMA, generated_contract)
    payload = json.loads(_resolve_repo_path(str(akto_result_path)).read_text(encoding="utf-8"))
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


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        text = _resolve_repo_path(str(packet["source_ref"])).read_text(encoding="utf-8")
        hints.extend(line.strip() for line in text.splitlines() if line.strip())
    return hints


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _source_packet(*, index: int, source: dict[str, str]) -> dict[str, Any]:
    source_type = str(source["source_type"])
    source_ref = str(source["source_ref"])
    path = _resolve_repo_path(source_ref)
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


def _resolve_repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else _REPO_ROOT / candidate


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
