"""Reth domain pack for the investigation harness — peer-starvation slice.

This is the second-domain proof: same harness contracts, same loop,
different planner and tool set. The peer-starvation family covers the
"my node has zero peers, why?" investigation:

* ``read_peer_sync``  — peer count and sync state.
* ``read_consensus_status`` — engine-API reachability.
* ``read_recent_logs`` — recent error signatures.

Each tool is read-only; the implementations are thin wrappers around
``services.evidence.reth_probe_registry.snapshot_for_probe`` so the
existing redaction logic carries over for free.

The planner mirrors the existing hypothesis_engine peer-starvation
template logic in tool-call form: get peers → if below floor, check
engine API → check recent logs → stop.
"""

from __future__ import annotations

from typing import Any

from services.evidence.reth_probe_registry import (
    citation_for_probe,
    snapshot_for_probe,
)

from .harness import (
    InvestigationLoopState,
    LoopDecision,
    RawToolOutput,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    make_call,
)


RETH_DOMAIN = "reth"


_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("read_peer_sync", "json_rpc_peer_sync", "Read peer count, sync status, block lag."),
    ("read_consensus_status", "consensus_status", "Read consensus client and Engine API reachability."),
    ("read_recent_logs", "recent_logs", "Read recent error signatures and recent error log lines."),
    ("read_rpc_health", "json_rpc_rpc_health", "Read RPC reachability, latency, and error rate."),
    ("read_disk_jwt", "disk_jwt_metadata", "Read disk pressure and JWT metadata (no secret contents)."),
)


def reth_tool_definitions() -> list[ToolDefinition]:
    """Return the Reth peer-starvation tool definitions."""
    args_schema = {"snapshot": {"type": "dict", "required": False}}
    return [
        ToolDefinition(
            name=name,
            domain=RETH_DOMAIN,
            description=description,
            args_schema=dict(args_schema),
            mutation_class="read_only",
            timeout_seconds=2.0,
            budget_cost=1.0,
            citations_kind="reth_probe",
        )
        for name, _, description in _TOOLS
    ]


RETH_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(reth_tool_definitions())
RETH_TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in RETH_TOOL_DEFINITIONS)


def register_reth_tools(registry: ToolRegistry, signal_payload: dict[str, Any]) -> None:
    """Register Reth peer-starvation tools backed by ``signal_payload``.

    The signal payload is the audited node snapshot passed through the
    pipeline. Each tool reads its slice via the existing
    ``snapshot_for_probe`` implementation, which already redacts JWT and
    secret material.
    """
    for harness_name, probe_name, _description in _TOOLS:
        definition = next(d for d in RETH_TOOL_DEFINITIONS if d.name == harness_name)
        registry.register(definition, _make_reth_invoker(probe_name, signal_payload))


def _make_reth_invoker(probe_name: str, signal_payload: dict[str, Any]):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        snapshot = args.get("snapshot") if isinstance(args.get("snapshot"), dict) else signal_payload
        data = snapshot_for_probe(probe_name, snapshot)
        valid = bool(data)
        summary = _summarize_probe_data(probe_name, data)
        citation = citation_for_probe(probe_name)
        return RawToolOutput(
            output=data,
            output_summary=summary,
            citations=[citation],
            valid=valid,
            redaction_status="redacted" if probe_name in {"disk_jwt_metadata", "recent_logs"} else "clean",
            status="completed",
        )

    return invoke


def _summarize_probe_data(probe_name: str, data: dict[str, Any]) -> str:
    if not data:
        return f"{probe_name}: no data in snapshot"
    parts = [f"{key}={data[key]}" for key in sorted(data) if data[key] not in (None, [], {})]
    return f"{probe_name}: " + " ".join(parts) if parts else f"{probe_name}: empty"


class RethLoopPlanner:
    """Peer-starvation planner driven by observed snapshot data.

    Sequence:
    1. ``read_peer_sync`` — establish peer count.
    2. If peers are below floor, call ``read_consensus_status`` (is the
       consensus client reachable? local-isolation vs. consensus-disconnect).
    3. ``read_recent_logs`` — corroborate from recent error signatures.
    4. Stop with the planner's confidence.
    """

    domain: str = RETH_DOMAIN

    def __init__(self, *, peer_floor: int = 1) -> None:
        self._peer_floor = peer_floor

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        called = {call.tool_name for call in state.tool_calls}
        if "read_peer_sync" not in called:
            return _continue("read_peer_sync", reason="reth_first_peer_check")
        peer_data = self._peer_sync_data(state)
        peer_count = int(peer_data.get("peer_count") or 0) if isinstance(peer_data, dict) else 0
        if peer_count < self._peer_floor and "read_consensus_status" not in called:
            return _continue("read_consensus_status", reason="reth_peers_below_floor")
        if "read_recent_logs" not in called:
            return _continue("read_recent_logs", reason="reth_corroborate_logs")
        return LoopDecision(action="stop", reason="reth_peer_starvation_plan_complete", confidence=0.6)

    def _peer_sync_data(self, state: InvestigationLoopState) -> dict[str, Any]:
        for call, result in zip(state.tool_calls, state.tool_results):
            if call.tool_name == "read_peer_sync" and isinstance(result.output, dict):
                return result.output
        return {}


def _continue(tool_name: str, *, reason: str) -> LoopDecision:
    definition = next((d for d in RETH_TOOL_DEFINITIONS if d.name == tool_name), None)
    if definition is None:
        raise KeyError(f"reth tool {tool_name} not in registry definitions")
    call: ToolCall = make_call(tool=definition, args={}, purpose=reason)
    return LoopDecision(action="continue", next_calls=(call,), reason=reason, confidence=0.5)
