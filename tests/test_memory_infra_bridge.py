"""Tests for the InfraGraph ↔ memory bridge.

The bridge stamps each ``RelationshipRecord`` with an
``infra_node_key`` (the canonical InfraGraph node key for the
``from_id`` side) at write time, and uses it at retrieval time to walk
InfraGraph edges from a seed claim's resource to topologically-adjacent
resources, then surface claims about those resources.

These tests cover the contract end-to-end without a live Postgres:

* The contract field roundtrips through ``RelationshipRecord``.
* ``MemoryLifecycleService`` populates ``infra_node_key`` from
  trigger + namespace.
* ``MemoryRetrievalService._graph_rank`` preserves its pre-bridge
  1-hop behavior when no ``infra_graph`` is supplied.
* When ``infra_graph`` IS supplied, the metapath pass surfaces claims
  about adjacent resources that the 1-hop walk would not.
* Parser helpers are robust to malformed inputs.
"""

from __future__ import annotations

import unittest
from typing import Any

from shared.mesh_runtime.contracts import RelationshipRecord
from shared.mesh_runtime.infra_graph import _node_key
from shared.mesh_runtime.memory_lifecycle import _namespace_from_artifacts
from shared.mesh_runtime.memory_retrieval import (
    MemoryRetrievalService,
    _neighbor_to_node_key,
    _parse_infra_node_key,
)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class RelationshipRecordContractTests(unittest.TestCase):
    def test_pre_bridge_row_still_validates(self) -> None:
        """Existing data lacks infra_node_key. The contract must
        treat the field as optional or every old row in the DB
        becomes invalid on next read."""
        row = RelationshipRecord(
            relationship_id="rel_1",
            from_id="emailservice",
            to_id="claim_1",
            type="describes",
            confidence=0.8,
            supporting_observation_ids=["obs_1"],
            state="active",
        )
        row.validate()
        self.assertIsNone(row.infra_node_key)

    def test_bridged_row_roundtrips_through_dict(self) -> None:
        row = RelationshipRecord(
            relationship_id="rel_2",
            from_id="emailservice",
            to_id="claim_2",
            type="describes",
            confidence=0.8,
            supporting_observation_ids=["obs_2"],
            state="active",
            infra_node_key="service:boutique:emailservice",
        )
        row.validate()
        roundtripped = RelationshipRecord.from_dict(row.to_dict())
        self.assertEqual(roundtripped.infra_node_key, "service:boutique:emailservice")


# ---------------------------------------------------------------------------
# MemoryLifecycle namespace extractor
# ---------------------------------------------------------------------------


class NamespaceExtractorTests(unittest.TestCase):
    """``_namespace_from_artifacts`` is what crystallization uses to
    compute the InfraGraph node key. Triggers don't carry a top-level
    namespace field; we have to dig through ``related_context``."""

    def test_cloudopsbench_namespace_shape(self) -> None:
        artifacts = {"trigger": {"related_context": {"cloudopsbench_namespace": "boutique"}}}
        self.assertEqual(_namespace_from_artifacts(artifacts), "boutique")

    def test_native_k8s_namespace_shape(self) -> None:
        artifacts = {"trigger": {"related_context": {"namespace": "production"}}}
        self.assertEqual(_namespace_from_artifacts(artifacts), "production")

    def test_top_level_namespace_fallback(self) -> None:
        # Some triggers carry a top-level namespace (Reth-style signals).
        artifacts = {"trigger": {"namespace": "blockchain"}}
        self.assertEqual(_namespace_from_artifacts(artifacts), "blockchain")

    def test_missing_namespace_returns_none(self) -> None:
        # _node_key treats None as ``_cluster``, so this is fine.
        self.assertIsNone(_namespace_from_artifacts({"trigger": {}}))
        self.assertIsNone(_namespace_from_artifacts({}))
        self.assertIsNone(_namespace_from_artifacts(None))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


