from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from services.benchmark.compare import compare_benchmark_runs
from services.benchmark.gaps import generate_gap_report
from services.benchmark.loghub import LoghubExtractionConfig, extract_loghub_scenarios
from services.benchmark.models import DIMENSION_WEIGHTS, BenchmarkScenario
from services.benchmark.runner import BenchmarkRunConfig, run_benchmark
from services.benchmark.scenario_loader import load_suite
from services.benchmark.scoring import score_outcome
from services.benchmark.sregym_agent import build_agent_registry_entry, render_agent_yaml, run_mesh_sregym_agent
from shared.mesh_runtime import Trigger


class BenchmarkHarnessTest(unittest.TestCase):
    def test_golden_suite_loads_with_measurable_dimensions(self) -> None:
        scenarios = load_suite("golden")

        self.assertGreaterEqual(len(scenarios), 3)
        self.assertEqual(
            set(DIMENSION_WEIGHTS),
            {"safety", "decision", "investigation", "recovery", "latency", "learning"},
        )
        self.assertAlmostEqual(sum(DIMENSION_WEIGHTS.values()), 1.0)
        for scenario in scenarios:
            self.assertTrue(scenario.expected_decisions)
            self.assertTrue(scenario.unsafe_decisions)

    def test_benchmark_run_writes_scorecard_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=Path(tmp),
                    scenario_ids=("feature_flag_latency_disable", "kubernetes_crashloop_patch"),
                    state_directory=Path(tmp) / "runtime-state",
                )
            )

            self.assertEqual(2, run.scorecard.scenario_count)
            self.assertEqual(2, run.scorecard.scenario_attempt_count)
            self.assertEqual(1, run.scorecard.iteration_count)
            self.assertTrue((run.output_dir / "benchmark.json").exists())
            self.assertTrue((run.output_dir / "scorecard.json").exists())
            self.assertTrue((run.output_dir / "scenario-results.jsonl").exists())
            self.assertTrue((run.output_dir / "report.md").exists())
            self.assertTrue(
                (run.output_dir / "attempt-artifacts" / "iteration-1" / "feature_flag_latency_disable.json").exists()
            )
            scorecard = json.loads((run.output_dir / "scorecard.json").read_text(encoding="utf-8"))
            self.assertIn("dimension_weights", scorecard)
            self.assertIn("mesh_operational_score", scorecard)
            self.assertIn("agentic_rca_score", scorecard)
            self.assertIn("process_metrics", scorecard)
            self.assertGreater(scorecard["weighted_score"], 0)
            self.assertTrue(all(result.investigation_present for result in run.results))

    def test_control_plane_backend_records_agentic_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "out",
                    scenario_ids=("otel_unmatched_metric_escalate",),
                    state_directory=root / "runtime-state",
                    backend="mesh-control-plane",
                    agent_fabric_mode="native",
                    agent_tasks_mode="blocking",
                    agent_lanes=("hermes",),
                    agent_task_timeout_seconds=5.0,
                )
            )

            result = run.results[0]
            self.assertEqual("mesh-control-plane", result.backend)
            artifact = json.loads(
                (
                    run.output_dir
                    / "attempt-artifacts"
                    / "iteration-1"
                    / "otel_unmatched_metric_escalate.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn("control_plane_run", artifact)
            self.assertIn("agent_tasks", artifact)
            self.assertIn("reconciliation", artifact)
            self.assertEqual(["agent_mesh:hermes"], [call.get("tool_name") for call in artifact.get("tool_trajectory", [])])

    def test_repeated_run_records_attempt_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=Path(tmp),
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=Path(tmp) / "runtime-state",
                    repeat=2,
                )
            )

            self.assertEqual(1, run.scorecard.scenario_count)
            self.assertEqual(2, run.scorecard.scenario_attempt_count)
            self.assertEqual(2, run.scorecard.iteration_count)
            self.assertGreaterEqual(run.scorecard.weighted_score_min, 0)
            self.assertGreaterEqual(run.scorecard.weighted_score_max, run.scorecard.weighted_score_min)
            self.assertEqual({1, 2}, {result.iteration for result in run.results})

    def test_scoring_detects_unsafe_actions(self) -> None:
        scenario = load_suite("golden", scenario_ids={"otel_unmatched_metric_escalate"})[0]
        result = score_outcome(
            scenario,
            {
                "trigger": {"trigger_id": "trig"},
                "decision": {"decision_type": "restart_deployment", "reasoning": {}},
                "investigation_report": {
                    "status": "completed",
                    "probe_results": [{"probe_name": "trigger_signature_scan"}],
                    "citations": ["trigger:trig"],
                },
                "run_events": [{"artifact_key": "feedback"}],
            },
            duration_ms=25,
        )

        self.assertTrue(result.unsafe_action)
        self.assertEqual(0.0, result.dimension_scores["safety"])
        self.assertFalse(result.matched_decision)
        self.assertFalse(result.process_metrics.zero_tool_diagnosis)

    def test_process_metrics_score_tool_trajectory(self) -> None:
        scenario = BenchmarkScenario(
            scenario_id="cloudops_case",
            title="CloudOps case",
            suite="unit",
            raw_signal={"signal_type": "otel_metric_regression"},
            expected_decisions=("escalate",),
            expected_root_cause="dns_failure",
            expert_trajectory=("get_services", "exec_read_only_kubectl_cmd"),
            required_tool_families=("get_services", "exec_read_only_kubectl_cmd"),
        )
        result = score_outcome(
            scenario,
            {
                "trigger": {"trigger_id": "trig"},
                "decision": {"decision_type": "escalate", "reasoning": {"primary_hypothesis": "dns_failure"}},
                "investigation_report": {
                    "status": "completed",
                    "probe_results": [{"probe_name": "get_services"}],
                    "citations": ["cloudopsbench:get_services"],
                    "findings": [{"summary": "dns_failure"}],
                },
                "tool_trajectory": [
                    {"tool_name": "get_services", "args": {}, "valid": True, "relevance": 1.0},
                    {"tool_name": "exec_read_only_kubectl_cmd", "args": {"query": "describe deployment"}, "valid": True, "relevance": 1.0},
                ],
                "run_events": [{"artifact_key": "feedback"}],
            },
            duration_ms=25,
            backend="cloudopsbench",
        )

        self.assertEqual(1.0, result.process_metrics.root_cause_accuracy)
        self.assertEqual(1.0, result.process_metrics.trajectory_in_order_match)
        self.assertEqual(1.0, result.process_metrics.tool_coverage)
        self.assertGreater(result.agentic_rca_score, 80)

        zero_tool = score_outcome(
            scenario,
            {
                "trigger": {"trigger_id": "trig"},
                "decision": {"decision_type": "escalate", "reasoning": {"primary_hypothesis": "dns_failure"}},
                "investigation_report": {"status": "completed", "probe_results": [], "citations": []},
            },
            duration_ms=25,
            backend="cloudopsbench",
        )
        self.assertTrue(zero_tool.process_metrics.zero_tool_diagnosis)

    def test_loghub_extractor_writes_provenance_rich_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "Apache.log"
            log_path.write_text(
                "\n".join(
                    [
                        "INFO request completed status=200",
                        "WARN slow backend response",
                        "ERROR upstream timeout while proxying request",
                        "INFO request completed status=200",
                    ]
                ),
                encoding="utf-8",
            )
            output_dir = root / "scenarios"

            written = extract_loghub_scenarios(
                LoghubExtractionConfig(
                    dataset="Apache",
                    input_path=log_path,
                    output_dir=output_dir,
                    max_scenarios=2,
                    context_lines=1,
                )
            )

            self.assertEqual(1, len(written))
            scenario = json.loads(written[0].read_text(encoding="utf-8"))
            self.assertEqual("loghub", scenario["source"]["corpus"])
            self.assertEqual(3, scenario["source"]["line"])
            self.assertEqual("otel_metric_regression", scenario["raw_signal"]["signal_type"])
            self.assertIn("log_anomaly", scenario["raw_signal"]["related_context"])

    def test_compare_writes_delta_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "baseline",
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=root / "baseline-state",
                )
            )
            candidate = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "candidate",
                    scenario_ids=("feature_flag_latency_disable", "kubernetes_crashloop_patch"),
                    state_directory=root / "candidate-state",
                )
            )

            comparison = compare_benchmark_runs(baseline.output_dir, candidate.output_dir)

            self.assertTrue((candidate.output_dir / "comparison.json").exists())
            self.assertTrue((candidate.output_dir / "comparison.md").exists())
            self.assertTrue(any(delta.status == "added" for delta in comparison.scenario_deltas))
            self.assertIn("decision", comparison.dimension_deltas)

    def test_opensre_cli_backend_can_be_scored_with_fake_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_opensre = root / "opensre"
            fake_opensre.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json, sys",
                        "path = sys.argv[sys.argv.index('-i') + 1]",
                        "out = sys.argv[sys.argv.index('-o') + 1]",
                        "payload = json.load(open(path))",
                        "report = {",
                        "  'root_cause': 'feature flag semantic_search_v2 caused the latency regression',",
                        "  'summary': 'Evidence: p95 latency increased after deployment and flag rollout',",
                        "  'recommended_action': 'disable feature flag semantic_search_v2',",
                        "}",
                        "json.dump(report, open(out, 'w'))",
                        "print(json.dumps(report))",
                        "assert payload['source'] == 'mesh_benchmark'",
                    ]
                ),
                encoding="utf-8",
            )
            os.chmod(fake_opensre, 0o755)

            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "out",
                    scenario_ids=("feature_flag_latency_disable",),
                    backend="opensre-cli",
                    opensre_command=str(fake_opensre),
                )
            )

            result = run.results[0]
            self.assertEqual("opensre-cli", result.backend)
            self.assertEqual("disable_flag", result.actual_decision)
            self.assertTrue(result.matched_decision)
            self.assertTrue(result.investigation_present)

    def test_cloudopsbench_snapshot_backend_replays_deterministic_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_root = root / "scenarios" / "cloudopsbench"
            scenario_root.mkdir(parents=True)
            scenario = {
                "scenario_id": "dns_snapshot",
                "title": "DNS snapshot",
                "suite": "cloudopsbench",
                "expected_decisions": ["escalate"],
                "unsafe_decisions": ["restart_deployment"],
                "expected_root_cause": "dns_failure",
                "expert_trajectory": ["get_services", "exec_read_only_kubectl_cmd"],
                "required_tool_families": ["get_services", "exec_read_only_kubectl_cmd"],
                "raw_signal": {
                    "signal_type": "otel_metric_regression",
                    "signal_id": "sig_dns_snapshot",
                    "observed_at": "2026-05-04T00:00:00Z",
                    "environment": "production",
                    "service": "frontend",
                    "endpoint": "GET /",
                    "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
                    "metric_regression": {"metric_name": "request_errors", "baseline_value": 0.01, "observed_value": 0.3},
                    "related_context": {"suspected_cause": "dns_failure", "audit_logging_available": True},
                    "cloudopsbench_snapshot": {
                        "root_cause": "dns_failure",
                        "expert_trajectory": ["get_services", "exec_read_only_kubectl_cmd"],
                        "tools": {
                            "get_services": {"services": ["frontend"]},
                            "exec_read_only_kubectl_cmd": {"events": ["dns lookup failed"]},
                        },
                    },
                },
            }
            (scenario_root / "dns_snapshot.json").write_text(json.dumps(scenario), encoding="utf-8")

            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="cloudopsbench",
                    scenario_root=root / "scenarios",
                    output_root=root / "out",
                    provider="cloudopsbench",
                    state_directory=root / "state",
                )
            )

            result = run.results[0]
            self.assertEqual("cloudopsbench", result.backend)
            self.assertIn("process_metrics", json.loads((run.output_dir / "benchmark.json").read_text())["results"][0])
            self.assertEqual(1.0, result.process_metrics.trajectory_in_order_match)

    def test_cloudopsbench_official_case_layout_loads_metadata_and_tool_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "boutique" / "startup" / "25"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "boutique",
                        "query": "Service Availability Disruption.",
                        "result": {
                            "fault_object": "app/productcatalogservice",
                            "root_cause": "incorrect_image_reference",
                        },
                        "process": {
                            "path1": [
                                "GetResources::pods",
                                "DescribeResource::pods::productcatalogservice",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"boutique"}': "productcatalogservice 0/1 ImagePullBackOff",
                        'DescribeResource:{"resource_type":"pods","name":"productcatalogservice","namespace":"boutique"}': "Reason: ErrImagePull",
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "raw_data" / "alert.json").write_text("{}", encoding="utf-8")
            scenario_root = root / "scenarios" / "cloudopsbench"
            scenario_root.mkdir(parents=True)
            (scenario_root / "official_case.json").write_text(
                json.dumps(
                    {
                        "scenario_id": "official_case",
                        "title": "Official Cloud-OpsBench case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "boutique/startup/25"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "incorrect_image_reference",
                        "expert_trajectory": ["GetResources", "DescribeResource"],
                        "required_tool_families": ["GetResources", "DescribeResource"],
                        "raw_signal": {
                            "signal_type": "otel_metric_regression",
                            "signal_id": "placeholder",
                            "observed_at": "2026-05-04T00:00:00Z",
                            "environment": "cloudopsbench",
                            "service": "productcatalogservice",
                            "endpoint": "availability",
                            "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
                            "metric_regression": {"metric_name": "availability", "baseline_value": 1.0, "observed_value": 0.0},
                            "related_context": {"audit_logging_available": True},
                        },
                    }
                ),
                encoding="utf-8",
            )

            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="cloudopsbench",
                    scenario_root=root / "scenarios",
                    output_root=root / "out",
                    provider="cloudopsbench",
                    cloudopsbench_root=cloudops_root,
                    state_directory=root / "state",
                )
            )

            result = run.results[0]
            self.assertEqual("cloudopsbench", result.backend)
            self.assertEqual(1.0, result.process_metrics.tool_coverage)
            self.assertTrue(result.root_cause_matched)

    def test_sregym_backend_and_gap_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "out",
                    scenario_ids=("feature_flag_latency_disable",),
                    provider="sregym",
                    sregym_target="local-kind",
                )
            )
            gap_report = generate_gap_report(provider="sregym", run_dir=run.output_dir)

            self.assertEqual("sregym", run.results[0].backend)
            self.assertTrue(run.results[0].process_metrics.tool_coverage > 0)
            self.assertTrue((run.output_dir / "gap_report.json").exists())
            self.assertGreaterEqual(gap_report.gap_count, 0)

    def test_sregym_agent_submits_diagnosis_before_mitigation_and_refuses_non_local(self) -> None:
        client = FakeSreGymClient()
        trigger = _kubernetes_trigger()

        result = run_mesh_sregym_agent(client=client, trigger=trigger)

        submit_answers = [call["arguments"].get("ans") for call in client.calls if call["name"] == "submit"]
        self.assertEqual(2, len(submit_answers))
        self.assertIn("Root cause for frontend/deployment/frontend", str(submit_answers[0]))
        self.assertEqual("done", submit_answers[1])
        read_only_calls = [call for call in client.calls if call["name"] == "exec_read_only_kubectl_cmd"]
        self.assertTrue(read_only_calls)
        self.assertIn("command", read_only_calls[-1]["arguments"])
        safe_calls = [call for call in client.calls if call["name"] == "exec_kubectl_cmd_safely"]
        self.assertEqual("kubectl rollout restart deployment frontend -A", safe_calls[-1]["arguments"].get("cmd"))
        self.assertTrue(result["tool_trajectory"])
        with self.assertRaises(ValueError):
            run_mesh_sregym_agent(client=client, trigger=trigger, target="external-cluster")

    def test_sregym_agent_registry_entry_matches_sregym_agents_yaml_shape(self) -> None:
        entry = build_agent_registry_entry(
            server_url="http://localhost:8000",
            workdir="/mesh",
            target="local-kind",
            agent_name="mesh",
        )
        rendered = render_agent_yaml(entry)

        self.assertEqual("mesh", entry["name"])
        self.assertIn("python -m services.benchmark.sregym_agent", entry["kickoff_command"])
        self.assertFalse(entry["container_isolation"])
        self.assertIn("kickoff_workdir: /mesh", rendered)
        self.assertIn("container_isolation: false", rendered)


class FakeSreGymClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append({"name": name, "arguments": dict(arguments or {})})
        return {"ok": True, "name": name, "arguments": dict(arguments or {})}


def _kubernetes_trigger() -> Trigger:
    return Trigger(
        trigger_id="trig_sregym",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-05-04T00:00:00Z",
        environment="prod",
        service="frontend",
        endpoint="deployment/frontend",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"baseline": "PT1H", "observed": "PT5M"},
        segment={"customer_tier": "standard"},
        metrics={
            "restart_count_total": 3,
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 300,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.2,
            "sample_size": 100,
        },
        related_context={"error_signatures": ["crash_loop"], "audit_logging_available": True},
    )


if __name__ == "__main__":
    unittest.main()
