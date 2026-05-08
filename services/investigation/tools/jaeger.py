"""Jaeger domain pack — read-only distributed-trace queries.

Three tools:

* ``get_services`` — list services known to Jaeger.
* ``get_traces`` — recent traces for a service, optionally filtered.
* ``get_dependencies`` — service-to-service dependency graph.

Pure HTTP via ``urllib.request``. Always-on at the engine root when
``MESH_JAEGER_URL`` is set.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Any

from ..harness import RawToolOutput, ToolDefinition, ToolRegistry
from ._http import failure_result, http_get_json


DOMAIN = "jaeger"


def _build_definitions() -> tuple[ToolDefinition, ...]:
    schemas = {
        "get_services": {},
        "get_traces": {
            "service": {"type": "str", "required": True},
            "operation": {"type": "str", "required": False, "nullable": True},
            "lookback_seconds": {"type": "int", "required": False},
            "limit": {"type": "int", "required": False},
            "tags": {"type": "dict", "required": False, "nullable": True},
        },
        "get_dependencies": {
            "lookback_seconds": {"type": "int", "required": False},
        },
    }
    descriptions = {
        "get_services": "List services known to the Jaeger instance.",
        "get_traces": "List recent traces for a service, optionally filtered by operation/tags.",
        "get_dependencies": "List service-to-service call counts over a window.",
    }
    return tuple(
        ToolDefinition(
            name=name,
            domain=DOMAIN,
            description=descriptions[name],
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.5,
            citations_kind="jaeger_query",
        )
        for name in schemas
    )


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = _build_definitions()


def register(
    registry: ToolRegistry,
    *,
    base_url: str,
    headers: dict[str, str] | None = None,
) -> None:
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(definition.name, base_url, headers or {}))


def maybe_register_at_root(registry: ToolRegistry) -> bool:
    """Register iff ``MESH_JAEGER_URL`` is set. Returns whether registration fired."""
    base_url = os.environ.get("MESH_JAEGER_URL")
    if not base_url:
        return False
    register(registry, base_url=base_url)
    return True


def _make_invoker(tool_name: str, base_url: str, headers: dict[str, str]):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        path, params = _build_request(tool_name, args)
        if path is None:
            return failure_result(DOMAIN, tool_name, "could not build jaeger request (missing required args)")
        url = f"{base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body, error = http_get_json(url, headers=headers, timeout=10.0)
        if error:
            return failure_result(DOMAIN, tool_name, error)
        summary = _summarize(tool_name, body)
        return RawToolOutput(
            output=body,
            output_summary=summary,
            citations=[{"source_type": "jaeger_query", "source_ref": url}],
            valid=bool(body),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_request(tool_name: str, args: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    end_ts = time.time()
    lookback = int(args.get("lookback_seconds") or 1800)
    start_ts = end_ts - lookback
    if tool_name == "get_services":
        return "/api/services", {}
    if tool_name == "get_traces":
        service = str(args.get("service") or "").strip()
        if not service:
            return None, {}
        params: dict[str, str] = {
            "service": service,
            "start": str(int(start_ts * 1e6)),  # Jaeger uses microseconds
            "end": str(int(end_ts * 1e6)),
            "limit": str(int(args.get("limit") or 20)),
        }
        operation = args.get("operation")
        if operation:
            params["operation"] = str(operation)
        tags = args.get("tags") if isinstance(args.get("tags"), dict) else None
        if tags:
            params["tags"] = json.dumps(tags)
        return "/api/traces", params
    if tool_name == "get_dependencies":
        return "/api/dependencies", {
            "endTs": str(int(end_ts * 1000)),  # milliseconds
            "lookback": str(int(lookback * 1000)),
        }
    return None, {}


def _summarize(tool_name: str, body: Any) -> str:
    if tool_name == "get_services":
        data = body.get("data") if isinstance(body, dict) else None
        services = data if isinstance(data, list) else []
        return f"jaeger services: count={len(services)} sample={services[:5]}"
    if tool_name == "get_traces":
        data = body.get("data") if isinstance(body, dict) else None
        traces = data if isinstance(data, list) else []
        return f"jaeger traces: count={len(traces)}"
    if tool_name == "get_dependencies":
        data = body.get("data") if isinstance(body, dict) else None
        deps = data if isinstance(data, list) else []
        return f"jaeger deps: edges={len(deps)}"
    return f"jaeger {tool_name}: ok"
