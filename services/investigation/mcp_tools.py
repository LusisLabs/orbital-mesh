"""MCP (Model Context Protocol) bridge for the investigation harness.

This is the architectural piece that lets Mesh consume tools from
external MCP servers — SREGym's MCP fleet, opensre's planned MCP
exposure, any future MCP-shaped tool source — without writing one
adapter per server.

Design — bridge, not transport:

* Mesh does **not** implement the MCP wire protocol here. The
  ``MCPClientProtocol`` is a duck-typed interface (``list_tools()``
  and ``call_tool(name, args)``); callers wire in their preferred
  client library (the official ``mcp`` SDK, FastMCP, a hand-rolled
  stdio bridge, etc.).
* This file's job is to **register** discovered MCP tools as
  ``ToolDefinition``s in our registry so the harness contract holds
  unchanged: critic, planner, loop, observability all keep working
  as if these were native tools.

Read-only enforcement:

* Discovery happens at registration. Each MCP-advertised tool turns
  into a separate ``ToolDefinition`` so the critic *can* see it.
* Each registered MCP tool's mutation_class is set from the caller's
  ``mutation_class_map`` (or defaults to ``read_only`` with a
  ``block_mutating=True`` floor). Servers that advertise mutating
  tools beyond the caller's allowlist get filtered out before
  reaching the registry.
* Per-server ``allow_tools`` allowlist gives the operator final say:
  even if an MCP server offers ``delete_everything``, if it's not
  in the allowlist the registry doesn't know it exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from .harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


@dataclass(frozen=True)
class MCPToolMeta:
    """Subset of MCP's tool advertisement that we care about."""

    name: str
    description: str
    input_schema: dict[str, Any]


class MCPClientProtocol(Protocol):
    """Caller-provided MCP client.

    Two methods are enough for the bridge:

    * ``list_tools()`` — return the server's advertised tools.
    * ``call_tool(name, args)`` — invoke one and return its result
      (any JSON-serializable value).

    Real implementations: ``mcp.ClientSession`` from the official
    Python SDK, FastMCP's HTTP client, a stdio JSON-RPC wrapper, etc.
    Callers translate their lib's shape into this minimal interface.
    """

    def list_tools(self) -> list[MCPToolMeta]: ...

    def call_tool(self, name: str, args: dict[str, Any]) -> Any: ...


def register_mcp_tools(
    registry: ToolRegistry,
    *,
    client: MCPClientProtocol,
    server_id: str,
    allow_tools: Iterable[str] | None = None,
    mutation_class_map: dict[str, str] | None = None,
    block_mutating: bool = True,
    domain: str = "mcp",
) -> list[str]:
    """Register MCP-advertised tools in ``registry``.

    Returns the list of qualified names (``<domain>:<server_id>:<tool>``)
    that were registered. Skips silently when the client refuses to
    list (raises) — no MCP server availability shouldn't kill engine
    startup.

    Tools are namespaced under ``server_id`` so two MCP servers
    advertising the same tool name (``get_logs`` from Loki MCP and
    ``get_logs`` from CloudWatch MCP) coexist.
    """

    try:
        advertised = list(client.list_tools())
    except Exception as exc:
        import logging
        logging.getLogger("mesh.mcp").warning(
            "mcp list_tools failed for %s: %s", server_id, exc,
        )
        return []

    allowlist = set(allow_tools) if allow_tools is not None else None
    mutation_map = dict(mutation_class_map or {})

    registered: list[str] = []
    for tool in advertised:
        if not isinstance(tool, MCPToolMeta) or not tool.name:
            continue
        if allowlist is not None and tool.name not in allowlist:
            continue
        mutation_class = mutation_map.get(tool.name, "read_only")
        if mutation_class != "read_only" and block_mutating:
            # Caller wants only read-only tools forwarded; mutating
            # advertisements are silently dropped. Operators that need
            # mutating MCP tools must opt in via mutation_class_map and
            # block_mutating=False.
            continue
        qualified_local = f"{server_id}__{tool.name}"
        definition = ToolDefinition(
            name=qualified_local,
            domain=domain,
            description=f"[mcp:{server_id}] {tool.description}",
            args_schema=_args_schema_from_mcp_input_schema(tool.input_schema),
            mutation_class=mutation_class,  # type: ignore[arg-type]
            timeout_seconds=15.0,
            budget_cost=1.5,
            citations_kind="mcp_call",
        )
        try:
            registry.register(definition, _make_mcp_invoker(client, tool.name, server_id))
        except ValueError:
            # Already registered (e.g. same server_id used twice).
            # Skip rather than crash.
            continue
        registered.append(definition.qualified_name)
    return registered


