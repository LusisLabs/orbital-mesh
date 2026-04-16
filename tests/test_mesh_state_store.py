from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.mesh_runtime import FileStateStore, RuntimeConfig, build_mesh_state_store
from shared.mesh_runtime.json_store import LockedJsonFile
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

    def test_locked_json_file_read_only_access_does_not_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"runs": [{"run_id": "run_1"}]}\n', encoding="utf-8")

            with patch("shared.mesh_runtime.json_store.os.replace") as replace_mock:
                with LockedJsonFile(path) as payload:
                    self.assertEqual(payload["runs"][0]["run_id"], "run_1")

            replace_mock.assert_not_called()

    def test_file_store_lists_empty_runs_when_run_session_file_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_sessions.json"
            raw = '{"runs": [{"run_id": "x" INVALID}]}'
            path.write_text(raw, encoding="utf-8")

            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))

            self.assertEqual(store.list_run_sessions(), [])
            backups = sorted(Path(tmp).glob("run_sessions.json.corrupt.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), raw)
            self.assertEqual(path.read_text(encoding="utf-8"), "{}\n")

    def test_postgres_backend_requires_database_url(self) -> None:
        with self.assertRaises(ValueError):
            build_mesh_state_store(RuntimeConfig(state_backend="postgres", database_url=None))


if __name__ == "__main__":
    unittest.main()
