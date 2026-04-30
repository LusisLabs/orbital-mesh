from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .posttraining import PosttrainingRun, TrainingJobSpec, plan_posttraining_run
from .runtime import DatasetBundle, stable_digest, utc_now


JOB_METHODS = {"sft", "lora", "qlora", "dpo", "ipo", "kto", "agent_rl", "quantization", "qat"}
METHOD_ROW_TYPES = {
    "sft": {"sft"},
    "lora": {"sft"},
    "qlora": {"sft"},
    "dpo": {"preference_pair"},
    "ipo": {"preference_pair"},
    "kto": {"preference_pair"},
    "agent_rl": {"rl_trajectory"},
    "quantization": {"sft", "eval_case"},
    "qat": {"sft", "eval_case"},
}
METHOD_ARTIFACT_TYPES = {
    "sft": "task_adapter",
    "lora": "tenant_adapter",
    "qlora": "tenant_adapter",
    "dpo": "policy_adapter",
    "ipo": "policy_adapter",
    "kto": "policy_adapter",
    "agent_rl": "policy_adapter",
    "quantization": "quantized_checkpoint",
    "qat": "quantized_checkpoint",
}


@dataclass
class TrainingJobRequest:
    method: str
    tenant_id: str
    task_type: str
    dataset_bundle: DatasetBundle
    code_version: str
    base_artifact_id: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    hardware_tier: str = "nvidia_datacenter"
    output_directory: str | None = None
    artifact_type: str | None = None

    def validate(self) -> None:
        if self.method not in JOB_METHODS:
            raise ValueError(f"unsupported training job method: {self.method}")
        if not self.tenant_id:
            raise ValueError("training jobs require tenant_id")
        if not self.task_type:
            raise ValueError("training jobs require task_type")
        if not self.base_artifact_id:
            raise ValueError("training jobs require base_artifact_id")
        trainable_rows = [row for row in self.dataset_bundle.rows if not row.excluded_from_training]
        if not trainable_rows:
            raise ValueError("training job has no trainable rows")
        tenant_ids = {row.tenant_id for row in trainable_rows}
        if tenant_ids - {self.tenant_id}:
            raise ValueError("training rows contain another tenant")
        required_types = METHOD_ROW_TYPES[self.method]
        if not any(row.row_type in required_types for row in trainable_rows):
            expected = ", ".join(sorted(required_types))
            raise ValueError(f"{self.method} job requires trainable rows of type: {expected}")


@dataclass
class TrainingJobOutput:
    name: str
    artifact_ref: str
    digest: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingJobResult:
    job_id: str
    request: TrainingJobRequest
    posttraining_run: PosttrainingRun
    status: str
    metrics: dict[str, float]
    outputs: list[TrainingJobOutput]
    deployment_manifest: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "request": {
                "method": self.request.method,
                "tenant_id": self.request.tenant_id,
                "task_type": self.request.task_type,
                "dataset_version": self.request.dataset_bundle.dataset_version,
                "code_version": self.request.code_version,
                "base_artifact_id": self.request.base_artifact_id,
                "hyperparameters": dict(self.request.hyperparameters),
                "hardware_tier": self.request.hardware_tier,
                "artifact_type": self.artifact_type,
            },
            "posttraining_run": self.posttraining_run.to_dict(),
            "status": self.status,
            "metrics": dict(self.metrics),
            "outputs": [output.to_dict() for output in self.outputs],
            "deployment_manifest": dict(self.deployment_manifest),
            "created_at": self.created_at,
        }

    @property
    def artifact_type(self) -> str:
        return self.request.artifact_type or METHOD_ARTIFACT_TYPES[self.request.method]

    @property
    def signed_model_card(self) -> dict[str, Any]:
        return self.posttraining_run.model_card


def launch_sft_job(request: TrainingJobRequest) -> TrainingJobResult:
    return launch_mesh_brain_training_job(_request_with_method(request, "sft"))


def launch_lora_job(request: TrainingJobRequest, *, qlora: bool = False) -> TrainingJobResult:
    return launch_mesh_brain_training_job(_request_with_method(request, "qlora" if qlora else "lora"))


