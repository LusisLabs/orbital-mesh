from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime import FileStateStore, RuntimeConfig
from shared.mesh_runtime.memory_lifecycle import MemoryLifecycleService


class MemoryLifecycleTests(unittest.TestCase):
    def test_memory_maintenance_demotes_stale_and_promotes_supported_semantic_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            store.save_claim({
                "claim_id": "claim_stale",
                "statement": "Old transient incident note",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_1"],
                "contradicting_claim_ids": [],
                "superseded_by": None,
                "confidence": 0.5,
                "confidence_factors": {
                    "support_score": 0.4,
                    "recency_score": 0.4,
                    "authority_score": 0.6,
                    "consistency_score": 0.5,
                    "verification_score": 0.5,
                },
                "freshness": 0.4,
                "tier": "episodic",
                "state": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
            store.save_claim({
                "claim_id": "claim_promote",
                "statement": "Rollback is the standard mitigation for this service",
                "entity_refs": ["search"],
                "supporting_observation_ids": ["obs_1", "obs_2", "obs_3"],
                "contradicting_claim_ids": [],
                "superseded_by": None,
                "confidence": 0.9,
                "confidence_factors": {
                    "support_score": 0.9,
                    "recency_score": 0.95,
                    "authority_score": 0.9,
                    "consistency_score": 0.9,
                    "verification_score": 0.9,
                },
                "freshness": 0.95,
                "tier": "semantic",
                "state": "active",
                "created_at": "2026-04-15T00:00:00+00:00",
                "updated_at": "2026-04-15T00:00:00+00:00",
            })

            result = MemoryLifecycleService(store).run_memory_maintenance(now="2026-10-01T00:00:00+00:00")

            self.assertEqual(store.get_claim("claim_stale")["state"], "stale")
            self.assertEqual(store.get_claim("claim_promote")["tier"], "procedural")
            self.assertGreaterEqual(result["claims_updated"], 2)


if __name__ == "__main__":
    unittest.main()
