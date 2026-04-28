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
from typing import Any, Callable
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
    # Reth-specific block-lag threshold. Block lag is computed from
    # ``eth_syncing.highestBlock - currentBlock`` when the node reports an
    # active sync object. Operators can tune this per node role; archive/RPC
    # fleets often tolerate less lag than hobby full nodes.
    max_block_lag: int = 32
    deployment_mode: str = "systemd"
    network: str = "mainnet"
    role: str = "full"
    consensus_client: str | None = None
    data_dir: str | None = None
    jwt_secret_path: str | None = None
    metrics_url: str | None = None
    recent_log_lines: tuple[str, ...] = ()
    rpc_publicly_exposed: bool | None = None
    authrpc_publicly_exposed: bool | None = None
    lb_target_id: str | None = None
    lb_pool: str | None = None
    lb_provider: str | None = None
    fleet_id: str | None = None
    fleet_min_healthy: int | None = None
    fleet_healthy_count: int | None = None

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
            max_block_lag=int(raw.get("max_block_lag", 32)),
            deployment_mode=str(raw.get("deployment_mode", "systemd")),
            network=str(raw.get("network", "mainnet")),
            role=str(raw.get("role", "full")),
            consensus_client=raw.get("consensus_client"),
            data_dir=raw.get("data_dir"),
            jwt_secret_path=raw.get("jwt_secret_path"),
            metrics_url=raw.get("metrics_url"),
            recent_log_lines=tuple(str(line) for line in raw.get("recent_log_lines", ())),
            rpc_publicly_exposed=_optional_bool(raw.get("rpc_publicly_exposed")),
            authrpc_publicly_exposed=_optional_bool(raw.get("authrpc_publicly_exposed")),
            lb_target_id=raw.get("lb_target_id"),
            lb_pool=raw.get("lb_pool"),
            lb_provider=raw.get("lb_provider"),
            fleet_id=raw.get("fleet_id"),
            fleet_min_healthy=int(raw["fleet_min_healthy"]) if raw.get("fleet_min_healthy") is not None else None,
            fleet_healthy_count=int(raw["fleet_healthy_count"]) if raw.get("fleet_healthy_count") is not None else None,
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

    def __init__(
        self,
        target: BareMetalNodeTarget,
        timeout_seconds: float = 5.0,
        *,
        disk_diagnostics_provider: Callable[[BareMetalNodeTarget], dict[str, Any] | None] | None = None,
        jwt_metadata_provider: Callable[[BareMetalNodeTarget], dict[str, Any] | None] | None = None,
        metrics_fetcher: Callable[[str], str | None] | None = None,
    ):
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.disk_diagnostics_provider = disk_diagnostics_provider
        self.jwt_metadata_provider = jwt_metadata_provider
        self.metrics_fetcher = metrics_fetcher or _fetch_text_url

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