def launch_preference_job(request: TrainingJobRequest, *, method: str = "dpo") -> TrainingJobResult:
    if method not in {"dpo", "ipo", "kto"}:
        raise ValueError(f"unsupported preference method: {method}")
    return launch_mesh_brain_training_job(_request_with_method(request, method))


def launch_rl_rollout_job(request: TrainingJobRequest) -> TrainingJobResult:
    return launch_mesh_brain_training_job(_request_with_method(request, "agent_rl"))


def launch_quantization_job(request: TrainingJobRequest, *, qat: bool = False) -> TrainingJobResult:
    return launch_mesh_brain_training_job(_request_with_method(request, "qat" if qat else "quantization"))


def launch_mesh_brain_training_job(request: TrainingJobRequest) -> TrainingJobResult:
    request.validate()
    artifact_type = request.artifact_type or METHOD_ARTIFACT_TYPES[request.method]
    spec = TrainingJobSpec(
        method="qat" if request.method == "quantization" else request.method,
        tenant_id=request.tenant_id,
        task_type=request.task_type,
        dataset_bundle=request.dataset_bundle,
        code_version=request.code_version,
        artifact_type=artifact_type,
        base_artifact_id=request.base_artifact_id,
        hyperparameters={
            **_default_hyperparameters(request.method),
            **dict(request.hyperparameters),
            "hardware_tier": request.hardware_tier,
        },
    )
    posttraining_run = plan_posttraining_run(spec=spec, previous_artifact_id=request.base_artifact_id)
    job_core = {
        "method": request.method,
        "dataset_version": request.dataset_bundle.dataset_version,
        "code_version": request.code_version,
        "base_artifact_id": request.base_artifact_id,
        "artifact_id": posttraining_run.artifact.artifact_id,
    }
    digest = stable_digest(job_core)
    outputs = _build_outputs(request=request, artifact_id=posttraining_run.artifact.artifact_id, digest=digest)
    deployment_manifest = build_deployment_manifest(request=request, run=posttraining_run, outputs=outputs)
    return TrainingJobResult(
        job_id=f"mb_job_{digest[:12]}",
        request=request,
        posttraining_run=posttraining_run,
        status="completed",
        metrics=_estimate_metrics(request),
        outputs=outputs,
        deployment_manifest=deployment_manifest,
        created_at=utc_now(),
    )


def write_training_job_result(*, result: TrainingJobResult, output_directory: str | Path | None = None) -> dict[str, str]:
    output_path = Path(output_directory or result.request.output_directory or ".")
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "training_job.json": result.to_dict(),
        "model_card.json": result.signed_model_card,
        "deployment_manifest.json": result.deployment_manifest,
        "metrics.json": result.metrics,
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(_json(payload), encoding="utf-8")
        written[name] = str(path)
    return written


def build_training_jobs_e2e(*, dataset_bundle: DatasetBundle, output_directory: str | Path) -> dict[str, TrainingJobResult]:
    base = TrainingJobRequest(
        method="sft",
        tenant_id="tenant_a",
        task_type="crops",
        dataset_bundle=dataset_bundle,
        code_version="mesh-brain-training-jobs-reference",
        base_artifact_id="qwen-27b-base",
        output_directory=str(output_directory),
    )
    jobs = {
        "sft": launch_sft_job(base),
        "qlora": launch_lora_job(base, qlora=True),
        "dpo": launch_preference_job(base, method="dpo"),
        "agent_rl": launch_rl_rollout_job(base),
        "qat": launch_quantization_job(base, qat=True),
    }
    for name, result in jobs.items():
        write_training_job_result(result=result, output_directory=Path(output_directory) / name)
    return jobs


