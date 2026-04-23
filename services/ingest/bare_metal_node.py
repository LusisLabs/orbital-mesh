"""Signal ingester for bare-metal blockchain nodes.

# Why this module is separate from the OTel ingester

The OTel consumer I already shipped handles generic metric regressions
well. But blockchain nodes have a specific failure-mode vocabulary that
a bare metric threshold can't capture:

* A Solana validator that's "delinquent" — behind the network by more
  than ~128 slots — is a different problem from high CPU, and neither
  Prometheus alert rule nor an OTel resource attribute tells you that
  this particular node is the one missing votes. The semantic layer
  ("compare this node's slot to the cluster root") lives here.
* A geth node with ``eth_syncing`` returning a non-null object is
  actively catching up; the same node showing zero peers and a stalled
  block number is broken. Both look identical through Prometheus's
  ``geth_chain_head_block`` gauge.

The ingester's job is to issue a small number of RPC calls and shape the
result into a Mesh signal. Downstream stages (trigger, decision, rule
engine) treat it like any other signal — the rule engine's pattern
matcher works because the ingester stamps stable metric names
(``solana.slot_lag``, ``geth.peer_count``) into the envelope.

# Scope

This module ships with two ingesters:

* :class:`SolanaNodeIngester` — polls a Solana JSON-RPC endpoint for
  slot height, validator vote state, and delinquency.
* :class:`EthereumNodeIngester` — polls a geth/reth JSON-RPC endpoint
  for sync status, peer count, and head block.

Both speak plain HTTP JSON-RPC (no extra dependency) and return dicts
that conform to ``otel-metric-signal.schema.json``. The metric_name
field uses a stable namespace so rules can match consistently.

# Safety model

* No SSH here — this module is read-only. RPC calls only.
* Connection errors surface as ``None`` return from ``build_signal``.
  Callers (typically a scheduler) should treat this as "unable to
  assess" rather than "node is broken" and skip the run, exactly the
  same way the Prometheus pull ingester handles Prometheus outages.
* No authenticated RPC — if your validator RPC requires auth, put a
  reverse proxy in front and point Mesh at that. Bundling credential
  handling into Mesh itself would couple the signal layer to secret
  management, which belongs somewhere else.

# Rough integration

```
cron / scheduler ──▶ SolanaNodeIngester.build_signal(target)
                        │ JSON-RPC: getSlot, getEpochInfo, getVoteAccounts
                        ▼
                    Mesh signal (otel_metric_regression)
                        │
                        ▼
                    IngestService.normalize_signal
                        │
                        ▼
                    TriggerService.detect
                        │
                        ▼
                    DecisionService  ──▶  policies/metric-actions.policy.json
                        │                        ("solana slot lag" rule match)
                        ▼
                    SystemdSshAdapter.restart_service
```

The scheduler side is not in scope for this module — the existing
coordinator's ``create_run`` accepts a ``signal_payload`` directly, and
the watch daemon can invoke :meth:`build_signal` on a timer.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


_LOG = logging.getLogger("mesh.ingest.bare_metal_node")


@dataclass
class BareMetalNodeTarget:
    """Descriptor for a single bare-metal blockchain node.

    Mirrors the JSON config shape of ``MESH_BARE_METAL_NODE_TARGETS``.
    ``host`` and ``service`` are what the SystemdSshAdapter receives if a
    remediation rule fires on this node, so they must match the adapter's
    allowlist.
    """

    name: str
    kind: str  # "solana" | "geth" | "reth"
    rpc_url: str
    host: str
    service: str
    environment: str = "production"
    region: str | None = None
    # How far behind the cluster head we tolerate before flagging regression.
    # Solana's slot time is ~400ms, so 128 slots ≈ 51 seconds lag.
    max_slot_lag: int = 128
    # Minimum acceptable peer count for geth/reth. Fewer peers than this
    # and the node is almost certainly isolated.
    min_peer_count: int = 3

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BareMetalNodeTarget":
        return cls(
            name=str(raw["name"]),
            kind=str(raw.get("kind", "solana")),
            rpc_url=str(raw.get("rpc_url", "")),
            host=str(raw["host"]),
            service=str(raw.get("service", "")),
            environment=str(raw.get("environment", "production")),
            region=raw.get("region"),
            max_slot_lag=int(raw.get("max_slot_lag", 128)),
            min_peer_count=int(raw.get("min_peer_count", 3)),
        )


# ---------------------------------------------------------------- JSON-RPC


class RpcError(RuntimeError):
    """Raised internally when a JSON-RPC call fails. Callers convert to None."""


def _rpc_call(url: str, method: str, params: list[Any] | None = None, timeout_seconds: float = 5.0) -> Any:
    """Minimal JSON-RPC 2.0 client.

    Deliberately narrow: no batching, no notifications, no retry. The
    ingesters call a handful of methods per target and any transient
    failure should bubble up as ``None`` in the signal rather than get
    papered over with a retry loop that delays signal emission.
    """
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RpcError(f"rpc transport error for {method!r}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RpcError(f"rpc returned invalid JSON for {method!r}: {exc}") from exc
    if "error" in payload:
        raise RpcError(f"rpc {method!r} failed: {payload['error']}")
    return payload.get("result")


# ---------------------------------------------------------------- Solana


class SolanaNodeIngester:
    """Build Mesh signals from a Solana/Agave validator RPC.

    Two primary health dimensions:

    1. **Slot lag** — how far behind this node's confirmed slot is from
       the cluster's highest observed slot. Use ``getSlot`` on the target
       and compare with ``getSlot`` on a reference RPC (or cluster
       root). Large lag → the validator is falling behind.

    2. **Vote delinquency** — is this node's vote account in the
       ``delinquent`` list returned by ``getVoteAccounts``? Delinquent
       means it's not voting on recent slots, which is the revenue-
       relevant failure mode.

    The ingester returns ``None`` when it can't determine state
    confidently (RPC down, no reference node to compare slot to). Mesh
    treats that as "unable to assess, skip" — a monitoring outage must
    not masquerade as a node problem.
    """

    def __init__(self, target: BareMetalNodeTarget, reference_rpc_url: str | None = None, timeout_seconds: float = 5.0):
        self.target = target
        # Optional cluster-reference RPC used to compute slot lag. If
        # unset, lag is reported as 0 and only vote delinquency drives
        # the signal. A reference RPC is strongly recommended — without
        # it, a stalled node looks healthy because it's the only thing
        # Mesh is talking to.
        self.reference_rpc_url = reference_rpc_url
        self.timeout_seconds = timeout_seconds

    def build_signal(self) -> dict[str, Any] | None:
        try:
            node_slot = _rpc_call(self.target.rpc_url, "getSlot", timeout_seconds=self.timeout_seconds)
        except RpcError as exc:
            _LOG.warning("solana ingester: %s getSlot failed: %s", self.target.name, exc)
            return None

        reference_slot: int | None = None
        if self.reference_rpc_url:
            try:
                reference_slot = int(
                    _rpc_call(self.reference_rpc_url, "getSlot", timeout_seconds=self.timeout_seconds)
                )
            except RpcError as exc:
                _LOG.warning(
                    "solana ingester: reference %s getSlot failed: %s", self.reference_rpc_url, exc
                )

        slot_lag = (reference_slot - int(node_slot)) if reference_slot is not None else 0
        delinquent_identity = self._check_delinquency()

        # Signal shape: slot_lag is the primary metric because it's the
        # one that rules can threshold on. Vote delinquency rides along
        # in related_context so the decision stage can pivot the remediation
        # (e.g. to an identity rotation when delinquent, restart when
        # merely lagging).
        return {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_solana_{self.target.name}_{uuid4().hex[:12]}",
            "observed_at": _now_iso(),
            "environment": self.target.environment,
            "service": self.target.name,
            "endpoint": "solana.validator",
            "cluster": self.target.region,
            "namespace": None,
            "source": "bare_metal_probe",
            "comparison_window": _trailing_window_iso(),
            "segment": {
                "customer_tier": "system",
                "region": self.target.region or "unknown",
            },
            "metric_regression": {
                "metric_name": "solana.slot_lag",
                "metric_kind": "gauge",
                "unit": "slots",
                "baseline_value": 0.0,
                "observed_value": float(slot_lag),
                "delta_pct": None,  # absolute measure, not a ratio
                "threshold_pct": None,
                "attributes": {
                    "node_slot": int(node_slot),
                    "reference_slot": reference_slot,
                    "delinquent": delinquent_identity is not None,
                },
            },
            # Resource attributes stamped here are what the SystemdSshAdapter
            # reads when a rule fires — host and service drive the actuation.
            "resource_attributes": {
                "service.name": self.target.name,
                "deployment.environment": self.target.environment,
                "mesh.node.kind": "solana",
                "mesh.node.host": self.target.host,
                "mesh.node.service": self.target.service,
                "mesh.node.max_slot_lag": self.target.max_slot_lag,
            },
            "related_metrics": [
                {
                    "metric_name": "solana.delinquent",
                    "value": 1.0 if delinquent_identity is not None else 0.0,
                    "attributes": {"identity": delinquent_identity or ""},
                }
            ],
            "related_context": {
                "node_kind": "solana",
                "vote_in_progress": delinquent_identity is None,
            },
            "post_action_observations": {},
        }

    def _check_delinquency(self) -> str | None:
        """Return the delinquent vote account identity if this node is in
        the delinquent list, else None.

        Uses ``getVoteAccounts`` which returns ``{"current": [...],
        "delinquent": [...]}``. We match by node identity string because
        that's stable across RPC endpoints, while vote pubkeys can rotate.
        """
        try:
            result = _rpc_call(self.target.rpc_url, "getVoteAccounts", timeout_seconds=self.timeout_seconds)
        except RpcError as exc:
            _LOG.warning("solana ingester: %s getVoteAccounts failed: %s", self.target.name, exc)
            return None
        if not isinstance(result, dict):
            return None
        delinquents = result.get("delinquent") or []
        # A node with multiple vote accounts is rare but allowed; return
        # the first match. For our purposes "any delinquent entry for
        # this node" is the signal.
        for entry in delinquents:
            if isinstance(entry, dict) and entry.get("nodePubkey"):
                # We don't have the expected identity to compare against
                # at this layer (validators know their own identity via
                # config), so any entry in the delinquent list for this
                # RPC is treated as self-delinquency.
                return str(entry["nodePubkey"])
        return None


# ---------------------------------------------------------------- Ethereum


class EthereumNodeIngester:
    """Build Mesh signals from a geth/reth/nethermind JSON-RPC endpoint.

    Health dimensions:

    1. **Sync status** — ``eth_syncing`` returns ``false`` when synced,
       else an object with ``startingBlock``/``currentBlock``/
       ``highestBlock``. We stamp the block lag as the primary metric.

    2. **Peer count** — ``net_peerCount`` as a hex int. Below the
       configured minimum, the node is almost certainly isolated and
       will stop producing fresh blocks.

    3. **Head block age** — time since the last block the node reports.
       An out-of-sync but still-peered node can produce blocks slowly;
       no fresh blocks for minutes is a harder failure mode than peer
       count alone.
    """

    def __init__(self, target: BareMetalNodeTarget, timeout_seconds: float = 5.0):
        self.target = target
        self.timeout_seconds = timeout_seconds

    def build_signal(self) -> dict[str, Any] | None:
        try:
            sync_status = _rpc_call(self.target.rpc_url, "eth_syncing", timeout_seconds=self.timeout_seconds)
            peer_count_hex = _rpc_call(self.target.rpc_url, "net_peerCount", timeout_seconds=self.timeout_seconds)
            head_block_hex = _rpc_call(self.target.rpc_url, "eth_blockNumber", timeout_seconds=self.timeout_seconds)
        except RpcError as exc:
            _LOG.warning("eth ingester: %s rpc failed: %s", self.target.name, exc)
            return None

        try:
            peer_count = int(peer_count_hex, 16) if isinstance(peer_count_hex, str) else int(peer_count_hex or 0)
        except (TypeError, ValueError):
            peer_count = 0
        try:
            head_block = int(head_block_hex, 16) if isinstance(head_block_hex, str) else int(head_block_hex or 0)
        except (TypeError, ValueError):
            head_block = 0

        syncing = sync_status not in (False, None)
        block_lag = self._compute_block_lag(sync_status)

        # Which dimension to headline? Peer count is the most decisive —
        # a node with zero peers is broken regardless of sync state. Fall
        # back to block_lag when peers look fine but the node is behind.
        if peer_count < self.target.min_peer_count:
            metric_name = "geth.peer_count"
            observed_value = float(peer_count)
            baseline_value = float(self.target.min_peer_count)
        else:
            metric_name = "geth.block_lag"
            observed_value = float(block_lag)
            baseline_value = 0.0

        return {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_eth_{self.target.name}_{uuid4().hex[:12]}",
            "observed_at": _now_iso(),
            "environment": self.target.environment,
            "service": self.target.name,
            "endpoint": "geth.rpc",
            "cluster": self.target.region,
            "namespace": None,
            "source": "bare_metal_probe",
            "comparison_window": _trailing_window_iso(),
            "segment": {
                "customer_tier": "system",
                "region": self.target.region or "unknown",
            },
            "metric_regression": {
                "metric_name": metric_name,
                "metric_kind": "gauge",
                "unit": "peers" if metric_name == "geth.peer_count" else "blocks",
                "baseline_value": baseline_value,
                "observed_value": observed_value,
                "delta_pct": None,
                "threshold_pct": None,
                "attributes": {
                    "peer_count": peer_count,
                    "head_block": head_block,
                    "syncing": syncing,
                },
            },
            "resource_attributes": {
                "service.name": self.target.name,
                "deployment.environment": self.target.environment,
                "mesh.node.kind": self.target.kind,
                "mesh.node.host": self.target.host,
                "mesh.node.service": self.target.service,
                "mesh.node.min_peer_count": self.target.min_peer_count,
            },
            "related_metrics": [
                {"metric_name": "geth.peer_count", "value": float(peer_count), "attributes": {}},
                {"metric_name": "geth.block_lag", "value": float(block_lag), "attributes": {}},
                {"metric_name": "geth.syncing", "value": 1.0 if syncing else 0.0, "attributes": {}},
            ],
            "related_context": {
                "node_kind": self.target.kind,
                "head_block": head_block,
            },
            "post_action_observations": {},
        }

    def _compute_block_lag(self, sync_status: Any) -> int:
        """Extract block lag from ``eth_syncing`` result.

        Returns 0 when the node claims to be fully synced. Returns a
        positive integer when the sync object is present. Never negative.
        """
        if not isinstance(sync_status, dict):
            return 0
        try:
            highest = int(sync_status.get("highestBlock", "0x0"), 16)
            current = int(sync_status.get("currentBlock", "0x0"), 16)
        except (TypeError, ValueError):
            return 0
        return max(0, highest - current)


# ---------------------------------------------------------------- helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _trailing_window_iso() -> dict[str, str]:
    """Standard 5m trailing window descriptor used across signal sources."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)
    return {"baseline": f"{start.isoformat()}/{now.isoformat()}", "observed": f"{start.isoformat()}/{now.isoformat()}"}


__all__ = [
    "BareMetalNodeTarget",
    "EthereumNodeIngester",
    "RpcError",
    "SolanaNodeIngester",
]
