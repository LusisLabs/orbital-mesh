from __future__ import annotations

import tempfile
import unittest

from shared.mesh_runtime import FileStateStore, RuntimeConfig
from shared.mesh_runtime.memory_lifecycle import MemoryLifecycleService


class MemoryCrystallizationTests(unittest.TestCase):
    def test_crystallize_run_emits_observations_and_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            goal = store.ensure_default_goal()
            session = store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="search_latency_regression",
                steering_mode="interruptible_auto",
                auto_mode=True,
                pause_points=[],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={
                    "trigger": {"service": "search"},
                    "decision": {"summary": "Disable the rollout", "decision_type": "disable_flag"},
                    "feedback": {"outcome": "successful"},
                    "agent_tasks": [{"attempts": [{"agent": "hermes", "summary": "Root cause points to rollout timing.", "citations": [{"ref": "obs"}]}]}],
                },
            )
            session.operator_notes.append("Operator confirmed the blast radius was contained.")
            store.save_run_session(session)
            store.append_run_event(
                session.run_id,
                stage="trigger_ready",
                event_type="trigger_ready",
                payload={"service": "search"},
                summary={"trigger_type": "feature_flag_performance_regression"},
                artifact_key="trigger",
                status="recorded",
            )

            result = MemoryLifecycleService(store).crystallize_run(session.run_id)

            self.assertGreaterEqual(result["observations_recorded"], 2)
            self.assertGreaterEqual(result["claims_recorded"], 1)
            claims = store.list_claims({"service": "search"}, {"limit": 20})
            self.assertTrue(any("Disable the rollout" in claim["statement"] for claim in claims))


if __name__ == "__main__":
    unittest.main()
