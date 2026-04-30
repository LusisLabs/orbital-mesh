from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .inference_catalog import backend_capability_report, default_backend_for_hardware
from .runtime import ModelArtifact, new_model_artifact, stable_digest, utc_now


HARDWARE_REQUIRED_TECHNIQUES: dict[str, tuple[str, ...]] = {
    "nvidia_datacenter": ("prefix", "speculative", "constrained", "batching"),
    "nvidia_consumer": ("prefix", "speculative", "batching"),
    "amd_rocm": ("prefix", "batching"),
    "apple_silicon": ("prompt caching", "Metal"),
    "cpu_edge": ("GGUF", "grammar"),
}

QUANTIZATION_EXPORT_FORMATS: dict[str, tuple[str, ...]] = {
    "nvidia_datacenter": ("NVFP4", "FP8", "GPTQ", "AWQ"),
    "nvidia_consumer": ("GPTQ", "AWQ", "INT4"),
    "amd_rocm": ("GPTQ", "AWQ"),
    "apple_silicon": ("MLX-4bit", "MLX-8bit"),
    "cpu_edge": ("GGUF-Q4", "GGUF-Q8"),
}

ADAPTER_EXPORT_FORMATS: dict[str, tuple[str, ...]] = {
    "apple_silicon": ("mlx_lm_lora",),
    "cpu_edge": ("llama_cpp_lora",),
    "nvidia_datacenter": ("vllm_lora", "sglang_lora"),
    "nvidia_consumer": ("vllm_lora",),
}


@dataclass(frozen=True)
class HardwareServingProfile:
    hardware_tier: str
    default_backend: str
    required_techniques: list[str]
    supported_features: list[str]
    unsupported_features: list[str]
    quantization_formats: list[str]
    smoke_passed: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantizationExportManifest:
    export_id: str
    source_artifact_id: str
    target_hardware_tier: str
    export_format: str
    output_artifact: ModelArtifact
    quality_baseline_eval_report_id: str
    expected_quality_delta: float
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "source_artifact_id": self.source_artifact_id,
            "target_hardware_tier": self.target_hardware_tier,
            "export_format": self.export_format,
            "output_artifact": self.output_artifact.to_dict(),
            "quality_baseline_eval_report_id": self.quality_baseline_eval_report_id,
            "expected_quality_delta": self.expected_quality_delta,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AdapterExportManifest:
    export_id: str
    source_artifact_id: str
    base_model_id: str
    target_hardware_tier: str
    export_format: str
    adapter_files: list[dict[str, Any]]
    backend_compatibility: dict[str, Any]
    load_metadata: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultiHardwareSmokeResult:
    profiles: list[HardwareServingProfile]
    quantization_exports: list[QuantizationExportManifest]
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "profiles": [profile.to_dict() for profile in self.profiles],
            "quantization_exports": [manifest.to_dict() for manifest in self.quantization_exports],
            "passed": self.passed,
        }


def build_hardware_serving_profile(*, hardware_tier: str) -> HardwareServingProfile:
    required = list(HARDWARE_REQUIRED_TECHNIQUES.get(hardware_tier, ("prefix",)))
    report = backend_capability_report(hardware_tier=hardware_tier, required_techniques=required)
    supported = [technique for technique, backends in report["coverage"].items() if backends]
    unsupported = list(report["missing_techniques"])
    return HardwareServingProfile(
        hardware_tier=hardware_tier,
        default_backend=default_backend_for_hardware(hardware_tier).name,
        required_techniques=required,
        supported_features=supported,
        unsupported_features=unsupported,
        quantization_formats=list(QUANTIZATION_EXPORT_FORMATS.get(hardware_tier, ())),
        smoke_passed=not unsupported,
        notes=_profile_notes(hardware_tier),
    )


def run_multi_hardware_smoke(
    *,
    hardware_tiers: list[str] | None = None,
    source_artifact: ModelArtifact | None = None,
    quality_baseline_eval_report_id: str = "baseline_eval_report",
) -> MultiHardwareSmokeResult:
    tiers = hardware_tiers or ["nvidia_datacenter", "apple_silicon", "cpu_edge"]
    profiles = [build_hardware_serving_profile(hardware_tier=tier) for tier in tiers]
    source = source_artifact or new_model_artifact(
        artifact_type="tenant_adapter",
        version="multi-hardware-source",
        signed_manifest_ref="sha256:multi-hardware-source",
        tenant_id="tenant_a",
        task_type="crops",
    )
    exports = [
        build_quantization_export_manifest(
            source_artifact=source,
            target_hardware_tier=profile.hardware_tier,
            quality_baseline_eval_report_id=quality_baseline_eval_report_id,
        )
        for profile in profiles
    ]
    return MultiHardwareSmokeResult(
        profiles=profiles,
        quantization_exports=exports,
        passed=len(profiles) >= 3 and all(profile.smoke_passed for profile in profiles),
    )


