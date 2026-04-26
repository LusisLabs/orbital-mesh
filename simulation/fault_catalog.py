"""Catalog of fault scenarios injected into the simulated Reth node.

Each ``Fault`` carries a mutator that takes the healthy baseline and
returns a faulted state, plus an ``ExpectedOutcome`` the driver scores
against. The catalog is deliberately broad — the point is to exercise
Mesh's decision surface across the realistic failure-mode vocabulary
for an Ethereum execution node, not to be exhaustive.

# Outcome classes

We score against decision_type, not decision_id, because the actual ID
includes a UUID. Outcome classes:

* ``escalate`` — Mesh should refuse autonomy and route to a human
* ``restart_systemd_service`` — Mesh should propose an approval-gated
  restart (still gated by autonomy policy at execution time)
* ``no_action`` — Mesh should leave the node alone (transient,
  recovering, or irrelevant signal)

A scenario can list multiple acceptable outcomes when there's
legitimate ambiguity (e.g. a transient peer dip is fine to restart OR
to ignore). ``escalate`` is always acceptable as a more conservative
fallback — that's the one-way safety property we built into the
decision service.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable


_Mutator = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Fault:
    """A single fault scenario the simulation can inject."""

    fault_id: str
    category: str
    description: str
    expected_outcomes: tuple[str, ...]
    mutator: _Mutator
    # Tags help group results in the report. Keep small and consistent.
    tags: tuple[str, ...] = field(default_factory=tuple)


def _set(path: str, value: Any) -> _Mutator:
    """Helper: build a mutator that sets a dotted path on the state."""
    keys = path.split(".")

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        cursor = state
        for key in keys[:-1]:
            cursor = cursor.setdefault(key, {})
        cursor[keys[-1]] = value
        return state

    return apply


def _multi(*mutators: _Mutator) -> _Mutator:
    def apply(state: dict[str, Any]) -> dict[str, Any]:
        for m in mutators:
            m(state)
        return state

    return apply


def _append_log(message: str) -> _Mutator:
    def apply(state: dict[str, Any]) -> dict[str, Any]:
        state["logs"]["recent_errors"].append(message)
        return state

    return apply


# ----------------------------------------------------------------------
# Catalog
# ----------------------------------------------------------------------


CATALOG: tuple[Fault, ...] = (
    # --- Peer-related ---
    Fault(
        "peer_zero_rpc_up",
        "peer",
        "Peer count zero, RPC still serving traffic — local network isolation",
        ("restart_systemd_service", "escalate"),
        _multi(_set("execution.peer_count", 0), _append_log("no peers connected for 5m")),
        ("peer_starvation",),
    ),
    Fault(
        "peer_below_floor",
        "peer",
        "Peer count below configured floor (1 of 3 required)",
        ("restart_systemd_service", "escalate"),
        _set("execution.peer_count", 1),
        ("peer_starvation",),
    ),
    Fault(
        "peer_transient_dip",
        "peer",
        "Peer count briefly at 2 (just below floor) — discovery hiccup",
        ("restart_systemd_service", "escalate", "no_action"),
        _set("execution.peer_count", 2),
        ("peer_starvation", "transient"),
    ),
    # --- Sync-related ---
    Fault(
        "sync_stalled_clean",
        "sync",
        "Sync object active, block lag growing, no other symptoms",
        ("restart_systemd_service", "escalate"),
        _multi(_set("execution.syncing", True), _set("execution.block_lag", 800)),
        ("sync_stalled",),
    ),
    Fault(
        "sync_with_disk_pressure",
        "sync",
        "Sync stalled AND disk at 92% — restart would risk DB corruption",
        ("escalate",),
        _multi(
            _set("execution.syncing", True),
            _set("execution.block_lag", 4500),
            _set("storage.disk_used_pct", 92.0),
            _set("storage.data_dir_free_bytes", 32_212_254_720),
        ),
        ("sync_stalled", "disk_pressure"),
    ),
    Fault(
        "sync_with_consensus_disconnect",
        "sync",
        "Sync stalled AND engine_api unreachable — root cause is CL",
        ("escalate",),
        _multi(
            _set("execution.syncing", True),
            _set("execution.block_lag", 1200),
            _set("consensus.engine_api_reachable", False),
            _set("consensus.forkchoice_updates_recent", False),
        ),
        ("sync_stalled", "consensus_disconnected"),
    ),
    Fault(
        "sync_catching_up",
        "sync",
        "Block lag of 8 — node is catching up normally, not stalled",
        ("no_action", "restart_systemd_service", "escalate"),
        _multi(_set("execution.syncing", True), _set("execution.block_lag", 8)),
        ("transient",),
    ),
    # --- Disk pressure ---
    Fault(
        "disk_pressure_92",
        "disk",
        "Disk at 92% — node still functional but compaction throttled",
        ("escalate",),
        _multi(
            _set("storage.disk_used_pct", 92.0),
            _set("storage.data_dir_free_bytes", 32_212_254_720),
            _append_log("compaction throttled: low free space"),
        ),
        ("disk_pressure",),
    ),
    Fault(
        "disk_pressure_critical_99",
        "disk",
        "Disk at 99% — imminent corruption risk on shutdown",
        ("escalate",),
        _multi(
            _set("storage.disk_used_pct", 99.1),
            _set("storage.data_dir_free_bytes", 4_294_967_296),
        ),
        ("disk_pressure",),
    ),
    Fault(
        "disk_warning_85",
        "disk",
        "Disk at 85% — warning band, not yet critical",
        ("no_action", "escalate"),
        _set("storage.disk_used_pct", 85.0),
        ("disk_warning",),
    ),
    # --- RPC ---
    Fault(
        "rpc_error_rate_8pct",
        "rpc",
        "RPC error rate at 8% on internal-only endpoint",
        ("restart_systemd_service", "escalate"),
        _set("rpc.error_rate", 0.08),
        ("rpc_degraded",),
    ),
    Fault(
        "rpc_publicly_exposed_overload",
        "rpc",
        "RPC publicly exposed AND error rate elevated — abuse traffic",
        ("escalate",),
        _multi(
            _set("rpc.publicly_exposed", True),
            _set("rpc.error_rate", 0.15),
        ),
        ("rpc_degraded", "rpc_exposed"),
    ),
    Fault(
        "rpc_unreachable",
        "rpc",
        "RPC server not responding to HTTP requests",
        ("restart_systemd_service", "escalate"),
        _set("rpc.http_reachable", False),
        ("rpc_degraded",),
    ),
    Fault(
        "rpc_high_latency",
        "rpc",
        "RPC latency elevated to 800ms p95 (vs 30ms baseline)",
        ("no_action", "restart_systemd_service", "escalate"),
        _set("rpc.latency_ms", 800.0),
        ("rpc_degraded", "transient"),
    ),
    # --- Consensus / Engine API / JWT ---
    Fault(
        "engine_api_unreachable",
        "consensus",
        "Engine API unreachable — paired CL is gone",
        ("escalate",),
        _multi(
            _set("consensus.engine_api_reachable", False),
            _set("consensus.forkchoice_updates_recent", False),
            _set("consensus.client_healthy", False),
        ),
        ("consensus_disconnected",),
    ),
    Fault(
        "forkchoice_stale",
        "consensus",
        "Engine API reachable but no forkchoice updates received recently",
        ("escalate",),
        _set("consensus.forkchoice_updates_recent", False),
        ("consensus_disconnected",),
    ),
    Fault(
        "jwt_secret_missing",
        "consensus",
        "JWT secret file deleted",
        ("escalate",),
        _multi(
            _set("consensus.jwt_secret_exists", False),
            _set("consensus.jwt_configured", False),
        ),
        ("jwt_missing",),
    ),
    Fault(
        "jwt_world_readable",
        "consensus",
        "JWT secret has world-readable permissions (0644)",
        ("escalate",),
        _set("consensus.jwt_secret_mode", "0644"),
        ("jwt_secret_insecure_permissions",),
    ),
    # --- Exposure ---
    Fault(
        "authrpc_publicly_exposed",
        "exposure",
        "Auth-RPC publicly exposed — credential exfiltration risk",
        ("escalate",),
        _set("rpc.authrpc_publicly_exposed", True),
        ("authrpc_exposed",),
    ),
    Fault(
        "rpc_publicly_exposed_no_overload",
        "exposure",
        "RPC publicly exposed but no error rate spike yet",
        ("escalate",),
        _set("rpc.publicly_exposed", True),
        ("rpc_exposed",),
    ),
    # --- Bad release / version ---
    Fault(
        "snapshot_restoring",
        "release",
        "Node is in snapshot restore mode — must not be touched",
        ("no_action", "escalate"),
        _set("storage.snapshot_mode", "restoring"),
        ("snapshot_restore",),
    ),
    # --- Cascading / multi-cause ---
    Fault(
        "cascade_peer_zero_engine_down",
        "cascade",
        "Peers zero AND engine API down — both symptoms; CL is upstream",
        ("escalate",),
        _multi(
            _set("execution.peer_count", 0),
            _set("consensus.engine_api_reachable", False),
        ),
        ("peer_starvation", "consensus_disconnected"),
    ),
    Fault(
        "cascade_sync_disk_jwt",
        "cascade",
        "Sync stalled, disk pressure, AND JWT misconfigured — multiple unsafe",
        ("escalate",),
        _multi(
            _set("execution.syncing", True),
            _set("execution.block_lag", 1200),
            _set("storage.disk_used_pct", 91.0),
            _set("consensus.jwt_secret_mode", "0644"),
        ),
        ("sync_stalled", "disk_pressure", "jwt_secret_insecure_permissions"),
    ),
    # --- Restart-rate limiting ---
    Fault(
        "restart_frequency_exceeded",
        "policy",
        "Same node restarted twice in last hour — should escalate, not retry",
        ("escalate",),
        _multi(
            _set("execution.peer_count", 0),
            _set("related_context.systemd_restarts_last_1h", 2),
        ),
        ("peer_starvation", "restart_frequency_exceeded"),
    ),
    # --- False positives / quiet noise ---
    Fault(
        "log_noise_no_real_failure",
        "noise",
        "Recent error logs but every metric healthy",
        ("no_action", "escalate"),
        _multi(
            _append_log("warning: discovery: peer scoring rebalanced"),
            _append_log("info: pruner: deleted 12000 stale receipts"),
        ),
        ("noise",),
    ),
    Fault(
        "all_clear",
        "noise",
        "Pristine baseline — should produce no_trigger",
        ("no_action",),
        lambda state: state,
        ("baseline",),
    ),
)


def by_category() -> dict[str, list[Fault]]:
    """Return a category -> faults mapping for grouped reporting."""
    out: dict[str, list[Fault]] = {}
    for fault in CATALOG:
        out.setdefault(fault.category, []).append(fault)
    return out


def apply_fault(fault: Fault, baseline: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``baseline`` with the fault mutator applied."""
    state = copy.deepcopy(baseline)
    return fault.mutator(state)
