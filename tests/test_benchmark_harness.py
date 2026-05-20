from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from services.benchmark.compare import compare_benchmark_runs
from services.benchmark.cloudopsbench_import import import_cloudopsbench_scenarios
from services.benchmark.gaps import generate_gap_report
from services.benchmark.harbor_loghub import (
    HarborResultImportConfig,
    LoghubCaseBuildConfig,
    LoghubHarborExportConfig,
    build_loghub_cases,
    export_loghub_harbor_dataset,
    find_oracle_leaks,
    import_harbor_results,
    score_loghub_answer,
)
from services.benchmark.loghub import LoghubExtractionConfig, extract_loghub_scenarios
from services.benchmark.models import DIMENSION_WEIGHTS, BenchmarkScenario
from services.benchmark.runner import BenchmarkRunConfig, run_benchmark
from services.benchmark.scenario_loader import load_suite
from services.benchmark.scoring import _evidence_kind_matches, score_outcome
from services.benchmark.sregym_agent import (
    SreGymEndpointConfig,
    build_agent_registry_entry,
    render_agent_yaml,
    run_mesh_sregym_agent,
)
from services.investigation.cloudops_ontology import rank_root_causes
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

    def test_loghub_harbor_build_creates_deterministic_cases_and_splits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "HDFS.log"
            log_path.write_text(
                "\n".join(
                    [
                        "INFO blk_1 request completed",
                        "worker-a ERROR blk_2 failed to replicate block",
                        "INFO blk_3 request completed",
                    ]
                ),
                encoding="utf-8",
            )
            (root / "anomaly_label.csv").write_text("BlockId,Label\nblk_2,Anomaly\n", encoding="utf-8")

            first = build_loghub_cases(
                LoghubCaseBuildConfig(
                    dataset="HDFS",
                    input_path=root,
                    output_dir=root / "first",
                    max_cases=1,
                    split_salt="unit-salt",
                )
            )
            second = build_loghub_cases(
                LoghubCaseBuildConfig(
                    dataset="HDFS",
                    input_path=root,
                    output_dir=root / "second",
                    max_cases=1,
                    split_salt="unit-salt",
                )
            )

            self.assertEqual(first.cases[0]["case_id"], second.cases[0]["case_id"])
            self.assertEqual("gold", first.cases[0]["track"])
            self.assertIn(first.cases[0]["split"], {"smoke", "dev", "eval"})
            manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["publishable_case_count"])
            self.assertEqual({"gold": 1}, manifest["tracks"])

    def test_loghub_harbor_build_uses_structured_csv_label_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "BGL"
            corpus.mkdir()
            (corpus / "BGL_2k.log").write_text(
                "\n".join(
                    [
                        "INFO instruction cache parity error corrected",
                        "FATAL node card failed with machine check",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (corpus / "BGL_2k.log_structured.csv").write_text(
                "\n".join(
                    [
                        "LineId,Label,Content",
                        "1,-,instruction cache parity error corrected",
                        "2,FATAL,node card failed with machine check",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = build_loghub_cases(
                LoghubCaseBuildConfig(
                    dataset="BGL",
                    input_path=corpus,
                    output_dir=root / "cases",
                    max_cases=5,
                    split_salt="structured-labels",
                )
            )

            self.assertEqual("gold", result.cases[0]["track"])
            self.assertEqual(2, result.cases[0]["source"]["line"])

    def test_loghub_harbor_export_writes_task_without_oracle_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_root = root / "cases"
            (case_root / "cases").mkdir(parents=True)
            case = {
                "case_id": "loghub_unit_secret",
                "title": "Secret leak guard",
                "dataset": "Unit",
                "track": "gold",
                "split": "eval",
                "benchmark": {"publishable": True},
                "visible": {
                    "log_file": "logs/unit.log",
                    "log_window": [
                        {"line_id": "L000001", "line_number": 1, "text": "INFO request completed"},
                        {"line_id": "L000002", "line_number": 2, "text": "ERROR request failed with code 500"},
                    ],
                },
                "oracle": {
                    "is_incident": True,
                    "anomaly_line_ids": ["L000002"],
                    "root_cause_type": "failure",
                    "affected_component": "secret-component-not-in-log",
                    "recommended_action": "escalate",
                    "label_source": "label_file",
                    "leak_guard_tokens": ["secret-oracle-token"],
                },
            }
            (case_root / "cases" / "loghub_unit_secret.json").write_text(json.dumps(case), encoding="utf-8")

            export = export_loghub_harbor_dataset(
                LoghubHarborExportConfig(
                    case_root=case_root,
                    output_dir=root / "harbor",
                    split="full",
                    track="gold",
                )
            )

            task_dir = export.task_dirs[0]
            self.assertTrue((task_dir / "instruction.md").exists())
            self.assertTrue((task_dir / "task.toml").exists())
            self.assertTrue((task_dir / "environment" / "Dockerfile").exists())
            self.assertTrue((task_dir / "tests" / "test.sh").exists())
            self.assertTrue((task_dir / "tests" / "verifier.py").exists())
            oracle_path = export.oracle_dir / "loghub_unit_secret.oracle.json"
            self.assertTrue(oracle_path.exists())
            self.assertEqual([], find_oracle_leaks(task_dir, case["oracle"]))

            answer_path = root / "answer.json"
            verifier_dir = root / "verifier-output"
            answer_path.write_text(
                json.dumps(
                    {
                        "is_incident": True,
                        "anomaly_line_ids": ["L000002"],
                        "root_cause_type": "failure",
                        "evidence": [{"line_id": "L000002", "quote": "ERROR request failed", "reason": "failure signal"}],
                        "recommended_action": "escalate",
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(task_dir / "tests" / "verifier.py")],
                env={
                    **os.environ,
                    "LOGHUB_HARBOR_ORACLE_PATH": str(oracle_path),
                    "LOGHUB_HARBOR_ANSWER_PATH": str(answer_path),
                    "LOGHUB_HARBOR_VERIFIER_DIR": str(verifier_dir),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual("", completed.stderr)
            self.assertEqual(0, completed.returncode)
            reward = json.loads((verifier_dir / "reward.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(reward["reward"], 0.9)

    def test_loghub_harbor_verifier_scores_perfect_and_penalizes_hallucination(self) -> None:
        oracle = {
            "is_incident": True,
            "anomaly_line_ids": ["L000002"],
            "root_cause_type": "failure",
            "recommended_action": "escalate",
        }
        perfect = {
            "is_incident": True,
            "anomaly_line_ids": ["L000002"],
            "root_cause_type": "failure",
            "affected_component": "worker-a",
            "evidence": [{"line_id": "L000002", "quote": "ERROR request failed", "reason": "failure signal"}],
            "recommended_action": "escalate",
            "confidence": 0.9,
        }
        bad = {
            "is_incident": True,
            "anomaly_line_ids": ["L999999"],
            "root_cause_type": "impossible_magic",
            "evidence": [{"line_id": "L999999", "quote": "not present", "reason": "invented"}],
            "recommended_action": "restart the production database",
        }

        perfect_grade = score_loghub_answer(perfect, oracle, visible_line_ids={"L000001", "L000002"})
        bad_grade = score_loghub_answer(bad, oracle, visible_line_ids={"L000001", "L000002"})

        self.assertEqual(1.0, perfect_grade["reward"])
        self.assertLess(bad_grade["reward"], 0.5)
        self.assertIn("hallucinated_line_reference", bad_grade["penalties"])
        self.assertIn("unsafe_remediation_recommendation", bad_grade["penalties"])
        self.assertIn("impossible_root_cause", bad_grade["penalties"])

    def test_harbor_result_importer_computes_pass_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rewards = {
                "task-a": [0.8, 0.9, 0.85],
                "task-b": [0.1, 0.8, 0.2],
            }
            for task_id, values in rewards.items():
                for index, reward in enumerate(values, start=1):
                    trial_dir = root / "job" / task_id / f"trial-{index}"
                    trial_dir.mkdir(parents=True)
                    (trial_dir / "result.json").write_text(
                        json.dumps(
                            {
                                "task_id": task_id,
                                "verifier_result": {
                                    "rewards": {"reward": reward},
                                    "details": {
                                        "valid": True,
                                        "malformed": False,
                                        "zero_evidence": False,
                                        "citation_precision": 1.0,
                                        "citation_recall": 1.0,
                                    },
                                },
                                "cost_usd": 0.01,
                                "latency_ms": 1000,
                            }
                        ),
                        encoding="utf-8",
                    )

            imported = import_harbor_results(
                HarborResultImportConfig(
                    job_dir=root / "job",
                    output_dir=root / "imported",
                    pass_threshold=0.75,
                )
            )

            self.assertEqual(6, imported.summary["attempt_count"])
            self.assertEqual(2, imported.summary["task_count"])
            self.assertEqual(1.0, imported.summary["pass_at_3"])
            self.assertEqual(0.5, imported.summary["pass_3"])
            self.assertTrue((imported.output_dir / "report.md").exists())
            self.assertTrue((imported.output_dir / "metadata.yaml").exists())

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

    def test_cloudopsbench_hidden_mode_normalizes_workload_name_for_probe_port_rca(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "boutique" / "runtime" / "41"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "boutique",
                        "query": "Service abnormal restart.",
                        "result": {
                            "fault_object": "app/currencyservice",
                            "root_cause": "readiness_probe_incorrect_port",
                        },
                        "process": {
                            "path1": [
                                "GetResources::pods",
                                "DescribeResource::pods::currencyservice",
                                "GetAppYAML::currencyservice",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"boutique"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            "currencyservice-7cc975cfff-nk87k 0/1 Running 0 91s\n"
                        ),
                        'DescribeResource:{"resource_type":"pods","name":"currencyservice-7cc975cfff-nk87k","namespace":"boutique"}': (
                            "Name: currencyservice-7cc975cfff-nk87k\n"
                            "Labels: app=currencyservice\n"
                            "Port: 7000/TCP\n"
                            "Readiness: grpc <pod>:7001 delay=5s timeout=1s period=10s\n"
                            "Warning Unhealthy Readiness probe failed: timeout connecting to 172.20.2.130:7001\n"
                        ),
                        'GetAppYAML:{"app_name":"currencyservice"}': (
                            "apiVersion: apps/v1\n"
                            "kind: Deployment\n"
                            "metadata:\n"
                            "  name: currencyservice\n"
                            "spec:\n"
                            "  template:\n"
                            "    spec:\n"
                            "      containers:\n"
                            "      - name: server\n"
                            "        ports:\n"
                            "        - containerPort: 7000\n"
                            "        readinessProbe:\n"
                            "          grpc:\n"
                            "            port: 7001\n"
                            "---\n"
                            "kind: Service\n"
                            "metadata:\n"
                            "  name: currencyservice\n"
                            "spec:\n"
                            "  ports:\n"
                            "  - targetPort: 7000\n"
                        ),
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
                        "title": "Official Cloud-OpsBench readiness port case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "boutique/runtime/41"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "readiness_probe_incorrect_port",
                        "expert_trajectory": ["GetResources::pods", "DescribeResource::pods::currencyservice", "GetAppYAML::currencyservice"],
                        "required_tool_families": ["GetResources", "DescribeResource", "GetAppYAML"],
                        "raw_signal": {
                            "signal_type": "otel_metric_regression",
                            "signal_id": "placeholder",
                            "observed_at": "2026-05-04T00:00:00Z",
                            "environment": "cloudopsbench",
                            "service": "unknown-service",
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
            app_yaml_calls = [call for call in artifact["tool_trajectory"] if call.get("tool_name") == "GetAppYAML"]
            self.assertEqual("currencyservice", app_yaml_calls[0]["args"].get("app_name"))
            self.assertIn("currencyservice", app_yaml_calls[0].get("output_summary", ""))
            self.assertEqual(
                "readiness_probe_incorrect_port",
                artifact["investigation_report"]["root_cause_candidates"][0]["root_cause"],
            )
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)

    def test_cloudops_ontology_maps_malformed_http_probe_response_to_protocol_rca(self) -> None:
        readiness = rank_root_causes(
            [
                "Readiness: http-get http://:5050/health delay=5s timeout=1s period=10s",
                'Warning Unhealthy Readiness probe failed: Get "http://172.20.2.80:5050/health": '
                'net/http: HTTP/1.x transport connection broken: malformed HTTP response "\\x00\\x00"',
            ]
        )
        liveness = rank_root_causes(
            [
                "Liveness: http-get http://:8080/ delay=5s timeout=1s period=10s",
                'Warning Unhealthy Liveness probe failed: Get "http://172.20.1.99:8080/": '
                'net/http: HTTP/1.x transport connection broken: malformed HTTP response "\\x00\\x00"',
            ]
        )
        generic = rank_root_causes(["Warning Unhealthy Readiness probe failed: timeout connecting to 172.20.2.80:5050"])

        self.assertEqual("readiness_probe_incorrect_protocol", readiness[0].root_cause)
        self.assertEqual("liveness_probe_incorrect_protocol", liveness[0].root_cause)
        self.assertEqual("readiness_probe_failed", generic[0].root_cause)

    def test_cloudopsbench_hidden_mode_uses_full_inventory_for_late_unhealthy_pod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "trainticket" / "startup" / "16"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "train-ticket",
                        "query": "Partial Service Unreachability.",
                        "result": {
                            "fault_object": "app/ts-station-service",
                            "root_cause": "missing_secret_binding",
                        },
                        "process": {"path1": ["GetResources::pods", "DescribeResource::pods::ts-station-service"]},
                    }
                ),
                encoding="utf-8",
            )
            healthy_rows = "".join(
                f"ts-healthy-service-{idx:03d}-85577d9b4d-a{idx:04d} 1/1 Running 0 5m\n"
                for idx in range(100)
            )
            bad_pod = "ts-station-service-5f5c7cc968-f9dzr"
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"train-ticket"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            f"{healthy_rows}"
                            f"{bad_pod} 0/1 CreateContainerConfigError 0 4m55s\n"
                        ),
                        f'DescribeResource:{{"resource_type":"pods","name":"{bad_pod}","namespace":"train-ticket"}}': (
                            f"Name: {bad_pod}\n"
                            'Warning Failed secret "station-secret" not found\n'
                            "State: Waiting\n"
                            "Reason: CreateContainerConfigError\n"
                        ),
                        'GetAppYAML:{"app_name":"ts-station-service"}': (
                            "kind: Deployment\n"
                            "metadata:\n"
                            "  name: ts-station-service\n"
                        ),
                        f'GetErrorLogs:{{"resource_type":"pods","name":"{bad_pod}","namespace":"train-ticket"}}': (
                            'CreateContainerConfigError: secret "station-secret" not found\n'
                        ),
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
                        "title": "Official Cloud-OpsBench late inventory case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "trainticket/startup/16"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "missing_secret_binding",
                        "expert_trajectory": ["GetResources::pods", "DescribeResource::pods::ts-station-service"],
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
                            "related_context": {"audit_logging_available": True, "cloudopsbench_namespace": "train-ticket"},
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
            describe_calls = [call for call in artifact["tool_trajectory"] if call.get("tool_name") == "DescribeResource"]
            self.assertEqual(bad_pod, describe_calls[0]["args"].get("name"))
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)

    def test_cloudopsbench_hidden_mode_does_not_probe_unknown_service_from_restarts_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "boutique" / "infrastructure" / "12"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "boutique",
                        "query": "Service Availability Disruption.",
                        "result": {
                            "fault_object": "node/worker-02",
                            "root_cause": "kube_proxy_unavailable",
                        },
                        "process": {"path1": ["GetResources::pods", "GetClusterConfiguration::"]},
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"boutique"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            "frontend-6778bd7b8b-jm6t9 1/1 Running 0 72s\n"
                            "cartservice-7c5f46fc47-s596z 1/1 Running 0 73s\n"
                        ),
                        'GetResources:{"resource_type":"deployments","name":"","namespace":"boutique"}': (
                            "NAME READY UP-TO-DATE AVAILABLE AGE\n"
                            "frontend 1/1 1 1 72s\n"
                            "cartservice 1/1 1 1 73s\n"
                        ),
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
                        "title": "Official Cloud-OpsBench healthy inventory case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "boutique/infrastructure/12"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "kube_proxy_unavailable",
                        "expert_trajectory": ["GetResources::pods", "GetClusterConfiguration::"],
                        "required_tool_families": ["GetResources"],
                        "raw_signal": {
                            "signal_type": "otel_metric_regression",
                            "signal_id": "placeholder",
                            "observed_at": "2026-05-04T00:00:00Z",
                            "environment": "cloudopsbench",
                            "service": "unknown-service",
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

            artifact = json.loads(
                (run.output_dir / "attempt-artifacts" / "iteration-1" / "official_case.json").read_text()
            )
            tool_names = [call.get("tool_name") for call in artifact["tool_trajectory"]]
            self.assertNotIn("DescribeResource", tool_names)
            self.assertFalse(
                any(call.get("args", {}).get("name") == "unknown-service" for call in artifact["tool_trajectory"])
            )
            self.assertEqual(0, run.results[0].process_metrics.invalid_action_count)

    def test_cloudopsbench_hidden_mode_lists_deployments_for_zero_replica_rca(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "trainticket" / "runtime" / "16"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "train-ticket",
                        "query": "Service Availability Disruption.",
                        "result": {
                            "fault_object": "app/ts-assurance-service",
                            "root_cause": "deployment_zero_replicas",
                        },
                        "process": {
                            "path1": [
                                "GetResources::pods",
                                "GetAlerts::",
                                "GetResources::deployments",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"train-ticket"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            "ts-assurance-service-85577d9b4d-4ld9p 1/1 Running 0 5m\n"
                            "ts-basic-service-7695b48fbc-lr6bf 1/1 Running 0 5m\n"
                        ),
                        "GetAlerts:{}": {
                            "status": "has_anomalies",
                            "alert_count": 1,
                            "alerts": [
                                {
                                    "entry_service": "ts-assurance-service",
                                    "raw_error": "HTTPError('503 Server Error: Service Unavailable')",
                                }
                            ],
                        },
                        'GetResources:{"resource_type":"deployments","name":"","namespace":"train-ticket"}': (
                            "NAME READY UP-TO-DATE AVAILABLE AGE\n"
                            "ts-assurance-service 0/0 0 0 5m\n"
                            "ts-basic-service 1/1 1 1 5m\n"
                        ),
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
                        "title": "Official Cloud-OpsBench zero replica case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "trainticket/runtime/16"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "deployment_zero_replicas",
                        "expert_trajectory": ["GetResources::pods", "GetAlerts::", "GetResources::deployments"],
                        "required_tool_families": ["GetResources", "GetAlerts"],
                        "raw_signal": {
                            "signal_type": "otel_metric_regression",
                            "signal_id": "placeholder",
                            "observed_at": "2026-05-04T00:00:00Z",
                            "environment": "cloudopsbench",
                            "service": "unknown-service",
                            "endpoint": "availability",
                            "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
                            "metric_regression": {"metric_name": "availability", "baseline_value": 1.0, "observed_value": 0.0},
                            "related_context": {"audit_logging_available": True, "cloudopsbench_namespace": "train-ticket"},
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
            deployment_calls = [
                call
                for call in artifact["tool_trajectory"]
                if call.get("tool_name") == "GetResources" and call.get("args", {}).get("resource_type") == "deployments"
            ]
            self.assertTrue(deployment_calls)
            self.assertEqual(
                "deployment_zero_replicas",
                artifact["investigation_report"]["root_cause_candidates"][0]["root_cause"],
            )
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)

    def test_cloudopsbench_hidden_mode_maps_network_drop_alert_to_pod_network_delay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "trainticket" / "performance" / "1"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "train-ticket",
                        "query": "Service quality degradation.",
                        "result": {
                            "fault_object": "app/ts-basic-service",
                            "root_cause": "pod_network_delay",
                        },
                        "process": {"path1": ["GetResources::pods", "GetAlerts::"]},
                    }
                ),
                encoding="utf-8",
            )
            alert_payload = {
                "status": "has_anomalies",
                "alert_count": 1,
                "alerts": [
                    {
                        "name": "ts-basic-service",
                        "metric_category": "TRAFFIC_ANOMALY",
                        "evidence": [
                            "TRAFFIC_ANOMALY [Network Drop] | Inbound: Normal=5.73pps -> Current=2.32pps (-59.6%)"
                        ],
                    }
                ],
            }
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"train-ticket"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            "ts-basic-service-57fb684696-6nfpd 1/1 Running 0 35m\n"
                        ),
                        "GetAlerts:{}": alert_payload,
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "raw_data" / "alert.json").write_text(json.dumps(alert_payload), encoding="utf-8")
            scenario_root = root / "scenarios" / "cloudopsbench"
            scenario_root.mkdir(parents=True)
            (scenario_root / "official_case.json").write_text(
                json.dumps(
                    {
                        "scenario_id": "official_case",
                        "title": "Official Cloud-OpsBench network drop case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "trainticket/performance/1"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "pod_network_delay",
                        "expert_trajectory": ["GetResources::pods", "GetAlerts::"],
                        "required_tool_families": ["GetResources", "GetAlerts"],
                        "raw_signal": {
                            "signal_type": "otel_metric_regression",
                            "signal_id": "placeholder",
                            "observed_at": "2026-05-04T00:00:00Z",
                            "environment": "cloudopsbench",
                            "service": "unknown-service",
                            "endpoint": "latency",
                            "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
                            "metric_regression": {"metric_name": "latency", "baseline_value": 1.0, "observed_value": 10.0},
                            "related_context": {"audit_logging_available": True, "cloudopsbench_namespace": "train-ticket"},
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
            self.assertEqual(
                "pod_network_delay",
                artifact["investigation_report"]["root_cause_candidates"][0]["root_cause"],
            )
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)

    def test_cloudopsbench_hidden_mode_ranks_untolerated_taint_above_generic_scheduler_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cloudops_root = root / "Cloud-OpsBench"
            case_dir = cloudops_root / "benchmark" / "boutique" / "scheduling" / "154"
            (case_dir / "raw_data").mkdir(parents=True)
            (case_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "namespace": "boutique",
                        "query": "Service pod pending.",
                        "result": {
                            "fault_object": "app/recommendationservice",
                            "root_cause": "taint_toleration_mismatch",
                        },
                        "process": {
                            "path1": [
                                "GetResources::pods",
                                "DescribeResource::pods::recommendationservice",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            pod_name = "recommendationservice-68858794d6-pd6vc"
            (case_dir / "tool_cache.json").write_text(
                json.dumps(
                    {
                        'GetResources:{"resource_type":"pods","name":"","namespace":"boutique"}': (
                            "NAME READY STATUS RESTARTS AGE\n"
                            f"{pod_name} 0/1 Pending 0 70s\n"
                        ),
                        f'DescribeResource:{{"resource_type":"pods","name":"{pod_name}","namespace":"boutique"}}': (
                            f"Name: {pod_name}\n"
                            "Status: Pending\n"
                            "Warning FailedScheduling 0/4 nodes are available: "
                            "1 node(s) had untolerated taint {dedicated: batch}, "
                            "3 node(s) didn't match pod's node affinity/selector.\n"
                        ),
                        "GetClusterConfiguration:{}": {"node_count": 4, "nodes": []},
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
                        "title": "Official Cloud-OpsBench taint scheduling case",
                        "suite": "cloudopsbench",
                        "source": {"cloudopsbench_case": "boutique/scheduling/154"},
                        "expected_decisions": ["escalate"],
                        "expected_root_cause": "taint_toleration_mismatch",
                        "expert_trajectory": ["GetResources::pods", "DescribeResource::pods::recommendationservice"],
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
            self.assertEqual(
                "taint_toleration_mismatch",
                artifact["investigation_report"]["root_cause_candidates"][0]["root_cause"],
            )
            self.assertTrue(result.root_cause_matched)
            self.assertEqual(1.0, result.process_metrics.root_cause_at_1)

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

    def test_sregym_endpoint_config_separates_conductor_and_mcp_server(self) -> None:
        endpoints = SreGymEndpointConfig.from_server_url(
            "http://localhost:8000",
            mcp_server_url="http://localhost:9954",
        )

        self.assertEqual("http://localhost:9954/kubectl/sse", endpoints.kubectl_url)
        self.assertEqual("http://localhost:9954/prometheus/sse", endpoints.prometheus_url)
        self.assertEqual("http://localhost:8000/submit_mcp/sse", endpoints.submit_url)

    def test_sregym_agent_fails_when_required_submit_fails(self) -> None:
        client = FakeSreGymClient(fail_submit=True)

        with self.assertRaises(RuntimeError):
            run_mesh_sregym_agent(client=client, trigger=_kubernetes_trigger())

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


class EvidenceKindMatchTests(unittest.TestCase):
    """Regression tests for the substring-match tightening in scoring.

    The previous ``needle.lower() in haystack.lower()`` check matched any
    substring anywhere in the JSON-stringified haystack, producing
    false positives like ``"oom"`` matching ``"boom"`` or
    ``"a8oom42-test"``. The replacement uses identifier-token subset
    matching: every alphanumeric segment of the needle must appear as
    a token in the haystack.
    """

    def test_canonical_snake_case_match(self) -> None:
        haystack = '{"reason": "oom_killed", "container": "search-api"}'
        self.assertTrue(_evidence_kind_matches("oom_killed", haystack))

    def test_canonical_with_hyphen_separator_match(self) -> None:
        haystack = "report says image-pull-back-off observed"
        self.assertTrue(_evidence_kind_matches("image_pull_back_off", haystack))

    def test_substring_inside_unrelated_token_does_not_match(self) -> None:
        # The previous behavior would have ``"oom" in "a8oom42"`` → True.
        haystack = '{"run_id": "a8oom42-test", "phase": "running"}'
        self.assertFalse(_evidence_kind_matches("oom", haystack))

    def test_substring_inside_natural_word_does_not_match(self) -> None:
        # ``"oom" in "room"`` previously fired. Now requires whole-token.
        haystack = "the room temperature is fine"
        self.assertFalse(_evidence_kind_matches("oom", haystack))

    def test_partial_token_subset_does_not_match(self) -> None:
        # Both "oom" and "killed" must appear separately.
        haystack = "we saw oom but the pod was not killed"
        self.assertTrue(_evidence_kind_matches("oom_killed", haystack))
        self.assertFalse(_evidence_kind_matches("oom_killed", "we saw oom only"))

    def test_empty_inputs_do_not_match(self) -> None:
        self.assertFalse(_evidence_kind_matches("", "anything"))
        self.assertFalse(_evidence_kind_matches("oom", ""))

    def test_camelcase_haystack_treated_as_one_token(self) -> None:
        # K8s CamelCase strings (``OOMKilled``) are a single token.
        # ``"oom_killed"`` (snake_case) requires both ``oom`` and ``killed``
        # as separate tokens — CamelCase doesn't satisfy that. Tests can
        # use the canonical snake_case kind on either side.
        haystack = '{"reason": "OOMKilled"}'
        self.assertFalse(_evidence_kind_matches("oom_killed", haystack))


class FakeSreGymClient:
    def __init__(self, *, fail_submit: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_submit = fail_submit

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object]:
        self.calls.append({"name": name, "arguments": dict(arguments or {})})
        if name == "submit" and self.fail_submit:
            return {"status": "error", "text": "submission rejected"}
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
