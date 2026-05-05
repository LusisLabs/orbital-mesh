"""Tests for the TrustLadder — per-(action_class, service) graduation."""

from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime.trust_ladder import TRUST_LEVELS, TrustLadder


class TrustLadderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Lowered thresholds so tests stay small and fast.
        self.ladder = TrustLadder(
            self._tmp.name,
            min_draft_runs=3,
            min_approve_runs=5,
            min_auto_runs=10,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_unknown_pair_defaults_to_suggest(self):
        self.assertEqual(self.ladder.get_level("restart_deployment", "search"), "suggest")
        entry = self.ladder.get_entry("restart_deployment", "search")
        self.assertEqual(entry["next_level"], "draft")
        self.assertEqual(entry["promotion_requirements"], {"min_runs": 3, "min_success_rate": 0.5})
        self.assertIn("3 more successful or reviewed runs before draft", entry["promotion_blockers"])
        self.assertIn("success rate 0% below 50% for draft", entry["autonomy_ceiling_reason"])

    def test_graduation_suggest_to_draft(self):
        for _ in range(3):
            self.ladder.record_outcome("restart_deployment", "search", "successful")
        self.assertEqual(self.ladder.get_level("restart_deployment", "search"), "draft")

    def test_graduation_through_all_levels(self):
        # 10 successes → auto
        for _ in range(10):
            self.ladder.record_outcome("restart_deployment", "search", "successful")
        entry = self.ladder.get_entry("restart_deployment", "search")
        self.assertEqual(entry["level"], "auto")
        self.assertEqual(entry["success_rate"], 1.0)
        self.assertIsNone(entry["next_level"])
        self.assertEqual(entry["promotion_blockers"], [])
        self.assertIn("auto ceiling reached", entry["autonomy_ceiling_reason"])

    def test_demotion_on_consecutive_failures(self):
        # Graduate to auto first
        for _ in range(10):
            self.ladder.record_outcome("restart_deployment", "search", "successful")
        self.assertEqual(self.ladder.get_level("restart_deployment", "search"), "auto")
        # Two consecutive failures → demote
        self.ladder.record_outcome("restart_deployment", "search", "escalated")
        self.ladder.record_outcome("restart_deployment", "search", "escalated")
        # After 2 failures: consecutive_failures=2 triggers demotion once per call
        entry = self.ladder.get_entry("restart_deployment", "search")
        self.assertIn(entry["level"], ("approve", "draft", "suggest"))
        self.assertLess(TRUST_LEVELS.index(entry["level"]), TRUST_LEVELS.index("auto"))

    def test_success_rate_blocks_graduation_when_too_low(self):
        # 3 runs, only 1 successful → 33% below the 50% draft threshold
        self.ladder.record_outcome("reduce_rollout", "api", "successful")
        self.ladder.record_outcome("reduce_rollout", "api", "escalated")
        self.ladder.record_outcome("reduce_rollout", "api", "escalated")
        entry = self.ladder.get_entry("reduce_rollout", "api")
        # After 2 consecutive failures demotion kicks in, so still suggest
        self.assertEqual(entry["level"], "suggest")

    def test_override_bypasses_rules(self):
        self.ladder.record_outcome("scale_deployment", "api", "successful")
        self.ladder.override_level("scale_deployment", "api", "auto", reason="operator_bootstrap")
        entry = self.ladder.get_entry("scale_deployment", "api")
        self.assertEqual(entry["level"], "auto")
        self.assertEqual(entry["manual_override_reason"], "operator_bootstrap")
        self.assertIn("manual override: operator_bootstrap", entry["promotion_blockers"])

    def test_override_rejects_unknown_level(self):
        with self.assertRaises(ValueError):
            self.ladder.override_level("scale_deployment", "api", "godmode")

    def test_override_outcome_does_not_affect_counts(self):
        # Baseline
        for _ in range(3):
            self.ladder.record_outcome("restart_deployment", "web", "successful")
        entry_before = self.ladder.get_entry("restart_deployment", "web")
        self.assertEqual(entry_before["total_runs"], 3)
        # Override run — shouldn't change counters
        self.ladder.record_outcome("restart_deployment", "web", "successful", override=True)
        entry_after = self.ladder.get_entry("restart_deployment", "web")
        self.assertEqual(entry_after["total_runs"], 3)
        self.assertEqual(entry_after["override_count"], 1)

    def test_list_entries(self):
        self.ladder.record_outcome("restart_deployment", "search", "successful")
        self.ladder.record_outcome("scale_deployment", "api", "successful")
        entries = self.ladder.list_entries()
        self.assertEqual(len(entries), 2)
        keys = {(e["action_class"], e["service"]) for e in entries}
        self.assertEqual(keys, {("restart_deployment", "search"), ("scale_deployment", "api")})


class TrustLadderConcurrencyTests(unittest.TestCase):
    def test_concurrent_writes(self):
        import threading
        tmp = tempfile.TemporaryDirectory()
        try:
            ladder = TrustLadder(tmp.name)
            errors: list[Exception] = []

            def worker(idx: int) -> None:
                try:
                    for _ in range(5):
                        ladder.record_outcome("restart_deployment", f"svc-{idx}", "successful")
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            entries = ladder.list_entries()
            self.assertEqual(len(entries), 4)
            for entry in entries:
                self.assertEqual(entry["total_runs"], 5)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
