from __future__ import annotations

from typing import Any


RETH_PROBE_DEFINITIONS: dict[str, dict[str, str]] = {
    "json_rpc_peer_sync": {
        "source": "json_rpc",
        "purpose": "Read peer count, sync status, block lag, and head progress.",
    },
    "json_rpc_rpc_health": {
        "source": "json_rpc",
        "purpose": "Read RPC reachability, latency, and error-rate evidence.",
    },
    "consensus_status": {
        "source": "metrics_or_logs",
        "purpose": "Read consensus and Engine API reachability evidence.",
    },
    "disk_jwt_metadata": {
        "source": "filesystem",
        "purpose": "Read disk pressure and JWT metadata without reading secret contents.",
    },
    "systemd_status": {
        "source": "systemd",
        "purpose": "Read systemd service state and restart posture.",
    },
    "exposure_posture": {
        "source": "posture",
        "purpose": "Read public RPC/authrpc exposure posture.",
    },
    "recent_logs": {
        "source": "logs",
        "purpose": "Classify recent node log evidence for corruption, consensus, and RPC failures.",
    },
    "aggregate_reth_snapshot": {
        "source": "aggregate",
        "purpose": "Compatibility fallback that gathers the existing aggregate Reth snapshot.",
    },
}

UNSAFE_RETH_SIGNATURES: frozenset[str] = frozenset({
    "authrpc_exposed",
    "consensus_disconnected",
    "db_corruption_suspected",
    "disk_pressure",
    "filesystem_unsuitable",
    "jwt_missing",
    "jwt_secret_insecure_permissions",
    "node_unreachable",
    "rpc_exposed",
    "validator_duty_imminent",
})


def known_reth_probe_names() -> tuple[str, ...]:
    return tuple(RETH_PROBE_DEFINITIONS)


def probe_names_for_signatures(signatures: list[str], *, sparse: bool = False) -> tuple[str, ...]:
    names: list[str] = ["aggregate_reth_snapshot", "json_rpc_peer_sync", "json_rpc_rpc_health"]
    sigs = set(signatures)
    if "peer_starvation" in sigs:
        names.extend(["consensus_status", "recent_logs"])
    if "sync_stalled" in sigs:
        names.extend(["consensus_status", "disk_jwt_metadata", "recent_logs"])
    if "rpc_degraded" in sigs:
        names.extend(["exposure_posture", "recent_logs"])
    if sigs & UNSAFE_RETH_SIGNATURES:
        names.extend(["disk_jwt_metadata", "exposure_posture", "recent_logs", "systemd_status"])
    if sparse or not sigs:
        names.extend(["consensus_status", "disk_jwt_metadata", "exposure_posture", "recent_logs"])
    return sanitize_probe_names(names)


def sanitize_probe_names(names: list[str] | tuple[str, ...], *, max_probes: int | None = None) -> tuple[str, ...]:
    seen: set[str] = set()
    selected: list[str] = []
    for name in names:
        if name not in RETH_PROBE_DEFINITIONS or name in seen:
            continue
        selected.append(name)
        seen.add(name)
        if max_probes is not None and len(selected) >= max_probes:
            break
    return tuple(selected)


def build_probe_dicts(names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "probe_id": f"probe_{name}",
            "name": name,
            "purpose": RETH_PROBE_DEFINITIONS[name]["purpose"],
            "read_only": True,
            "source": RETH_PROBE_DEFINITIONS[name]["source"],
        }
        for name in names
    ]


def is_sparse_reth_signal(signal: dict[str, Any]) -> bool:
    required_sections = ("execution", "consensus", "storage", "rpc")
    return any(not isinstance(signal.get(section), dict) for section in required_sections)


def snapshot_for_probe(name: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    if name == "json_rpc_peer_sync":
        execution = snapshot.get("execution") if isinstance(snapshot.get("execution"), dict) else {}
        return _pick(
            execution,
            "peer_count",
            "min_peer_count",
            "syncing",
            "block_lag",
            "max_block_lag",
            "head_block",
        )
    if name == "json_rpc_rpc_health":
        rpc = snapshot.get("rpc") if isinstance(snapshot.get("rpc"), dict) else {}
        return _pick(rpc, "http_reachable", "latency_ms", "error_rate")
    if name == "consensus_status":
        consensus = snapshot.get("consensus") if isinstance(snapshot.get("consensus"), dict) else {}
        return _pick(
            consensus,
            "engine_api_reachable",
            "forkchoice_updates_recent",
            "client_healthy",
            "client_kind",
            "jwt_configured",
            "jwt_secret_exists",
        )
    if name == "disk_jwt_metadata":
        storage = snapshot.get("storage") if isinstance(snapshot.get("storage"), dict) else {}
        consensus = snapshot.get("consensus") if isinstance(snapshot.get("consensus"), dict) else {}
        payload = _pick(storage, "disk_used_pct", "data_dir_free_bytes", "snapshot_mode", "filesystem_type")
        payload.update(_pick(consensus, "jwt_configured", "jwt_secret_exists", "jwt_secret_mode"))
        return payload
    if name == "systemd_status":
        related = snapshot.get("related_context") if isinstance(snapshot.get("related_context"), dict) else {}
        attrs = snapshot.get("resource_attributes") if isinstance(snapshot.get("resource_attributes"), dict) else {}
        return {
            "systemd_service": related.get("systemd_service") or attrs.get("mesh.node.service"),
            "host": attrs.get("mesh.node.host"),
            "deployment_mode": (snapshot.get("node") or {}).get("deployment_mode")
            if isinstance(snapshot.get("node"), dict)
            else None,
        }
    if name == "exposure_posture":
        rpc = snapshot.get("rpc") if isinstance(snapshot.get("rpc"), dict) else {}
        return _pick(rpc, "publicly_exposed", "authrpc_publicly_exposed")
    if name == "recent_logs":
        logs = snapshot.get("logs") if isinstance(snapshot.get("logs"), dict) else {}
        return {
            "error_signatures": list(logs.get("error_signatures") or [])[:12],
            "recent_errors": _redact_lines(list(logs.get("recent_errors") or [])[:8]),
        }
    if name == "aggregate_reth_snapshot":
        return {
            "signal_type": snapshot.get("signal_type"),
            "signal_id": snapshot.get("signal_id"),
            "observed_at": snapshot.get("observed_at"),
            "source": snapshot.get("source"),
        }
    return {}


def citation_for_probe(name: str) -> dict[str, str]:
    source = RETH_PROBE_DEFINITIONS.get(name, {}).get("source", "unknown")
    return {"source_type": source, "source_ref": name}


def _pick(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: _redact_value(key, payload.get(key)) for key in keys if key in payload}


def _redact_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    lowered = key.lower()
    if "secret" in lowered or "token" in lowered or "password" in lowered:
        if "mode" in lowered or "exists" in lowered or "configured" in lowered:
            return value
        return "[redacted]"
    return value


def _redact_lines(lines: list[Any]) -> list[str]:
    redacted: list[str] = []
    for item in lines:
        line = str(item)
        for marker in ("jwt", "secret", "token", "password"):
            if marker in line.lower():
                line = "[redacted sensitive log line]"
                break
        redacted.append(line[:500])
    return redacted