class ParseInfraNodeKeyTests(unittest.TestCase):
    """``_parse_infra_node_key`` is the inverse of ``_node_key``. Bad
    inputs (legacy rows with garbage in the field, malformed keys,
    None) must return None rather than crash retrieval."""

    def test_namespaced_resource_roundtrip(self) -> None:
        key = _node_key("service", "boutique", "emailservice")
        self.assertEqual(_parse_infra_node_key(key), ("service", "boutique", "emailservice"))

    def test_cluster_scoped_resource_decodes_namespace_as_none(self) -> None:
        key = _node_key("node", None, "worker-01")
        kind, namespace, name = _parse_infra_node_key(key)  # type: ignore[misc]
        self.assertEqual(kind, "node")
        self.assertIsNone(namespace)
        self.assertEqual(name, "worker-01")

    def test_malformed_keys_return_none(self) -> None:
        self.assertIsNone(_parse_infra_node_key(""))
        self.assertIsNone(_parse_infra_node_key("only_one_part"))
        self.assertIsNone(_parse_infra_node_key("two:parts"))
        self.assertIsNone(_parse_infra_node_key("four:parts:in:key"))
        self.assertIsNone(_parse_infra_node_key("::name"))   # empty kind
        self.assertIsNone(_parse_infra_node_key("kind:ns:"))  # empty name
        # Non-string input
        self.assertIsNone(_parse_infra_node_key(None))  # type: ignore[arg-type]
        self.assertIsNone(_parse_infra_node_key(12345))  # type: ignore[arg-type]


