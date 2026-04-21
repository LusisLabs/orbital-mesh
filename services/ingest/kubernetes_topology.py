"""Collect Kubernetes cluster topology into an InfraGraph.

Shells out to ``kubectl`` to enumerate Services, Deployments, Pods, Ingresses,
ConfigMaps, Secrets, StatefulSets, DaemonSets, and Nodes.  Builds the nodes +
edges for the infra graph (``InfraGraph.update_snapshot``).

This is intentionally read-only and idempotent — it can be invoked on a timer
or via ``POST /api/graph/refresh``.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from typing import Any, Iterable

from shared.mesh_runtime.infra_graph import GraphEdge, GraphNode, _node_key


_DEFAULT_RESOURCES = (
    "services",
    "deployments",
    "pods",
    "ingresses",
    "configmaps",
    "secrets",
    "statefulsets",
    "daemonsets",
    "nodes",
)


class TopologyCollectionError(RuntimeError):
    pass


def collect_topology(
    *,
    kubectl_command: str = "kubectl",
    kube_context: str | None = None,
    namespaces: Iterable[str] | None = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Enumerate cluster resources and return (nodes, edges) for the graph."""
    kubectl_base = shlex.split(kubectl_command)
    if not kubectl_base:
        raise TopologyCollectionError("kubectl command is empty")
    exe = kubectl_base[0]
    if shutil.which(exe) is None and not exe.startswith("/"):
        raise TopologyCollectionError(f"kubectl not found on PATH: {kubectl_command}")
    if kube_context:
        kubectl_base.extend(["--context", kube_context])

    namespace_filter = list(namespaces) if namespaces else None
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Always include the cluster-scoped nodes
    _collect_nodes_resource(kubectl_base, nodes)

    # Collect namespace-scoped resources. If no filter, ask kubectl for all.
    if namespace_filter is None:
        ns_items = _kubectl_json(kubectl_base + ["get", "namespaces", "-o", "json"]).get("items", [])
        namespace_filter = [item["metadata"]["name"] for item in ns_items if item.get("metadata", {}).get("name")]

    # Track pod index to resolve selectors
    all_pods: list[dict[str, Any]] = []
    all_deployments: list[dict[str, Any]] = []
    all_statefulsets: list[dict[str, Any]] = []
    all_daemonsets: list[dict[str, Any]] = []
    all_services: list[dict[str, Any]] = []
    all_ingresses: list[dict[str, Any]] = []

    for ns in namespace_filter:
        _add_namespace_node(ns, nodes)
        all_pods += _collect_pods(kubectl_base, ns, nodes, edges)
        all_deployments += _collect_deployments(kubectl_base, ns, nodes, edges)
        all_statefulsets += _collect_statefulsets(kubectl_base, ns, nodes, edges)
        all_daemonsets += _collect_daemonsets(kubectl_base, ns, nodes, edges)
        all_services += _collect_services(kubectl_base, ns, nodes)
        all_ingresses += _collect_ingresses(kubectl_base, ns, nodes, edges)
        _collect_configmaps(kubectl_base, ns, nodes)
        _collect_secrets(kubectl_base, ns, nodes)

    # Resolve service→pod selection + service→deployment exposure
    _wire_services(all_services, all_pods, all_deployments, all_statefulsets, edges)
    # Resolve pod→configmap / pod→secret mounts
    _wire_pod_mounts(all_pods, edges)

    return nodes, edges


# ----------------------------------------------------------------------
# Resource collectors
# ----------------------------------------------------------------------


def _add_namespace_node(namespace: str, nodes: list[GraphNode]) -> None:
    nodes.append(GraphNode(kind="namespace", name=namespace, namespace=None))


def _collect_nodes_resource(kubectl_base: list[str], nodes: list[GraphNode]) -> None:
    payload = _kubectl_json(kubectl_base + ["get", "nodes", "-o", "json"], allow_empty=True)
    for item in payload.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        status = item.get("status", {})
        conditions = {c.get("type"): c.get("status") for c in status.get("conditions", [])}
        nodes.append(GraphNode(
            kind="node",
            name=name,
            namespace=None,
            labels=dict(meta.get("labels", {})),
            attributes={
                "ready": conditions.get("Ready") == "True",
                "schedulable": not item.get("spec", {}).get("unschedulable", False),
                "capacity": status.get("capacity", {}),
            },
        ))


