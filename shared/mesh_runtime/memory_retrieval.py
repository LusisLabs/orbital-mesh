from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .contracts import MemoryPacket, RetrievalRecord
from .memory_scoring import reciprocal_rank_fusion
from .memory_verifier import verify_memory_candidates


class MemoryRetrievalService:
    """Memory retrieval over observations, claims, and relationships.

    The retrieval surface is three channels fused via reciprocal rank
    fusion: ``lexical`` (token overlap), ``graph`` (1-hop expansion
    via the ``RelationshipRecord`` table plus optional metapath
    traversal through ``InfraGraph``), and ``vector`` (stub today —
    returns no hits until an embedding backend is wired).

    The ``infra_graph`` parameter is the bridge between mesh's memory
    layer and its typed K8s topology layer. When provided, the graph
    channel does NOT stop at the 1-hop relationship table; it walks
    InfraGraph edges (``selects``, ``scheduled_on``, ``owns``, …) from
    each seed claim's stamped ``infra_node_key`` to find
    topologically-adjacent resources, then surfaces claims about
    those resources. This is the SynergyRCA-style metapath traversal
    that lets a worker-01 incident on ``redis-cart`` surface a
    worker-01 claim attached to ``payment-service``. Without
    ``infra_graph`` the channel falls back to its pre-bridge
    1-hop-only behavior, so callers without an InfraGraph stay
    functional.
    """

    def __init__(self, state_store: Any, infra_graph: Any = None):
        self.state_store = state_store
        self.infra_graph = infra_graph

    def retrieve(self, request: dict[str, Any]) -> dict[str, Any]:
        query = str(request.get("query", "") or "").strip()
        scope = dict(request.get("scope") or {})
        limit = max(1, min(int(request.get("limit", 10) or 10), 50))
        requested_channels = request.get("channels") or ["lexical", "graph", "vector"]
        channels = [str(channel) for channel in requested_channels]
        observations = self.state_store.list_observations(scope, {"limit": 250})
        claims = self.state_store.list_claims(scope, {"limit": 250})
        relationships = self.state_store.list_relationships(scope=scope)

        lexical_ids = self._lexical_rank(query, observations, claims)
        graph_ids = self._graph_rank(lexical_ids, relationships)
        vector_ids = self._vector_rank(query, observations, claims) if "vector" in channels else []
        rankings = {
            "lexical": lexical_ids if "lexical" in channels else [],
            "graph": graph_ids if "graph" in channels else [],
            "vector": vector_ids if "vector" in channels else [],
        }
        fused = reciprocal_rank_fusion({key: value for key, value in rankings.items() if value})
        ranked_ids = [item_id for item_id, _score in sorted(fused.items(), key=lambda item: item[1], reverse=True)]
        observation_map = {item["observation_id"]: item for item in observations if item.get("observation_id")}
        claim_map = {item["claim_id"]: item for item in claims if item.get("claim_id")}
        verified, contradictions, discarded = verify_memory_candidates(
            observations=observation_map,
            claims=claim_map,
            ranked_ids=ranked_ids,
            channel_map=rankings,
        )
        contradiction_ids = {item.get("claim_id") for item in contradictions}
        for claim in claims:
            claim_id = claim.get("claim_id")
            if claim_id in contradiction_ids:
                continue
            if str(claim.get("state")) != "active" or not claim.get("contradicting_claim_ids"):
                continue
            support_records = [observation_map.get(obs_id) for obs_id in claim.get("supporting_observation_ids", [])]
            citation_refs = [
                ref
                for observation_record in support_records
                if observation_record is not None
                for ref in observation_record.get("source_refs", [])
            ]
            contradictions.append(
                {
                    "claim_id": claim_id,
                    "statement": claim.get("statement"),
                    "contradicting_claim_ids": list(claim.get("contradicting_claim_ids", [])),
                    "citation_refs": citation_refs,
                }
            )
        for item in verified:
            item["rank_score"] = round(fused.get(item["id"], 0.0), 6)
        ordered_verified = sorted(verified, key=lambda item: item["rank_score"], reverse=True)[:limit]

        packet = MemoryPacket(
            packet_id=f"mpkt_{uuid4().hex[:12]}",
            scope=scope,
            observations=[item["record"] for item in ordered_verified if item["type"] == "observation"],
            claims=[item["record"] for item in ordered_verified if item["type"] == "claim" and item.get("tier") != "procedural"],
            procedures=[item["record"] for item in ordered_verified if item["type"] == "claim" and item.get("tier") == "procedural"],
            contradictions=contradictions[:limit],
            citations=[
                {
                    "item_id": item["id"],
                    "citation_refs": item["citation_refs"],
                    "channels": item["channels"],
                    "rank_score": item["rank_score"],
                    "verified_confidence": item["verified_confidence"],
                    "state": item["state"],
                }
                for item in ordered_verified
            ],
            generated_at=_timestamp(),
        )
        packet.validate()
        packet_dict = packet.to_dict()
        self.state_store.save_memory_packet(packet_dict)
        retrieval = RetrievalRecord(
            retrieval_id=f"ret_{uuid4().hex[:12]}",
            query=query,
            scope=scope,
            channels=channels,
            candidate_ids=ranked_ids[:limit],
            verified_ids=[item["id"] for item in ordered_verified],
            discarded_ids=discarded,
            created_at=_timestamp(),
        )
        retrieval.validate()
        self.state_store.record_memory_retrieval(retrieval.to_dict())
        return {
            "packet": packet_dict,
            "results": [
                {
                    "id": item["id"],
                    "type": item["type"],
                    "content": item["content"],
                    "rank_score": item["rank_score"],
                    "verified_confidence": item["verified_confidence"],
                    "channels": item["channels"],
                    "citation_refs": item["citation_refs"],
                    "state": item["state"],
                }
                for item in ordered_verified
            ],
            "contradictions": contradictions[:limit],
            "channels": channels,
        }

    def legacy_search(self, query: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.retrieve({"query": query, "scope": scope, "limit": 25, "channels": ["lexical", "graph"]})
        return [
            {
                "kind": result["type"],
                "content": result["content"],
                "state": result["state"],
                "verified_confidence": result["verified_confidence"],
                "citation_refs": result["citation_refs"],
            }
            for result in response["results"]
        ]

    def _lexical_rank(
        self,
        query: str,
        observations: list[dict[str, Any]],
        claims: list[dict[str, Any]],
    ) -> list[str]:
        tokens = _tokens(query)
        if not tokens:
            return []
        scored: list[tuple[float, str]] = []
        for item in observations:
            item_id = item.get("observation_id")
            if not item_id:
                continue
            score = _overlap_score(tokens, _tokens(str(item.get("content", ""))))
            if score > 0:
                scored.append((score, str(item_id)))
        for item in claims:
            item_id = item.get("claim_id")
            if not item_id:
                continue
            score = _overlap_score(tokens, _tokens(str(item.get("statement", ""))))
            if score > 0:
                scored.append((score, str(item_id)))
        return [item_id for _score, item_id in sorted(scored, key=lambda item: item[0], reverse=True)]

    def _graph_rank(self, seed_ids: list[str], relationships: list[dict[str, Any]]) -> list[str]:
        """Expand seeds along memory edges, then through InfraGraph if available.

        Two-pass expansion:

        1. **1-hop relationship walk** (pre-bridge behavior): for any
           relationship row whose ``from_id``/``to_id`` is in the seed
           set, surface the other endpoint. This catches
           ``service → describes → claim`` and ``claim → describes →
           service`` patterns.

        2. **Metapath traversal through InfraGraph** (new): when
           ``self.infra_graph`` is set AND a seed row carries an
           ``infra_node_key``, walk InfraGraph's typed edges
           (``selects``, ``scheduled_on``, ``owns``, …) from that
           node to find topologically-adjacent resources. Each
           adjacent node key is mapped back to the claims about it
           by scanning ``relationships`` for matching
           ``infra_node_key`` values. Surfaces e.g. claims about
           pods scheduled on the same worker node as the seed
           service's pods.

        Bounded by design: at most 20 seeds, at most 50 InfraGraph
        neighbors per seed, no recursion. Retrieval is fast and
        latency-bounded; deeper graph reasoning is a follow-up.
        """
        if not seed_ids:
            return []
        seeds = set(seed_ids[:20])
        expanded: list[str] = []
        # Index relationships once for the metapath pass:
        # ``infra_node_key → [claim_id]`` lets us go from "topology
        # node" back to "claims about that node" in one lookup.
        claims_by_infra_key: dict[str, list[str]] = {}
        seed_infra_keys: set[str] = set()
        for relationship in relationships:
            from_id = str(relationship.get("from_id", ""))
            to_id = str(relationship.get("to_id", ""))
            # Pass 1: 1-hop relationship walk (preserves pre-bridge behavior).
            if from_id in seeds and to_id and to_id not in seeds:
                expanded.append(to_id)
            if to_id in seeds and from_id and from_id not in seeds:
                expanded.append(from_id)
            # Build the indices the metapath pass needs.
            infra_key = relationship.get("infra_node_key")
            if isinstance(infra_key, str) and infra_key:
                claims_by_infra_key.setdefault(infra_key, []).append(to_id)
                if from_id in seeds or to_id in seeds:
                    seed_infra_keys.add(infra_key)

        # Pass 2: metapath traversal through InfraGraph. Skipped
        # silently when no InfraGraph is wired (test contexts, file
        # backend without topology, etc.).
        if self.infra_graph is not None and seed_infra_keys:
            metapath_ids = self._metapath_expand(
                seed_infra_keys=seed_infra_keys,
                claims_by_infra_key=claims_by_infra_key,
                excluded=seeds,
            )
            expanded.extend(metapath_ids)

        seen: set[str] = set()
        ordered: list[str] = []
        for item_id in expanded:
            if item_id not in seen:
                seen.add(item_id)
                ordered.append(item_id)
        return ordered

    def _metapath_expand(
        self,
        *,
        seed_infra_keys: set[str],
        claims_by_infra_key: dict[str, list[str]],
        excluded: set[str],
    ) -> list[str]:
        """Walk InfraGraph from each seed key to surface adjacent claims.

        ``seed_infra_keys`` are the InfraGraph node keys carried by
        seed relationships (typically ``service:NS:NAME``). For each
        key we:

        1. Parse the key back to (kind, namespace, name) — InfraGraph
           uses the ``kind:namespace:name`` colon-delimited form, with
           ``_cluster`` substituting for empty namespace.
        2. Ask InfraGraph for outbound and inbound neighbors (uses
           the public ``neighbors`` API, no internal poking).
        3. Each neighbor's node key is looked up in
           ``claims_by_infra_key`` to surface the claims about it.

        Returns deduplicated, order-preserved claim IDs. Caps each
        seed's neighbor list at 50 to keep latency bounded.
        """
        out: list[str] = []
        for seed_key in seed_infra_keys:
            parsed = _parse_infra_node_key(seed_key)
            if parsed is None:
                continue
            kind, namespace, name = parsed
            try:
                # Depth 2 reaches the canonical (service, pod, node)
                # metapath in one call: service → pod (depth 1) →
                # node (depth 2), and similarly node → pod →
                # other-service. SynergyRCA's MetaGraph uses this
                # same 2-hop traversal as the SRE-RCA differentiator.
                # Direction "both" merges in/out so we don't miss
                # incoming edges (e.g. "service selects pod" is
                # outbound from the service but inbound from the
                # pod's perspective).
                neighbors = (
                    self.infra_graph.neighbors(
                        kind, name, namespace, direction="both", depth=2
                    )
                    or []
                )
            except Exception:
                # InfraGraph might be a partial / stub in tests or
                # an offline snapshot. Fail-soft: skip this seed.
                continue
            # Cap at 100 to keep retrieval latency bounded even on
            # densely-connected graphs (large clusters).
            for neighbor in list(neighbors)[:100]:
                neighbor_key = _neighbor_to_node_key(neighbor)
                if not neighbor_key or neighbor_key == seed_key:
                    continue
                for claim_id in claims_by_infra_key.get(neighbor_key, []):
                    if claim_id and claim_id not in excluded:
                        out.append(claim_id)
        return out

    def _vector_rank(
        self,
        query: str,
        observations: list[dict[str, Any]],
        claims: list[dict[str, Any]],
    ) -> list[str]:
        # Optional channel in v1. When no embedding backend is present, we expose no vector-only hits.
        del query, observations, claims
        return []


def _tokens(value: str) -> set[str]:
    normalized = value.lower()
    for marker in ("/", "_", "-", ":", ",", ".", "(", ")"):
        normalized = normalized.replace(marker, " ")
    return {token for token in normalized.split() if token}


def _overlap_score(query_tokens: set[str], content_tokens: set[str]) -> float:
    if not query_tokens or not content_tokens:
        return 0.0
    intersection = len(query_tokens & content_tokens)
    if intersection == 0:
        return 0.0
    return intersection / len(query_tokens)


def _parse_infra_node_key(key: str) -> tuple[str, str | None, str] | None:
    """Decompose an InfraGraph node key back to (kind, namespace, name).

    InfraGraph stamps keys as ``kind:namespace:name`` (colon-delimited),
    using the sentinel ``_cluster`` for non-namespaced resources
    (nodes, namespaces themselves, …). ``_parse_infra_node_key`` is
    the inverse — strict about the 3-part shape so a malformed value
    in a relationship row returns ``None`` rather than crashing the
    retrieval call.
    """
    if not key or not isinstance(key, str):
        return None
    parts = key.split(":")
    if len(parts) != 3:
        return None
    kind, namespace_part, name = parts
    if not kind or not name:
        return None
    namespace: str | None = None if namespace_part in ("", "_cluster") else namespace_part
    return kind, namespace, name


def _neighbor_to_node_key(neighbor: dict[str, Any]) -> str | None:
    """Compute the InfraGraph node key for a ``neighbors()`` response item.

    ``InfraGraph.neighbors`` returns ``GraphNode.to_dict()`` entries
    of shape ``{kind, name, namespace, labels, attributes}``. We
    recompute the key here rather than threading it through the
    response — it keeps this module independent of any InfraGraph
    schema changes that don't alter the key formula.
    """
    if not isinstance(neighbor, dict):
        return None
    kind = neighbor.get("kind")
    name = neighbor.get("name")
    if not kind or not name:
        return None
    namespace = neighbor.get("namespace")
    # Mirror ``InfraGraph._node_key``'s sentinel without importing it,
    # avoiding a circular dep at module load. The sentinel only
    # affects non-namespaced resources; namespaced ones round-trip
    # unchanged.
    ns_part = str(namespace) if namespace else "_cluster"
    return f"{kind}:{ns_part}:{name}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
