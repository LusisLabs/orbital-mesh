from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    EvalSuiteSpec,
    ReleaseGatePolicy,
    backend_capability_report,
    build_data_plane_e2e,
    build_eval_cases_from_dataset,
    build_eval_plane_e2e,
    build_posttraining_e2e,
    default_backend_for_hardware,
    get_backend,
    list_backends,
    run_eval_suite,
)


class MeshBrainInferenceCatalogTests(unittest.TestCase):
    def test_catalog_exposes_prd_reference_backends_by_hardware(self) -> None:
        nvidia_names = {backend.name for backend in list_backends(hardware_tier="nvidia_datacenter")}
        apple_names = {backend.name for backend in list_backends(hardware_tier="apple_silicon")}
        cpu_names = {backend.name for backend in list_backends(hardware_tier="cpu_edge")}

        self.assertIn("sgl-project/sglang", nvidia_names)
        self.assertIn("ai-dynamo/dynamo", nvidia_names)
        self.assertIn("NVIDIA/TensorRT-LLM", nvidia_names)
        self.assertIn("ml-explore/mlx", apple_names)
        self.assertIn("waybarrios/vllm-mlx", apple_names)
        self.assertIn("ggml-org/llama.cpp", cpu_names)
        self.assertEqual(default_backend_for_hardware("nvidia_datacenter").name, "sgl-project/sglang")
        self.assertEqual(get_backend("modelcloud/GPTQModel").category, "quantization")

    def test_backend_capability_report_flags_missing_required_techniques(self) -> None:
        report = backend_capability_report(
            hardware_tier="cpu_edge",
            required_techniques=["grammar", "disaggregated prefill", "NVFP4"],
        )

        self.assertEqual(report["default_backend"], "ggml-org/llama.cpp")
        self.assertIn("grammar", report["coverage"])
        self.assertIn("disaggregated prefill", report["missing_techniques"])
        self.assertIn("NVFP4", report["missing_techniques"])


class MeshBrainEvalPlaneTests(unittest.TestCase):
    def test_eval_plane_e2e_promotes_when_backend_capabilities_cover_requirements(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            eval_result = build_eval_plane_e2e(
                candidate_artifact=posttraining.artifact,
                dataset_bundle=data_result.bundle,
                output_directory=Path(temp_dir) / "eval",
                hardware_tier="nvidia_datacenter",
            )
            report = json.loads((Path(temp_dir) / "eval" / "eval_report.json").read_text(encoding="utf-8"))

        self.assertEqual(eval_result.backend_name, "sgl-project/sglang")
        self.assertEqual(eval_result.release_gate.release_decision, "promote")
        self.assertEqual(eval_result.backend_capabilities["missing_techniques"], [])
        self.assertTrue(report["release_gate"]["passed"])

    def test_eval_plane_blocks_when_required_backend_capability_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=Path(temp_dir) / "data")
            posttraining = build_posttraining_e2e(dataset_bundle=data_result.bundle, output_directory=Path(temp_dir) / "posttraining")
            eval_result = run_eval_suite(
                EvalSuiteSpec(
                    candidate_artifact=posttraining.artifact,
                    dataset_bundle=data_result.bundle,
                    hardware_tier="cpu_edge",
                    policy=ReleaseGatePolicy(task_success_threshold=0.8),
                    required_backend_techniques=["disaggregated prefill", "NVFP4"],
                )
            )

        self.assertEqual(eval_result.backend_name, "ggml-org/llama.cpp")
        self.assertEqual(eval_result.release_gate.release_decision, "block")
        self.assertEqual(eval_result.metrics["critical_policy_regressions"], 1)
        self.assertEqual(eval_result.metrics["backend_missing_required_techniques"], 2)

    def test_eval_cases_are_derived_from_dataset_eval_and_red_team_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_result = build_data_plane_e2e(tenant_id="tenant_a", output_directory=temp_dir)
            cases = build_eval_cases_from_dataset(data_result.bundle)

        self.assertEqual(len(cases), 2)
        self.assertIn("red_team_prompt_injection", {case.family for case in cases})
        self.assertTrue(all(case.case_id.startswith("mb_eval_") for case in cases))


if __name__ == "__main__":
    unittest.main()
