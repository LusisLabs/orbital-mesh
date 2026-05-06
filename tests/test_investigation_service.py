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
        registry: Any = None,
        planner: Any = None,
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

    def test_ontology_distinguishes_readiness_from_liveness_probe_failures(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        readiness = rank_root_causes(["Readiness probe failed: HTTP probe failed with statuscode: 503"])
        liveness = rank_root_causes(["Liveness probe failed: dial tcp 10.1.1.4:8080: connect: connection refused"])

        self.assertTrue(readiness and liveness)
        self.assertEqual(readiness[0].root_cause, "readiness_probe_incorrect_protocol")
        self.assertEqual(liveness[0].root_cause, "liveness_probe_incorrect_port")

    def test_ontology_covers_service_port_and_pvc_binding_families(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        port = rank_root_causes(["Service target port web does not have a port named web on selected pods"])
        pvc = rank_root_causes(["pod has unbound immediate PersistentVolumeClaims"])

        self.assertTrue(port and pvc)
        self.assertEqual(port[0].root_cause, "service_port_mismatch")
        self.assertEqual(pvc[0].root_cause, "persistent_volume_claim_pending")

    def test_ontology_covers_dev_split_capacity_and_affinity_families(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        cpu = rank_root_causes(["0/4 nodes are available: 3 Insufficient cpu."])
        memory = rank_root_causes(["0/4 nodes are available: 3 Insufficient memory."])
        anti_affinity = rank_root_causes(["3 node(s) didn't match pod anti-affinity rules."])

        self.assertTrue(cpu and memory and anti_affinity)
        self.assertEqual(cpu[0].root_cause, "cpu_capacity_mismatch")
        self.assertEqual(memory[0].root_cause, "memory_capacity_mismatch")
        self.assertEqual(anti_affinity[0].root_cause, "pod_anti_affinity_conflict")

    def test_ontology_covers_dev_split_image_pull_secret_family(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        ranked = rank_root_causes([
            "Warning FailedToRetrieveImagePullSecret kubelet Unable to retrieve some image pull secrets"
        ])

        self.assertTrue(ranked)
        self.assertEqual(ranked[0].root_cause, "missing_image_pull_secret")

    def test_ontology_ignores_normal_service_account_and_ready_counts(self) -> None:
        from services.investigation.cloudops_ontology import rank_root_causes

        ranked = rank_root_causes([
            "Service Account: default",
            "NAME cartservice READY 0/1 STATUS Pending",
        ])

        self.assertEqual(ranked, [])


class _StubToolProvider:
    """Test-only stub used to record per-tool invocations.

    Holds canned text per tool name and exposes ``call_records`` so
    tests can assert what the harness actually called. We keep the
    legacy ``invoke`` shape (``{output, valid, status}``) so the same
    fixtures work; ``_harness_from_stub`` adapts that shape to the
    ``RawToolOutput`` the harness registry expects.
    """

    name = "stub"

    def __init__(self, outputs: dict[str, Any], available_tools: tuple[str, ...] | None = None) -> None:
        self._outputs = outputs
        self._calls: list[dict[str, Any]] = []
        self._available_tools = available_tools or ("GetResources", "DescribeResource", "GetErrorLogs")

    def available_tools(self) -> tuple[str, ...]:
        return self._available_tools

    def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "tool_name": tool_name,
            "args": dict(args or {}),
            "output_summary": self._outputs.get(tool_name, ""),
            "valid": tool_name in self._outputs,
            "status": "completed",
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


def _harness_from_stub(stub: _StubToolProvider, trigger: Trigger):
    """Adapt a ``_StubToolProvider`` into a ``(registry, planner)`` pair.

    Replaces the deleted ``_registry_for_tool_provider`` /
    ``_make_provider_invoker`` helpers from ``service.py``. Tests that
    used the legacy ``tool_provider=`` parameter now build the same
    registry+planner shape the production harness uses (CloudOps rule
    pack + native probe selector), so behavior under test matches the
    real path that runs under ``run_sync``.
    """
    from services.investigation.cloudops_tools import (
        CLOUDOPS_DOMAIN,
        CLOUDOPS_TOOL_DEFINITIONS,
        CloudOpsRulePack,
    )
    from services.investigation.harness import (
        NativeProbeSelector,
        RawToolOutput,
        ToolRegistry,
    )

    registry = ToolRegistry()
    definitions = {definition.name: definition for definition in CLOUDOPS_TOOL_DEFINITIONS}

    def _stub_invoker(tool_name: str):
        # Closure binds tool_name; shapes the stub's dict response into
        # the RawToolOutput the harness registry expects. The stub's
        # text output goes verbatim into output_summary so the cloudops
        # ontology can match against it.
        def invoke(args: dict[str, Any]) -> "RawToolOutput":
            response = stub.invoke(tool_name, args)
            output = response.get("output")
            valid = bool(response.get("valid", True))
            arg_summary = ",".join(f"{k}={v}" for k, v in (args or {}).items() if v) or tool_name
            return RawToolOutput(
                output=output,
                output_summary=str(output) if output is not None else "",
                citations=[{"source_type": f"stub:{tool_name}", "source_ref": arg_summary}],
                valid=valid,
                redaction_status="clean",
                status="completed",
            )

        return invoke

    for tool_name in stub.available_tools():
        definition = definitions.get(tool_name)
        if definition is None:
            continue
        registry.register(definition, _stub_invoker(tool_name))

    planner = NativeProbeSelector(
        CloudOpsRulePack(trigger),
        tool_definitions=registry.list_definitions(domain=CLOUDOPS_DOMAIN, mutation_class="read_only"),
    )
    return registry, planner


class InvestigationHarnessLoopTests(unittest.TestCase):
    """Harness-driven loop behavior, exercised through the canonical
    ``registry + planner`` interface that ``run_sync`` uses in
    production. Pre-refactor these tests went through the legacy
    ``tool_provider`` parameter; the migration to ``registry + planner``
    keeps the same fixtures and assertions. Stop reasons gain a
    ``harness_`` prefix because the harness path produces them
    (previously the legacy bridge translated them away)."""

    def test_harness_drives_probe_loop_and_emits_ranked_findings(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        provider = _StubToolProvider({
            "GetResources": "frontend 0/1 ImagePullBackOff",
            "DescribeResource": "Reason: ErrImagePull manifest unknown",
        })
        registry, planner = _harness_from_stub(provider, trigger)

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
            registry=registry,
            planner=planner,
        )

        names = [probe["name"] for probe in report.probe_results]
        self.assertIn("GetResources", names)
        self.assertIn("DescribeResource", names)
        self.assertEqual(report.stop_reason, "harness_root_cause_candidate_found")
        ranked = [finding for finding in report.findings if finding.get("kind") == "ranked_root_causes"]
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["summary"], "incorrect_image_reference")
        self.assertEqual(report.root_cause_candidates[0]["root_cause"], "incorrect_image_reference")
        self.assertIn("DescribeResource", report.root_cause_candidates[0]["supporting_tools"])
        telemetry = [finding for finding in report.findings if finding.get("kind") == "planner_telemetry"]
        self.assertEqual(len(telemetry), 1)
        telemetry_details = telemetry[0]["details"]
        self.assertEqual(telemetry_details["critic_rejections_by_reason"], {})
        self.assertEqual(telemetry_details["valid_result_rate"], 1.0)
        self.assertIn("GetResources", telemetry_details["tool_latency_ms_by_family"])
        self.assertTrue(telemetry_details["rca_confidence_trace"])
        self.assertTrue(telemetry_details["planner_decisions"])
        # Calls were recorded on the stub so the runner can surface
        # them as tool_trajectory.
        self.assertGreaterEqual(len(provider.call_records()), 2)

    def test_harness_uses_get_resources_output_to_pick_describe_target(self) -> None:
        # Simulates a hidden-mode CloudOps run: the trigger redacts the
        # service name to "unknown-service", but GetResources output
        # reveals the unhealthy pod. The loop should describe that pod
        # rather than blindly using the trigger hint.
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        seen_describe_args: list[dict[str, Any]] = []

        class CapturingProvider(_StubToolProvider):
            def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
                if tool_name == "DescribeResource":
                    seen_describe_args.append(dict(args or {}))
                return super().invoke(tool_name, args)

        provider = CapturingProvider({
            "GetResources": "productcatalogservice-7c9f-abc12 0/1 ImagePullBackOff",
            "DescribeResource": "Reason: ErrImagePull",
            "GetErrorLogs": "manifest unknown",
        })
        registry, planner = _harness_from_stub(provider, trigger)

        InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
            registry=registry,
            planner=planner,
        )

        self.assertTrue(seen_describe_args)
        self.assertEqual(seen_describe_args[0]["name"], "productcatalogservice")

    def test_harness_selects_follow_up_from_observed_signal_and_records_reason(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        provider = _StubToolProvider(
            {
                "GetResources": "checkoutservice-7c9f-abc12 0/1 CrashLoopBackOff",
                "DescribeResource": "Warning BackOff back-off restarting failed container",
                "GetErrorLogs": "Traceback RuntimeError: checkout exception",
                "GetAppYAML": "image: checkout:v1",
            },
            available_tools=("GetResources", "DescribeResource", "GetAppYAML", "GetErrorLogs"),
        )
        registry, planner = _harness_from_stub(provider, trigger)

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
            registry=registry,
            planner=planner,
        )

        tool_names = [record["tool_name"] for record in provider.call_records()]
        self.assertEqual(tool_names, ["GetResources", "DescribeResource", "GetErrorLogs"])
        self.assertNotIn("GetAppYAML", tool_names)
        reasons = {
            probe["name"]: probe["findings"][0]["details"]["selection_reason"]
            for probe in report.probe_results
            if probe["name"] in {"GetResources", "DescribeResource", "GetErrorLogs"}
        }
        self.assertIn("inventory_discovery", reasons["GetResources"])
        self.assertIn("resource_status_signal", reasons["DescribeResource"])
        self.assertIn("runtime_failure_signal", reasons["GetErrorLogs"])

    def test_harness_stops_when_evidence_value_is_exhausted(self) -> None:
        trigger, signal = _trigger_and_signal()
        evidence_pack = EvidenceService().assemble(trigger=trigger, signal_payload=signal)
        provider = _StubToolProvider(
            {
                "GetResources": "frontend 1/1 Running",
                "DescribeResource": "no warning events",
                "GetErrorLogs": "no errors",
            },
            available_tools=("GetResources", "DescribeResource", "GetAppYAML", "GetErrorLogs"),
        )
        registry, planner = _harness_from_stub(provider, trigger)

        report = InvestigationService().investigate(
            trigger=trigger,
            evidence_pack=evidence_pack.to_dict(),
            registry=registry,
            planner=planner,
        )

        self.assertEqual([record["tool_name"] for record in provider.call_records()], ["GetResources"])
        self.assertEqual(report.stop_reason, "harness_evidence_value_exhausted")
        self.assertEqual(report.root_cause_candidates, [])
        telemetry = [finding for finding in report.findings if finding.get("kind") == "planner_telemetry"]
        self.assertEqual(telemetry[0]["details"]["evidence_value_exhaustion_rate"], 1.0)

    def test_harness_absent_keeps_deterministic_path(self) -> None:
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
