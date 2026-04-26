"""Healthy Reth node baseline state.

The simulation maintains one of these dicts as the live world state.
Faults mutate this baseline; the driver serializes the post-fault state
into a ``reth_node`` signal that Mesh ingests.

Schema is the same as ``shared/mesh_runtime/schemas/reth-node-signal.schema.json``
because we want fixtures and live signals to be byte-compatible — the
sim should exercise the exact code paths production runs.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


_NODE_NAME = "reth-mainnet-sim-01"
_HOST = "vault-sim-01"
_SERVICE = "reth.service"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def healthy_state() -> dict[str, Any]:
    """A fresh healthy Reth node state. Each call returns a new dict so
    callers can mutate without aliasing."""
    return copy.deepcopy(_HEALTHY)


_HEALTHY: dict[str, Any] = {
    "signal_type": "reth_node",
    "signal_id": "",
    "observed_at": "",
    "environment": "production",
    "service": _NODE_NAME,
    "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
    "segment": {"customer_tier": "system", "region": "us-east-1"},
    "node": {
        "name": _NODE_NAME,
        "deployment_mode": "systemd",
        "network": "mainnet",
        "role": "rpc",
        "client_version": "reth/v1.0.6",
        "data_dir": "/var/lib/reth",
        "jwt_secret_path": "/etc/reth/jwt.hex",
    },
    "execution": {
        "syncing": False,
        "head_block": 19234567,
        "block_lag": 0,
        "peer_count": 12,
        "min_peer_count": 3,
        "max_block_lag": 32,
        "safe_block": None,
        "finalized_block": None,
    },
    "consensus": {
        "engine_api_reachable": True,
        "jwt_configured": True,
        "forkchoice_updates_recent": True,
        "consensus_client": "lighthouse",
        "client_kind": "lighthouse",
        "client_healthy": True,
        "jwt_secret_exists": True,
        "jwt_secret_mode": "0600",
    },
    "storage": {
        "data_dir_free_bytes": 549_755_813_888,
        "disk_used_pct": 60.0,
        "db_growth_rate_bytes_per_hour": 1_073_741_824.0,
        "snapshot_mode": "none",
        "diagnostic_source": "ssh_df",
    },
    "rpc": {
        "http_reachable": True,
        "latency_ms": 32.0,
        "error_rate": 0.0,
        "publicly_exposed": False,
        "authrpc_publicly_exposed": False,
    },
    "logs": {
        "error_signatures": [],
        "recent_errors": [],
    },
    "resource_attributes": {
        "service.name": _NODE_NAME,
        "deployment.environment": "production",
        "mesh.node.kind": "reth",
        "mesh.node.host": _HOST,
        "mesh.node.service": _SERVICE,
        "mesh.node.min_peer_count": 3,
        "mesh.node.max_block_lag": 32,
        "mesh.node.deployment_mode": "systemd",
        "mesh.node.network": "mainnet",
        "mesh.node.role": "rpc",
    },
    "related_context": {
        "node_kind": "reth",
        "host": _HOST,
        "systemd_service": _SERVICE,
        "systemd_restarts_last_1h": 0,
    },
    "post_action_observations": {},
}


def stamp_signal(state: dict[str, Any]) -> dict[str, Any]:
    """Stamp a fresh ``signal_id`` and ``observed_at`` on the state.

    The state dict is mutated in place and returned for chaining.
    """
    state["signal_id"] = f"sig_sim_{uuid4().hex[:12]}"
    state["observed_at"] = _now_iso()
    return state
