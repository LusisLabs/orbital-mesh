from __future__ import annotations

import time
from typing import Any

from services.ingest.bare_metal_node import BareMetalNodeTarget, RethNodeIngester
from services.evidence.service import ProbeResult, ProbeRunner, _probe_results_from_plan
from shared.mesh_runtime import RuntimeConfig


def build_configured_probe_runner(config: RuntimeConfig) -> ProbeRunner:
    targets = [
        BareMetalNodeTarget.from_dict(raw)
        for raw in config.bare_metal_node_targets
        if str(raw.get("kind", "")).lower() == "reth"
    ]

    def run(
        signal: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[ProbeResult]]:
        target = _match_reth_target(signal, targets)
        if target is None:
            typed = _probe_results_from_plan(signal, investigation_plan, default_source="inline")
            if typed and all(result.success for result in typed):
                return signal, typed
            return signal, [
                ProbeResult(
                    name="reth_target_resolution",
                    source="configured_targets",
                    success=False,
                    error="no_matching_reth_target",
                    citations=[{"source_type": "config", "source_ref": "MESH_BARE_METAL_NODE_TARGETS"}],
                )
            ]

        started = time.monotonic()
        enriched = RethNodeIngester(target).build_signal()
        latency_ms = (time.monotonic() - started) * 1000
        if enriched is None:
            return signal, [
                ProbeResult(
                    name="reth_live_probe",
                    source="json_rpc",
                    success=False,
                    latency_ms=latency_ms,
                    error="reth_ingester_returned_none",
                    citations=[{"source_type": "target", "source_ref": target.name}],
                )
            ]

        typed = _probe_results_from_plan(enriched, investigation_plan, default_source="live_probe")
        if typed:
            return enriched, typed

        return enriched, [
            ProbeResult(
                name="reth_live_probe",
                source="json_rpc",
                success=True,
                latency_ms=latency_ms,
                payload={"target": target.name, "signal_id": enriched.get("signal_id")},
                citations=[{"source_type": "target", "source_ref": target.name}],
            )
        ]

    return run


def _match_reth_target(signal: dict[str, Any], targets: list[BareMetalNodeTarget]) -> BareMetalNodeTarget | None:
    node = signal.get("node") if isinstance(signal.get("node"), dict) else {}
    resource_attributes = (
        signal.get("resource_attributes") if isinstance(signal.get("resource_attributes"), dict) else {}
    )
    host = str(resource_attributes.get("mesh.node.host") or node.get("name") or "")
    service = str(resource_attributes.get("mesh.node.service") or signal.get("service") or "")
    node_name = str(node.get("name") or "")

    for target in targets:
        if host and target.host == host:
            return target
        if node_name and target.name == node_name:
            return target
        if service and target.service == service:
            return target
    return targets[0] if len(targets) == 1 else None
