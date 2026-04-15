from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime import FileStateStore, RuntimeConfig, build_mesh_state_store
from shared.mesh_runtime.mesh_state_store import RunFilters


class MeshStateStoreTests(unittest.TestCase):
    def test_factory_defaults_to_file_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault")
            store = build_mesh_state_store(config)
            self.assertIsInstance(store, FileStateStore)

    def test_file_store_preserves_run_event_snapshot_and_learning_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            goal = store.ensure_default_goal()
            session = store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="scenario_test",
                steering_mode="approval_gate",
                auto_mode=False,
                pause_points=["evaluation_ready"],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={"input_signal": {"service": "search"}},
            )
            event = store.append_run_event(
                session.run_id,
                stage="queued",
                event_type="run_queued",
                payload={"ok": True},
                summary={"status": "queued"},
                status="queued",
            )
            updated = store.get_run(session.run_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.latest_event_id, event.event_id)
            self.assertEqual(updated.latest_event_sequence, 1)
            self.assertEqual(len(store.list_events(session.run_id)), 1)
            self.assertEqual(store.list_runs(RunFilters(limit=1))[0].run_id, session.run_id)

            store.record_learning_outcome({
                "decision_type": "rollback_deployment",
                "service": "search",
                "endpoint": "deployment/search",
                "outcome": "successful",
                "world_model_updates": {"service_recovery_pattern": "rollback_restores_search"},
            })
            self.assertEqual(store.get_learning_context("search")["similar_prior_cases"], 1)
            self.assertEqual(store.get_historical_success_rate("rollback_deployment", "search"), 1.0)
            self.assertEqual(store.get_recovery_patterns("search")["rollback_restores_search"], 1)

    def test_postgres_backend_requires_database_url(self) -> None:
        with self.assertRaises(ValueError):
            build_mesh_state_store(RuntimeConfig(state_backend="postgres", database_url=None))


if __name__ == "__main__":
    unittest.main()