def _collect_pods(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "pods", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        status = item.get("status", {})
        spec = item.get("spec", {})
        node_name = spec.get("nodeName")
        nodes.append(GraphNode(
            kind="pod",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={
                "phase": status.get("phase"),
                "pod_ip": status.get("podIP"),
                "node_name": node_name,
            },
        ))
        if node_name:
            edges.append(GraphEdge(
                kind="scheduled_on",
                source=_node_key("pod", namespace, name),
                target=_node_key("node", None, node_name),
            ))
        # Owner references → edge from deployment/statefulset/daemonset
        for owner in meta.get("ownerReferences", []) or []:
            kind = (owner.get("kind") or "").lower()
            owner_name = owner.get("name")
            if kind == "replicaset":
                # Rewrite replicaset → deployment later in _wire_services
                continue
            if kind in ("statefulset", "daemonset") and owner_name:
                edges.append(GraphEdge(
                    kind="owns",
                    source=_node_key(kind, namespace, owner_name),
                    target=_node_key("pod", namespace, name),
                ))
    return items


def _collect_deployments(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "deployments", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        selector = spec.get("selector", {}).get("matchLabels", {})
        nodes.append(GraphNode(
            kind="deployment",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={
                "replicas": spec.get("replicas"),
                "ready_replicas": status.get("readyReplicas", 0),
                "selector_labels": dict(selector),
                "image": _first_image(spec),
            },
        ))
    # Deployment→pod owns edge resolved by label selector (replicasets hide this)
    return items


def _collect_statefulsets(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "statefulsets", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        nodes.append(GraphNode(
            kind="statefulset",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={
                "replicas": spec.get("replicas"),
                "selector_labels": dict(spec.get("selector", {}).get("matchLabels", {})),
                "image": _first_image(spec),
            },
        ))
    return items


def _collect_daemonsets(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "daemonsets", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        nodes.append(GraphNode(
            kind="daemonset",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={
                "selector_labels": dict(spec.get("selector", {}).get("matchLabels", {})),
                "image": _first_image(spec),
            },
        ))
    return items


def _collect_services(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "services", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        nodes.append(GraphNode(
            kind="service",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={
                "selector": dict(spec.get("selector", {})),
                "type": spec.get("type"),
                "cluster_ip": spec.get("clusterIP"),
                "ports": spec.get("ports", []),
            },
        ))
    return items


def _collect_ingresses(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> list[dict[str, Any]]:
    payload = _kubectl_json(
        kubectl_base + ["get", "ingresses", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    items = payload.get("items", [])
    for item in items:
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        rules = spec.get("rules", [])
        hosts = [r.get("host") for r in rules if r.get("host")]
        nodes.append(GraphNode(
            kind="ingress",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={"hosts": hosts},
        ))
        # Ingress rules → services
        seen_services: set[str] = set()
        for rule in rules:
            for path in rule.get("http", {}).get("paths", []):
                backend = path.get("backend", {}).get("service", {})
                svc_name = backend.get("name")
                if svc_name and svc_name not in seen_services:
                    seen_services.add(svc_name)
                    edges.append(GraphEdge(
                        kind="routes_to",
                        source=_node_key("ingress", namespace, name),
                        target=_node_key("service", namespace, svc_name),
                    ))
    return items


def _collect_configmaps(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
) -> None:
    payload = _kubectl_json(
        kubectl_base + ["get", "configmaps", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    for item in payload.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        nodes.append(GraphNode(
            kind="configmap",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
        ))


def _collect_secrets(
    kubectl_base: list[str],
    namespace: str,
    nodes: list[GraphNode],
) -> None:
    payload = _kubectl_json(
        kubectl_base + ["get", "secrets", "-n", namespace, "-o", "json"],
        allow_empty=True,
    )
    for item in payload.get("items", []):
        meta = item.get("metadata", {})
        name = meta.get("name")
        if not name:
            continue
        nodes.append(GraphNode(
            kind="secret",
            name=name,
            namespace=namespace,
            labels=dict(meta.get("labels", {})),
            attributes={"secret_type": item.get("type")},
        ))


# ----------------------------------------------------------------------
# Relationship resolution
# ----------------------------------------------------------------------


def _wire_services(
    services: list[dict[str, Any]],
    pods: list[dict[str, Any]],
    deployments: list[dict[str, Any]],
    statefulsets: list[dict[str, Any]],
    edges: list[GraphEdge],
) -> None:
    for svc in services:
        selector = svc.get("spec", {}).get("selector") or {}
        if not selector:
            continue
        ns = svc.get("metadata", {}).get("namespace", "default")
        svc_key = _node_key("service", ns, svc["metadata"]["name"])
        # selects → pods
        for pod in pods:
            pod_ns = pod.get("metadata", {}).get("namespace", "default")
            if pod_ns != ns:
                continue
            pod_labels = pod.get("metadata", {}).get("labels", {})
            if _matches_selector(selector, pod_labels):
                edges.append(GraphEdge(
                    kind="selects",
                    source=svc_key,
                    target=_node_key("pod", ns, pod["metadata"]["name"]),
                ))
        # exposes → deployments (matching selector against deployment labels)
        for dep in deployments:
            dep_ns = dep.get("metadata", {}).get("namespace", "default")
            if dep_ns != ns:
                continue
            dep_sel = dep.get("spec", {}).get("selector", {}).get("matchLabels", {}) or {}
            # If the service selector is a subset of the deployment's template selector, link
            if _matches_selector(selector, dep_sel):
                edges.append(GraphEdge(
                    kind="exposes",
                    source=svc_key,
                    target=_node_key("deployment", ns, dep["metadata"]["name"]),
                ))
            # And owns edges: deployment selector matching pod labels
        for ss in statefulsets:
            ss_ns = ss.get("metadata", {}).get("namespace", "default")
            if ss_ns != ns:
                continue
            ss_sel = ss.get("spec", {}).get("selector", {}).get("matchLabels", {}) or {}
            if _matches_selector(selector, ss_sel):
                edges.append(GraphEdge(
                    kind="exposes",
                    source=svc_key,
                    target=_node_key("statefulset", ns, ss["metadata"]["name"]),
                ))

    # Deployment→pod owns edge via label selector (since ReplicaSet hides this)
    for dep in deployments:
        dep_ns = dep.get("metadata", {}).get("namespace", "default")
        dep_sel = dep.get("spec", {}).get("selector", {}).get("matchLabels", {}) or {}
        if not dep_sel:
            continue
        dep_key = _node_key("deployment", dep_ns, dep["metadata"]["name"])
        for pod in pods:
            pod_ns = pod.get("metadata", {}).get("namespace", "default")
            if pod_ns != dep_ns:
                continue
            pod_labels = pod.get("metadata", {}).get("labels", {})
            if _matches_selector(dep_sel, pod_labels):
                edges.append(GraphEdge(
                    kind="owns",
                    source=dep_key,
                    target=_node_key("pod", pod_ns, pod["metadata"]["name"]),
                ))


def _wire_pod_mounts(pods: list[dict[str, Any]], edges: list[GraphEdge]) -> None:
    for pod in pods:
        ns = pod.get("metadata", {}).get("namespace", "default")
        name = pod.get("metadata", {}).get("name")
        if not name:
            continue
        pod_key = _node_key("pod", ns, name)
        volumes = pod.get("spec", {}).get("volumes", []) or []
        for vol in volumes:
            if "configMap" in vol and vol["configMap"].get("name"):
                edges.append(GraphEdge(
                    kind="mounts",
                    source=pod_key,
                    target=_node_key("configmap", ns, vol["configMap"]["name"]),
                ))
            if "secret" in vol and vol["secret"].get("secretName"):
                edges.append(GraphEdge(
                    kind="mounts",
                    source=pod_key,
                    target=_node_key("secret", ns, vol["secret"]["secretName"]),
                ))
        # envFrom
        for container in pod.get("spec", {}).get("containers", []) or []:
            for env_from in container.get("envFrom", []) or []:
                if "configMapRef" in env_from and env_from["configMapRef"].get("name"):
                    edges.append(GraphEdge(
                        kind="mounts",
                        source=pod_key,
                        target=_node_key("configmap", ns, env_from["configMapRef"]["name"]),
                    ))
                if "secretRef" in env_from and env_from["secretRef"].get("name"):
                    edges.append(GraphEdge(
                        kind="mounts",
                        source=pod_key,
                        target=_node_key("secret", ns, env_from["secretRef"]["name"]),
                    ))


def _matches_selector(selector: dict[str, str], labels: dict[str, str]) -> bool:
    if not selector:
        return False
    for k, v in selector.items():
        if labels.get(k) != v:
            return False
    return True


def _first_image(spec: dict[str, Any]) -> str | None:
    template = spec.get("template", {})
    containers = template.get("spec", {}).get("containers", [])
    if containers and containers[0].get("image"):
        return containers[0]["image"]
    return None


# ----------------------------------------------------------------------
# Subprocess helpers
# ----------------------------------------------------------------------


def _kubectl_json(command: list[str], *, allow_empty: bool = False) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if allow_empty:
            return {}
        raise TopologyCollectionError(f"{' '.join(command)}: {exc}")
    if completed.returncode != 0:
        if allow_empty:
            return {}
        raise TopologyCollectionError(
            f"{' '.join(command)} exited {completed.returncode}: {completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout) if completed.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise TopologyCollectionError(f"invalid JSON from kubectl: {exc}")