def build_quantization_export_manifest(
    *,
    source_artifact: ModelArtifact,
    target_hardware_tier: str,
    quality_baseline_eval_report_id: str,
    export_format: str | None = None,
) -> QuantizationExportManifest:
    formats = QUANTIZATION_EXPORT_FORMATS.get(target_hardware_tier)
    if not formats:
        raise ValueError(f"unsupported quantization target hardware tier: {target_hardware_tier}")
    selected_format = export_format or formats[0]
    if selected_format not in formats:
        raise ValueError(f"unsupported export format for {target_hardware_tier}: {selected_format}")
    digest = stable_digest(
        {
            "source": source_artifact.artifact_id,
            "hardware": target_hardware_tier,
            "format": selected_format,
            "baseline": quality_baseline_eval_report_id,
        }
    )
    output = new_model_artifact(
        artifact_type="quantized_checkpoint",
        version=f"{source_artifact.version}-{selected_format.lower()}",
        signed_manifest_ref=f"sha256:{digest}",
        tenant_id=source_artifact.tenant_id,
        task_type=source_artifact.task_type,
        base_artifact_id=source_artifact.artifact_id,
        dataset_manifest_ids=list(source_artifact.dataset_manifest_ids),
        training_run_id=source_artifact.training_run_id,
        metadata={
            "target_hardware_tier": target_hardware_tier,
            "export_format": selected_format,
            "quality_baseline_eval_report_id": quality_baseline_eval_report_id,
            "expected_quality_delta": _quality_delta(selected_format),
        },
    )
    return QuantizationExportManifest(
        export_id=f"mb_quant_export_{digest[:12]}",
        source_artifact_id=source_artifact.artifact_id,
        target_hardware_tier=target_hardware_tier,
        export_format=selected_format,
        output_artifact=output,
        quality_baseline_eval_report_id=quality_baseline_eval_report_id,
        expected_quality_delta=_quality_delta(selected_format),
        created_at=utc_now(),
    )


def build_adapter_export_manifest(
    *,
    source_artifact: ModelArtifact,
    base_model_id: str,
    target_hardware_tier: str,
    adapter_files: list[dict[str, Any]],
    export_format: str | None = None,
) -> AdapterExportManifest:
    formats = ADAPTER_EXPORT_FORMATS.get(target_hardware_tier)
    if not formats:
        raise ValueError(f"unsupported adapter export target hardware tier: {target_hardware_tier}")
    selected_format = export_format or formats[0]
    if selected_format not in formats:
        raise ValueError(f"unsupported adapter export format for {target_hardware_tier}: {selected_format}")
    normalized_files = [_normalize_adapter_file(file) for file in adapter_files]
    if not normalized_files:
        raise ValueError("adapter export requires at least one adapter file")
    digest = stable_digest(
        {
            "source": source_artifact.artifact_id,
            "base_model": base_model_id,
            "hardware": target_hardware_tier,
            "format": selected_format,
            "files": normalized_files,
        }
    )
    return AdapterExportManifest(
        export_id=f"mb_adapter_export_{digest[:12]}",
        source_artifact_id=source_artifact.artifact_id,
        base_model_id=base_model_id,
        target_hardware_tier=target_hardware_tier,
        export_format=selected_format,
        adapter_files=normalized_files,
        backend_compatibility=_adapter_backend_compatibility(
            target_hardware_tier=target_hardware_tier,
            export_format=selected_format,
        ),
        load_metadata=_adapter_load_metadata(
            export_format=selected_format,
            base_model_id=base_model_id,
            adapter_files=normalized_files,
        ),
        created_at=utc_now(),
    )