def _make_mcp_invoker(client: MCPClientProtocol, tool_name: str, server_id: str):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        try:
            result = client.call_tool(tool_name, args)
        except Exception as exc:
            return RawToolOutput(
                output={"server_id": server_id, "tool": tool_name, "error": str(exc)},
                output_summary=f"mcp:{server_id}:{tool_name} failed: {exc}",
                citations=[{"source_type": "mcp_call", "source_ref": f"{server_id}:{tool_name}"}],
                valid=False,
                redaction_status="clean",
                status="failed",
                error=str(exc),
            )
        summary = _summarize_mcp_result(server_id, tool_name, result)
        return RawToolOutput(
            output={"server_id": server_id, "tool": tool_name, "result": result},
            output_summary=summary,
            citations=[{"source_type": "mcp_call", "source_ref": f"{server_id}:{tool_name}"}],
            valid=result is not None,
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _summarize_mcp_result(server_id: str, tool_name: str, result: Any) -> str:
    if result is None:
        return f"mcp:{server_id}:{tool_name} -> null"
    if isinstance(result, str):
        return f"mcp:{server_id}:{tool_name} -> {result[:400]}"
    if isinstance(result, (dict, list)):
        import json

        return f"mcp:{server_id}:{tool_name} -> {json.dumps(result)[:400]}"
    return f"mcp:{server_id}:{tool_name} -> {str(result)[:400]}"


def _args_schema_from_mcp_input_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Translate an MCP tool's JSON Schema into our minimal field map.

    The harness critic only validates type and required-ness today;
    richer JSON Schema features (oneOf, format, regex) are not enforced
    here. The MCP server itself remains the authoritative validator —
    we just want enough surface to catch obvious mistakes early.
    """
    schema = input_schema or {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") if isinstance(schema.get("required"), list) else [])
    out: dict[str, Any] = {}
    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict):
            continue
        type_name = str(field_schema.get("type") or "any").lower()
        out[field_name] = {
            "type": _map_json_schema_type(type_name),
            "required": field_name in required,
        }
    return out


def _map_json_schema_type(json_type: str) -> str:
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "object": "dict",
        "array": "list",
    }.get(json_type, "any")


# ---------------------------------------------------------------------
# Optional auto-registration helpers
# ---------------------------------------------------------------------


def maybe_register_mcp_at_root(
    registry: ToolRegistry,
    *,
    client_factory: Callable[[str], MCPClientProtocol] | None = None,
) -> int:
    """Register MCP tools from ``MESH_MCP_SERVERS`` env if a factory is supplied.

    The env var is a comma-separated list of ``id=url`` pairs:
    ``MESH_MCP_SERVERS=sregym=http://localhost:8000,custom=stdio:./srv``.
    The ``client_factory`` constructs an ``MCPClientProtocol`` from a
    URL — Mesh doesn't ship one. Without a factory, the function
    returns 0 and registration is a no-op. This keeps MCP transport
    out of Mesh's hard dependencies until a deployment needs it.

    Returns the number of tools registered across all servers.
    """
    if client_factory is None:
        return 0
    raw = os.environ.get("MESH_MCP_SERVERS")
    if not raw:
        return 0
    total = 0
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        server_id, server_url = entry.split("=", 1)
        server_id = server_id.strip()
        server_url = server_url.strip()
        if not server_id or not server_url:
            continue
        try:
            client = client_factory(server_url)
        except Exception:
            import logging
            logging.getLogger("mesh.mcp").exception(
                "mcp client_factory failed for server %s", server_id,
            )
            continue
        registered = register_mcp_tools(registry, client=client, server_id=server_id)
        total += len(registered)
    return total
