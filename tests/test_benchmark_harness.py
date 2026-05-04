from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from services.benchmark.compare import compare_benchmark_runs
from services.benchmark.cloudopsbench_import import import_cloudopsbench_scenarios
from services.benchmark.gaps import generate_gap_report
from services.benchmark.gates import load_gate_profiles, resolve_gate_suite, run_benchmark_gate
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

    def test_compact_run_artifacts_record_scorecard_and_small_result_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=Path(tmp),
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=Path(tmp) / "runtime-state",
                    compact_artifacts=True,
                )
            )

            compact = json.loads((run.output_dir / "benchmark-compact.json").read_text(encoding="utf-8"))
            rows = (run.output_dir / "scenario-results-compact.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual("mesh.benchmark.compact.v1", compact["schema"])
            self.assertEqual(run.run_id, compact["run_id"])
            self.assertEqual(1, compact["result_count"])
            self.assertEqual(1, len(rows))
            self.assertIn("agentic_rca_score", json.loads(rows[0]))

    def test_attempt_artifact_mode_can_skip_successful_attempt_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=Path(tmp),
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=Path(tmp) / "runtime-state",
                    attempt_artifact_mode="errors",
                )
            )

            self.assertTrue((run.output_dir / "benchmark.json").exists())
            self.assertFalse((run.output_dir / "attempt-artifacts").exists())

    def test_runtime_state_mode_can_skip_persisted_state_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "out",
                    scenario_ids=("feature_flag_latency_disable",),
                    runtime_state_mode="none",
                )
            )

            self.assertTrue((run.output_dir / "benchmark.json").exists())
            self.assertFalse((run.output_dir / "runtime-state-1").exists())

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
        self.assertEqual(1.0, result.process_metrics.root_cause_at_1)
        self.assertEqual(1.0, result.process_metrics.root_cause_at_3)
        self.assertEqual(1.0, result.process_metrics.trajectory_in_order_match)
        self.assertEqual(1.0, result.process_metrics.tool_coverage)
        self.assertGreater(result.agentic_rca_score, 80)

        ranked_third = score_outcome(
            scenario,
            {
                "trigger": {"trigger_id": "trig"},
                "decision": {"decision_type": "escalate", "reasoning": {}},
                "investigation_report": {
                    "status": "completed",
                    "probe_results": [{"name": "get_services"}],
                    "citations": ["cloudopsbench:get_services"],
                    "root_cause_candidates": [
                        {"rank": 1, "root_cause": "service_selector_mismatch", "confidence": 0.5},
                        {"rank": 2, "root_cause": "connection_refused", "confidence": 0.3},
                        {"rank": 3, "root_cause": "dns_failure", "confidence": 0.2},
                    ],
                },
                "tool_trajectory": [{"tool_name": "get_services", "args": {}, "valid": True}],
                "run_events": [{"artifact_key": "feedback"}],
            },
            duration_ms=25,
            backend="cloudopsbench",
        )
        self.assertFalse(ranked_third.root_cause_matched)
        self.assertEqual(0.0, ranked_third.process_metrics.root_cause_at_1)
        self.assertEqual(1.0, ranked_third.process_metrics.root_cause_at_3)

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
            self.assertIn("root_cause_accuracy", comparison.process_metric_deltas)
            self.assertGreaterEqual(comparison.mesh_operational_score_delta, -100.0)

    def test_gate_profiles_resolve_dev_and_eval_suites(self) -> None:
        profiles = load_gate_profiles()

        self.assertEqual(
            "cloudopsbench_official_dev_full",
            resolve_gate_suite("cloudopsbench_official_full", profiles["dev"]),
        )
        self.assertEqual(
            "cloudopsbench_official_eval_full",
            resolve_gate_suite("cloudopsbench_official_dev_full", profiles["eval"]),
        )
        self.assertEqual("golden", resolve_gate_suite("golden", profiles["ci"]))

    def test_benchmark_gate_writes_threshold_and_compact_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = run_benchmark_gate(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "out",
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=root / "state",
                ),
                profile_name="ci",
                threshold_overrides={"weighted_score_min": 1.0, "pass_rate_min": 0.5},
                repeat_override=1,
            )

            self.assertTrue(gate.passed)
            self.assertTrue((gate.output_dir / "gate.json").exists())
            self.assertTrue((gate.output_dir / "gate.md").exists())
            self.assertTrue((gate.output_dir / "benchmark-compact.json").exists())
            self.assertFalse((gate.output_dir / "attempt-artifacts").exists())
            payload = json.loads((gate.output_dir / "gate.json").read_text(encoding="utf-8"))
            self.assertEqual("mesh.benchmark.gate.v1", payload["schema"])
            self.assertEqual("ci", payload["profile"])
            self.assertTrue(payload["passed"])

    def test_benchmark_gate_marks_threshold_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = run_benchmark_gate(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=Path(tmp) / "out",
                    scenario_ids=("feature_flag_latency_disable",),
                    state_directory=Path(tmp) / "state",
                ),
                profile_name="ci",
                threshold_overrides={"weighted_score_min": 101.0},
                repeat_override=1,
            )

            self.assertFalse(gate.passed)
            self.assertTrue(any(check.metric == "weighted_score" and not check.passed for check in gate.checks))

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
                    cloudopsbench_ground_truth_mode="oracle",
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
                    cloudopsbench_ground_truth_mode="oracle",
                )
            )

            result = run.results[0]
            self.assertEqual("cloudopsbench", result.backend)
            self.assertEqual(1.0, result.process_metrics.tool_coverage)
            self.assertTrue(result.root_cause_matched)

    def test_cloudopsbench_importer_writes_full_and_split_suites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "boutique" / "startup" / "25"
            case_dir.mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "boutique",
                        "query": "Service Availability Disruption.",
                        "result": {"root_cause": "incorrect_image_reference"},
                        "process": {"path1": ["GetResources::pods", "DescribeResource::pods::frontend"]},
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "tool_cache.json").write_text("{}", encoding="utf-8")

            summary = import_cloudopsbench_scenarios(
                cloudopsbench_root=cloudops_root,
                output_root=root / "scenarios",
            )

            self.assertEqual(1, summary.full_count)
            self.assertTrue((root / "scenarios" / "cloudopsbench_official_full" / "cloudops_boutique_startup_25.json").exists())
            split_files = list((root / "scenarios").glob("cloudopsbench_official_*_full/cloudops_boutique_startup_25.json"))
            self.assertEqual(1, len(split_files))

    def test_cloudopsbench_hidden_mode_does_not_replay_oracle_data(self) -> None:
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
            (case_dir / "tool_cache.json").write_text("{}", encoding="utf-8")
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
                            "service": "unknown-service",
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

            artifact = json.loads(
                (run.output_dir / "attempt-artifacts" / "iteration-1" / "official_case.json").read_text()
            )
            self.assertEqual("hidden", artifact["cloudopsbench_ground_truth_mode"])
            # Hidden mode hands the snapshot tools to the investigator and
            # records the calls it actually makes — it does not replay the
            # expert trajectory. With an empty tool_cache the calls land
            # invalid, but they still must show up so scoring can credit
            # tool coverage and so we can see what the agent attempted.
            tool_calls = artifact["tool_trajectory"]
            self.assertTrue(tool_calls, "hidden mode should still attempt diagnostic tool calls")
            self.assertIn("GetResources", {call.get("tool_name") for call in tool_calls})
            self.assertTrue(all(call.get("valid") is False for call in tool_calls))
            # Without any cached tool output, the agent has no observed
            # text to map onto a canonical root cause — the ground truth
            # must remain hidden.
            self.assertNotIn("incorrect_image_reference", json.dumps(artifact["investigation_report"]))
            self.assertFalse(run.results[0].root_cause_matched)

    def test_cloudopsbench_hidden_mode_drives_tool_loop_and_ranks_root_cause(self) -> None:
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
                        'DescribeResource:{"resource_type":"pods","name":"productcatalogservice","namespace":"boutique"}': "Reason: ErrImagePull manifest unknown",
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
                            "related_context": {"audit_logging_available": True, "cloudopsbench_namespace": "boutique"},
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
            artifact = json.loads(
                (run.output_dir / "attempt-artifacts" / "iteration-1" / "official_case.json").read_text()
            )
            self.assertEqual("hidden", artifact["cloudopsbench_ground_truth_mode"])
            tool_calls = artifact["tool_trajectory"]
            tool_names = {call.get("tool_name") for call in tool_calls}
            self.assertIn("GetResources", tool_names)
            self.assertIn("DescribeResource", tool_names)
            self.assertTrue(any(call.get("valid") for call in tool_calls))
            # Hidden mode should now achieve > 0 tool coverage.
            self.assertGreater(result.process_metrics.tool_coverage, 0.0)
            # The ontology should map ErrImagePull → incorrect_image_reference
            # and surface it through the investigation report so scoring
            # can credit root_cause_accuracy.
            self.assertIn("incorrect_image_reference", json.dumps(artifact["investigation_report"]))
            self.assertEqual(
                artifact["investigation_report"]["root_cause_candidates"][0]["root_cause"],
                "incorrect_image_reference",
            )
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_3)

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
