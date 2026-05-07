from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    run_micro_runtime_benchmark,
    run_micro_transformer_correctness_probe,
    run_model_kernel_probe,
)


class MeshBrainModelKernelProbeTests(unittest.TestCase):
    def test_micro_transformer_probe_checks_forward_gradient_adam_and_q412_drift(self) -> None:
        probe = run_micro_transformer_correctness_probe()

        self.assertTrue(probe.passed)
        self.assertEqual(probe.deterministic_digest, "03f68ae7fd8c39521a3bc4a27486428278656a45268e5d3b4cb22295678d6a65")
        self.assertEqual(probe.max_forward_delta, 0.0)
        self.assertLess(probe.max_gradient_relative_error, 1e-6)
        self.assertLess(probe.loss_after_adam, probe.loss_before)
        self.assertLess(probe.q412_max_logit_delta, 0.01)
        self.assertIn("microgpt.apl", probe.source_influences[0])

    def test_runtime_benchmark_executes_local_reference_without_backend_claims(self) -> None:
        benchmark = run_micro_runtime_benchmark(iterations=20)

        self.assertTrue(benchmark.gate["passed"])
        self.assertEqual(benchmark.local_target["status"], "executed")
        self.assertEqual(benchmark.local_target["promotion_use"], "does_not_set_production_throughput_claims")
        self.assertGreater(benchmark.local_target["tokens_per_second"], 0.0)
        guidance = {target["name"]: target for target in benchmark.guidance_targets}
        self.assertIn("apple_silicon_native_cpu", guidance)
        self.assertIn("apple_silicon_mlx_gpu", guidance)
        self.assertEqual(guidance["q4_12_fixed_point"]["status"], "drift_checked_by_correctness_probe")

    def test_model_kernel_probe_writes_artifacts_and_passes_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_model_kernel_probe(output_directory=Path(temp_dir), benchmark_iterations=20)
            summary = json.loads(Path(result.artifact_paths["model_kernel_probe_summary"]).read_text(encoding="utf-8"))
            gate = json.loads(Path(result.artifact_paths["model_kernel_gate"]).read_text(encoding="utf-8"))

        self.assertEqual(result.release_decision, "pass")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.correctness.passed)
        self.assertTrue(result.runtime_benchmark.gate["passed"])
        self.assertEqual(gate["decision"], "pass")
        self.assertEqual(summary["correctness"]["deterministic_digest"], result.correctness.deterministic_digest)
        self.assertEqual(
            set(result.artifact_paths),
            {
                "model_kernel_correctness",
                "model_kernel_runtime_benchmark",
                "model_kernel_gate",
                "model_kernel_probe_summary",
            },
        )


if __name__ == "__main__":
    unittest.main()
