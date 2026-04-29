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

    def test_file_store_debounces_running_vault_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            goal = store.ensure_default_goal()
            with patch.object(store.vault, "write_run_bundle") as write_run_bundle:
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
                self.assertEqual(write_run_bundle.call_count, 1)

                store.append_run_event(
                    session.run_id,
                    stage="scenario_analysis_ready",
                    event_type="subdecision_recorded",
                    payload={"ok": True},
                    status="recorded",
                )
                store.append_run_event(
                    session.run_id,
                    stage="scenario_analysis_ready",
                    event_type="subdecision_recorded",
                    payload={"ok": True},
                    status="recorded",
                )
                self.assertEqual(write_run_bundle.call_count, 1)

                updated = store.get_run_session(session.run_id)
                self.assertIsNotNone(updated)
                assert updated is not None
                updated.stage = "awaiting_operator"
                updated.status = "awaiting_operator"
                store.save_run_session(updated)
                self.assertEqual(write_run_bundle.call_count, 2)

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

    def test_file_store_persists_verified_memory_records_and_packets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            observation = store.append_observation({
                "observation_id": "obs_1",
                "scope": {"shared": True, "service": "search"},
                "kind": "incident_summary",
                "content": "Search latency spiked after rollout.",
                "service": "search",
                "run_id": "run_1",
                "source_type": "run_event",
                "source_refs": [{"run_id": "run_1", "event_id": "evt_1"}],
                "created_at": "2026-04-16T00:00:00+00:00",
                "author": "mesh",
                "tags": ["search"],
                "metadata": {},
            })
            self.assertEqual(observation["observation_id"], "obs_1")

            claim = store.save_claim({
                "claim_id": "claim_1",
                "statement": "Search rollout regression requires investigation.",
                "entity_refs": ["search", "disable_flag"],
                "supporting_observation_ids": ["obs_1"],
                "contradicting_claim_ids": [],
                "superseded_by": None,
                "confidence": 0.81,
                "confidence_factors": {
                    "support_score": 0.7,
                    "recency_score": 0.8,
                    "authority_score": 0.9,
                    "consistency_score": 0.8,
                    "verification_score": 0.85,
                },
                "freshness": 0.8,
                "tier": "semantic",
                "state": "active",
                "created_at": "2026-04-16T00:00:00+00:00",
                "updated_at": "2026-04-16T00:00:00+00:00",
            })
            self.assertEqual(claim["claim_id"], "claim_1")

            response = store.retrieve_memory({"query": "search rollout regression", "scope": {"service": "search"}, "limit": 5})
            self.assertEqual(response["packet"]["claims"][0]["claim_id"], "claim_1")
            self.assertEqual(response["results"][0]["state"], "active")

            packet_id = response["packet"]["packet_id"]
            self.assertEqual(store.get_memory_packet(packet_id)["packet_id"], packet_id)

            maintenance = store.run_memory_maintenance(now="2026-09-16T00:00:00+00:00")
            self.assertGreaterEqual(maintenance["claims_scanned"], 1)

            tree = store.tree()
            flat_paths = _flatten_tree(tree)
            self.assertIn("MemoryObservations/obs_1.md", flat_paths)
            self.assertIn("MemoryClaims/claim_1.md", flat_paths)
            self.assertTrue(any(path.startswith("MemoryRetrievals/ret_") for path in flat_paths))


def _flatten_tree(nodes: list[dict[str, object]]) -> list[str]:
    paths: list[str] = []
    for node in nodes:
        path = node["path"]
        if isinstance(path, str):
            paths.append(path)
        children = node.get("children")
        if isinstance(children, list):
            paths.extend(_flatten_tree(children))
    return paths


if __name__ == "__main__":
    unittest.main()
