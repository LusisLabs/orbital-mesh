from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import (
    FileBackedWorkflowStore,
    FileStateStore,
    MeshStateWorkflowStore,
    RuntimeConfig,
    attach_workflow_event,
    resume_workflow,
    schedule_workflow_retry,
    start_or_replay_workflow,
)


class DurableWorkflowTests(unittest.TestCase):
    def test_workflow_replays_checkpoint_and_attaches_run_event_without_stage_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_store = FileStateStore(
                RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="off")
            )
            goal = state_store.ensure_default_goal()
            session = state_store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="scenario_test",
                steering_mode="approval_gate",
                auto_mode=False,
                pause_points=[],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={},
            )
            workflow_store = FileBackedWorkflowStore(Path(tmp) / "workflows")
            workflow = start_or_replay_workflow(
                store=workflow_store,
                workflow_id="wf_readiness",
                workflow_type="recurring_readiness_sweep",
                run_id=session.run_id,
                sleep_until="2026-05-21T01:00:00Z",
            )

            recorded = attach_workflow_event(
                workflow=workflow,
                store=workflow_store,
                state_store=state_store,
                checkpoint_id="checkpoint_1",
                payload={"note": "ready"},
            )
            replayed = attach_workflow_event(
                workflow=recorded,
                store=workflow_store,
                state_store=state_store,
                checkpoint_id="checkpoint_1",
                payload={"note": "ready"},
            )

            events = state_store.list_run_events(session.run_id)
            current = state_store.get_run_session(session.run_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "durable_workflow_checkpoint")
            self.assertEqual(events[0].payload["workflow_id"], "wf_readiness")
            self.assertEqual(len(replayed["checkpoints"]), 1)
            self.assertIsNotNone(current)
            assert current is not None
            self.assertEqual(current.stage, "queued")

    def test_workflow_can_resume_and_retry_without_owning_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow_store = FileBackedWorkflowStore(Path(tmp) / "workflows")
            workflow = start_or_replay_workflow(
                store=workflow_store,
                workflow_id="wf_approval_expiration",
                workflow_type="wait_for_approval_expiration",
                run_id="run_waiting",
                sleep_until="2026-05-21T01:00:00Z",
            )

            resumed = resume_workflow(
                workflow=workflow,
                store=workflow_store,
                reason="sleep_deadline_reached",
            )
            retried = schedule_workflow_retry(
                workflow=resumed,
                store=workflow_store,
                retry_after="2026-05-21T01:05:00Z",
                reason="operator_identity_lookup_unavailable",
            )
            replayed = workflow_store.load("wf_approval_expiration")

            self.assertEqual(resumed["status"], "ready")
            self.assertIsNone(resumed["sleep_until"])
            self.assertEqual(retried["status"], "retry_scheduled")
            self.assertEqual(retried["retry_count"], 1)
            self.assertIsNotNone(replayed)
            assert replayed is not None
            self.assertEqual(replayed["retry_reason"], "operator_identity_lookup_unavailable")
            self.assertFalse(replayed["authority"]["workflow_owns_remediation"])

    def test_workflow_state_can_persist_through_mesh_state_store_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_store = FileStateStore(
                RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault", vault_mirror_mode="off")
            )
            goal = state_store.ensure_default_goal()
            session = state_store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="scenario_test",
                steering_mode="approval_gate",
                auto_mode=False,
                pause_points=[],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={},
            )
            workflow_store = MeshStateWorkflowStore(state_store, run_id=session.run_id)
            workflow = start_or_replay_workflow(
                store=workflow_store,
                workflow_id="wf_postgres_compatible",
                workflow_type="delayed_evidence_refresh",
                run_id=session.run_id,
                sleep_until="2026-05-21T01:00:00Z",
            )

            resumed = resume_workflow(
                workflow=workflow,
                store=workflow_store,
                reason="process_restarted",
            )
            replay_store = MeshStateWorkflowStore(state_store, run_id=session.run_id)
            replayed = replay_store.load("wf_postgres_compatible")
            events = state_store.list_run_events(session.run_id)

            self.assertEqual(resumed["status"], "ready")
            self.assertIsNotNone(replayed)
            assert replayed is not None
            self.assertEqual(replayed["resume_reason"], "process_restarted")
            self.assertIn("durable_workflow_state", {event.event_type for event in events})
            self.assertFalse(replayed["authority"]["workflow_owns_remediation"])


if __name__ == "__main__":
    unittest.main()
