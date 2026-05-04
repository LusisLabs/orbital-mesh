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
        tool_provider: Any = None,
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


class CloudOpsRcaOntologyTests(unittest.TestCase):
    def test_ontology_ranks_image_pull_failure_above_others(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        ranked = rank_root_causes([
            "productcatalogservice 0/1 ImagePullBackOff",
            "Reason: ErrImagePull manifest unknown",
        ])

        self.assertTrue(ranked, "expected at least one ranked cause")
        self.assertEqual(ranked[0].root_cause, "incorrect_image_reference")
        self.assertGreater(ranked[0].confidence, 0.0)

    def test_ontology_returns_empty_when_no_signals(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        ranked = rank_root_causes(["pod is healthy", "no events"])

        self.assertEqual(ranked, [])

    def test_ontology_distinguishes_selector_from_taint(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        selector = rank_root_causes(["0/3 nodes are available: 3 didn't match Pod's node affinity/selector"])
        taint = rank_root_causes(["0/3 nodes are available: 3 had untolerated taint"])

        self.assertTrue(selector and taint)
        self.assertEqual(selector[0].root_cause, "node_selector_mismatch")
        self.assertEqual(taint[0].root_cause, "taint_toleration_mismatch")


class _StubToolProvider:
    name = "stub"

    def __init__(self, outputs: dict[str, Any]) -> None:
        self._outputs = outputs
        self._calls: list[dict[str, Any]] = []

    def available_tools(self) -> tuple[str, ...]:
        return ("GetResources", "DescribeResource", "GetErrorLogs")

    def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "tool_name": tool_name,
            "args": dict(args or {}),
            "output_summary": self._outputs.get(tool_name, ""),
            "valid": tool_name in self._outputs,
            "status": "completed" if tool_name in self._outputs else "completed",
            "citation_ids": [f"stub:{tool_name}"],
        }
        self._calls.append(record)
        return {
            "tool_name": tool_name,
            "args": record["args"],
            "output": self._outputs.get(tool_name),
            "valid": record["valid"],
            "status": record["status"],
        }

    def call_records(self) -> list[dict[str, Any]]:
        return list(self._calls)


class InvestigationToolLoopTests(unittest.TestCase):
    def test_tool_provider_drives_probe_loop_and_emits_ranked_findings(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        provider = _StubToolProvider({
            "GetResources": "frontend 0/1 ImagePullBackOff",
            "DescribeResource": "Reason: ErrImagePull manifest unknown",
        })

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
            tool_provider=provider,
        )

        names = [probe["name"] for probe in report.probe_results]
        self.assertIn("GetResources", names)
        self.assertIn("DescribeResource", names)
        self.assertEqual(report.stop_reason, "root_cause_candidate_found")
        ranked = [finding for finding in report.findings if finding.get("kind") == "ranked_root_causes"]
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["summary"], "incorrect_image_reference")
        self.assertEqual(report.root_cause_candidates[0]["root_cause"], "incorrect_image_reference")
        self.assertIn("DescribeResource", report.root_cause_candidates[0]["supporting_tools"])
        # Calls were recorded on the provider so the runner can surface
        # them as tool_trajectory.
        self.assertGreaterEqual(len(provider.call_records()), 2)

    def test_tool_provider_absent_keeps_deterministic_path(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
        )

        self.assertEqual(report.stop_reason, "deterministic_probe_budget_exhausted")
        self.assertEqual(report.root_cause_candidates, [])
        self.assertFalse(any(finding.get("kind") == "ranked_root_causes" for finding in report.findings))


if __name__ == "__main__":
    unittest.main()
