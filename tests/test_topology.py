"""Tests for the topology populator + topology tool pack.

Three layers, tested independently then end-to-end:

* ``topology_builder.populate`` — parses snapshot text into nodes/edges.
* ``tools.topology`` — exposes graph queries as ``ToolDefinition``s.
* ``MeshRuntimeEngine.run_sync`` — populates the graph per-run and the
  topology tools see the populated data.
"""

from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime.infra_graph import InfraGraph
from services.investigation.harness import ToolRegistry, make_call
from services.investigation.tools import topology
from services.investigation.topology_builder import populate


# Minimal snapshot fixture: two services (frontend, backend), two pods
# selected by them, both scheduled on worker-01. The same shape a
# Cloud-OpsBench tool_cache produces, just shorter.
_DESCRIBE_FRONTEND_POD = """Name:             frontend-7c9f1a-abc12
Namespace:        boutique
Service Account:  frontend-sa
Node:             worker-01/192.168.0.10
Status:           Running
Labels:           app=frontend
                  tier=web
Controlled By:    ReplicaSet/frontend-7c9f1a
Containers:
  server:
    Image:        registry.example.com/frontend:v1
"""

_DESCRIBE_BACKEND_POD = """Name:             backend-9b1da7-xyz45
Namespace:        boutique
Service Account:  default
Node:             worker-01/192.168.0.10
Status:           CrashLoopBackOff
Labels:           app=backend
Controlled By:    ReplicaSet/backend-9b1da7
"""

_DESCRIBE_FRONTEND_SVC = """Name:             frontend
Namespace:        boutique
Type:             ClusterIP
Labels:           app=frontend
Selector:         app=frontend
Port:             80/TCP
TargetPort:       8080/TCP
"""

_DESCRIBE_BACKEND_SVC = """Name:             backend
Namespace:        boutique
Type:             ClusterIP
Selector:         app=backend
Port:             3000/TCP
TargetPort:       3000/TCP
"""


def _toy_snapshot() -> dict[str, dict[str, str]]:
    return {
        "tool_cache": {
            'DescribeResource:{"resource_type":"pods","name":"frontend-7c9f1a-abc12","namespace":"boutique"}': _DESCRIBE_FRONTEND_POD,
            'DescribeResource:{"resource_type":"pods","name":"backend-9b1da7-xyz45","namespace":"boutique"}': _DESCRIBE_BACKEND_POD,
            'DescribeResource:{"resource_type":"services","name":"frontend","namespace":"boutique"}': _DESCRIBE_FRONTEND_SVC,
            'DescribeResource:{"resource_type":"services","name":"backend","namespace":"boutique"}': _DESCRIBE_BACKEND_SVC,
        }
    }


