"""Loki (logs) + Jaeger (traces) read-only domain pack.

Two domains in one module because they share a transport (HTTP) and a
short shape:

* ``loki:query_range`` — LogQL range query.
* ``loki:labels`` — list label names.
* ``loki:label_values`` — list values for a label.
* ``jaeger:get_services`` — list services known to Jaeger.
* ``jaeger:get_traces`` — recent traces for a service.
* ``jaeger:get_dependencies`` — service dependency graph for a window.

Both are pure-HTTP, both ship with a hand-rolled tiny client (we avoid
``requests`` as a hard dep — ``urllib.request`` is sufficient for these
fixed read endpoints).

Read-only enforcement:

* Critic blocks anything not classified ``read_only``.
* The clients only know GET endpoints. There is no "post arbitrary
  log line" or "create span" surface.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


LOKI_DOMAIN = "loki"
JAEGER_DOMAIN = "jaeger"
MAX_RESPONSE_BYTES = 96 * 1024


# ---------------------------------------------------------------------
# Loki
# ---------------------------------------------------------------------


def loki_tool_definitions() -> list[ToolDefinition]:
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
    return [
        ToolDefinition(
            name=name,
            domain=LOKI_DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.5,
            citations_kind="loki_query",
        )
        for name, description in descriptions.items()
    ]


LOKI_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(loki_tool_definitions())


def register_loki_tools(
    registry: ToolRegistry,
    *,
    base_url: str,
    headers: dict[str, str] | None = None,
) -> None:
    """Register Loki tools backed by a real (or stub) HTTP base URL."""
    for definition in LOKI_TOOL_DEFINITIONS:
        registry.register(definition, _make_loki_invoker(definition.name, base_url, headers or {}))


def _make_loki_invoker(tool_name: str, base_url: str, headers: dict[str, str]):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        path, params = _build_loki_request(tool_name, args)
        if path is None:
            return _failure(LOKI_DOMAIN, tool_name, "could not build loki request (missing required args)")
        url = f"{base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body, error = _http_get_json(url, headers=headers, timeout=10.0)
        if error:
            return _failure(LOKI_DOMAIN, tool_name, error)
        summary = _summarize_loki(tool_name, body)
        return RawToolOutput(
            output=body,
            output_summary=summary,
            citations=[{"source_type": "loki_query", "source_ref": url}],
            valid=bool(body),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_loki_request(
    tool_name: str,
    args: dict[str, Any],
) -> tuple[str | None, dict[str, str]]:
    end_ts = float(args.get("end_ts") or time.time())
    start_ts = float(args.get("start_ts") or end_ts - 900.0)
    if tool_name == "query_range":
        query = str(args.get("query") or "").strip()
        if not query:
            return None, {}
        return "/loki/api/v1/query_range", {
            "query": query,
            "start": str(int(start_ts * 1e9)),  # Loki wants nanoseconds
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


def _summarize_loki(tool_name: str, body: dict[str, Any]) -> str:
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


# ---------------------------------------------------------------------
# Jaeger
# ---------------------------------------------------------------------


def jaeger_tool_definitions() -> list[ToolDefinition]:
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
    return [
        ToolDefinition(
            name=name,
            domain=JAEGER_DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.5,
            citations_kind="jaeger_query",
        )
        for name, description in descriptions.items()
    ]


JAEGER_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(jaeger_tool_definitions())


def register_jaeger_tools(
    registry: ToolRegistry,
    *,
    base_url: str,
    headers: dict[str, str] | None = None,
) -> None:
    for definition in JAEGER_TOOL_DEFINITIONS:
        registry.register(definition, _make_jaeger_invoker(definition.name, base_url, headers or {}))


def _make_jaeger_invoker(tool_name: str, base_url: str, headers: dict[str, str]):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        path, params = _build_jaeger_request(tool_name, args)
        if path is None:
            return _failure(JAEGER_DOMAIN, tool_name, "could not build jaeger request (missing required args)")
        url = f"{base_url.rstrip('/')}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        body, error = _http_get_json(url, headers=headers, timeout=10.0)
        if error:
            return _failure(JAEGER_DOMAIN, tool_name, error)
        summary = _summarize_jaeger(tool_name, body)
        return RawToolOutput(
            output=body,
            output_summary=summary,
            citations=[{"source_type": "jaeger_query", "source_ref": url}],
            valid=bool(body),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_jaeger_request(
    tool_name: str,
    args: dict[str, Any],
) -> tuple[str | None, dict[str, str]]:
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


def _summarize_jaeger(tool_name: str, body: Any) -> str:
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


# ---------------------------------------------------------------------
# Shared HTTP + auto-registration
# ---------------------------------------------------------------------


def _http_get_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
) -> tuple[Any, str | None]:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return None, f"http {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, f"url error: {exc.reason}"
    except OSError as exc:
        return None, f"io error: {exc}"
    if len(raw) > MAX_RESPONSE_BYTES:
        return None, "response too large"
    try:
        return json.loads(raw.decode("utf-8") or "null"), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"decode error: {exc}"


def _failure(domain: str, tool_name: str, message: str) -> RawToolOutput:
    return RawToolOutput(
        output={"error": message},
        output_summary=f"{domain}:{tool_name} failed: {message[:400]}",
        citations=[{"source_type": f"{domain}_query", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )


def maybe_register_loki_at_root(registry: ToolRegistry) -> bool:
    base_url = os.environ.get("MESH_LOKI_URL")
    if not base_url:
        return False
    register_loki_tools(registry, base_url=base_url)
    return True


def maybe_register_jaeger_at_root(registry: ToolRegistry) -> bool:
    base_url = os.environ.get("MESH_JAEGER_URL")
    if not base_url:
        return False
    register_jaeger_tools(registry, base_url=base_url)
    return True
