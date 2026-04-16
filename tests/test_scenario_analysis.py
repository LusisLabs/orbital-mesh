from __future__ import annotations

import tempfile
import unittest

from services.decision.service import DecisionService
from services.ingest.service import IngestService
from services.scenario_analysis import ScenarioAnalysisService
from services.trigger.service import TriggerService
from shared.mesh_runtime import ActiveMemoryStore, FileStateStore, RuntimeConfig, load_fixture


def _feature_flag_trigger():
    raw = load_fixture("signals", "search_latency_regression.json")
    envelope = IngestService().normalize_signal(raw)
    trigger = TriggerService().detect(envelope)
    assert trigger is not None
    return trigger


class ScenarioAnalysisTests(unittest.TestCase):
    def test_analyzers_return_schema_valid_subdecisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trigger = _feature_flag_trigger()
            service = ScenarioAnalysisService(active_memory=ActiveMemoryStore(tmp))

            analysis, compaction = service.analyze(trigger)

            self.assertGreaterEqual(len(analysis.subdecisions), 6)
            self.assertGreaterEqual(len(analysis.evidence_nodes), 6)
            self.assertEqual(analysis.suggested_decision_type, "disable_flag")
            self.assertIsNotNone(compaction)
            for subdecision in analysis.subdecisions:
                self.assertIn("subdecision_id", subdecision)
                self.assertIn("evidence_refs", subdecision)

    def test_edge_case_analysis_routes_conflicts_to_review(self) -> None:
        trigger = _feature_flag_trigger()
        trigger.related_context["conflicting_signals"] = True
        analysis, _ = ScenarioAnalysisService().analyze(trigger)

        decision = DecisionService().decide(trigger, scenario_analysis=analysis)

        self.assertIn("conflicting signals are present", analysis.required_review_reasons)
        self.assertEqual(decision.autonomy_tier, "escalated")
        self.assertEqual(decision.decision_type, "escalate")
        self.assertLessEqual(decision.confidence, 0.74)

    def test_memory_compaction_keeps_active_context_separate_from_run_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(RuntimeConfig(state_directory=tmp, vault_path=f"{tmp}/vault"))
            active_memory = ActiveMemoryStore(tmp)
            goal = store.ensure_default_goal()
            session = store.create_run_session(
                goal_id=goal.goal_id,
                scenario_key="search_latency_regression",
                steering_mode="approval_gate",
                auto_mode=False,
                pause_points=["evaluation_ready"],
                evaluation_mode="native",
                orchestration_mode="native",
                artifacts={},
            )
            trigger = _feature_flag_trigger()
            store.append_run_event(
                session.run_id,
                stage="trigger_ready",
                event_type="trigger_ready",
                payload=trigger.to_dict(),
                summary={"trigger_type": trigger.trigger_type},
                artifact_key="trigger",
                status="recorded",
            )

            analysis, compaction = ScenarioAnalysisService(
                state_store=store,
                active_memory=active_memory,
            ).analyze(trigger, run_id=session.run_id)

            snapshot = active_memory.active_facts(trigger.service)
            self.assertIn(trigger.service, snapshot["services"])
            self.assertGreater(len(snapshot["services"][trigger.service]), 0)
            self.assertGreaterEqual(len(store.list_run_events(session.run_id)), 1)
            self.assertIsNotNone(compaction)
            self.assertGreaterEqual(len(analysis.evidence_refs), 1)


if __name__ == "__main__":
    unittest.main()
