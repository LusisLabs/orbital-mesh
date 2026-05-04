from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain import (
    build_adapter_export_manifest,
    build_hardware_serving_profile,
    build_mlx_lm_lora_export_manifest,
    build_quantization_export_manifest,
    new_model_artifact,
    run_multi_hardware_smoke,
    write_adapter_export_manifest,
    write_multi_hardware_smoke_result,
)


class MeshBrainHardwareProfilesTests(unittest.TestCase):
    def test_multi_hardware_smoke_passes_three_required_tiers_and_writes_reports(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_multi_hardware_smoke(hardware_tiers=["nvidia_datacenter", "apple_silicon", "cpu_edge"])
            written = write_multi_hardware_smoke_result(result=result, output_directory=temp_dir)
            report = json.loads(Path(written["multi_hardware_smoke.json"]).read_text(encoding="utf-8"))

        self.assertTrue(result.passed)
        self.assertEqual({profile.hardware_tier for profile in result.profiles}, {"nvidia_datacenter", "apple_silicon", "cpu_edge"})
        self.assertEqual({manifest.target_hardware_tier for manifest in result.quantization_exports}, {"nvidia_datacenter", "apple_silicon", "cpu_edge"})
        self.assertEqual(len(report["profiles"]), 3)
        self.assertTrue(all(not profile.unsupported_features for profile in result.profiles))

    def test_profiles_document_supported_features_and_default_backends(self) -> None:
        nvidia = build_hardware_serving_profile(hardware_tier="nvidia_datacenter")
        apple = build_hardware_serving_profile(hardware_tier="apple_silicon")
        cpu = build_hardware_serving_profile(hardware_tier="cpu_edge")

        self.assertEqual(nvidia.default_backend, "sgl-project/sglang")
        self.assertIn("prefix", nvidia.supported_features)
        self.assertEqual(apple.default_backend, "ml-explore/mlx")
        self.assertIn("Metal", apple.supported_features)
        self.assertEqual(cpu.default_backend, "ggml-org/llama.cpp")
        self.assertIn("GGUF", cpu.supported_features)

    def test_quantization_export_manifest_tracks_baseline_quality_and_output_artifact(self) -> None:
        source = new_model_artifact(
            artifact_type="tenant_adapter",
            version="adapter-v1",
            signed_manifest_ref="sha256:adapter-v1",
            tenant_id="tenant_a",
            task_type="crops",
            dataset_manifest_ids=["dataset_v1"],
            training_run_id="train_v1",
        )
        manifest = build_quantization_export_manifest(
            source_artifact=source,
            target_hardware_tier="cpu_edge",
            export_format="GGUF-Q4",
            quality_baseline_eval_report_id="eval_baseline",
        )

        self.assertEqual(manifest.source_artifact_id, source.artifact_id)
        self.assertEqual(manifest.export_format, "GGUF-Q4")
        self.assertEqual(manifest.output_artifact.artifact_type, "quantized_checkpoint")
        self.assertEqual(manifest.output_artifact.base_artifact_id, source.artifact_id)
        self.assertEqual(manifest.output_artifact.metadata["quality_baseline_eval_report_id"], "eval_baseline")
        self.assertLess(manifest.expected_quality_delta, 0)

    def test_quantization_export_rejects_wrong_format_for_hardware(self) -> None:
        source = new_model_artifact(
            artifact_type="tenant_adapter",
            version="adapter-v1",
            signed_manifest_ref="sha256:adapter-v1",
        )

        with self.assertRaisesRegex(ValueError, "unsupported export format"):
            build_quantization_export_manifest(
                source_artifact=source,
                target_hardware_tier="apple_silicon",
                export_format="GGUF-Q4",
                quality_baseline_eval_report_id="eval_baseline",
            )

    def test_mlx_lm_lora_adapter_export_manifest_records_train_and_generate_commands(self) -> None:
        source = new_model_artifact(
            artifact_type="tenant_adapter",
            version="adapter-v1",
            signed_manifest_ref="sha256:adapter-v1",
            tenant_id="tenant_a",
            task_type="crops",
            base_artifact_id="nvidia/nemotron-3-nano-4b",
        )
        with TemporaryDirectory() as temp_dir:
            adapter_file = Path(temp_dir) / "adapter_model.safetensors"
            adapter_file.write_text("adapter\n", encoding="utf-8")
            manifest = build_mlx_lm_lora_export_manifest(
                source_artifact=source,
                base_model_id="nvidia/nemotron-3-nano-4b",
                adapter_files=[{"path": str(adapter_file), "sha256": "sha256:adapter"}],
            )
            written = write_adapter_export_manifest(manifest=manifest, output_directory=temp_dir)
            persisted = json.loads(Path(written["adapter_export_manifest.json"]).read_text(encoding="utf-8"))

        self.assertEqual(manifest.target_hardware_tier, "apple_silicon")
        self.assertEqual(manifest.export_format, "mlx_lm_lora")
        self.assertEqual(manifest.backend_compatibility["training_entrypoint"], "mlx_lm_lora.train")
        self.assertEqual(manifest.backend_compatibility["generation_entrypoint"], "mlx_lm.generate")
        self.assertFalse(manifest.backend_compatibility["supports_runtime_adapter_load"])
        self.assertIn("--adapter-path", manifest.load_metadata["generate_command"])
        self.assertIn("--train-mode", manifest.load_metadata["train_command"])
        self.assertEqual(persisted["export_id"], manifest.export_id)

    def test_adapter_export_rejects_wrong_format_for_hardware(self) -> None:
        source = new_model_artifact(
            artifact_type="tenant_adapter",
            version="adapter-v1",
            signed_manifest_ref="sha256:adapter-v1",
        )

        with self.assertRaisesRegex(ValueError, "unsupported adapter export format"):
            build_adapter_export_manifest(
                source_artifact=source,
                base_model_id="base",
                target_hardware_tier="apple_silicon",
                export_format="llama_cpp_lora",
                adapter_files=[{"path": "/tmp/adapter.safetensors"}],
            )


if __name__ == "__main__":
    unittest.main()
