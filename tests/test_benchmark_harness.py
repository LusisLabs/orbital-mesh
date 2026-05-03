from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from services.benchmark.compare import compare_benchmark_runs
from services.benchmark.loghub import LoghubExtractionConfig, extract_loghub_scenarios
from services.benchmark.models import DIMENSION_WEIGHTS
from services.benchmark.runner import BenchmarkRunConfig, run_benchmark
from services.benchmark.scenario_loader import load_suite
from services.benchmark.scoring import score_outcome


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
            scorecard = json.loads((run.output_dir / "scorecard.json").read_text(encoding="utf-8"))
            self.assertIn("dimension_weights", scorecard)
            self.assertGreater(scorecard["weighted_score"], 0)
            self.assertTrue(all(result.investigation_present for result in run.results))

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


if __name__ == "__main__":
    unittest.main()
