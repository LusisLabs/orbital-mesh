"""Tests for the InfraGraph — versioned K8s topology model."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.infra_graph import (
    GraphEdge,
    GraphNode,
    InfraGraph,
    _node_key,
)


def _build_small_graph():
    """A tiny cluster: 1 ingress -> 1 service -> 1 deployment -> 2 pods -> 1 node."""
    nodes = [
        GraphNode(kind="namespace", name="prod"),
        GraphNode(kind="node", name="node-1"),
        GraphNode(kind="ingress", name="web-ingress", namespace="prod", attributes={"hosts": ["app.example.com"]}),
        GraphNode(kind="service", name="web", namespace="prod", attributes={"selector": {"app": "web"}}),
        GraphNode(
            kind="deployment",
            name="web-api",
            namespace="prod",
            attributes={"selector_labels": {"app": "web"}, "image": "registry/web:1.0"},
        ),
        GraphNode(kind="pod", name="web-api-abc", namespace="prod", labels={"app": "web"}),
        GraphNode(kind="pod", name="web-api-def", namespace="prod", labels={"app": "web"}),
        GraphNode(kind="configmap", name="web-config", namespace="prod"),
    ]
    edges = [
        GraphEdge(kind="routes_to",
                  source=_node_key("ingress", "prod", "web-ingress"),
                  target=_node_key("service", "prod", "web")),
        GraphEdge(kind="exposes",
                  source=_node_key("service", "prod", "web"),
                  target=_node_key("deployment", "prod", "web-api")),
        GraphEdge(kind="selects",
                  source=_node_key("service", "prod", "web"),
                  target=_node_key("pod", "prod", "web-api-abc")),
        GraphEdge(kind="selects",
                  source=_node_key("service", "prod", "web"),
                  target=_node_key("pod", "prod", "web-api-def")),
        GraphEdge(kind="owns",
                  source=_node_key("deployment", "prod", "web-api"),
                  target=_node_key("pod", "prod", "web-api-abc")),
        GraphEdge(kind="owns",
                  source=_node_key("deployment", "prod", "web-api"),
                  target=_node_key("pod", "prod", "web-api-def")),
        GraphEdge(kind="scheduled_on",
                  source=_node_key("pod", "prod", "web-api-abc"),
                  target=_node_key("node", None, "node-1")),
        GraphEdge(kind="scheduled_on",
                  source=_node_key("pod", "prod", "web-api-def"),
                  target=_node_key("node", None, "node-1")),
        GraphEdge(kind="mounts",
                  source=_node_key("pod", "prod", "web-api-abc"),
                  target=_node_key("configmap", "prod", "web-config")),
    ]
    return nodes, edges


class InfraGraphTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.graph = InfraGraph(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_graph_returns_none(self):
        self.assertIsNone(self.graph.snapshot())
        self.assertEqual(self.graph.status()["node_count"], 0)

    def test_update_and_read_snapshot(self):
        nodes, edges = _build_small_graph()
        snap = self.graph.update_snapshot(nodes, edges)
        self.assertEqual(len(snap.nodes), 8)
        self.assertEqual(len(snap.edges), 9)

        loaded = self.graph.snapshot()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.nodes), 8)
        self.assertEqual(len(loaded.edges), 9)

    def test_get_node(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        node = self.graph.get_node("deployment", "web-api", "prod")
        self.assertIsNotNone(node)
        self.assertEqual(node["attributes"]["image"], "registry/web:1.0")

        missing = self.graph.get_node("deployment", "nonexistent", "prod")
        self.assertIsNone(missing)

    def test_neighbors_depth_1(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        nbrs = self.graph.neighbors("deployment", "web-api", "prod", depth=1)
        names = {n["name"] for n in nbrs}
        # Deployment has 2 pod neighbors (owns) + 1 service neighbor (exposes ingress)
        self.assertIn("web-api-abc", names)
        self.assertIn("web-api-def", names)
        self.assertIn("web", names)

    def test_neighbors_depth_2(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        nbrs = self.graph.neighbors("ingress", "web-ingress", "prod", depth=3)
        names = {n["name"] for n in nbrs}
        # ingress -> service -> deployment -> pods
        self.assertIn("web", names)
        self.assertIn("web-api", names)
        self.assertIn("web-api-abc", names)

    def test_neighbors_edge_kind_filter(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        # Only follow "owns" edges from deployment
        nbrs = self.graph.neighbors(
            "deployment", "web-api", "prod",
            depth=1, edge_kinds=["owns"], direction="out",
        )
        names = {n["name"] for n in nbrs}
        self.assertEqual(names, {"web-api-abc", "web-api-def"})

    def test_neighbors_direction_out_only(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        # Service outward only
        nbrs = self.graph.neighbors("service", "web", "prod", depth=1, direction="out")
        names = {n["name"] for n in nbrs}
        self.assertIn("web-api", names)
        self.assertIn("web-api-abc", names)
        self.assertNotIn("web-ingress", names)

    def test_affected_services(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        affected = self.graph.affected_services("web-api", "prod")
        self.assertEqual(affected, ["web"])

    def test_affected_services_empty_for_unknown(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        affected = self.graph.affected_services("does-not-exist", "prod")
        self.assertEqual(affected, [])

    def test_versions_are_persisted(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        # Second update → second version
        # Modify a node attribute to simulate topology change
        new_nodes = list(nodes)
        new_nodes[4] = GraphNode(
            kind="deployment",
            name="web-api",
            namespace="prod",
            attributes={"selector_labels": {"app": "web"}, "image": "registry/web:2.0"},
        )
        self.graph.update_snapshot(new_nodes, edges)
        versions = self.graph.list_versions()
        self.assertGreaterEqual(len(versions), 2)
        # Load an older version and confirm image is v1
        oldest = self.graph.load_version(versions[0])
        deployment = next(n for n in oldest.nodes if n.kind == "deployment" and n.name == "web-api")
        self.assertEqual(deployment.attributes["image"], "registry/web:1.0")

    def test_invalid_node_kind_raises(self):
        nodes = [GraphNode(kind="unknown_thing", name="x")]
        with self.assertRaises(ValueError):
            self.graph.update_snapshot(nodes, [])

    def test_invalid_edge_kind_raises(self):
        nodes = [
            GraphNode(kind="service", name="a", namespace="prod"),
            GraphNode(kind="service", name="b", namespace="prod"),
        ]
        edges = [GraphEdge(kind="invented_edge",
                           source=_node_key("service", "prod", "a"),
                           target=_node_key("service", "prod", "b"))]
        with self.assertRaises(ValueError):
            self.graph.update_snapshot(nodes, edges)

    def test_dangling_edge_raises(self):
        nodes = [GraphNode(kind="service", name="a", namespace="prod")]
        edges = [GraphEdge(kind="routes_to",
                           source=_node_key("service", "prod", "a"),
                           target=_node_key("service", "prod", "b"))]
        with self.assertRaises(ValueError):
            self.graph.update_snapshot(nodes, edges)

    def test_status_reports_counts(self):
        nodes, edges = _build_small_graph()
        self.graph.update_snapshot(nodes, edges)
        status = self.graph.status()
        self.assertEqual(status["node_count"], 8)
        self.assertEqual(status["edge_count"], 9)
        self.assertIsNotNone(status["recorded_at"])
        self.assertGreaterEqual(status["versions"], 1)


class InfraGraphConcurrencyTests(unittest.TestCase):
    def test_concurrent_updates(self):
        import threading
        tmp = tempfile.TemporaryDirectory()
        try:
            graph = InfraGraph(tmp.name)
            errors: list[Exception] = []

            def writer(idx: int) -> None:
                try:
                    for _ in range(3):
                        nodes = [
                            GraphNode(kind="namespace", name=f"ns-{idx}"),
                            GraphNode(kind="service", name=f"svc-{idx}", namespace=f"ns-{idx}"),
                        ]
                        graph.update_snapshot(nodes, [])
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            snap = graph.snapshot()
            self.assertIsNotNone(snap)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
