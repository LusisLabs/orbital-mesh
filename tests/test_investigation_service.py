from __future__ import annotations

import tempfile
import unittest
from typing import Any

from services.evidence import EvidenceService
from services.ingest.service import IngestService
from services.investigation import InvestigationService
from services.runtime import MeshRuntimeEngine
from services.scenario_analysis import ScenarioAnalysisService
from services.trigger.service import TriggerService
from shared.mesh_runtime import InvestigationReport, RuntimeConfig, Trigger, load_fixture


def _trigger_and_signal():
    signal = load_fixture("signals", "search_latency_regression.json")
    envelope = IngestService().normalize_signal(signal)
    trigger = TriggerService().detect(envelope)
    assert trigger is not None
    return trigger, signal


class FailingInvestigationService(InvestigationService):
    def investigate(
        self,
        *,
        trigger: Trigger,
        evidence_pack: dict[str, Any] | None,
        memory_packet: dict[str, Any] | None = None,
        service_context: dict[str, Any] | None = None,
        topology: dict[str, Any] | None = None,
        recent_runs: list[dict[str, Any]] | None = None,
    ) -> InvestigationReport:
        raise RuntimeError("forced investigation failure")


class InvestigationServiceTests(unittest.TestCase):
    def test_investigation_report_validates_against_contract(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
        )

        payload = report.to_dict()
        validated = InvestigationReport.from_dict(payload)
        self.assertEqual(validated.trigger_id, trigger.trigger_id)
        self.assertEqual(validated.recommended_next_step, "continue_to_scenario_analysis")
        self.assertGreaterEqual(len(validated.probe_results), 2)
        self.assertTrue(all("source_type" in item for item in validated.citations))

    def test_runtime_emits_investigation_before_scenario_analysis(self) -> None:
        _, signal = _trigger_and_signal()
        with tempfile.TemporaryDirectory() as state_dir:
            result = MeshRuntimeEngine(
                config=RuntimeConfig(
                    state_directory=state_dir,
                    evaluation_mode="native",
                    orchestration_mode="native",
                ),
            ).run_sync(signal)

        event_types = [event["event_type"] for event in result["run_events"]]
        self.assertIn("investigation_ready", event_types)
        self.assertIn("scenario_analysis_ready", event_types)
        self.assertLess(event_types.index("investigation_ready"), event_types.index("scenario_analysis_ready"))
        self.assertIn("investigation_report", result)
        self.assertEqual(result["decision"]["decision_type"], "disable_flag")
        self.assertIn("investigation_report", result["decision"]["reasoning"]["evidence_pack"])

    def test_scenario_analysis_consumes_investigation_report_as_advisory_evidence(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
        )

        analysis, _ = ScenarioAnalysisService().analyze(
            trigger,
            investigation_report=report.to_dict(),
        )

        investigation_nodes = [
            node for node in analysis.evidence_nodes if node.get("analyzer") == "investigation"
        ]
        self.assertEqual(len(investigation_nodes), 1)
        self.assertEqual(investigation_nodes[0]["kind"], "investigation_report")
        self.assertEqual(analysis.suggested_decision_type, "disable_flag")

    def test_investigation_failure_records_artifact_and_existing_path_continues(self) -> None:
        _, signal = _trigger_and_signal()
        with tempfile.TemporaryDirectory() as state_dir:
            result = MeshRuntimeEngine(
                config=RuntimeConfig(
                    state_directory=state_dir,
                    evaluation_mode="native",
                    orchestration_mode="native",
                ),
                investigation=FailingInvestigationService(),
            ).run_sync(signal)

        self.assertEqual(result["decision"]["decision_type"], "disable_flag")
        self.assertEqual(
            result["investigation_report"]["stop_reason"],
            "investigation_failed_existing_path_continues",
        )
        investigation_events = [
            event for event in result["run_events"] if event["event_type"] == "investigation_ready"
        ]
        self.assertEqual(investigation_events[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
