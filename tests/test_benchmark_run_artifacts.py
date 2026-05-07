from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.benchmark.runner import BenchmarkRunConfig, run_benchmark
from shared.mesh_runtime.benchmark_artifacts import verify_benchmark_run_artifacts


class BenchmarkRunArtifactVerificationTests(unittest.TestCase):
    def test_generated_benchmark_run_artifacts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "benchmark-runs",
                    scenario_ids=("feature_flag_latency_disable", "kubernetes_crashloop_patch"),
                    runtime_state_mode="none",
                )
            )
            payload = verify_benchmark_run_artifacts(
                run.output_dir,
                expected_suite="golden",
                expected_scenario_ids=("feature_flag_latency_disable", "kubernetes_crashloop_patch"),
                min_pass_rate=1.0,
                max_unsafe_action_rate=0.0,
            )

            self.assertEqual("pass", payload["status"])
            self.assertEqual(run.run_id, payload["run_id"])
            self.assertEqual(["feature_flag_latency_disable", "kubernetes_crashloop_patch"], payload["scenario_ids"])
            self.assertEqual(set(payload["artifacts"]), {"benchmark.json", "scorecard.json", "scenario-results.jsonl", "report.md"})

    def test_missing_required_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = run_benchmark(
                BenchmarkRunConfig(
                    suite="golden",
                    output_root=root / "benchmark-runs",
                    scenario_ids=("feature_flag_latency_disable",),
                    runtime_state_mode="none",
                )
            )
            (run.output_dir / "report.md").unlink()
            payload = verify_benchmark_run_artifacts(
                run.output_dir,
                expected_suite="golden",
                expected_scenario_ids=("feature_flag_latency_disable",),
            )

            self.assertEqual("fail", payload["status"])
            self.assertIn("required_artifacts_present", payload["blockers"])
            self.assertIn("report_present", payload["blockers"])


if __name__ == "__main__":
    unittest.main()
