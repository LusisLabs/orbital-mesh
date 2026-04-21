"""Infrastructure graph — versioned model of K8s objects + service dependencies.

Node types:
    service, deployment, pod, namespace, node, configmap, secret,
    ingress, statefulset, daemonset, job

Edge types:
    routes_to       ingress -> service
    selects         service -> pod (via selector labels)
    owns            deployment/statefulset -> pod
    mounts          pod -> configmap / secret
    scheduled_on    pod -> node
    exposes         service -> deployment (inferred from selector)

The graph is persisted as file-locked JSON at
``state_directory/graph/snapshot.json``.  Each refresh also writes an
append-only versioned copy at ``graph/versions/<iso-timestamp>.json`` so
we can diff topology over time (e.g. "what changed in the last hour").
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .json_store import LockedJsonFile


NODE_KINDS = frozenset({
    "service",
    "deployment",
    "pod",
    "namespace",
    "node",
    "configmap",
    "secret",
    "ingress",
    "statefulset",
    "daemonset",
    "job",
})

EDGE_KINDS = frozenset({
    "routes_to",
    "selects",
    "owns",
    "mounts",
    "scheduled_on",
    "exposes",
})

_MAX_VERSIONS = 50


def _node_key(kind: str, namespace: str | None, name: str) -> str:
    ns = namespace or "_cluster"
    return f"{kind}:{ns}:{name}"


@dataclass
class GraphNode:
    kind: str
    name: str
    namespace: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return _node_key(self.kind, self.namespace, self.name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    kind: str
    source: str  # node key
    target: str  # node key
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphSnapshot:
    recorded_at: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recorded_at": self.recorded_at,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


class InfraGraph:
    """File-locked JSON-backed infrastructure graph."""

    def __init__(self, state_directory: str | Path):
        self._graph_dir = Path(state_directory) / "graph"
        self._graph_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir = self._graph_dir / "versions"
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_path = self._graph_dir / "snapshot.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def update_snapshot(
        self,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
    ) -> GraphSnapshot:
        """Replace the current snapshot and append a versioned copy."""
        nodes_list = list(nodes)
        edges_list = list(edges)
        self._validate(nodes_list, edges_list)
        recorded_at = datetime.now(timezone.utc).isoformat()
        snapshot = GraphSnapshot(recorded_at=recorded_at, nodes=nodes_list, edges=edges_list)

        with self._lock:
            with LockedJsonFile(self._snapshot_path) as payload:
                payload.clear()
                payload.update(snapshot.to_dict())
            # Versioned copy
            safe_ts = recorded_at.replace(":", "").replace(".", "")
            version_path = self._versions_dir / f"{safe_ts}.json"
            with LockedJsonFile(version_path) as vpayload:
                vpayload.clear()
                vpayload.update(snapshot.to_dict())
            self._prune_versions()
        return snapshot

    def _prune_versions(self) -> None:
        versions = sorted(self._versions_dir.glob("*.json"))
        if len(versions) > _MAX_VERSIONS:
            for stale in versions[: len(versions) - _MAX_VERSIONS]:
                try:
                    stale.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def snapshot(self) -> GraphSnapshot | None:
        if not self._snapshot_path.exists():
            return None
        with LockedJsonFile(self._snapshot_path) as payload:
            if not payload:
                return None
            return GraphSnapshot(
                recorded_at=payload.get("recorded_at", ""),
                nodes=[GraphNode(**n) for n in payload.get("nodes", [])],
                edges=[GraphEdge(**e) for e in payload.get("edges", [])],
            )

    def get_node(self, kind: str, name: str, namespace: str | None = None) -> dict[str, Any] | None:
        snap = self.snapshot()
        if snap is None:
            return None
        target_key = _node_key(kind, namespace, name)
        for node in snap.nodes:
            if node.key == target_key:
                return node.to_dict()
        return None

    def neighbors(
        self,
        kind: str,
        name: str,
        namespace: str | None = None,
        *,
        depth: int = 1,
        edge_kinds: Iterable[str] | None = None,
        direction: str = "both",  # "in" | "out" | "both"
    ) -> list[dict[str, Any]]:
        """Return reachable neighbors up to ``depth`` hops."""
        snap = self.snapshot()
        if snap is None:
            return []
        node_index = {n.key: n for n in snap.nodes}
        allowed_edges = set(edge_kinds) if edge_kinds else None
        start = _node_key(kind, namespace, name)
        if start not in node_index:
            return []

        visited: set[str] = {start}
        frontier: set[str] = {start}
        results: list[dict[str, Any]] = []
        for _ in range(max(depth, 0)):
            next_frontier: set[str] = set()
            for edge in snap.edges:
                if allowed_edges and edge.kind not in allowed_edges:
                    continue
                if direction in ("out", "both") and edge.source in frontier:
                    if edge.target not in visited and edge.target in node_index:
                        next_frontier.add(edge.target)
                if direction in ("in", "both") and edge.target in frontier:
                    if edge.source not in visited and edge.source in node_index:
                        next_frontier.add(edge.source)
            for key in next_frontier:
                results.append(node_index[key].to_dict())
            visited |= next_frontier
            frontier = next_frontier
            if not frontier:
                break
        return results

    def affected_services(self, deployment_name: str, namespace: str) -> list[str]:
        """Services that route traffic to (or select pods from) this deployment."""
        snap = self.snapshot()
        if snap is None:
            return []
        # Find pods owned by the deployment
        dep_key = _node_key("deployment", namespace, deployment_name)
        pod_keys: set[str] = set()
        for edge in snap.edges:
            if edge.kind == "owns" and edge.source == dep_key:
                pod_keys.add(edge.target)
        # Find services selecting any of those pods
        service_names: set[str] = set()
        node_index = {n.key: n for n in snap.nodes}
        for edge in snap.edges:
            if edge.kind == "selects" and edge.target in pod_keys:
                svc = node_index.get(edge.source)
                if svc and svc.kind == "service":
                    service_names.add(svc.name)
        # Also services exposing this deployment directly
        for edge in snap.edges:
            if edge.kind == "exposes" and edge.target == dep_key:
                svc = node_index.get(edge.source)
                if svc and svc.kind == "service":
                    service_names.add(svc.name)
        return sorted(service_names)

    def upstream_dependencies(
        self,
        service: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Services that this service depends on (reverse direction from affected_services)."""
        snap = self.snapshot()
        if snap is None:
            return []
        deps: list[dict[str, Any]] = []
        node_index = {n.key: n for n in snap.nodes}
        # Find deployments selected by this service
        svc_key = _node_key("service", namespace, service)
        if svc_key not in node_index:
            return []
        dep_keys: set[str] = set()
        for edge in snap.edges:
            if edge.kind == "exposes" and edge.source == svc_key:
                dep_keys.add(edge.target)
        # Any ConfigMap/Secret the deployment's pods mount is an upstream dep
        pod_keys: set[str] = set()
        for edge in snap.edges:
            if edge.kind == "owns" and edge.source in dep_keys:
                pod_keys.add(edge.target)
        for edge in snap.edges:
            if edge.kind == "mounts" and edge.source in pod_keys:
                target = node_index.get(edge.target)
                if target and target.kind in ("configmap", "secret"):
                    deps.append(target.to_dict())
        return deps

    def list_versions(self) -> list[str]:
        return sorted(p.stem for p in self._versions_dir.glob("*.json"))

    def load_version(self, version: str) -> GraphSnapshot | None:
        path = self._versions_dir / f"{version}.json"
        if not path.exists():
            return None
        with LockedJsonFile(path) as payload:
            if not payload:
                return None
            return GraphSnapshot(
                recorded_at=payload.get("recorded_at", ""),
                nodes=[GraphNode(**n) for n in payload.get("nodes", [])],
                edges=[GraphEdge(**e) for e in payload.get("edges", [])],
            )

    def status(self) -> dict[str, Any]:
        snap = self.snapshot()
        if snap is None:
            return {"recorded_at": None, "node_count": 0, "edge_count": 0, "versions": 0}
        return {
            "recorded_at": snap.recorded_at,
            "node_count": len(snap.nodes),
            "edge_count": len(snap.edges),
            "versions": len(self.list_versions()),
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        node_keys = {n.key for n in nodes}
        for node in nodes:
            if node.kind not in NODE_KINDS:
                raise ValueError(f"unknown node kind: {node.kind}")
        for edge in edges:
            if edge.kind not in EDGE_KINDS:
                raise ValueError(f"unknown edge kind: {edge.kind}")
            if edge.source not in node_keys:
                raise ValueError(f"edge source not in graph: {edge.source}")
            if edge.target not in node_keys:
                raise ValueError(f"edge target not in graph: {edge.target}")
