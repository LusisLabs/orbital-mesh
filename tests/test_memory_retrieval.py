from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime import FileStateStore, RuntimeConfig


class MemoryRetrievalTests(unittest.TestCase):
    def test_verified_retrieval_filters_superseded_and_contradictory_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            store.append_observation({
                "observation_id": "obs_a",
                "scope": {"shared": True, "service": "search"},
                "kind": "note",
                "content": "Redis upgrade increased search latency.",
                "service": "search",
                "run_id": "run_1",
                "source_type": "run_event",
                "source_refs": [{"run_id": "run_1", "event_id": "evt_1"}],
                "created_at": "2026-04-16T00:00:00+00:00",
                "author": "mesh",
                "tags": [],
                "metadata": {},
            })
            store.append_observation({
                "observation_id": "obs_b",
                "scope": {"shared": True, "service": "search"},
                "kind": "note",
                "content": "Search latency stabilized after rollback.",
                "service": "search",
                "run_id": "run_2",
                "source_type": "run_event",
                "source_refs": [{"run_id": "run_2", "event_id": "evt_2"}],
                "created_at": "2026-04-17T00:00:00+00:00",
                "author": "mesh",
                "tags": [],
                "metadata": {},
            })
            store.save_claim({
                "claim_id": "claim_old",
                "statement": "Redis upgrade caused the regression",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_a"],
                "contradicting_claim_ids": [],
                "superseded_by": "claim_new",
                "confidence": 0.7,
                "confidence_factors": {
                    "support_score": 0.5,
                    "recency_score": 0.5,
                    "authority_score": 0.8,
                    "consistency_score": 0.7,
                    "verification_score": 0.7,
                },
                "freshness": 0.5,
                "tier": "semantic",
                "state": "superseded",
                "created_at": "2026-04-16T00:00:00+00:00",
                "updated_at": "2026-04-16T00:00:00+00:00",
            })
            store.save_claim({
                "claim_id": "claim_new",
                "statement": "Rollback reversed the Redis-related regression",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_b"],
                "contradicting_claim_ids": [],
                "superseded_by": None,
                "confidence": 0.88,
                "confidence_factors": {
                    "support_score": 0.8,
                    "recency_score": 0.9,
                    "authority_score": 0.8,
                    "consistency_score": 0.9,
                    "verification_score": 0.85,
                },
                "freshness": 0.9,
                "tier": "semantic",
                "state": "active",
                "created_at": "2026-04-17T00:00:00+00:00",
                "updated_at": "2026-04-17T00:00:00+00:00",
            })
            store.save_claim({
                "claim_id": "claim_conflict_a",
                "statement": "Search uses Redis for caching",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_a"],
                "contradicting_claim_ids": ["claim_conflict_b"],
                "superseded_by": None,
                "confidence": 0.75,
                "confidence_factors": {
                    "support_score": 0.6,
                    "recency_score": 0.6,
                    "authority_score": 0.8,
                    "consistency_score": 0.5,
                    "verification_score": 0.7,
                },
                "freshness": 0.6,
                "tier": "semantic",
                "state": "active",
                "created_at": "2026-04-16T00:00:00+00:00",
                "updated_at": "2026-04-16T00:00:00+00:00",
            })
            store.save_claim({
                "claim_id": "claim_conflict_b",
                "statement": "Search does not use Redis for caching",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_b"],
                "contradicting_claim_ids": ["claim_conflict_a"],
                "superseded_by": None,
                "confidence": 0.72,
                "confidence_factors": {
                    "support_score": 0.6,
                    "recency_score": 0.6,
                    "authority_score": 0.8,
                    "consistency_score": 0.5,
                    "verification_score": 0.7,
                },
                "freshness": 0.6,
                "tier": "semantic",
                "state": "active",
                "created_at": "2026-04-17T00:00:00+00:00",
                "updated_at": "2026-04-17T00:00:00+00:00",
            })

            response = store.retrieve_memory({"query": "redis regression", "scope": {"service": "search"}, "limit": 10})

            result_ids = [item["id"] for item in response["results"]]
            self.assertIn("claim_new", result_ids)
            self.assertNotIn("claim_old", result_ids)
            self.assertNotIn("claim_conflict_a", result_ids)
            self.assertNotIn("claim_conflict_b", result_ids)
            contradiction_ids = {item["claim_id"] for item in response["contradictions"]}
            self.assertIn("claim_conflict_a", contradiction_ids)
            self.assertIn("claim_conflict_b", contradiction_ids)


if __name__ == "__main__":
    unittest.main()
