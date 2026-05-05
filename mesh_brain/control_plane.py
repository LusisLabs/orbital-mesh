from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model_kernel_probe import ModelKernelProbeResult
from .mvp import MeshBrainMVPResult
from .observability import mesh_brain_observation_to_prometheus
from .run_mvp_e2e import persisted_artifact_paths
from .runtime import utc_now


MESH_BRAIN_ARTIFACT_KEYS = (
    "mesh_brain_dataset_manifest",
    "mesh_brain_training_job",
    "mesh_brain_eval_job",
    "mesh_brain_serving_plan",
    "mesh_brain_runtime_trace",
    "mesh_brain_observability_metrics",
    "mesh_brain_catalog_snapshot",
)

MESH_BRAIN_LIVE_SERVING_ARTIFACT_KEYS = (
    "mesh_brain_live_serving_execution",
    "mesh_brain_live_smoke_gate",
    "mesh_brain_live_response_eval",
    "mesh_brain_live_judge_eval",
    "mesh_brain_live_release_gate",
    "mesh_brain_live_serving_summary",
)

MESH_BRAIN_LIVE_ADAPTER_RUNTIME_ARTIFACT_KEYS = (
    "mesh_brain_live_adapter_runtime_probe",
)

MESH_BRAIN_BACKEND_MATRIX_ARTIFACT_KEYS = (
    "mesh_brain_backend_matrix_results",
    "mesh_brain_backend_matrix_summary",
)

MESH_BRAIN_POSTTRAINING_PROOF_ARTIFACT_KEYS = (
    "mesh_brain_posttraining_dataset_manifest",
    "mesh_brain_posttraining_training_job",
    "mesh_brain_posttraining_backend_result",
    "mesh_brain_posttraining_registered_artifact",
    "mesh_brain_posttraining_adapter_export",
    "mesh_brain_posttraining_eval_job",
    "mesh_brain_posttraining_serving_smoke",
    "mesh_brain_posttraining_deployment_record",
)

MESH_BRAIN_MLX_LM_LORA_ARTIFACT_KEYS = (
    "mesh_brain_mlx_lm_lora_mesh_dataset_manifest",
    "mesh_brain_mlx_lm_lora_train_jsonl",
    "mesh_brain_mlx_lm_lora_valid_jsonl",
    "mesh_brain_mlx_lm_lora_test_jsonl",
    "mesh_brain_mlx_lm_lora_command_plan",
    "mesh_brain_mlx_lm_lora_train_stdout",
    "mesh_brain_mlx_lm_lora_train_stderr",
    "mesh_brain_mlx_lm_lora_native_inference_stdout",
    "mesh_brain_mlx_lm_lora_native_inference_stderr",
    "mesh_brain_mlx_lm_lora_adapter_export",
    "mesh_brain_mlx_lm_lora_backend_compatibility",
    "mesh_brain_mlx_lm_lora_native_server_probe",
    "mesh_brain_mlx_lm_lora_native_response_eval",
    "mesh_brain_mlx_lm_lora_lm_studio_compatibility",
    "mesh_brain_mlx_lm_lora_run_summary",
)

MESH_BRAIN_MODEL_KERNEL_ARTIFACT_KEYS = (
    "mesh_brain_model_kernel_correctness",
    "mesh_brain_model_kernel_runtime_benchmark",
    "mesh_brain_model_kernel_gate",
    "mesh_brain_model_kernel_probe_summary",
)


@dataclass(frozen=True)
class MeshBrainArtifactRef:
    artifact_key: str
    path: str
    exists: bool
    sha256: str | None
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "path": self.path,
            "exists": self.exists,
            "sha256": self.sha256,
            "content_type": self.content_type,
        }


@dataclass(frozen=True)
class MeshBrainArtifactBundle:
    workflow_id: str
    tenant_id: str
    output_directory: str
    artifacts: dict[str, MeshBrainArtifactRef]
    release_decision: str
    deployment_record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "output_directory": self.output_directory,
            "artifacts": {key: ref.to_dict() for key, ref in self.artifacts.items()},
            "release_decision": self.release_decision,
            "deployment_record": dict(self.deployment_record),
        }


