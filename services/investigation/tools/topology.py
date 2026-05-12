"""Topology domain pack — read-only graph queries over ``InfraGraph``.

The graph is the typed view Mesh already builds for K8s relationships;
this pack exposes it as a tool surface the LLM (or any planner) can
query. Five tools cover the high-leverage relationship questions:

* ``topology_resolve_service_pods`` — which pods does this service select?
  Localizes ``service_selector_mismatch`` without re-parsing kubectl text.
* ``topology_pod_lineage`` — pod → owning deployment + backing service(s).
  Anchors RCA on "which workload is this pod part of?"
* ``topology_pod_node`` — pod → physical node it's scheduled on. Anchors
  node-affinity / taint / capacity hypotheses.
* ``topology_resource_neighbors`` — generic graph traversal. Lets the
  LLM ask "what depends on this resource?" without us anticipating
  every relationship question.
* ``topology_snapshot`` — full graph snapshot (capped). Useful when the
  LLM wants to summarize cluster state for the user.

Always-on root pack: ``maybe_register_at_root(registry, infra_graph)``
registers unconditionally as long as an ``InfraGraph`` instance is
provided. The graph may be empty (the populator hasn't run for this
trigger) and the tools return empty results in that case — they never
fail or crash. This is the "tools readily available on every run"
contract: the LLM always sees the same surface, the answers depend on
what the populator has captured.

Read-only by construction. ``InfraGraph`` exposes only query methods;
there is no write path through this pack.
"""

from __future__ import annotations

from typing import Any

from shared.mesh_runtime.infra_graph import InfraGraph

from ..harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


DOMAIN = "topology"


def _build_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="topology_resolve_service_pods",
            domain=DOMAIN,
            description="Return pods selected by a Kubernetes service (via label selector match).",
            args_schema={
                "service": {"type": "str", "required": True},
                "namespace": {"type": "str", "required": False, "nullable": True},
            },
            mutation_class="read_only",
            timeout_seconds=1.0,
            budget_cost=0.5,
            citations_kind="topology_graph",
        ),
        ToolDefinition(
            name="topology_pod_lineage",
            domain=DOMAIN,
            description="Return a pod's owning deployment, backing services, and scheduled node.",
            args_schema={
                "pod": {"type": "str", "required": True},
                "namespace": {"type": "str", "required": False, "nullable": True},
            },
            mutation_class="read_only",
            timeout_seconds=1.0,
            budget_cost=0.5,
            citations_kind="topology_graph",
        ),
        ToolDefinition(
            name="topology_pod_node",
            domain=DOMAIN,
            description="Return the physical node a pod is scheduled on (or null if unscheduled).",
            args_schema={
                "pod": {"type": "str", "required": True},
                "namespace": {"type": "str", "required": False, "nullable": True},
            },
            mutation_class="read_only",
            timeout_seconds=1.0,
            budget_cost=0.5,
            citations_kind="topology_graph",
        ),
        ToolDefinition(
            name="topology_resource_neighbors",
            domain=DOMAIN,
            description=(
                "Generic graph traversal: list neighbors of a resource, "
                "optionally filtered by edge kind and direction."
            ),
            args_schema={
                "kind": {"type": "str", "required": True},
                "name": {"type": "str", "required": True},
                "namespace": {"type": "str", "required": False, "nullable": True},
                "edge_kind": {"type": "str", "required": False, "nullable": True},
                "direction": {"type": "str", "required": False, "nullable": True},
            },
            mutation_class="read_only",
            timeout_seconds=1.0,
            budget_cost=0.5,
            citations_kind="topology_graph",
        ),
        ToolDefinition(
            name="topology_snapshot",
            domain=DOMAIN,
            description="Return a compact snapshot of the topology graph (node/edge counts + samples).",
            args_schema={
                "limit": {"type": "int", "required": False},
            },
            mutation_class="read_only",
            timeout_seconds=1.0,
            budget_cost=0.5,
            citations_kind="topology_graph",
        ),
    ]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_tool_definitions())


def register(registry: ToolRegistry, infra_graph: InfraGraph) -> None:
    """Register the five topology tools backed by ``infra_graph``."""
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(definition.name, infra_graph))


def maybe_register_at_root(registry: ToolRegistry, infra_graph: InfraGraph | None) -> bool:
    """Register at root iff an ``InfraGraph`` instance is provided.

    The graph may be empty — the populator runs per-trigger, not at
    engine startup — but the tools are always callable. They return
    empty results when the graph has no relevant data, which is the
    correct contract for "tools readily available on every run."
    """
    if infra_graph is None:
        return False
    register(registry, infra_graph)
    return True


def _make_invoker(tool_name: str, infra_graph: InfraGraph):
    if tool_name == "topology_resolve_service_pods":
        return _invoker_resolve_service_pods(infra_graph)
    if tool_name == "topology_pod_lineage":
        return _invoker_pod_lineage(infra_graph)
    if tool_name == "topology_pod_node":
        return _invoker_pod_node(infra_graph)
    if tool_name == "topology_resource_neighbors":
        return _invoker_resource_neighbors(infra_graph)
    if tool_name == "topology_snapshot":
        return _invoker_snapshot(infra_graph)
    raise KeyError(f"unknown topology tool: {tool_name}")


