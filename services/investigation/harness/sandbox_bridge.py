"""Read-only tool bridge for sandboxed proposal agents.

State slice: `mesh.investigation_tool_registry.v1`.

Provenance: adapted from the Centaur tool-discovery pattern recorded in
docs/centaur-source-input.md. Mesh keeps its typed ToolRegistry and exposes
only read-only/proposal-safe metadata to sandbox agents.
"""

from __future__ import annotations

from typing import Any

from .contracts import ToolCall, ToolResult
from .registry import ToolRegistry, make_call


def sandbox_tool_manifest(registry: ToolRegistry, *, domain: str | None = None) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for definition in registry.list_definitions(domain=domain):
        access = _sandbox_access(definition)
        if not access["allowed"]:
            continue
        record = definition.to_dict()
        record["sandbox_access"] = access
        record["credential_policy"] = {
            "requires_credentials": bool(record.get("credential_policy", {}).get("requires_credentials")),
            "raw_secret_in_sandbox": False,
            **record.get("credential_policy", {}),
        }
        manifest.append(record)
    return manifest


def invoke_sandbox_tool(
    registry: ToolRegistry,
    *,
    domain: str,
    name: str,
    args: dict[str, Any] | None = None,
    purpose: str = "",
    audit_log: list[dict[str, Any]] | None = None,
) -> ToolResult:
    entry = registry.get(domain, name)
    if entry is None:
        call = ToolCall(
            call_id="sandbox_missing_tool",
            tool_name=name,
            domain=domain,
            args=dict(args or {}),
            requested_at="sandbox",
            purpose=purpose,
        )
        result = registry.invoke(call)
        _record_audit(audit_log, call=call, result=result, decision="rejected_missing_tool")
        return result
    definition, _ = entry
    call = make_call(tool=definition, args=dict(args or {}), purpose=purpose)
    access = _sandbox_access(definition)
    if not access["allowed"]:
        result = ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            domain=call.domain,
            status="rejected",
            valid=False,
            output_summary="",
            citations=[],
            redaction_status="clean",
            started_at=call.requested_at,
            completed_at=call.requested_at,
            latency_ms=0.0,
            error=str(access["reason"]),
        )
        _record_audit(audit_log, call=call, result=result, decision="rejected_mutation", access=access)
        return result
    result = registry.invoke(call)
    if access["proposal_only"] and not _result_is_proposal_only(result.output):
        result = ToolResult(
            call_id=result.call_id,
            tool_name=result.tool_name,
            domain=result.domain,
            status="rejected",
            valid=False,
            output_summary=result.output_summary,
            citations=list(result.citations),
            redaction_status=result.redaction_status,
            started_at=result.started_at,
            completed_at=result.completed_at,
            latency_ms=result.latency_ms,
            error="proposal-only sandbox tool returned output without proposal contract",
            output=result.output,
        )
        _record_audit(audit_log, call=call, result=result, decision="rejected_non_proposal_output", access=access)
        return result
    decision = "invoked_proposal_only" if access["proposal_only"] else "invoked_read_only"
    _record_audit(audit_log, call=call, result=result, decision=decision, access=access)
    return result


def _sandbox_access(definition: Any) -> dict[str, Any]:
    if definition.mutation_class == "read_only":
        return {
            "allowed": True,
            "reason": "read_only_tool",
            "raw_secret_in_sandbox": False,
            "proposal_only": False,
            "mutation_requires_proposal": False,
            "side_effects_allowed": False,
        }
    contract = dict(getattr(definition, "proposal_contract", {}) or {})
    proposal_only = (
        contract.get("returns_proposal") is True
        and contract.get("executes_side_effects") is False
        and contract.get("requires_mesh_approval") is True
    )
    return {
        "allowed": proposal_only,
        "reason": "proposal_only_mutation_tool" if proposal_only else "mutating tools must declare proposal-only output and Mesh approval",
        "raw_secret_in_sandbox": False,
        "proposal_only": proposal_only,
        "mutation_requires_proposal": True,
        "side_effects_allowed": False,
        "proposal_contract": contract,
    }


def _result_is_proposal_only(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    proposal = output.get("proposal")
    return (
        isinstance(proposal, dict)
        and output.get("side_effects_executed") is False
        and proposal.get("requires_mesh_approval") is True
    )


def _record_audit(
    audit_log: list[dict[str, Any]] | None,
    *,
    call: ToolCall,
    result: ToolResult,
    decision: str,
    access: dict[str, Any] | None = None,
) -> None:
    if audit_log is None:
        return
    audit_log.append(
        {
            "state_slice": "mesh.investigation_tool_registry.v1",
            "call_id": call.call_id,
            "qualified_name": call.qualified_name,
            "decision": decision,
            "status": result.status,
            "valid": result.valid,
            "raw_secret_in_sandbox": False,
            "mutation_allowed": False,
            "proposal_only": bool((access or {}).get("proposal_only")),
            "side_effects_allowed": False,
        }
    )
