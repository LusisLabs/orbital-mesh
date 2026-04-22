from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .contracts import MemoryPacket, RetrievalRecord
from .memory_scoring import reciprocal_rank_fusion
from .memory_verifier import verify_memory_candidates


class MemoryRetrievalService:
    def __init__(self, state_store: Any):
        self.state_store = state_store

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
        if not seed_ids:
            return []
        seeds = set(seed_ids[:20])
        expanded: list[str] = []
        for relationship in relationships:
            from_id = str(relationship.get("from_id", ""))
            to_id = str(relationship.get("to_id", ""))
            if from_id in seeds and to_id and to_id not in seeds:
                expanded.append(to_id)
            if to_id in seeds and from_id and from_id not in seeds:
                expanded.append(from_id)
        seen: set[str] = set()
        ordered: list[str] = []
        for item_id in expanded:
            if item_id not in seen:
                seen.add(item_id)
                ordered.append(item_id)
        return ordered

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


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