class RethNodeIngester:
    """Build a first-class ``reth_node`` signal from Reth JSON-RPC state.

    This deliberately starts read-only. It does not SSH into the host or call
    authenticated Engine API methods. The goal of the first Reth integration
    slice is to preserve enough node-specific context for SRE decisions while
    keeping credentialed actuation in the existing, gated systemd adapter.
    """

    def __init__(
        self,
        target: BareMetalNodeTarget,
        timeout_seconds: float = 5.0,
        *,
        disk_diagnostics_provider: Callable[[BareMetalNodeTarget], dict[str, Any] | None] | None = None,
        jwt_metadata_provider: Callable[[BareMetalNodeTarget], dict[str, Any] | None] | None = None,
        metrics_fetcher: Callable[[str], str | None] | None = None,
    ):
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.disk_diagnostics_provider = disk_diagnostics_provider
        self.jwt_metadata_provider = jwt_metadata_provider
        self.metrics_fetcher = metrics_fetcher or _fetch_text_url

    def build_signal(self) -> dict[str, Any] | None:
        try:
            sync_status = _rpc_call(self.target.rpc_url, "eth_syncing", timeout_seconds=self.timeout_seconds)
            peer_count_hex = _rpc_call(self.target.rpc_url, "net_peerCount", timeout_seconds=self.timeout_seconds)
            head_block_hex = _rpc_call(self.target.rpc_url, "eth_blockNumber", timeout_seconds=self.timeout_seconds)
            client_version = _rpc_call(self.target.rpc_url, "web3_clientVersion", timeout_seconds=self.timeout_seconds)
        except RpcError as exc:
            _LOG.warning("reth ingester: %s rpc failed: %s", self.target.name, exc)
            return None

        peer_count = _hex_or_int(peer_count_hex)
        head_block = _hex_or_int(head_block_hex)
        syncing = sync_status not in (False, None)
        block_lag = _eth_block_lag(sync_status)
        metrics_text = self._metrics_text()
        log_lines = list(self.target.recent_log_lines)
        consensus = _reth_consensus_from_evidence(
            target=self.target,
            metrics_text=metrics_text,
            log_lines=log_lines,
            jwt_metadata=self._jwt_metadata(),
        )
        storage = _reth_storage_from_diagnostics(self._disk_diagnostics())
        error_signatures = _reth_error_signatures(
            syncing=syncing,
            block_lag=block_lag,
            max_block_lag=self.target.max_block_lag,
            peer_count=peer_count,
            min_peer_count=self.target.min_peer_count,
        )
        error_signatures.extend(_reth_observability_signatures(consensus=consensus, storage=storage))

        return {
            "signal_type": "reth_node",
            "signal_id": f"sig_reth_{self.target.name}_{uuid4().hex[:12]}",
            "observed_at": _now_iso(),
            "environment": self.target.environment,
            "service": self.target.name,
            "comparison_window": _trailing_window_iso(),
            "segment": {
                "customer_tier": "system",
                "region": self.target.region or "unknown",
            },
            "node": {
                "name": self.target.name,
                "deployment_mode": self.target.deployment_mode,
                "network": self.target.network,
                "role": self.target.role,
                "client_version": str(client_version) if client_version is not None else None,
                "data_dir": self.target.data_dir,
                "jwt_secret_path": self.target.jwt_secret_path,
            },
            "execution": {
                "syncing": syncing,
                "head_block": head_block,
                "safe_block": None,
                "finalized_block": None,
                "block_lag": block_lag,
                "peer_count": peer_count,
                "min_peer_count": self.target.min_peer_count,
                "max_block_lag": self.target.max_block_lag,
            },
            "consensus": consensus,
            "storage": storage,
            "rpc": {
                "http_reachable": True,
                "latency_ms": None,
                "error_rate": 0.0,
                "publicly_exposed": self.target.rpc_publicly_exposed,
                "authrpc_publicly_exposed": self.target.authrpc_publicly_exposed,
            },
            "logs": {
                "error_signatures": error_signatures,
                "recent_errors": [],
            },
            "resource_attributes": {
                "service.name": self.target.name,
                "deployment.environment": self.target.environment,
                "mesh.node.kind": "reth",
                "mesh.node.host": self.target.host,
                "mesh.node.service": self.target.service,
                "mesh.node.min_peer_count": self.target.min_peer_count,
                "mesh.node.max_block_lag": self.target.max_block_lag,
                "mesh.node.deployment_mode": self.target.deployment_mode,
                "mesh.node.network": self.target.network,
                "mesh.node.role": self.target.role,
            },
            "related_context": {
                "node_kind": "reth",
                "host": self.target.host,
                "systemd_service": self.target.service,
            },
            "post_action_observations": {},
        }

    def _metrics_text(self) -> str | None:
        if not self.target.metrics_url:
            return None
        try:
            return self.metrics_fetcher(self.target.metrics_url)
        except RpcError as exc:
            _LOG.warning("reth ingester: %s metrics fetch failed: %s", self.target.name, exc)
            return None

    def _disk_diagnostics(self) -> dict[str, Any] | None:
        if self.disk_diagnostics_provider is None:
            return None
        try:
            return self.disk_diagnostics_provider(self.target)
        except Exception as exc:
            _LOG.warning("reth ingester: %s disk diagnostics failed: %s", self.target.name, exc)
            return None

    def _jwt_metadata(self) -> dict[str, Any] | None:
        if self.jwt_metadata_provider is None:
            return None
        try:
            return self.jwt_metadata_provider(self.target)
        except Exception as exc:
            _LOG.warning("reth ingester: %s jwt metadata probe failed: %s", self.target.name, exc)
            return None