class TopologyPopulatorTests(unittest.TestCase):
    def test_populate_emits_pods_services_deployments_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            stats = populate(graph, snapshot=_toy_snapshot(), namespace_hint="boutique")

            self.assertEqual(stats["nodes"], 7)  # 2 pods + 2 services + 2 deployments + 1 node
            self.assertEqual(stats["edges"], 6)  # 2 selects + 2 scheduled_on + 2 owns

            snap = graph.snapshot()
            kinds = {n.kind for n in snap.nodes}
            self.assertEqual(kinds, {"pod", "service", "deployment", "node"})

            # Pod attributes populated correctly
            pod = next(n for n in snap.nodes if n.name == "frontend-7c9f1a-abc12")
            self.assertEqual(pod.attributes["owning_deployment"], "frontend")
            self.assertEqual(pod.attributes["node"], "worker-01")
            self.assertEqual(pod.attributes["service_account"], "frontend-sa")
            self.assertEqual(pod.labels, {"app": "frontend", "tier": "web"})

    def test_populate_emits_selects_edge_only_for_matching_labels(self) -> None:
        # frontend service selects only the frontend pod via app=frontend;
        # backend service selects only the backend pod via app=backend.
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            populate(graph, snapshot=_toy_snapshot(), namespace_hint="boutique")

            frontend_pods = graph.neighbors(
                "service", "frontend", "boutique", edge_kinds=["selects"], direction="out"
            )
            backend_pods = graph.neighbors(
                "service", "backend", "boutique", edge_kinds=["selects"], direction="out"
            )

            self.assertEqual([p["name"] for p in frontend_pods], ["frontend-7c9f1a-abc12"])
            self.assertEqual([p["name"] for p in backend_pods], ["backend-9b1da7-xyz45"])

    def test_populate_collapses_replicaset_into_owning_deployment(self) -> None:
        # ``Controlled By: ReplicaSet/frontend-7c9f`` → deployment ``frontend``
        # because the graph schema only carries deployment/statefulset/
        # daemonset/job — replicaset is an internal Kubernetes detail.
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            populate(graph, snapshot=_toy_snapshot(), namespace_hint="boutique")
            snap = graph.snapshot()
            self.assertNotIn("replicaset", {n.kind for n in snap.nodes})
            self.assertIn("frontend", {n.name for n in snap.nodes if n.kind == "deployment"})

    def test_populate_with_no_snapshot_is_a_noop(self) -> None:
        # Production runs without CloudOpsBench data must not crash; the
        # populator returns zero-counts and leaves the graph empty.
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            stats_none = populate(graph, snapshot=None)
            stats_empty = populate(graph, snapshot={})
            stats_malformed = populate(graph, snapshot={"unrelated": "data"})

            self.assertEqual(stats_none, {"nodes": 0, "edges": 0})
            self.assertEqual(stats_empty, {"nodes": 0, "edges": 0})
            self.assertEqual(stats_malformed, {"nodes": 0, "edges": 0})


class TopologyToolPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.graph = InfraGraph(self.tmpdir.name)
        populate(self.graph, snapshot=_toy_snapshot(), namespace_hint="boutique")
        self.registry = ToolRegistry()
        topology.register(self.registry, self.graph)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_all_five_tools_register(self) -> None:
        defs = self.registry.list_definitions(domain="topology")
        self.assertEqual(
            sorted(d.name for d in defs),
            sorted([
                "topology_pod_lineage",
                "topology_pod_node",
                "topology_resolve_service_pods",
                "topology_resource_neighbors",
                "topology_snapshot",
            ]),
        )
        # All tools must be classified read_only — this pack queries only.
        for defn in defs:
            self.assertEqual(defn.mutation_class, "read_only", defn.name)

    def test_pod_lineage_returns_deployment_service_node(self) -> None:
        defn, _ = self.registry.get("topology", "topology_pod_lineage")
        result = self.registry.invoke(
            make_call(tool=defn, args={"pod": "frontend-7c9f1a-abc12", "namespace": "boutique"})
        )
        self.assertTrue(result.valid)
        self.assertEqual([d["name"] for d in result.output["deployments"]], ["frontend"])
        self.assertEqual([s["name"] for s in result.output["services"]], ["frontend"])
        self.assertEqual(result.output["node"]["name"], "worker-01")

    def test_resolve_service_pods_matches_label_selector(self) -> None:
        defn, _ = self.registry.get("topology", "topology_resolve_service_pods")
        result = self.registry.invoke(
            make_call(tool=defn, args={"service": "frontend", "namespace": "boutique"})
        )
        self.assertTrue(result.valid)
        names = [p["name"] for p in result.output["pods"]]
        self.assertEqual(names, ["frontend-7c9f1a-abc12"])

    def test_resolve_service_pods_returns_empty_for_unknown_service(self) -> None:
        # Empty result is NOT a crash — it's the localization signal for
        # service_selector_mismatch (service exists, no pods match).
        defn, _ = self.registry.get("topology", "topology_resolve_service_pods")
        result = self.registry.invoke(
            make_call(tool=defn, args={"service": "nonexistent", "namespace": "boutique"})
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.output["pods"], [])

    def test_pod_node_resolves_scheduled_node(self) -> None:
        defn, _ = self.registry.get("topology", "topology_pod_node")
        result = self.registry.invoke(
            make_call(tool=defn, args={"pod": "backend-9b1da7-xyz45", "namespace": "boutique"})
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.output["node"]["name"], "worker-01")

    def test_snapshot_returns_compact_summary_with_kind_counts(self) -> None:
        defn, _ = self.registry.get("topology", "topology_snapshot")
        result = self.registry.invoke(make_call(tool=defn, args={"limit": 50}))
        self.assertTrue(result.valid)
        self.assertEqual(result.output["node_count"], 7)
        self.assertEqual(result.output["edge_count"], 6)
        # Topology tools never crash on a populated graph; counts surface.
        self.assertIn("pod", result.output["kind_counts"])

    def test_tools_return_empty_when_graph_is_empty(self) -> None:
        # The "always available" contract: tools register at root
        # regardless of whether the populator has run; queries return
        # empty results when the graph has no data — never crash.
        with tempfile.TemporaryDirectory() as state:
            empty_graph = InfraGraph(state)
            empty_registry = ToolRegistry()
            topology.register(empty_registry, empty_graph)

            defn, _ = empty_registry.get("topology", "topology_snapshot")
            result = empty_registry.invoke(make_call(tool=defn))
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.output["node_count"], 0)

    def test_maybe_register_at_root_skips_when_graph_is_none(self) -> None:
        registry = ToolRegistry()
        self.assertFalse(topology.maybe_register_at_root(registry, None))
        self.assertEqual(registry.list_definitions(domain="topology"), [])


