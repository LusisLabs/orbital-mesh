#!/usr/bin/env python3
"""Probe local Compose monitoring targets and emit Mesh-shaped evidence."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any


def main() -> None:
    targets = (
        {
            "name": "rpc_gateway",
            "service": "compose-rpc-gateway",
            "url": os.environ.get("MESH_STACK_RPC_GATEWAY_URL", "http://rpc-gateway:8080/health"),
            "metric_name": "rpc.gateway.error_rate",
            "component_kind": "rpc_gateway",
        },
        {
            "name": "indexer",
            "service": "compose-indexer",
            "url": os.environ.get("MESH_STACK_INDEXER_URL", "http://indexer:8080/health"),
            "metric_name": "indexer.indexing_lag",
            "component_kind": "indexer",
        },
    )
    timeout = float(os.environ.get("MESH_STACK_TARGET_PROBE_TIMEOUT_SECONDS", "30"))
    deadline = time.time() + timeout
    results = []
    for target in targets:
        results.append(_probe_until_ready(target, deadline))

    failed = [result for result in results if result["status"] != "ready"]
    payload = {
        "schema_version": "mesh.compose_target_probe.v1",
        "observed_at": _now(),
        "targets": results,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(f"compose monitoring targets not ready: {[item['name'] for item in failed]}")


def _probe_until_ready(target: dict[str, str], deadline: float) -> dict[str, Any]:
    last_error = None
    while True:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(target["url"], timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            if response.status == 200 and body.get("status") == "ok":
                return {
                    "name": target["name"],
                    "status": "ready",
                    "url": target["url"],
                    "latency_ms": latency_ms,
                    "signal": _signal(target, latency_ms, body),
                }
            last_error = f"unexpected response status={response.status} body={body!r}"
        except Exception as exc:
            last_error = repr(exc)
        if time.time() >= deadline:
            return {
                "name": target["name"],
                "status": "unavailable",
                "url": target["url"],
                "error": last_error,
            }
        time.sleep(1)


def _signal(target: dict[str, str], latency_ms: float, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_type": "otel_metric_regression",
        "signal_id": f"sig_compose_{target['name']}",
        "observed_at": _now(),
        "environment": "development",
        "service": target["service"],
        "endpoint": target["url"],
        "source": "compose_target_probe",
        "comparison_window": {"baseline": "compose_boot", "observed": "probe"},
        "segment": {"customer_tier": "system", "region": "compose"},
        "component_kind": target["component_kind"],
        "metric_regression": {
            "metric_name": target["metric_name"],
            "metric_kind": "gauge",
            "unit": "ms" if target["name"] == "rpc_gateway" else "blocks",
            "baseline_value": body.get("baseline_value", 1.0),
            "observed_value": body.get("observed_value", latency_ms),
            "delta_pct": body.get("delta_pct", 0.0),
            "threshold_pct": body.get("threshold_pct", 30.0),
            "attributes": {"target": target["name"]},
        },
        "resource_attributes": {
            "service.name": target["service"],
            "deployment.environment": "development",
            "mesh.component.kind": target["component_kind"],
        },
        "related_context": {"component_kind": target["component_kind"]},
        "post_action_observations": {},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
