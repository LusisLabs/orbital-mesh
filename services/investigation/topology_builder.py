"""Populate the InfraGraph from Cloud-OpsBench snapshot text.

``shared.mesh_runtime.infra_graph.InfraGraph`` is the typed graph the
control plane already maintains for live clusters; for benchmark and
LLM-driven investigations the graph sits empty because nothing parses
snapshot tool_cache content into nodes + edges. This module is the
bridge: a snapshot-text parser plus an idempotent ``populate(...)``
entrypoint the runtime engine calls once per run.

Scope (intentionally narrow for v1):

* **Pod nodes** — name, namespace, labels, status, service_account,
  controlled_by_kind/name, node, image, container_ports.
* **Service nodes** — name, namespace, selectors, ports.
* **Node nodes** — derived from pod ``Node:`` references.
* **ReplicaSet nodes** — derived from pod ``Controlled By:`` lines.
* **Edges:**
  * ``selects`` (service → pod, matched by label intersection).
  * ``owns`` (replicaset → pod, from ``Controlled By:``).
  * ``scheduled_on`` (pod → node).

That's enough to power the high-leverage topology tools
(``topology_resolve_service_pods``, ``topology_pod_lineage``,
``topology_pod_node``) and to localize ``service_selector_mismatch``
faults — the most common relationship failure family in
Cloud-OpsBench. Deeper parsing (secret/configmap mounts, deployment
hierarchy via replicaset → deployment chain, node affinity / taints)
lands in a follow-up PR alongside the analyzers that need it.

Parsing strategy: regex over ``kubectl describe`` text. Cloud-OpsBench
snapshots are stable kubectl output so this is reliable enough for
the benchmark surface. Live clusters would call ``kubectl get -o yaml``
instead — that's a separate populator we add later.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from shared.mesh_runtime.infra_graph import GraphEdge, GraphNode, InfraGraph


_DESCRIBE_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 /\-]+):\s*(.*)$")
_LABEL_LINE_RE = re.compile(r"^\s+([a-zA-Z0-9._/\-]+)=(.*)$")
_CONTROLLED_BY_RE = re.compile(r"^([A-Za-z]+)/([A-Za-z0-9._\-]+)$")
_NODE_FIELD_RE = re.compile(r"^([A-Za-z0-9._\-]+)(?:/[\d.:]+)?$")
# ReplicaSet names are ``<deployment>-<hash>`` where ``<hash>`` is the
# pod-template-hash (a 5-10 char alphanumeric Kubernetes assigns).
# Stripping it gives the deployment, which is what the graph models.
_RS_HASH_TAIL_RE = re.compile(r"-[a-z0-9]{5,10}$")


def populate(
    infra_graph: InfraGraph,
    *,
    snapshot: dict[str, Any] | None = None,
    namespace_hint: str | None = None,
) -> dict[str, int]:
    """Parse ``snapshot`` (CloudOps tool_cache) into ``infra_graph``.

    Returns ``{"nodes": N, "edges": M}`` for telemetry. Idempotent
    against the same snapshot — ``InfraGraph.update_snapshot`` replaces
    the graph wholesale so calling this twice with the same input is
    safe but wasteful.

    When ``snapshot`` is ``None`` or doesn't contain a parseable
    ``tool_cache``-shaped dict, this is a no-op (returns zeros). That
    lets the runtime engine call it unconditionally; production
    deployments without snapshot signals just get an empty graph and
    the topology tools return empty results.
    """
    if not isinstance(snapshot, dict):
        return {"nodes": 0, "edges": 0}
    cache = _extract_tool_cache(snapshot)
    if not cache:
        return {"nodes": 0, "edges": 0}

    pods, pod_attrs = _parse_pods(cache)
    services, service_attrs = _parse_services(cache, default_namespace=namespace_hint)

    nodes: list[GraphNode] = []
    seen_nodes: set[str] = set()

    def _add(node: GraphNode) -> None:
        if node.key in seen_nodes:
            return
        seen_nodes.add(node.key)
        nodes.append(node)

    for pod_name, attrs in pod_attrs.items():
        ns = attrs.get("namespace") or namespace_hint
        # Compute owning deployment first so we can stamp it on the
        # pod node's attributes. Skipping the intermediate ReplicaSet
        # keeps the graph in the human-facing workload kinds the
        # InfraGraph schema declares.
        deployment_name = _deployment_from_controller(
            attrs.get("controlled_by_kind"), attrs.get("controlled_by_name")
        )
        if deployment_name:
            attrs["owning_deployment"] = deployment_name
        _add(
            GraphNode(
                kind="pod",
                name=pod_name,
                namespace=ns,
                labels=dict(attrs.get("labels") or {}),
                attributes={
                    "status": attrs.get("status"),
                    "node": attrs.get("node"),
                    "service_account": attrs.get("service_account"),
                    "controlled_by_kind": attrs.get("controlled_by_kind"),
                    "controlled_by_name": attrs.get("controlled_by_name"),
                    "owning_deployment": deployment_name,
                    "containers": attrs.get("containers") or [],
                },
            )
        )
        if attrs.get("node"):
            _add(GraphNode(kind="node", name=str(attrs["node"]), namespace=None))
        if deployment_name:
            _add(GraphNode(kind="deployment", name=deployment_name, namespace=ns))

    for svc_name, attrs in service_attrs.items():
        _add(
            GraphNode(
                kind="service",
                name=svc_name,
                namespace=attrs.get("namespace") or namespace_hint,
                labels=dict(attrs.get("labels") or {}),
                attributes={
                    "selector": dict(attrs.get("selector") or {}),
                    "ports": list(attrs.get("ports") or []),
                    "type": attrs.get("type"),
                },
            )
        )

    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def _emit_edge(edge: GraphEdge) -> None:
        signature = (edge.kind, edge.source, edge.target)
        if signature in seen_edges:
            return
        seen_edges.add(signature)
        edges.append(edge)

    pod_by_key = {pod.key: pod for pod in nodes if pod.kind == "pod"}
    service_by_key = {svc.key: svc for svc in nodes if svc.kind == "service"}

    # Edge: selects (service → pod) — service selector ⊆ pod labels.
    for svc in service_by_key.values():
        selector = svc.attributes.get("selector") or {}
        if not selector:
            continue
        for pod in pod_by_key.values():
            if pod.namespace != svc.namespace:
                continue
            pod_labels = pod.labels or {}
            if all(pod_labels.get(key) == value for key, value in selector.items()):
                _emit_edge(GraphEdge(kind="selects", source=svc.key, target=pod.key))

    # Edges from per-pod attrs: scheduled_on + owns (replicaset → pod).
    for pod in pod_by_key.values():
        node_name = pod.attributes.get("node")
        if node_name:
            node_key = f"node:_cluster:{node_name}"
            if node_key in seen_nodes:
                _emit_edge(GraphEdge(kind="scheduled_on", source=pod.key, target=node_key))
        owning_deployment = pod_attrs.get(pod.name, {}).get("owning_deployment")
        if owning_deployment:
            deployment_key = f"deployment:{pod.namespace or '_cluster'}:{owning_deployment}"
            if deployment_key in seen_nodes:
                _emit_edge(GraphEdge(kind="owns", source=deployment_key, target=pod.key))

    infra_graph.update_snapshot(nodes, edges)
    return {"nodes": len(nodes), "edges": len(edges)}


# ---------------------------------------------------------------------
# Parsers — snapshot text → structured per-resource attrs
# ---------------------------------------------------------------------


def _deployment_from_controller(kind: str | None, name: str | None) -> str | None:
    """Return the owning deployment name implied by ``Controlled By:``.

    Pod owners are always ReplicaSets / StatefulSets / DaemonSets /
    Jobs; the user-facing workload is one level up. We collapse:

    * ``ReplicaSet/<deployment>-<hash>`` → ``<deployment>`` (strip the
      pod-template-hash suffix).
    * ``StatefulSet/<name>`` / ``DaemonSet/<name>`` / ``Job/<name>`` →
      ``<name>`` (no hash strip needed).

    Returns ``None`` for unknown controller kinds so the graph stays
    honest — we never invent a node for a workload we can't name.
    """
    if not name:
        return None
    if kind == "ReplicaSet":
        stripped = _RS_HASH_TAIL_RE.sub("", name)
        return stripped if stripped and stripped != name else name
    if kind in {"StatefulSet", "DaemonSet", "Job"}:
        return name
    return None


def _extract_tool_cache(snapshot: dict[str, Any]) -> dict[str, str]:
    """Snapshot can be the raw tool_cache dict or wrap it under ``tools``."""
    for candidate in (snapshot, snapshot.get("tools"), snapshot.get("tool_cache")):
        if isinstance(candidate, dict) and any(
            isinstance(k, str) and ":{" in k for k in candidate.keys()
        ):
            return {str(k): str(v) for k, v in candidate.items() if isinstance(v, str)}
    return {}


def _parse_pods(cache: dict[str, str]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """Return ``(pod_names, attrs_by_name)`` from ``DescribeResource`` text.

    Pods are populated only from ``DescribeResource`` rows — the row-
    oriented ``GetResources pods`` output gives names + status but
    misses labels/owner/node, which are the values the graph needs.
    """
    attrs: dict[str, dict[str, Any]] = {}
    for key, value in cache.items():
        if "DescribeResource" not in key or '"resource_type":"pods"' not in key:
            continue
        if '"name":""' in key:
            continue  # listing form, not per-pod
        pod_name, namespace = _resource_from_key(key)
        if not pod_name:
            continue
        parsed = _parse_pod_describe(value)
        if not parsed:
            continue
        parsed.setdefault("namespace", namespace)
        attrs[pod_name] = parsed
    return set(attrs.keys()), attrs


def _parse_services(
    cache: dict[str, str],
    *,
    default_namespace: str | None,
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    attrs: dict[str, dict[str, Any]] = {}
    for key, value in cache.items():
        if "DescribeResource" not in key or '"resource_type":"services"' not in key:
            continue
        if '"name":""' in key:
            continue
        svc_name, namespace = _resource_from_key(key)
        if not svc_name:
            continue
        parsed = _parse_service_describe(value)
        if not parsed:
            continue
        parsed.setdefault("namespace", namespace or default_namespace)
        attrs[svc_name] = parsed
    return set(attrs.keys()), attrs


def _resource_from_key(key: str) -> tuple[str | None, str | None]:
    """Extract ``(name, namespace)`` from a tool_cache key.

    Keys look like::

        DescribeResource:{"resource_type":"pods","name":"foo-xyz","namespace":"boutique"}

    Cheap regex; we don't validate the JSON shape because
    ``_extract_tool_cache`` already filtered for ``:{`` containing
    keys, and we accept any name that's a Kubernetes-safe identifier.
    """
    name_match = re.search(r'"name":"([^"]*)"', key)
    ns_match = re.search(r'"namespace":"([^"]*)"', key)
    name = name_match.group(1) if name_match else None
    namespace = ns_match.group(1) if ns_match else None
    return (name or None), (namespace or None)


def _parse_pod_describe(text: str) -> dict[str, Any]:
    """Parse one pod ``kubectl describe`` block into attrs."""
    attrs: dict[str, Any] = {"labels": {}, "containers": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _DESCRIBE_KEY_RE.match(line)
        if not match:
            i += 1
            continue
        field = match.group(1).strip()
        value = match.group(2).strip()
        if field == "Name":
            attrs["name"] = value
        elif field == "Namespace":
            attrs["namespace"] = value
        elif field == "Service Account":
            attrs["service_account"] = value
        elif field == "Node":
            node_match = _NODE_FIELD_RE.match(value)
            attrs["node"] = node_match.group(1) if node_match else value
        elif field == "Status":
            attrs["status"] = value
        elif field == "Labels":
            labels: dict[str, str] = {}
            if "=" in value:
                key, _, val = value.partition("=")
                labels[key.strip()] = val.strip()
            j = i + 1
            while j < len(lines):
                cont = _LABEL_LINE_RE.match(lines[j])
                if cont is None:
                    break
                labels[cont.group(1).strip()] = cont.group(2).strip()
                j += 1
            attrs["labels"] = labels
            i = j
            continue
        elif field == "Controlled By":
            cb = _CONTROLLED_BY_RE.match(value)
            if cb:
                attrs["controlled_by_kind"] = cb.group(1)
                attrs["controlled_by_name"] = cb.group(2)
        i += 1
    return attrs if attrs.get("name") or attrs.get("status") or attrs.get("labels") else {}


def _parse_service_describe(text: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"labels": {}, "selector": {}, "ports": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _DESCRIBE_KEY_RE.match(line)
        if not match:
            i += 1
            continue
        field = match.group(1).strip()
        value = match.group(2).strip()
        if field == "Name":
            attrs["name"] = value
        elif field == "Namespace":
            attrs["namespace"] = value
        elif field == "Type":
            attrs["type"] = value
        elif field == "Labels":
            attrs["labels"] = _inline_pairs(value, lines, i + 1)
            i = _skip_continuation(lines, i + 1)
            continue
        elif field == "Selector":
            attrs["selector"] = _inline_pairs(value, lines, i + 1)
            i = _skip_continuation(lines, i + 1)
            continue
        elif field == "Port":
            attrs["ports"].append({"port": value})
        elif field == "TargetPort":
            if attrs["ports"]:
                attrs["ports"][-1]["target_port"] = value
        i += 1
    return attrs if attrs.get("name") or attrs.get("selector") else {}


def _inline_pairs(first: str, lines: Iterable[str], start: int) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if "=" in first:
        for pair in first.split(","):
            if "=" in pair:
                key, _, value = pair.partition("=")
                pairs[key.strip()] = value.strip()
    lines_list = list(lines)
    j = 0
    while j + start < len(lines_list):
        cont = _LABEL_LINE_RE.match(lines_list[j + start])
        if cont is None:
            break
        pairs[cont.group(1).strip()] = cont.group(2).strip()
        j += 1
    return pairs


def _skip_continuation(lines: list[str], start: int) -> int:
    j = start
    while j < len(lines):
        if _LABEL_LINE_RE.match(lines[j]) is None:
            return j
        j += 1
    return j
