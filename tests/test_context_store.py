"""Tests for the ContextStore — service topology and incident history."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.context_store import ContextStore


def _mock_run_session(
    service="search",
    deployment_name="semantic-search",
    namespace="search",
    decision_type="restart_deployment",
    outcome="successful",
    error_signatures=None,
    run_id="run_test_001",
):
    return {
        "run_id": run_id,
        "artifacts": {
            "trigger": {
                "service": service,
                "related_context": {
                    "deployment_name": deployment_name,
                    "namespace": namespace,
                    "error_signatures": error_signatures or [],
                },
            },
            "decision": {
                "decision_type": decision_type,
                "summary": f"Action for {service}",
            },
            "feedback": {
                "outcome": outcome,
            },
        },
    }


class ContextStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ContextStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_update_from_run_creates_service_record(self):
        self.store.update_from_run(_mock_run_session())
        ctx = self.store.get_service_context("search")
        self.assertEqual(ctx["service_name"], "search")
        self.assertEqual(ctx["total_runs"], 1)
        self.assertEqual(ctx["successful_runs"], 1)
        self.assertIn("semantic-search", ctx["deployment_names"])
        self.assertIn("search", ctx["namespaces"])

    def test_update_from_run_increments_counters(self):
        self.store.update_from_run(_mock_run_session(outcome="successful"))
        self.store.update_from_run(_mock_run_session(outcome="escalated"))
        ctx = self.store.get_service_context("search")
        self.assertEqual(ctx["total_runs"], 2)
        self.assertEqual(ctx["successful_runs"], 1)
        self.assertAlmostEqual(ctx["success_rate"], 0.5)

    def test_get_service_context_returns_empty_for_unknown(self):
        self.assertEqual(self.store.get_service_context("nonexistent"), {})

    def test_get_similar_incidents(self):
        self.store.update_from_run(_mock_run_session(error_signatures=["crash_loop"], run_id="r1"))
        self.store.update_from_run(_mock_run_session(error_signatures=["image_pull_failure"], run_id="r2"))
        self.store.update_from_run(_mock_run_session(error_signatures=["crash_loop"], run_id="r3"))
        matches = self.store.get_similar_incidents("crash_loop")
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["run_id"], "r3")

    def test_incidents_capped_at_200(self):
        for i in range(210):
            self.store.update_from_run(_mock_run_session(
                error_signatures=["error"], run_id=f"r{i}",
            ))
        with open(Path(self._tmp.name) / "context" / "incidents.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["incidents"]), 200)

    def test_list_services(self):
        self.store.update_from_run(_mock_run_session(service="search"))
        self.store.update_from_run(_mock_run_session(service="auth"))
        services = self.store.list_services()
        names = {s["service_name"] for s in services}
        self.assertEqual(names, {"search", "auth"})

    def test_error_patterns_tracked(self):
        self.store.update_from_run(_mock_run_session(error_signatures=["crash_loop"]))
        self.store.update_from_run(_mock_run_session(error_signatures=["oom_killed"]))
        ctx = self.store.get_service_context("search")
        self.assertIn("crash_loop", ctx["common_error_patterns"])
        self.assertIn("oom_killed", ctx["common_error_patterns"])


if __name__ == "__main__":
    unittest.main()