def build_mlx_lm_lora_export_manifest(
    *,
    source_artifact: ModelArtifact,
    base_model_id: str,
    adapter_files: list[dict[str, Any]],
) -> AdapterExportManifest:
    return build_adapter_export_manifest(
        source_artifact=source_artifact,
        base_model_id=base_model_id,
        target_hardware_tier="apple_silicon",
        export_format="mlx_lm_lora",
        adapter_files=adapter_files,
    )


def write_multi_hardware_smoke_result(*, result: MultiHardwareSmokeResult, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "multi_hardware_smoke.json": result.to_dict(),
        "hardware_profiles.json": [profile.to_dict() for profile in result.profiles],
        "quantization_exports.json": [manifest.to_dict() for manifest in result.quantization_exports],
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(_json(payload), encoding="utf-8")
        written[name] = str(path)
    return written


def write_adapter_export_manifest(*, manifest: AdapterExportManifest, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    path = output_path / "adapter_export_manifest.json"
    path.write_text(_json(manifest.to_dict()), encoding="utf-8")
    return {"adapter_export_manifest.json": str(path)}


def _quality_delta(export_format: str) -> float:
    if export_format in {"NVFP4", "MLX-4bit", "GGUF-Q4", "INT4"}:
        return -0.03
    if export_format in {"FP8", "MLX-8bit", "GGUF-Q8"}:
        return -0.01
    return -0.02


def _profile_notes(hardware_tier: str) -> str:
    return {
        "nvidia_datacenter": "Primary enterprise GPU path for SGLang or vLLM.",
        "nvidia_consumer": "Departmental or demo GPU path.",
        "amd_rocm": "Private cloud portability path.",
        "apple_silicon": "Local private mode through MLX or vllm-mlx.",
        "cpu_edge": "Lower-throughput edge fallback through llama.cpp.",
    }.get(hardware_tier, "Custom hardware tier.")


def _normalize_adapter_file(file: dict[str, Any]) -> dict[str, Any]:
    path = str(file.get("path") or "")
    if not path:
        raise ValueError("adapter file requires path")
    return {
        "name": str(file.get("name") or Path(path).name),
        "path": path,
        "sha256": str(file.get("sha256") or ""),
    }


def _adapter_backend_compatibility(*, target_hardware_tier: str, export_format: str) -> dict[str, Any]:
    if export_format == "mlx_lm_lora":
        return {
            "hardware_tier": target_hardware_tier,
            "backend": "mlx-lm-lora",
            "training_package": "mlx-lm-lora",
            "training_entrypoint": "mlx_lm_lora.train",
            "generation_entrypoint": "mlx_lm.generate",
            "supports_runtime_adapter_load": False,
            "adapter_load_boundary": "process_start_or_generation_command",
        }
    if export_format == "llama_cpp_lora":
        return {
            "hardware_tier": target_hardware_tier,
            "backend": "llama.cpp",
            "supports_runtime_adapter_load": False,
            "adapter_load_boundary": "server_start_flags",
        }
    return {
        "hardware_tier": target_hardware_tier,
        "backend": export_format.removesuffix("_lora"),
        "supports_runtime_adapter_load": True,
        "adapter_load_boundary": "runtime_api",
    }


def _adapter_load_metadata(*, export_format: str, base_model_id: str, adapter_files: list[dict[str, Any]]) -> dict[str, Any]:
    adapter_path = _adapter_directory(adapter_files)
    if export_format == "mlx_lm_lora":
        return {
            "train_command": [
                "mlx_lm_lora.train",
                "--model",
                base_model_id,
                "--train",
                "--train-mode",
                "sft",
                "--train-type",
                "lora",
                "--data",
                "<dataset_directory>",
                "--adapter-path",
                adapter_path,
            ],
            "generate_command": [
                "mlx_lm.generate",
                "--model",
                base_model_id,
                "--adapter-path",
                adapter_path,
                "--prompt",
                "<prompt>",
            ],
            "fuse_command": [
                "mlx_lm_lora.train",
                "--model",
                base_model_id,
                "--adapter-path",
                adapter_path,
                "--fuse",
            ],
        }
    if export_format == "llama_cpp_lora":
        return {"server_flags": ["--model", base_model_id, "--lora", adapter_path]}
    return {"runtime_load_payload": {"base_model_id": base_model_id, "adapter_path": adapter_path}}


def _adapter_directory(adapter_files: list[dict[str, Any]]) -> str:
    first = Path(str(adapter_files[0]["path"]))
    return str(first.parent if first.name else first)


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