def build_mesh_brain_artifact_bundle(
    *,
    result: MeshBrainMVPResult,
    output_directory: str | Path,
) -> MeshBrainArtifactBundle:
    output_path = Path(output_directory)
    paths = persisted_artifact_paths(output_path)
    artifact_paths = {
        "mesh_brain_dataset_manifest": paths["dataset_manifest"],
        "mesh_brain_training_job": paths["training_job"],
        "mesh_brain_eval_job": paths["eval_job"],
        "mesh_brain_serving_plan": paths["serving_plan"],
        "mesh_brain_runtime_trace": paths["trace_dataset_row"],
        "mesh_brain_observability_metrics": paths["observability_metrics"],
        "mesh_brain_catalog_snapshot": paths["catalog_snapshot"],
    }
    refs = {
        key: _artifact_ref(key, Path(path))
        for key, path in artifact_paths.items()
    }
    release_decision = result.eval_job.release_decision
    return MeshBrainArtifactBundle(
        workflow_id=result.workflow_id,
        tenant_id=result.serving_plan.route.tenant_id,
        output_directory=str(output_path),
        artifacts=refs,
        release_decision=release_decision,
        deployment_record={
            "status": "blocked" if release_decision == "block" else "recorded",
            "deployed": release_decision in {"canary", "promote"},
            "release_decision": release_decision,
            "candidate_artifact_id": result.eval_job.candidate_artifact_id,
            "serving_backend": result.serving_plan.backend_name if release_decision != "block" else None,
            "canary_state": result.canary_alias.state if release_decision != "block" else None,
            "rollback_state": result.rollback_alias.state,
        },
    )


def mesh_brain_mvp_to_run_record(
    *,
    result: MeshBrainMVPResult,
    bundle: MeshBrainArtifactBundle,
    run_id: str,
) -> dict[str, Any]:
    audit_events = [event.to_dict() for event in result.agent_result.events]
    policy_events = [
        event
        for event in audit_events
        if event.get("event_type") in {"policy_decision", "approval_decision"}
    ]
    return {
        "run_id": run_id,
        "tenant_id": bundle.tenant_id,
        "stage": "failed" if bundle.release_decision == "block" else "completed",
        "status": "blocked" if bundle.release_decision == "block" else "completed",
        "artifact_refs": {key: ref.to_dict() for key, ref in bundle.artifacts.items()},
        "audit_events": audit_events,
        "policy_events": policy_events,
        "summary_metrics": {
            "golden_eval_case_count": result.acceptance_report["golden_eval_case_count"],
            "token_count": result.observability.token_count,
            "cache_hit_rate": result.observability.cache_hit_rate,
            "policy_route": result.observability.policy_route,
            "serving_backend": result.serving_plan.backend_name,
        },
        "final_release_decision": bundle.release_decision,
    }


def build_model_kernel_artifact_bundle(
    *,
    result: ModelKernelProbeResult,
) -> MeshBrainArtifactBundle:
    artifact_paths = {
        "mesh_brain_model_kernel_correctness": result.artifact_paths["model_kernel_correctness"],
        "mesh_brain_model_kernel_runtime_benchmark": result.artifact_paths["model_kernel_runtime_benchmark"],
        "mesh_brain_model_kernel_gate": result.artifact_paths["model_kernel_gate"],
        "mesh_brain_model_kernel_probe_summary": result.artifact_paths["model_kernel_probe_summary"],
    }
    refs = {
        key: _artifact_ref(key, Path(path))
        for key, path in artifact_paths.items()
    }
    return MeshBrainArtifactBundle(
        workflow_id=result.result_id,
        tenant_id="mesh_system",
        output_directory=str(Path(result.artifact_paths["model_kernel_probe_summary"]).parent),
        artifacts=refs,
        release_decision=result.release_decision,
        deployment_record={
            "status": "recorded" if result.release_decision == "pass" else "blocked",
            "deployed": False,
            "release_decision": result.release_decision,
            "correctness_probe_id": result.correctness.probe_id,
            "runtime_benchmark_id": result.runtime_benchmark.benchmark_id,
            "deterministic_digest": result.correctness.deterministic_digest,
        },
    )


def model_kernel_probe_to_run_record(
    *,
    result: ModelKernelProbeResult,
    bundle: MeshBrainArtifactBundle,
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "tenant_id": bundle.tenant_id,
        "stage": "completed" if bundle.release_decision == "pass" else "failed",
        "status": "completed" if bundle.release_decision == "pass" else "blocked",
        "artifact_refs": {key: ref.to_dict() for key, ref in bundle.artifacts.items()},
        "audit_events": [],
        "policy_events": [],
        "summary_metrics": {
            "loss_before": result.correctness.loss_before,
            "loss_after_adam": result.correctness.loss_after_adam,
            "max_forward_delta": result.correctness.max_forward_delta,
            "max_gradient_relative_error": result.correctness.max_gradient_relative_error,
            "q412_max_logit_delta": result.correctness.q412_max_logit_delta,
            "reference_tokens_per_second": result.runtime_benchmark.local_target["tokens_per_second"],
            "source_influences": list(result.correctness.source_influences),
        },
        "final_release_decision": bundle.release_decision,
    }


