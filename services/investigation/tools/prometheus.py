"""Prometheus domain pack — read-only metrics queries.

Two tools:

* ``query_metrics_instant`` — current value of a PromQL expression.
* ``query_metrics_range`` — sampled values over a window.

Backed by ``shared.mesh_runtime.otel.PrometheusClient`` (reused from
the feedback stage). Always-on at the engine root when
``RuntimeConfig.prometheus_url`` is set.
"""

from __future__ import annotations

import time
from typing import Any

from shared.mesh_runtime.otel import PrometheusClient

from ..harness import (
    InvestigationLoopState,
    LoopDecision,
    RawToolOutput,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    make_call,
)


DOMAIN = "prometheus"


def _build_definitions() -> tuple[ToolDefinition, ...]:
    instant_args = {"query": {"type": "str", "required": True}}
    range_args = {
        "query": {"type": "str", "required": True},
        "start_ts": {"type": "float", "required": True},
        "end_ts": {"type": "float", "required": True},
        "step_seconds": {"type": "int", "required": False},
    }
    schemas = {
        "query_metrics_instant": instant_args,
        "query_metrics_range": range_args,
    }
    descriptions = {
        "query_metrics_instant": "Run a PromQL instant query; return the first scalar value or null.",
        "query_metrics_range": "Run a PromQL range query over [start_ts, end_ts]; return up to N samples.",
    }
    return tuple(
        ToolDefinition(
            name=name,
            domain=DOMAIN,
            description=descriptions[name],
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.0,
            citations_kind="prometheus_query",
        )
        for name in schemas
    )


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = _build_definitions()


def register(registry: ToolRegistry, client: PrometheusClient) -> None:
    """Register the Prometheus tools backed by ``client``."""
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(definition.name, client))


def maybe_register_at_root(registry: ToolRegistry, config: Any) -> bool:
    """Register iff ``RuntimeConfig.prometheus_url`` is set. Returns whether registration fired."""
    prometheus_url = getattr(config, "prometheus_url", None)
    if not prometheus_url:
        return False
    timeout = getattr(config, "prometheus_query_timeout_seconds", 10.0)
    client = PrometheusClient(prometheus_url, timeout_seconds=timeout)
    register(registry, client)
    return True


def _make_invoker(tool_name: str, client: PrometheusClient):
    if tool_name == "query_metrics_instant":

        def invoke(args: dict[str, Any]) -> RawToolOutput:
            query = str(args.get("query") or "")
            value = client.instant_query(query)
            valid = value is not None
            summary = f"prometheus instant: {query} = {value if valid else 'no_data'}"
            return RawToolOutput(
                output={"query": query, "value": value},
                output_summary=summary,
                citations=[{"source_type": "prometheus_query", "source_ref": query[:200]}],
                valid=valid,
                redaction_status="clean",
                status="completed",
            )

        return invoke

    if tool_name == "query_metrics_range":

        def invoke(args: dict[str, Any]) -> RawToolOutput:
            query = str(args.get("query") or "")
            start_ts = float(args.get("start_ts") or 0.0)
            end_ts = float(args.get("end_ts") or time.time())
            step_seconds = int(args.get("step_seconds") or 60)
            samples = client.range_query(query, start_ts, end_ts, step_seconds=step_seconds)
            valid = bool(samples)
            stats = _series_stats(samples) if valid else {}
            summary = (
                f"prometheus range: {query} samples={len(samples)} "
                + " ".join(f"{key}={value:.3f}" for key, value in stats.items())
            )
            return RawToolOutput(
                output={"query": query, "samples": samples, "stats": stats},
                output_summary=summary,
                citations=[{"source_type": "prometheus_query_range", "source_ref": query[:200]}],
                valid=valid,
                redaction_status="clean",
                status="completed",
            )

        return invoke

    raise KeyError(f"unknown prometheus tool: {tool_name}")


def _series_stats(samples: list[tuple[float, float]]) -> dict[str, float]:
    if not samples:
        return {}
    values = [value for _, value in samples]
    values_sorted = sorted(values)
    mid = len(values_sorted) // 2
    median = (
        values_sorted[mid]
        if len(values_sorted) % 2 == 1
        else (values_sorted[mid - 1] + values_sorted[mid]) / 2.0
    )
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "median": median,
    }


class InstantPlanner:
    """Single-instant-query planner. Used for harness tests against a stub client."""

    domain: str = DOMAIN

    def __init__(self, query: str) -> None:
        self._query = query

    def plan(self, *, state: InvestigationLoopState, trigger_context: dict[str, Any]) -> LoopDecision:
        if any(call.tool_name == "query_metrics_instant" for call in state.tool_calls):
            return LoopDecision(action="stop", reason="prometheus_instant_complete", confidence=0.6)
        definition = next(d for d in TOOL_DEFINITIONS if d.name == "query_metrics_instant")
        call: ToolCall = make_call(tool=definition, args={"query": self._query}, purpose="prometheus_instant")
        return LoopDecision(action="continue", next_calls=(call,), reason="prometheus_instant", confidence=0.5)
