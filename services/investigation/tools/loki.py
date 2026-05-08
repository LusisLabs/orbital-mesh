"""Loki domain pack — read-only LogQL queries.

Three tools:

* ``query_range`` — LogQL range query, log lines for a time window.
* ``labels`` — list label names known to the Loki instance.
* ``label_values`` — list values for a given label.

Pure HTTP via ``urllib.request`` (no ``requests`` dep). Always-on at
the engine root when ``MESH_LOKI_URL`` is set.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any

from ..harness import RawToolOutput, ToolDefinition, ToolRegistry
from ._http import failure_result, http_get_json


DOMAIN = "loki"


def _build_definitions() -> tuple[ToolDefinition, ...]:
    schemas = {
        "query_range": {
            "query": {"type": "str", "required": True},
            "start_ts": {"type": "float", "required": False},
            "end_ts": {"type": "float", "required": False},
            "limit": {"type": "int", "required": False},
            "direction": {"type": "str", "required": False, "nullable": True},
        },
        "labels": {
            "start_ts": {"type": "float", "required": False},
            "end_ts": {"type": "float", "required": False},
        },
        "label_values": {
            "label": {"type": "str", "required": True},
            "start_ts": {"type": "float", "required": False},
            "end_ts": {"type": "float", "required": False},
        },
    }
    descriptions = {
        "query_range": "Run a LogQL range query and return matching log lines.",
        "labels": "List label names known to the Loki instance over a window.",
        "label_values": "List values for a given label over a window.",
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
            citations_kind="loki_query",
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
    """Register Loki tools backed by ``base_url``."""
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(definition.name, base_url, headers or {}))


def maybe_register_at_root(registry: ToolRegistry) -> bool:
    """Register iff ``MESH_LOKI_URL`` is set. Returns whether registration fired."""
    base_url = os.environ.get("MESH_LOKI_URL")
    if not base_url:
        return False
    register(registry, base_url=base_url)
    return True


def _make_invoker(tool_name: str, base_url: str, headers: dict[str, str]):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        path, params = _build_request(tool_name, args)
        if path is None:
            return failure_result(DOMAIN, tool_name, "could not build loki request (missing required args)")
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
            citations=[{"source_type": "loki_query", "source_ref": url}],
            valid=bool(body),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_request(tool_name: str, args: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    end_ts = float(args.get("end_ts") or time.time())
    start_ts = float(args.get("start_ts") or end_ts - 900.0)
    if tool_name == "query_range":
        query = str(args.get("query") or "").strip()
        if not query:
            return None, {}
        return "/loki/api/v1/query_range", {
            "query": query,
            "start": str(int(start_ts * 1e9)),  # Loki uses nanoseconds
            "end": str(int(end_ts * 1e9)),
            "limit": str(int(args.get("limit") or 100)),
            "direction": str(args.get("direction") or "backward"),
        }
    if tool_name == "labels":
        return "/loki/api/v1/labels", {
            "start": str(int(start_ts * 1e9)),
            "end": str(int(end_ts * 1e9)),
        }
    if tool_name == "label_values":
        label = str(args.get("label") or "").strip()
        if not label:
            return None, {}
        return f"/loki/api/v1/label/{urllib.parse.quote(label)}/values", {
            "start": str(int(start_ts * 1e9)),
            "end": str(int(end_ts * 1e9)),
        }
    return None, {}


def _summarize(tool_name: str, body: dict[str, Any]) -> str:
    if not isinstance(body, dict):
        return f"loki {tool_name}: non-dict response"
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    if tool_name == "query_range":
        result = data.get("result") if isinstance(data.get("result"), list) else []
        line_count = sum(len(stream.get("values", [])) for stream in result if isinstance(stream, dict))
        return f"loki query_range: streams={len(result)} lines={line_count}"
    if tool_name == "labels":
        labels = body.get("data") if isinstance(body.get("data"), list) else []
        return f"loki labels: count={len(labels)} sample={labels[:5]}"
    if tool_name == "label_values":
        values = body.get("data") if isinstance(body.get("data"), list) else []
        return f"loki label_values: count={len(values)} sample={values[:5]}"
    return f"loki {tool_name}: ok"