def _invoker_resolve_service_pods(infra_graph: InfraGraph):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        service = str(args.get("service") or "").strip()
        namespace = args.get("namespace")
        if not service:
            return _failure("topology_resolve_service_pods", "service is required")
        pods = infra_graph.neighbors(
            "service", service, namespace, edge_kinds=["selects"], direction="out"
        )
        pod_names = [p.get("name") for p in pods if p.get("kind") == "pod"]
        summary = f"service {service} selects {len(pod_names)} pod(s): {pod_names[:8]}"
        return RawToolOutput(
            output={"service": service, "namespace": namespace, "pods": pods},
            output_summary=summary,
            citations=[{"source_type": "topology_graph", "source_ref": f"selects:service:{service}"}],
            valid=bool(pods),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _invoker_pod_lineage(infra_graph: InfraGraph):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        pod = str(args.get("pod") or "").strip()
        namespace = args.get("namespace")
        if not pod:
            return _failure("topology_pod_lineage", "pod is required")
        pod_node = infra_graph.get_node("pod", pod, namespace)
        if pod_node is None:
            return RawToolOutput(
                output={"pod": pod, "namespace": namespace, "found": False},
                output_summary=f"pod {pod} not in graph",
                citations=[{"source_type": "topology_graph", "source_ref": f"pod:{pod}"}],
                valid=False,
                redaction_status="clean",
                status="completed",
            )
        inbound = infra_graph.neighbors("pod", pod, namespace, direction="in")
        services = [n for n in inbound if n.get("kind") == "service"]
        deployments = [n for n in inbound if n.get("kind") == "deployment"]
        node_neighbors = infra_graph.neighbors(
            "pod", pod, namespace, edge_kinds=["scheduled_on"], direction="out"
        )
        physical_node = node_neighbors[0] if node_neighbors else None
        summary = (
            f"pod {pod} owned by deployment={[d.get('name') for d in deployments]} "
            f"selected by services={[s.get('name') for s in services]} "
            f"on node={physical_node.get('name') if physical_node else 'unscheduled'}"
        )
        return RawToolOutput(
            output={
                "pod": pod_node,
                "services": services,
                "deployments": deployments,
                "node": physical_node,
            },
            output_summary=summary,
            citations=[{"source_type": "topology_graph", "source_ref": f"lineage:pod:{pod}"}],
            valid=True,
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _invoker_pod_node(infra_graph: InfraGraph):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        pod = str(args.get("pod") or "").strip()
        namespace = args.get("namespace")
        if not pod:
            return _failure("topology_pod_node", "pod is required")
        neighbors = infra_graph.neighbors(
            "pod", pod, namespace, edge_kinds=["scheduled_on"], direction="out"
        )
        node = neighbors[0] if neighbors else None
        summary = (
            f"pod {pod} -> node {node.get('name')}" if node else f"pod {pod} unscheduled"
        )
        return RawToolOutput(
            output={"pod": pod, "namespace": namespace, "node": node},
            output_summary=summary,
            citations=[{"source_type": "topology_graph", "source_ref": f"scheduled_on:pod:{pod}"}],
            valid=node is not None,
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _invoker_resource_neighbors(infra_graph: InfraGraph):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        kind = str(args.get("kind") or "").strip()
        name = str(args.get("name") or "").strip()
        namespace = args.get("namespace")
        edge_kind = args.get("edge_kind")
        direction = str(args.get("direction") or "both").lower()
        if direction not in {"in", "out", "both"}:
            return _failure(
                "topology_resource_neighbors",
                f"direction must be 'in' / 'out' / 'both', got {direction!r}",
            )
        if not kind or not name:
            return _failure("topology_resource_neighbors", "kind and name are required")
        edge_kinds = [edge_kind] if edge_kind else None
        neighbors = infra_graph.neighbors(
            kind, name, namespace, edge_kinds=edge_kinds, direction=direction
        )
        summary = (
            f"{kind}:{name} has {len(neighbors)} neighbor(s) "
            f"(direction={direction}, edge_kind={edge_kind or 'any'})"
        )
        return RawToolOutput(
            output={"kind": kind, "name": name, "namespace": namespace, "neighbors": neighbors},
            output_summary=summary,
            citations=[{"source_type": "topology_graph", "source_ref": f"neighbors:{kind}:{name}"}],
            valid=bool(neighbors),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _invoker_snapshot(infra_graph: InfraGraph):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        limit = int(args.get("limit") or 25)
        snapshot = infra_graph.snapshot()
        if snapshot is None:
            return RawToolOutput(
                output={"node_count": 0, "edge_count": 0, "nodes": [], "edges": []},
                output_summary="topology graph is empty",
                citations=[{"source_type": "topology_graph", "source_ref": "snapshot"}],
                valid=False,
                redaction_status="clean",
                status="completed",
            )
        nodes = [n.to_dict() for n in snapshot.nodes[:limit]]
        edges = [e.to_dict() for e in snapshot.edges[:limit]]
        kind_counts: dict[str, int] = {}
        for node in snapshot.nodes:
            kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1
        summary = (
            f"topology snapshot: {len(snapshot.nodes)} node(s), "
            f"{len(snapshot.edges)} edge(s); kinds={kind_counts}"
        )
        return RawToolOutput(
            output={
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
                "kind_counts": kind_counts,
                "nodes": nodes,
                "edges": edges,
            },
            output_summary=summary,
            citations=[{"source_type": "topology_graph", "source_ref": "snapshot"}],
            valid=bool(snapshot.nodes),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _failure(tool_name: str, message: str) -> RawToolOutput:
    return RawToolOutput(
        output={"error": message},
        output_summary=f"{tool_name} failed: {message[:200]}",
        citations=[{"source_type": "topology_graph", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )
