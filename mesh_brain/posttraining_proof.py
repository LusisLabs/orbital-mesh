from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .data_plane import build_data_plane_e2e
from .model_management import MeshBrainModelCatalog
from .runtime import stable_digest, utc_now
from .training_jobs import TrainingJobRequest, launch_mesh_brain_training_job, write_training_job_result


@dataclass(frozen=True)
class TrainingBackendRequest:
    job_id: str
    method: str
    dataset_manifest_path: str
    output_directory: str
    command: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingBackendResult:
    backend_name: str
    status: str
    return_code: int
    started_at: str
    completed_at: str
    logs: dict[str, str]
    metrics: dict[str, float]
    output_manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MeshBrainTrainingBackend(Protocol):
    backend_name: str

    def run(self, request: TrainingBackendRequest) -> TrainingBackendResult: ...


class DeterministicTrainingBackend:
    backend_name = "deterministic_training_backend"

    def run(self, request: TrainingBackendRequest) -> TrainingBackendResult:
        output_path = Path(request.output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        adapter_path = output_path / "adapter.bin"
        log_path = output_path / "training.log"
        metrics_path = output_path / "backend_metrics.json"
        adapter_payload = {
            "job_id": request.job_id,
            "method": request.method,
            "dataset_manifest_path": request.dataset_manifest_path,
        }
        adapter_path.write_text(json.dumps(adapter_payload, sort_keys=True) + "\n", encoding="utf-8")
        log_path.write_text("deterministic training backend completed\n", encoding="utf-8")
        metrics = {"loss": 0.42, "train_steps": 1.0, "wall_time_seconds": 0.0}
        metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        completed_at = utc_now()
        return TrainingBackendResult(
            backend_name=self.backend_name,
            status="completed",
            return_code=0,
            started_at=completed_at,
            completed_at=completed_at,
            logs={"stdout": str(log_path), "stderr": ""},
            metrics=metrics,
            output_manifest={
                "outputs": [{"name": "adapter_weights", "path": str(adapter_path), "sha256": stable_digest(adapter_payload)}],
                "metrics_path": str(metrics_path),
            },
        )


class LocalSubprocessTrainingBackend:
    backend_name = "local_subprocess_training_backend"

    def run(self, request: TrainingBackendRequest) -> TrainingBackendResult:
        if not request.command:
            raise ValueError("local subprocess training backend requires command")
        output_path = Path(request.output_directory)
        output_path.mkdir(parents=True, exist_ok=True)
        started_at = utc_now()
        stdout_path = output_path / "stdout.log"
        stderr_path = output_path / "stderr.log"
        try:
            completed = subprocess.run(
                request.command,
                cwd=output_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=request.timeout_seconds,
            )
            return_code = int(completed.returncode)
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            return_code = 124
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
            stderr = f"{stderr}\ntraining command timed out after {request.timeout_seconds}s".strip()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        status = "completed" if return_code == 0 else "failed"
        output_manifest = _discover_backend_outputs(output_path)
        metrics = {
            "return_code": float(return_code),
            "output_count": float(len(output_manifest["outputs"])),
        }
        return TrainingBackendResult(
            backend_name=self.backend_name,
            status=status,
            return_code=return_code,
            started_at=started_at,
            completed_at=utc_now(),
            logs={"stdout": str(stdout_path), "stderr": str(stderr_path)},
            metrics=metrics,
            output_manifest=output_manifest,
        )


@dataclass(frozen=True)
class PosttrainingProofResult:
    proof_id: str
    status: str
    tenant_id: str
    method: str
    training_job: dict[str, Any]
    backend_result: dict[str, Any]
    registered_artifact: dict[str, Any] | None
    deployment_record: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_posttraining_proof(
    *,
    output_directory: str | Path,
    tenant_id: str = "tenant_a",
    method: str = "sft",
    backend: MeshBrainTrainingBackend | None = None,
    command: list[str] | None = None,
    timeout_seconds: float = 30.0,
) -> PosttrainingProofResult:
    output_path = Path(output_directory)
    data_path = output_path / "data"
    job_path = output_path / "training_job"
    backend_path = output_path / "backend"
    output_path.mkdir(parents=True, exist_ok=True)
    data_result = build_data_plane_e2e(tenant_id=tenant_id, output_directory=data_path)
    request = TrainingJobRequest(
        method=method,
        tenant_id=tenant_id,
        task_type="crops",
        dataset_bundle=data_result.bundle,
        code_version="mesh-brain-posttraining-proof",
        base_artifact_id="qwen-27b-base",
        hardware_tier="local_cpu",
        output_directory=str(job_path),
    )
    training_job = launch_mesh_brain_training_job(request)
    training_paths = write_training_job_result(result=training_job, output_directory=job_path)
    backend_request = TrainingBackendRequest(
        job_id=training_job.job_id,
        method=method,
        dataset_manifest_path=data_result.report.output_files["dataset_manifest.json"],
        output_directory=str(backend_path),
        command=list(command or []),
        timeout_seconds=timeout_seconds,
    )
    backend_result = (backend or DeterministicTrainingBackend()).run(backend_request)
    registered_artifact = None
    if backend_result.status == "completed":
        catalog = MeshBrainModelCatalog()
        registered = catalog.register_artifact(training_job.posttraining_run.artifact)
        registered.metadata.update(
            {
                "posttraining_proof_backend": backend_result.backend_name,
                "posttraining_proof_outputs": backend_result.output_manifest.get("outputs", []),
                "eval_required_before_deployment": True,
            }
        )
        registered_artifact = registered.to_dict()
    deployment_record = {
        "status": "eval_required" if registered_artifact is not None else "blocked",
        "deployed": False,
        "release_decision": "manual_review" if registered_artifact is not None else "block",
        "registered_artifact_id": registered_artifact["artifact_id"] if registered_artifact else None,
        "eval_required_before_deployment": True,
        "backend_status": backend_result.status,
        "backend_name": backend_result.backend_name,
    }
    artifact_paths = _write_posttraining_proof_artifacts(
        output_path=output_path,
        data_paths=data_result.report.output_files,
        training_paths=training_paths,
        backend_result=backend_result,
        registered_artifact=registered_artifact,
        deployment_record=deployment_record,
    )
    proof_id = f"mesh_brain_posttraining_proof_{stable_digest({'job_id': training_job.job_id, 'backend': backend_result.to_dict()})[:12]}"
    return PosttrainingProofResult(
        proof_id=proof_id,
        status="completed" if registered_artifact is not None else "blocked",
        tenant_id=tenant_id,
        method=method,
        training_job=training_job.to_dict(),
        backend_result=backend_result.to_dict(),
        registered_artifact=registered_artifact,
        deployment_record=deployment_record,
        artifact_paths=artifact_paths,
    )


def _write_posttraining_proof_artifacts(
    *,
    output_path: Path,
    data_paths: dict[str, str],
    training_paths: dict[str, str],
    backend_result: TrainingBackendResult,
    registered_artifact: dict[str, Any] | None,
    deployment_record: dict[str, Any],
) -> dict[str, str]:
    artifacts = {
        "posttraining_backend_result.json": backend_result.to_dict(),
        "registered_artifact.json": registered_artifact or {},
        "posttraining_deployment_record.json": deployment_record,
    }
    paths = {
        "dataset_manifest": data_paths["dataset_manifest.json"],
        "training_job": training_paths["training_job.json"],
        "training_metrics": training_paths["metrics.json"],
    }
    for name, payload in artifacts.items():
        path = output_path / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        paths[name.removesuffix(".json")] = str(path)
    return paths


def _discover_backend_outputs(output_path: Path) -> dict[str, Any]:
    outputs = []
    for path in sorted(output_path.iterdir()):
        if path.is_file() and path.name not in {"stdout.log", "stderr.log"}:
            outputs.append({"name": path.name, "path": str(path), "sha256": stable_digest(path.read_text(encoding="utf-8", errors="replace"))})
    return {"outputs": outputs}
