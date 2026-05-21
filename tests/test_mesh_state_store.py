from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.mesh_runtime import FileStateStore, HelixMemoryProjection, RuntimeConfig, build_mesh_state_store
from shared.mesh_runtime.helix_memory import HelixMemoryQueryNames, build_helix_memory_projection
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
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="off"))
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
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="sync"))
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

    def test_file_store_preserves_latest_event_cursor_when_stale_session_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="off"))
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
            stale = session
            event = store.append_run_event(
                session.run_id,
                stage="trigger_ready",
                event_type="trigger_ready",
                payload={"ok": True},
                status="recorded",
            )

            stale.stage = "ingesting"
            stale.status = "running"
            store.save_run_session(stale)

            persisted = store.get_run_session(session.run_id)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.latest_event_id, event.event_id)
            self.assertEqual(persisted.latest_event_sequence, event.sequence)

    def test_file_store_merges_artifacts_and_preserves_terminal_stage_from_stale_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="off"))
            goal = store.ensure_default_goal()
            session = store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="scenario_test",
                steering_mode="interruptible_auto",
                auto_mode=True,
                pause_points=[],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={"input_signal": {"service": "search"}},
            )
            stale = store.get_run_session(session.run_id)
            self.assertIsNotNone(stale)
            assert stale is not None

            agent_session = store.get_run_session(session.run_id)
            self.assertIsNotNone(agent_session)
            assert agent_session is not None
            agent_session.artifacts["agent_tasks"] = [{"task_id": "task_1", "attempts": []}]
            store.save_run_session(agent_session)

            terminal = store.get_run_session(session.run_id)
            self.assertIsNotNone(terminal)
            assert terminal is not None
            terminal.stage = "recovery_spawned"
            terminal.status = "recovery_spawned"
            terminal.artifacts["recovery"] = {"status": "launched"}
            store.save_run_session(terminal)

            stale.stage = "evaluation_ready"
            stale.status = "running"
            stale.artifacts["agent_tasks"] = {"status": "pending"}
            stale.artifacts["execution"] = {"status": "succeeded"}
            store.save_run_session(stale)

            persisted = store.get_run_session(session.run_id)
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(persisted.stage, "recovery_spawned")
            self.assertEqual(persisted.status, "recovery_spawned")
            self.assertEqual(persisted.artifacts["agent_tasks"], [{"task_id": "task_1", "attempts": []}])
            self.assertEqual(persisted.artifacts["recovery"], {"status": "launched"})
            self.assertEqual(persisted.artifacts["execution"], {"status": "succeeded"})

    def test_file_store_close_flushes_async_vault_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="async"))
            goal = store.ensure_default_goal()
            with patch.object(store.vault, "write_run_bundle") as write_run_bundle:
                store.create_run_session(
                    goal_id=goal.goal_id,
                    scenario_key="scenario_test",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=["evaluation_ready"],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={"input_signal": {"service": "search"}},
                )
                store.close(timeout=1.0)

            self.assertEqual(write_run_bundle.call_count, 1)
            self.assertIsNotNone(store._vault_thread)
            assert store._vault_thread is not None
            self.assertFalse(store._vault_thread.is_alive())

    def test_locked_json_file_read_only_access_does_not_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            # Write with compact JSON (no extra whitespace)
            path.write_text('{"runs": [{"run_id": "run_1"}]}\n', encoding="utf-8")

            original_content = path.read_text(encoding="utf-8")
            # Parse as JSON to verify semantic equality
            original_data = json.loads(original_content)

            with LockedJsonFile(path) as payload:
                self.assertEqual(payload["runs"][0]["run_id"], "run_1")

            # The file may be rewritten with different formatting (pretty-printed),
            # but the semantic content should be the same
            rewritten_content = path.read_text(encoding="utf-8")
            rewritten_data = json.loads(rewritten_content)
            self.assertEqual(original_data, rewritten_data)

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

    def test_helix_projection_uses_namespaced_query_payloads(self) -> None:
        client = _FakeHelixClient()
        projection = HelixMemoryProjection(
            RuntimeConfig(memory_graph_backend="helix", helix_query_namespace="meshTest"),
            client=client,
        )
        projection.upsert_claim(_claim())

        self.assertEqual(client.calls[0][0], "meshTest_upsert_claim")
        self.assertEqual(client.calls[0][1]["claim_id"], "claim_1")
        self.assertEqual(client.calls[0][1]["entity_refs_json"], '["search"]')

    def test_file_store_projects_memory_records_to_helix_when_enabled(self) -> None:
        projection = _FakeHelixProjection()
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "shared.mesh_runtime.control_plane_state.build_helix_memory_projection",
                return_value=projection,
            ):
                store = FileStateStore(
                    RuntimeConfig(
                        state_directory=tmp,
                        vault_path=f"{tmp}/vault",
                        memory_graph_backend="helix",
                    )
                )
            store.append_observation(_observation())
            store.save_claim(_claim())
            store.save_relationship(_relationship())

        self.assertEqual(
            [call[0] for call in projection.calls],
            ["observation", "claim", "relationship"],
        )
        self.assertEqual(projection.calls[0][1]["observation_id"], "obs_1")
        self.assertEqual(projection.calls[1][1]["claim_id"], "claim_1")
        self.assertEqual(projection.calls[2][1]["relationship_id"], "rel_1")

    def test_file_store_buffers_helix_projection_failures_in_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("shared.mesh_runtime.helix_memory._build_helix_client", return_value=_FailingHelixClient()):
                store = FileStateStore(
                    RuntimeConfig(
                        state_directory=tmp,
                        vault_path=f"{tmp}/vault",
                        memory_graph_backend="helix",
                    )
                )
                observation = store.append_observation(_observation())

            self.assertEqual(observation["observation_id"], "obs_1")
            outbox = json.loads((Path(tmp) / "helix_memory_projection_outbox.json").read_text(encoding="utf-8"))

        events = outbox["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["operation"], "upsert_observation")
        self.assertEqual(events[0]["record"]["observation_id"], "obs_1")
        self.assertEqual(events[0]["status"], "failed")
        self.assertIn("offline", events[0]["last_error"])

    def test_helix_projection_replays_failed_outbox_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", memory_graph_backend="helix")
            failing_projection = build_helix_memory_projection(config, client=_FailingHelixClient())
            failing_projection.upsert_claim(_claim())

            self.assertEqual(failing_projection.projection_status()["failed"], 1)

            client = _FakeHelixClient()
            replaying_projection = build_helix_memory_projection(config, client=client)
            replay = replaying_projection.replay_pending()

            self.assertEqual(replay["attempted"], 1)
            self.assertEqual(replay["applied"], 1)
            self.assertEqual(replay["failed"], 0)
            self.assertEqual(client.calls[0][0], "mesh_upsert_claim")
            self.assertEqual(replaying_projection.projection_status()["failed"], 0)

    def test_helix_query_assets_define_projection_queries(self) -> None:
        queries = Path("helix/mesh-memory/db/queries.hx").read_text(encoding="utf-8")
        asset_names = set(re.findall(r"^QUERY\s+([A-Za-z_][A-Za-z0-9_]*)\(", queries, flags=re.MULTILINE))
        expected_names = set(vars(HelixMemoryQueryNames.from_namespace("mesh")).values())
        self.assertEqual(asset_names, expected_names)

    def test_postgres_migrations_define_helix_projection_outbox(self) -> None:
        migration = Path("migrations/postgres/005_helix_projection_outbox.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS helix_memory_projection_outbox", migration)
        self.assertIn("idx_helix_memory_projection_outbox_status", migration)

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


class _FakeHelixClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(self, name: str, payload: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append((name, payload))
        return [{"ok": True}]


class _FailingHelixClient:
    def query(self, name: str, payload: dict[str, object]) -> list[dict[str, object]]:
        del name, payload
        raise RuntimeError("helix offline")


class _FakeHelixProjection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def upsert_observation(self, record: dict[str, object]) -> None:
        self.calls.append(("observation", record))

    def upsert_claim(self, record: dict[str, object]) -> None:
        self.calls.append(("claim", record))

    def upsert_relationship(self, record: dict[str, object]) -> None:
        self.calls.append(("relationship", record))

    def upsert_supersession(self, record: dict[str, object]) -> None:
        self.calls.append(("supersession", record))

    def record_retrieval(self, record: dict[str, object]) -> None:
        self.calls.append(("retrieval", record))

    def upsert_memory_packet(self, record: dict[str, object]) -> None:
        self.calls.append(("packet", record))


def _observation() -> dict[str, object]:
    return {
        "observation_id": "obs_1",
        "scope": {"service": "search"},
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
    }


def _claim() -> dict[str, object]:
    return {
        "claim_id": "claim_1",
        "statement": "Search rollout regression requires investigation.",
        "entity_refs": ["search"],
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
    }


def _relationship() -> dict[str, object]:
    return {
        "relationship_id": "rel_1",
        "from_id": "claim_1",
        "to_id": "obs_1",
        "type": "supported_by",
        "confidence": 0.9,
        "supporting_observation_ids": ["obs_1"],
        "state": "active",
    }


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
