"""Prometheus domain pack for the investigation harness.

Lifts the existing ``shared.mesh_runtime.otel.PrometheusClient`` (used
today only by the feedback stage) into the harness as two read-only
tools:

* ``query_metrics_instant`` — current value of a PromQL expression.
* ``query_metrics_range`` — sampled values over a window.

This is the third domain pack on the harness (after ``cloudops`` and
``reth``) and the first that talks to a live external API. The
contract is the same: a ``ToolRegistry`` holds ``ToolDefinition``s,
the planner picks calls, the critic enforces read-only, the registry
invokes. No ``rules``, no ``write``, no ``delete`` — the Prometheus
HTTP API at ``/api/v1/query`` and ``/api/v1/query_range`` is
read-only by construction, so the mutation classification is honest.

The opensre tool surface inspired the naming and args shape (their
``execute_prometheus_query`` is roughly equivalent), but the
implementation reuses Mesh's existing client instead of pulling in
``app/services/prometheus_client.py`` from a different repo. Less
new code, identical safety floor.
"""

from __future__ import annotations

import time
from typing import Any

from shared.mesh_runtime.otel import PrometheusClient

from .harness import (
    InvestigationLoopState,
    LoopDecision,
    RawToolOutput,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    make_call,
)


PROMETHEUS_DOMAIN = "prometheus"


_TOOLS: tuple[tuple[str, str], ...] = (
    ("query_metrics_instant", "Run a PromQL instant query; return the first scalar value or null."),
    ("query_metrics_range", "Run a PromQL range query over [start_ts, end_ts]; return up to N samples."),
)


def prometheus_tool_definitions() -> list[ToolDefinition]:
    """Return the read-only Prometheus tool definitions."""
    instant_args = {
        "query": {"type": "str", "required": True},
    }
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
    return [
        ToolDefinition(
            name=name,
            domain=PROMETHEUS_DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.0,
            citations_kind="prometheus_query",
        )
        for name, description in _TOOLS
    ]


PROMETHEUS_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(prometheus_tool_definitions())
PROMETHEUS_TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in PROMETHEUS_TOOL_DEFINITIONS)


def register_prometheus_tools(registry: ToolRegistry, client: PrometheusClient) -> None:
    """Register the Prometheus tools backed by an existing client.

    The client is constructed by the caller — this lets a benchmark
    backend supply a fixture client (e.g. an in-memory stub during
    tests) and a production caller supply a real HTTP client without
    the registry knowing or caring.
    """
    for definition in PROMETHEUS_TOOL_DEFINITIONS:
        registry.register(definition, _make_prometheus_invoker(definition.name, client))


def _make_prometheus_invoker(tool_name: str, client: PrometheusClient):
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


class PrometheusInstantPlanner:
    """Minimal planner that fires a single instant query and stops.

    Used for unit-testing the harness against the prometheus domain
    without an external server. Real callers pair Prometheus with a
    domain-specific planner (e.g. the existing CloudOps / Reth
    planners would gain a Prometheus rule per signature once the
    NativeSelector lands).
    """

    domain: str = PROMETHEUS_DOMAIN

    def __init__(self, query: str) -> None:
        self._query = query

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        if any(call.tool_name == "query_metrics_instant" for call in state.tool_calls):
            return LoopDecision(action="stop", reason="prometheus_instant_complete", confidence=0.6)
        definition = next(d for d in PROMETHEUS_TOOL_DEFINITIONS if d.name == "query_metrics_instant")
        call: ToolCall = make_call(
            tool=definition,
            args={"query": self._query},
            purpose="prometheus_instant",
        )
        return LoopDecision(action="continue", next_calls=(call,), reason="prometheus_instant", confidence=0.5)