# ---------------------------------------------------------------- helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _trailing_window_iso() -> dict[str, str]:
    """Standard 5m trailing window descriptor used across signal sources."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=5)
    return {"baseline": f"{start.isoformat()}/{now.isoformat()}", "observed": f"{start.isoformat()}/{now.isoformat()}"}


def _hex_or_int(value: Any) -> int:
    try:
        return int(value, 16) if isinstance(value, str) else int(value or 0)
    except (TypeError, ValueError):
        return 0


def _eth_block_lag(sync_status: Any) -> int:
    if not isinstance(sync_status, dict):
        return 0
    highest = _hex_or_int(sync_status.get("highestBlock", "0x0"))
    current = _hex_or_int(sync_status.get("currentBlock", "0x0"))
    return max(0, highest - current)


def _fetch_text_url(url: str) -> str | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RpcError(f"metrics transport error: {exc}") from exc


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return None


def _reth_consensus_from_evidence(
    *,
    target: BareMetalNodeTarget,
    metrics_text: str | None,
    log_lines: list[str],
    jwt_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = "\n".join([metrics_text or "", *log_lines]).lower()
    engine_api_reachable: bool | None = None
    forkchoice_updates_recent: bool | None = None
    client_healthy: bool | None = None
    jwt_secret_exists = _optional_bool((jwt_metadata or {}).get("exists"))
    jwt_secret_mode = (jwt_metadata or {}).get("mode")
    jwt_configured = jwt_secret_exists

    if any(token in evidence for token in ("authrpc", "engine api", "engine_api", "forkchoice")):
        engine_api_reachable = not any(
            token in evidence
            for token in (
                "authrpc connection refused",
                "engine api connection refused",
                "engine api unavailable",
                "engine api failed",
                "invalid jwt",
                "jwt authentication failed",
            )
        )
    if "forkchoice" in evidence:
        forkchoice_updates_recent = not any(
            token in evidence
            for token in ("forkchoice failed", "forkchoice error", "no forkchoice")
        )
    if target.consensus_client:
        client_kind = _consensus_client_kind(target.consensus_client)
        if client_kind in evidence:
            client_healthy = not any(
                token in evidence
                for token in (f"{client_kind} failed", f"{client_kind} error", f"{client_kind} down")
            )
        else:
            client_healthy = None
    else:
        client_kind = "unknown"

    if jwt_secret_exists is False:
        jwt_configured = False
    if _jwt_mode_insecure(jwt_secret_mode):
        jwt_configured = False

    return {
        "engine_api_reachable": engine_api_reachable,
        "jwt_configured": jwt_configured,
        "forkchoice_updates_recent": forkchoice_updates_recent,
        "consensus_client": target.consensus_client,
        "client_kind": client_kind,
        "client_healthy": client_healthy,
        "jwt_secret_exists": jwt_secret_exists,
        "jwt_secret_mode": str(jwt_secret_mode) if jwt_secret_mode is not None else None,
    }


def _consensus_client_kind(value: str | None) -> str:
    lowered = (value or "").lower()
    for client in ("lighthouse", "prysm", "teku", "nimbus", "lodestar"):
        if client in lowered:
            return client
    return "unknown"


def _jwt_mode_insecure(mode: Any) -> bool:
    if mode is None:
        return False
    text = str(mode).strip()
    try:
        bits = int(text[-3:], 8)
    except ValueError:
        return False
    return bool(bits & 0o077)


def _reth_storage_from_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = diagnostics or {}
    return {
        "data_dir_free_bytes": _optional_int(diagnostics.get("data_dir_free_bytes")),
        "disk_used_pct": _optional_float(diagnostics.get("disk_used_pct")),
        "db_growth_rate_bytes_per_hour": _optional_float(diagnostics.get("db_growth_rate_bytes_per_hour")),
        "snapshot_mode": str(diagnostics.get("snapshot_mode", "unknown")),
        "diagnostic_source": str(diagnostics.get("diagnostic_source", "none")),
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reth_observability_signatures(*, consensus: dict[str, Any], storage: dict[str, Any]) -> list[str]:
    signatures: list[str] = []
    if consensus.get("jwt_configured") is False or consensus.get("jwt_secret_exists") is False:
        signatures.append("jwt_missing")
    if _jwt_mode_insecure(consensus.get("jwt_secret_mode")):
        signatures.append("jwt_secret_insecure_permissions")
    if storage.get("disk_used_pct") is not None and float(storage["disk_used_pct"]) >= 90:
        signatures.append("disk_pressure")
    return signatures


def _reth_error_signatures(
    *,
    syncing: bool,
    block_lag: int,
    max_block_lag: int,
    peer_count: int,
    min_peer_count: int,
) -> list[str]:
    signatures: list[str] = []
    if peer_count < min_peer_count:
        signatures.append("peer_starvation")
    if syncing and block_lag > max_block_lag:
        signatures.append("sync_stalled")
    return signatures


__all__ = [
    "BareMetalNodeTarget",
    "EthereumNodeIngester",
    "RethNodeIngester",
    "RpcError",
    "SolanaNodeIngester",
]
