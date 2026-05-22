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
    for definition in registry.list_definitions(domain=domain, mutation_class="read_only"):
        record = definition.to_dict()
        record["sandbox_access"] = {
            "allowed": True,
            "reason": "read_only_tool",
            "raw_secret_in_sandbox": False,
            "mutation_requires_proposal": False,
        }
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
    if definition.mutation_class != "read_only":
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
            error="sandbox agents may invoke read_only tools only; mutating tools must return Mesh proposals",
        )
        _record_audit(audit_log, call=call, result=result, decision="rejected_mutation")
        return result
    result = registry.invoke(call)
    _record_audit(audit_log, call=call, result=result, decision="invoked_read_only")
    return result


def _record_audit(
    audit_log: list[dict[str, Any]] | None,
    *,
    call: ToolCall,
    result: ToolResult,
    decision: str,
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
        }
    )
