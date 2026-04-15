"""Tests for the LearningStore — feedback-to-decision learning loop."""

from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from shared.mesh_runtime.learning import LearningStore


class LearningStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LearningStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_retrieve_outcome(self):
        self.store.record_outcome("restart_deployment", "search", "deployment/search", "successful", {"pattern": "restart_ok"})
        outcomes_path = Path(self._tmp.name) / "learning" / "outcomes.json"
        self.assertTrue(outcomes_path.exists())
        rate = self.store.get_historical_success_rate("restart_deployment")
        self.assertEqual(rate, 1.0)

    def test_success_rate_with_mixed_outcomes(self):
        for outcome in ["successful", "successful", "successful", "escalated"]:
            self.store.record_outcome("reduce_rollout", "api", "endpoint/api", outcome, {})
        rate = self.store.get_historical_success_rate("reduce_rollout")
        self.assertEqual(rate, 0.75)

    def test_success_rate_returns_none_when_empty(self):
        self.assertIsNone(self.store.get_historical_success_rate("reduce_rollout"))

    def test_success_rate_filtered_by_service(self):
        self.store.record_outcome("restart_deployment", "search", "deployment/search", "successful", {})
        self.store.record_outcome("restart_deployment", "auth", "deployment/auth", "escalated", {})
        rate_search = self.store.get_historical_success_rate("restart_deployment", service="search")
        rate_auth = self.store.get_historical_success_rate("restart_deployment", service="auth")
        self.assertEqual(rate_search, 1.0)
        self.assertEqual(rate_auth, 0.0)

    def test_enrich_context_with_recent_outcomes(self):
        self.store.record_outcome("reduce_rollout", "search", "endpoint/search", "escalated", {})
        self.store.record_outcome("restart_deployment", "search", "deployment/search", "successful", {})
        enrichment = self.store.enrich_context("search")
        self.assertEqual(enrichment["similar_prior_cases"], 2)
        self.assertGreaterEqual(enrichment["rollbacks_last_24h"], 1)
        self.assertGreaterEqual(enrichment["regressions_last_7d"], 1)

    def test_enrich_context_returns_zeros_when_empty(self):
        enrichment = self.store.enrich_context("nonexistent")
        self.assertEqual(enrichment["similar_prior_cases"], 0)
        self.assertEqual(enrichment["rollbacks_last_24h"], 0)
        self.assertEqual(enrichment["regressions_last_7d"], 0)

    def test_recovery_patterns(self):
        self.store.record_outcome("disable_flag", "search", "ep", "successful", {"service_recovery_pattern": "flag_disable_restores_latency"})
        self.store.record_outcome("disable_flag", "search", "ep", "successful", {"service_recovery_pattern": "flag_disable_restores_latency"})
        self.store.record_outcome("reduce_rollout", "search", "ep", "escalated", {"service_recovery_pattern": "rollout_reduction_insufficient"})
        patterns = self.store.get_recovery_patterns("search")
        self.assertEqual(patterns["flag_disable_restores_latency"], 2)
        self.assertEqual(patterns["rollout_reduction_insufficient"], 1)

    def test_outcomes_capped_at_500(self):
        for i in range(510):
            self.store.record_outcome("reduce_rollout", "svc", "ep", "successful", {})
        import json
        with open(Path(self._tmp.name) / "learning" / "outcomes.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["outcomes"]), 500)

    def test_concurrent_writes(self):
        errors = []

        def writer(n):
            try:
                for i in range(10):
                    self.store.record_outcome("restart", f"svc_{n}", "ep", "successful", {})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        rate = self.store.get_historical_success_rate("restart")
        self.assertEqual(rate, 1.0)


if __name__ == "__main__":
    unittest.main()