class NeighborToNodeKeyTests(unittest.TestCase):
    def test_namespaced_neighbor(self) -> None:
        neighbor = {"kind": "service", "name": "frontend", "namespace": "boutique"}
        self.assertEqual(_neighbor_to_node_key(neighbor), "service:boutique:frontend")

    def test_cluster_scoped_neighbor(self) -> None:
        # InfraGraph uses ``_cluster`` for null namespace; neighbor
        # response carries explicit None; helper must match.
        neighbor = {"kind": "node", "name": "worker-01", "namespace": None}
        self.assertEqual(_neighbor_to_node_key(neighbor), "node:_cluster:worker-01")

    def test_missing_kind_or_name_returns_none(self) -> None:
        self.assertIsNone(_neighbor_to_node_key({"name": "frontend"}))
        self.assertIsNone(_neighbor_to_node_key({"kind": "service"}))
        self.assertIsNone(_neighbor_to_node_key({}))
        self.assertIsNone(_neighbor_to_node_key("not a dict"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Retrieval: pre-bridge behavior preserved
# ---------------------------------------------------------------------------


class _FakeStateStore:
    """In-memory state-store stand-in for retrieval tests."""

    def __init__(
        self,
        observations: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        self._observations = observations
        self._claims = claims
        self._relationships = relationships

    def list_observations(self, scope: dict[str, Any], opts: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._observations)

    def list_claims(self, scope: dict[str, Any], opts: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._claims)

    def list_relationships(self, *, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return list(self._relationships)

    def record_memory_retrieval(self, record: dict[str, Any]) -> dict[str, Any]:
        return dict(record)


class GraphRankPreBridgeTests(unittest.TestCase):
    """``infra_graph=None`` must preserve the exact 1-hop behavior the
    pre-bridge code shipped. If we regress this, every existing
    deployment without an infra graph loses its graph channel."""

    def test_one_hop_walk_finds_connected_endpoints(self) -> None:
        service = MemoryRetrievalService(state_store=None, infra_graph=None)
        relationships = [
            {"from_id": "emailservice", "to_id": "claim_1", "type": "describes"},
            {"from_id": "emailservice", "to_id": "claim_2", "type": "describes"},
            {"from_id": "cartservice", "to_id": "claim_3", "type": "describes"},
        ]
        # Seed = the service. Expansion should surface its claims.
        out = service._graph_rank(["emailservice"], relationships)
        self.assertIn("claim_1", out)
        self.assertIn("claim_2", out)
        self.assertNotIn("claim_3", out)

    def test_one_hop_walk_is_bidirectional(self) -> None:
        service = MemoryRetrievalService(state_store=None, infra_graph=None)
        relationships = [
            {"from_id": "emailservice", "to_id": "claim_1", "type": "describes"},
        ]
        # Seed = the claim. Expansion should surface the service.
        out = service._graph_rank(["claim_1"], relationships)
        self.assertIn("emailservice", out)

    def test_empty_seed_returns_empty(self) -> None:
        service = MemoryRetrievalService(state_store=None, infra_graph=None)
        self.assertEqual(service._graph_rank([], []), [])


# ---------------------------------------------------------------------------
# Retrieval: metapath traversal through InfraGraph
# ---------------------------------------------------------------------------


class _FakeInfraGraph:
    """A counting, deterministic stand-in for ``InfraGraph``.

    Configured with explicit (kind, namespace, name) → list-of-neighbor
    dicts so each test pins exactly the edges it cares about. Honors
    ``depth`` by walking transitively — at depth=2 a node's
    grand-neighbors are included, mirroring the real
    ``InfraGraph.neighbors`` BFS expansion.
    """

    def __init__(self, neighbor_map: dict[tuple[str, str | None, str], list[dict[str, Any]]]) -> None:
        self._neighbor_map = neighbor_map
        self.calls: list[tuple[str, str, str | None, str, int]] = []

    def neighbors(
        self,
        kind: str,
        name: str,
        namespace: str | None = None,
        *,
        depth: int = 1,
        edge_kinds: Any = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        self.calls.append((kind, name, namespace, direction, depth))
        seen: set[tuple[str, str | None, str]] = {(kind, namespace, name)}
        frontier: list[tuple[str, str | None, str]] = [(kind, namespace, name)]
        results: list[dict[str, Any]] = []
        for _ in range(max(depth, 0)):
            next_frontier: list[tuple[str, str | None, str]] = []
            for src in frontier:
                for neighbor in self._neighbor_map.get(src, []):
                    nk = (
                        str(neighbor.get("kind", "")),
                        neighbor.get("namespace"),
                        str(neighbor.get("name", "")),
                    )
                    if nk in seen:
                        continue
                    seen.add(nk)
                    next_frontier.append(nk)
                    results.append(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        return results


class GraphRankMetapathTests(unittest.TestCase):
    def test_metapath_surfaces_claims_about_topology_adjacent_resources(self) -> None:
        # Topology:
        #     emailservice ──scheduled_on──► worker-01 ◄──scheduled_on── payment-service
        #
        # Memory:
        #   relationship_a: emailservice  → claim_email   (infra_key = service:boutique:emailservice)
        #   relationship_b: payment-service → claim_pay     (infra_key = service:boutique:payment-service)
        #   relationship_c: worker-01     → claim_worker  (infra_key = node:_cluster:worker-01)
        #
        # Seed: claim_email.
        # 1-hop walk surfaces only the relationship endpoint
        # ``emailservice``. The metapath pass should then walk
        # emailservice → worker-01 → payment-service (and worker-01
        # itself) and surface claim_worker + claim_pay.
        worker_node = {"kind": "node", "name": "worker-01", "namespace": None}
        email_service_node = {"kind": "service", "name": "emailservice", "namespace": "boutique"}
        payment_service_node = {"kind": "service", "name": "payment-service", "namespace": "boutique"}

        infra = _FakeInfraGraph(
            {
                ("service", "boutique", "emailservice"): [worker_node],
                ("node", None, "worker-01"): [email_service_node, payment_service_node],
                ("service", "boutique", "payment-service"): [worker_node],
            }
        )

        relationships = [
            {
                "from_id": "emailservice",
                "to_id": "claim_email",
                "type": "describes",
                "infra_node_key": "service:boutique:emailservice",
            },
            {
                "from_id": "payment-service",
                "to_id": "claim_pay",
                "type": "describes",
                "infra_node_key": "service:boutique:payment-service",
            },
            {
                "from_id": "worker-01",
                "to_id": "claim_worker",
                "type": "describes",
                "infra_node_key": "node:_cluster:worker-01",
            },
        ]

        service = MemoryRetrievalService(state_store=None, infra_graph=infra)
        out = service._graph_rank(["claim_email"], relationships)

        # 1-hop walk surfaces the source service.
        self.assertIn("emailservice", out)
        # Metapath pass surfaces the worker AND the co-scheduled
        # service's claims — the whole point of the bridge.
        self.assertIn("claim_worker", out)
        self.assertIn("claim_pay", out)

    def test_metapath_returns_empty_when_seed_has_no_infra_key(self) -> None:
        """Legacy rows (pre-bridge) have ``infra_node_key=None``. The
        metapath pass must skip them silently — they fall back to
        1-hop only."""
        infra = _FakeInfraGraph({})
        relationships = [
            # No infra_node_key on either row.
            {"from_id": "emailservice", "to_id": "claim_1", "type": "describes"},
        ]
        service = MemoryRetrievalService(state_store=None, infra_graph=infra)
        out = service._graph_rank(["claim_1"], relationships)
        # 1-hop walk still finds the service.
        self.assertIn("emailservice", out)
        # And InfraGraph was never consulted (no infra keys to feed it).
        self.assertEqual(infra.calls, [])

    def test_metapath_fails_soft_when_infra_graph_throws(self) -> None:
        """A broken InfraGraph (offline snapshot, partial bootstrap,
        etc.) must not crash retrieval — fall back to 1-hop only."""

        class _BrokenGraph:
            def neighbors(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("simulated InfraGraph outage")

        relationships = [
            {
                "from_id": "emailservice",
                "to_id": "claim_1",
                "type": "describes",
                "infra_node_key": "service:boutique:emailservice",
            },
            {
                "from_id": "cartservice",
                "to_id": "claim_2",
                "type": "describes",
                "infra_node_key": "service:boutique:cartservice",
            },
        ]
        service = MemoryRetrievalService(state_store=None, infra_graph=_BrokenGraph())
        # Should not raise; 1-hop walk still returns the service endpoint.
        out = service._graph_rank(["claim_1"], relationships)
        self.assertIn("emailservice", out)
        # claim_2 (cartservice) should NOT surface because the metapath
        # crashed before it could expand. 1-hop walk doesn't see it
        # either (no shared seed).
        self.assertNotIn("claim_2", out)

    def test_metapath_dedupes_against_seeds(self) -> None:
        """If the metapath walk loops back to a seed, that ID must
        not appear in the expansion output."""
        email_node = {"kind": "service", "name": "emailservice", "namespace": "boutique"}
        infra = _FakeInfraGraph(
            {
                ("service", "boutique", "emailservice"): [email_node],  # self-loop
            }
        )
        relationships = [
            {
                "from_id": "emailservice",
                "to_id": "claim_email",
                "type": "describes",
                "infra_node_key": "service:boutique:emailservice",
            },
        ]
        service = MemoryRetrievalService(state_store=None, infra_graph=infra)
        out = service._graph_rank(["claim_email"], relationships)
        # The self-loop should not double-count claim_email.
        self.assertEqual(out.count("claim_email"), 0)  # excluded as a seed
        self.assertEqual(out.count("emailservice"), 1)


# ---------------------------------------------------------------------------
# End-to-end: ReasoningBank forwards infra_graph
# ---------------------------------------------------------------------------


class ReasoningBankWiringTests(unittest.TestCase):
    """When a ReasoningBank is constructed with an ``infra_graph``,
    its internal ``_retrieve`` must route through
    ``MemoryRetrievalService(infra_graph=...)`` rather than the
    state-store wrapper that doesn't know about topology."""

    def test_reasoning_bank_threads_infra_graph_into_retrieval(self) -> None:
        from shared.mesh_runtime.reasoning_bank import ReasoningBankService

        captured: dict[str, Any] = {}

        class _CapturingStore:
            def list_observations(self, scope, opts):
                captured["scope"] = dict(scope)
                return []

            def list_claims(self, scope, opts):
                return []

            def list_relationships(self, *, scope=None):
                return []

            def retrieve_memory(self, request):
                # If this gets called when an infra_graph is set, the
                # plumbing skipped the direct MemoryRetrievalService
                # path. Tests fail loudly.
                captured["fell_through_wrapper"] = True
                return {"packet": {}, "contradictions": [], "channels": []}

            def record_memory_retrieval(self, record):
                return dict(record)

            def save_memory_packet(self, packet):
                # MemoryRetrievalService.retrieve persists the packet
                # back to the store at the end. Stub to no-op for the
                # wiring test; the assertion we care about is that
                # the wrapper path was skipped.
                return dict(packet)

        store = _CapturingStore()
        bank = ReasoningBankService(store, infra_graph=_FakeInfraGraph({}))
        # Ask retrieval to do its thing.
        bank._retrieve({"query": "test", "scope": {"service": "x"}, "limit": 5, "channels": ["lexical"]})
        # The wrapper must NOT have been called — we routed through
        # MemoryRetrievalService directly with the graph attached.
        self.assertNotIn("fell_through_wrapper", captured)
        # And the request scope reached list_observations.
        self.assertEqual(captured.get("scope"), {"service": "x"})

    def test_reasoning_bank_without_infra_graph_uses_wrapper(self) -> None:
        from shared.mesh_runtime.reasoning_bank import ReasoningBankService

        captured: dict[str, Any] = {}

        class _CapturingStore:
            def retrieve_memory(self, request):
                captured["request"] = dict(request)
                return {"packet": {}, "contradictions": [], "channels": []}

        store = _CapturingStore()
        bank = ReasoningBankService(store)  # no infra_graph
        bank._retrieve({"query": "test", "scope": {"service": "x"}, "limit": 5, "channels": ["lexical"]})
        # Backwards-compat: the wrapper IS called when no graph is
        # configured.
        self.assertEqual(captured["request"]["query"], "test")


if __name__ == "__main__":
    unittest.main()