class EnginePopulatesGraphPerRunTests(unittest.TestCase):
    def test_engine_default_constructs_infra_graph(self) -> None:
        # InfraGraph used to be control-plane-only; benchmark and
        # standalone runs left it empty. The engine now default-
        # constructs one so every code path has a graph.
        from shared.mesh_runtime.config import RuntimeConfig
        from services.runtime import MeshRuntimeEngine

        with tempfile.TemporaryDirectory() as state:
            engine = MeshRuntimeEngine(
                config=RuntimeConfig(
                    state_directory=state,
                    evaluation_mode="native",
                    orchestration_mode="native",
                )
            )
            self.assertIsNotNone(engine.infra_graph)
            # Topology pack must be registered at root regardless of
            # any other config — the graph is always present.
            tops = engine.root_registry.list_definitions(domain="topology")
            self.assertEqual(len(tops), 5)

    def test_run_sync_populates_graph_from_cloudops_snapshot(self) -> None:
        from shared.mesh_runtime.config import RuntimeConfig
        from services.runtime import MeshRuntimeEngine

        with tempfile.TemporaryDirectory() as state:
            engine = MeshRuntimeEngine(
                config=RuntimeConfig(
                    state_directory=state,
                    evaluation_mode="native",
                    orchestration_mode="native",
                )
            )
            self.assertIsNone(engine.infra_graph.snapshot())

            raw_signal = {
                "signal_type": "otel_metric_regression",
                "signal_id": "test_topology_engine",
                "observed_at": "2026-05-08T00:00:00Z",
                "environment": "test",
                "service": "frontend",
                "endpoint": "/",
                "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
                "metric_regression": {
                    "metric_name": "availability",
                    "baseline_value": 1.0,
                    "observed_value": 0.0,
                },
                "related_context": {"cloudopsbench_namespace": "boutique"},
                "cloudopsbench_snapshot": _toy_snapshot(),
            }
            engine.run_sync(raw_signal, scenario_name="topology_engine_test")

            snap = engine.infra_graph.snapshot()
            self.assertIsNotNone(snap)
            assert snap is not None
            self.assertGreater(len(snap.nodes), 0)
            self.assertIn("frontend", {n.name for n in snap.nodes if n.kind == "service"})


if __name__ == "__main__":
    unittest.main()
