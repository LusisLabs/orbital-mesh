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

``RethRulePack`` mirrors the existing hypothesis_engine peer-starvation
template in native-selector rules: get peers → if below floor, check
engine API → check recent logs → stop.
"""

from __future__ import annotations

from typing import Any

from services.evidence.reth_probe_registry import (
    citation_for_probe,
    snapshot_for_probe,
)

from ..harness import (
    InvestigationLoopState,
    LoopDecision,
    NativeProbeSelector,
    ObservationIndex,
    ProbeRule,
    RawToolOutput,
    RootCauseCandidate,
    ToolDefinition,
    ToolRegistry,
)


DOMAIN = "reth"


_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("read_peer_sync", "json_rpc_peer_sync", "Read peer count, sync status, block lag."),
    ("read_consensus_status", "consensus_status", "Read consensus client and Engine API reachability."),
    ("read_recent_logs", "recent_logs", "Read recent error signatures and recent error log lines."),
    ("read_rpc_health", "json_rpc_rpc_health", "Read RPC reachability, latency, and error rate."),
    ("read_disk_jwt", "disk_jwt_metadata", "Read disk pressure and JWT metadata (no secret contents)."),
)


def _build_definitions() -> list[ToolDefinition]:
    """Return the Reth peer-starvation tool definitions."""
    args_schema = {"snapshot": {"type": "dict", "required": False}}
    return [
        ToolDefinition(
            name=name,
            domain=DOMAIN,
            description=description,
            args_schema=dict(args_schema),
            mutation_class="read_only",
            timeout_seconds=2.0,
            budget_cost=1.0,
            citations_kind="reth_probe",
        )
        for name, _, description in _TOOLS
    ]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_definitions())
TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in TOOL_DEFINITIONS)


def register(registry: ToolRegistry, signal_payload: dict[str, Any]) -> None:
    """Register Reth peer-starvation tools backed by ``signal_payload``.

    The signal payload is the audited node snapshot passed through the
    pipeline. Each tool reads its slice via the existing
    ``snapshot_for_probe`` implementation, which already redacts JWT and
    secret material.
    """
    for harness_name, probe_name, _description in _TOOLS:
        definition = next(d for d in TOOL_DEFINITIONS if d.name == harness_name)
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


class RethRulePack:
    """Reth native selector rules for the peer-starvation slice."""

    domain: str = DOMAIN
    tool_definitions: tuple[ToolDefinition, ...] = TOOL_DEFINITIONS
    root_cause_ranker = None
    sufficient_stop_reason: str = "root_cause_candidate_found"
    exhausted_stop_reason: str = "evidence_value_exhausted"

    def __init__(self, *, peer_floor: int = 1) -> None:
        self._peer_floor = peer_floor
        self.rules: tuple[ProbeRule, ...] = (
            ProbeRule(
                name="peer_sync_first",
                tool_name="read_peer_sync",
                when=self._needs_peer_sync,
                build_args=self._empty_args,
                selection_reason=self._peer_sync_reason,
                priority=10,
                confidence=0.5,
            ),
            ProbeRule(
                name="consensus_when_peers_low",
                tool_name="read_consensus_status",
                when=self._needs_consensus_status,
                build_args=self._empty_args,
                selection_reason=self._consensus_reason,
                priority=20,
                confidence=0.55,
            ),
            ProbeRule(
                name="logs_corroboration",
                tool_name="read_recent_logs",
                when=self._needs_recent_logs,
                build_args=self._empty_args,
                selection_reason=self._logs_reason,
                priority=30,
                confidence=0.55,
            ),
        )

    def sufficient_root_cause(self, _index: ObservationIndex) -> RootCauseCandidate | None:
        return None

    def _needs_peer_sync(self, index: ObservationIndex) -> bool:
        return not index.tool_called("read_peer_sync")

    def _needs_consensus_status(self, index: ObservationIndex) -> bool:
        return self._peer_count(index) < self._peer_floor

    def _needs_recent_logs(self, _index: ObservationIndex) -> bool:
        return True

    def _empty_args(self, _index: ObservationIndex) -> dict[str, Any]:
        return {}

    def _peer_sync_reason(self, _index: ObservationIndex) -> str:
        return "reth_first_peer_check"

    def _consensus_reason(self, _index: ObservationIndex) -> str:
        return "reth_peers_below_floor"

    def _logs_reason(self, _index: ObservationIndex) -> str:
        return "reth_corroborate_logs"

    def _peer_count(self, index: ObservationIndex) -> int:
        peer_data = index.output_for("read_peer_sync")
        return int(peer_data.get("peer_count") or 0) if isinstance(peer_data, dict) else 0


class RethLoopPlanner:
    """Compatibility wrapper around ``NativeProbeSelector``."""

    domain: str = DOMAIN

    def __init__(self, *, peer_floor: int = 1) -> None:
        self._selector = NativeProbeSelector(RethRulePack(peer_floor=peer_floor))

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        return self._selector.plan(state=state, trigger_context=trigger_context)