def build_deployment_manifest(
    *,
    request: TrainingJobRequest,
    run: PosttrainingRun,
    outputs: list[TrainingJobOutput],
) -> dict[str, Any]:
    return {
        "deployment_manifest_id": f"deploy_{stable_digest({'artifact_id': run.artifact.artifact_id, 'outputs': [output.digest for output in outputs]})[:12]}",
        "artifact_id": run.artifact.artifact_id,
        "artifact_type": run.artifact.artifact_type,
        "base_artifact_id": request.base_artifact_id,
        "tenant_id": request.tenant_id,
        "task_type": request.task_type,
        "hardware_tier": request.hardware_tier,
        "dataset_versions": [request.dataset_bundle.dataset_version],
        "code_version": request.code_version,
        "training_run_id": run.training_manifest.training_run_id,
        "signed_manifest_ref": run.training_manifest.signed_manifest_ref,
        "model_card_ref": f"model_card:{run.artifact.artifact_id}",
        "rollback_manifest": run.rollback_manifest.to_dict(),
        "outputs": [output.to_dict() for output in outputs],
        "release_gate_required": True,
    }


def _request_with_method(request: TrainingJobRequest, method: str) -> TrainingJobRequest:
    return TrainingJobRequest(
        method=method,
        tenant_id=request.tenant_id,
        task_type=request.task_type,
        dataset_bundle=request.dataset_bundle,
        code_version=request.code_version,
        base_artifact_id=request.base_artifact_id,
        hyperparameters=dict(request.hyperparameters),
        hardware_tier=request.hardware_tier,
        output_directory=request.output_directory,
        artifact_type=request.artifact_type,
    )


def _build_outputs(*, request: TrainingJobRequest, artifact_id: str, digest: str) -> list[TrainingJobOutput]:
    output_names = ["adapter_weights", "optimizer_state", "training_trace"]
    if request.method in {"quantization", "qat"}:
        output_names = ["quantized_checkpoint", "calibration_report", "deployment_trace"]
    if request.method == "agent_rl":
        output_names = ["policy_adapter", "rollout_buffer", "reward_report"]
    return [
        TrainingJobOutput(
            name=name,
            artifact_ref=f"{artifact_id}/{name}",
            digest=f"sha256:{stable_digest({'job_digest': digest, 'name': name})}",
            metadata={"method": request.method, "dataset_version": request.dataset_bundle.dataset_version},
        )
        for name in output_names
    ]


def _estimate_metrics(request: TrainingJobRequest) -> dict[str, float]:
    trainable_rows = [row for row in request.dataset_bundle.rows if not row.excluded_from_training]
    matching_rows = [row for row in trainable_rows if row.row_type in METHOD_ROW_TYPES[request.method]]
    row_count = max(1, len(matching_rows))
    token_count = sum(len(str(row.payload).split()) for row in matching_rows)
    base = {
        "trainable_rows": float(len(trainable_rows)),
        "method_rows": float(row_count),
        "tokens_seen": float(token_count),
        "loss": round(1.0 / (1.0 + row_count), 6),
    }
    if request.method in {"dpo", "ipo", "kto"}:
        base["preference_accuracy"] = round(min(0.99, 0.70 + row_count / 100.0), 6)
    if request.method == "agent_rl":
        base["rollout_success_rate"] = round(min(0.99, 0.65 + row_count / 100.0), 6)
        base["unsafe_action_rate"] = 0.0
    if request.method in {"quantization", "qat"}:
        base["compression_ratio"] = float(request.hyperparameters.get("compression_ratio", 0.5))
        base["estimated_quality_delta"] = -0.01 if request.method == "qat" else -0.03
    return base


def _default_hyperparameters(method: str) -> dict[str, Any]:
    if method == "sft":
        return {"epochs": 2, "learning_rate": 0.0002}
    if method in {"lora", "qlora"}:
        return {"rank": 16, "learning_rate": 0.0002, "quantized_base": method == "qlora"}
    if method in {"dpo", "ipo", "kto"}:
        return {"beta": 0.1, "learning_rate": 0.00005}
    if method == "agent_rl":
        return {"rollout_batch_size": 16, "reward_model": "mesh-brain-policy-reward"}
    if method in {"quantization", "qat"}:
        return {"target_precision": "int4", "calibration_batches": 8}
    return {}


def _json(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