def build_live_serving_artifact_bundle(
    *,
    summary: dict[str, Any],
) -> MeshBrainArtifactBundle:
    artifact_paths = summary.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        raise ValueError("live serving summary missing artifact paths")
    key_map = {
        "mesh_brain_live_serving_execution": "live_serving_execution",
        "mesh_brain_live_smoke_gate": "live_smoke_gate",
        "mesh_brain_live_response_eval": "live_response_eval",
        "mesh_brain_live_judge_eval": "live_judge_eval",
        "mesh_brain_live_release_gate": "live_release_gate",
        "mesh_brain_live_serving_summary": "live_serving_summary",
    }
    refs = {
        artifact_key: _artifact_ref(artifact_key, Path(str(artifact_paths[source_key])))
        for artifact_key, source_key in key_map.items()
    }
    release_decision = str(summary.get("release_gate", {}).get("decision") or summary.get("status") or "block")
    deployment_record = summary.get("deployment_record")
    return MeshBrainArtifactBundle(
        workflow_id=str(summary.get("request_id") or summary.get("completion_id") or "mesh_brain_live_serving_smoke"),
        tenant_id=str(summary.get("tenant_id") or "unknown"),
        output_directory=str(Path(str(artifact_paths["live_serving_summary"])).parent),
        artifacts=refs,
        release_decision=release_decision,
        deployment_record=dict(deployment_record) if isinstance(deployment_record, dict) else {
            "status": "blocked",
            "release_decision": release_decision,
            "deployed": False,
        },
    )


def live_serving_smoke_to_run_record(
    *,
    summary: dict[str, Any],
    bundle: MeshBrainArtifactBundle,
    run_id: str,
) -> dict[str, Any]:
    release_decision = bundle.release_decision
    blocked = release_decision not in {"canary", "promote"}
    return {
        "run_id": run_id,
        "tenant_id": bundle.tenant_id,
        "stage": "failed" if blocked else "completed",
        "status": "blocked" if blocked else "completed",
        "artifact_refs": {key: ref.to_dict() for key, ref in bundle.artifacts.items()},
        "audit_events": [],
        "policy_events": [],
        "summary_metrics": {
            "model": summary.get("model"),
            "requested_model": summary.get("requested_model"),
            "backend_name": summary.get("backend_name"),
            "hardware_tier": summary.get("hardware_tier"),
            "task_type": summary.get("task_type"),
            "latency_ms": summary.get("latency_ms"),
            "total_tokens": (summary.get("usage") or {}).get("total_tokens") if isinstance(summary.get("usage"), dict) else None,
            "live_smoke_gate": (summary.get("gate") or {}).get("decision") if isinstance(summary.get("gate"), dict) else None,
            "live_response_eval": (summary.get("response_eval") or {}).get("decision") if isinstance(summary.get("response_eval"), dict) else None,
            "live_judge_eval": (summary.get("judge_eval") or {}).get("decision") if isinstance(summary.get("judge_eval"), dict) else None,
            "live_release_gate": (summary.get("release_gate") or {}).get("decision") if isinstance(summary.get("release_gate"), dict) else None,
        },
        "final_release_decision": release_decision,
    }


def mesh_brain_result_prometheus(result: MeshBrainMVPResult) -> str:
    return mesh_brain_observation_to_prometheus(result.observability)


def _artifact_ref(artifact_key: str, path: Path) -> MeshBrainArtifactRef:
    exists = path.exists()
    return MeshBrainArtifactRef(
        artifact_key=artifact_key,
        path=str(path),
        exists=exists,
        sha256=_sha256(path) if exists else None,
        content_type="text/plain" if path.suffix == ".prom" else "application/json",
    )


def mesh_brain_artifact_ref(artifact_key: str, path: str | Path) -> MeshBrainArtifactRef:
    return _artifact_ref(artifact_key, Path(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocked_eval_result(result: MeshBrainMVPResult) -> MeshBrainMVPResult:
    result.eval_job.release_decision = "block"
    result.acceptance_report["candidate_eval_passed"] = False
    result.acceptance_report["reported_at"] = utc_now()
    result.observability.eval_outcome = "block"
    result.observability.labels["eval_outcome"] = "block"
    for sample in result.observability.samples:
        sample.labels["eval_outcome"] = "block"
        if sample.name == "mesh_brain_eval_outcome":
            sample.value = 0.0
    return result
