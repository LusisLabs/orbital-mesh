from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .adapter_runtime import AdapterRuntimeRequest, DeterministicAdapterRuntime
from .data_plane import build_context_training_data_plane
from .eval_jobs import EvalJobRequest, run_eval_job, write_eval_job_result
from .hardware_profiles import build_mlx_lm_lora_export_manifest, write_adapter_export_manifest
from .model_management import MeshBrainModelCatalog
from .runtime import ModelArtifact, ReleaseGatePolicy, stable_digest, utc_now
from .serving import MeshBrainServingFabric, OpenAIChatRequest, ServingPool, TenantQuota
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
            env = os.environ.copy()
            repo_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else repo_root
            completed = subprocess.run(
                request.command,
                cwd=output_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=request.timeout_seconds,
                env=env,
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
        metrics_path = output_manifest.get("metrics_path")
        metrics = {
            "return_code": float(return_code),
            "output_count": float(len(output_manifest["outputs"])),
        }
        if isinstance(metrics_path, str) and Path(metrics_path).exists():
            metrics.update(_read_float_metrics(Path(metrics_path)))
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
    adapter_export: dict[str, Any] | None
    eval_job: dict[str, Any] | None
    serving_smoke: dict[str, Any] | None
    deployment_record: dict[str, Any]
    dataset_context_summary: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_posttraining_proof(
    *,
    output_directory: str | Path,
    tenant_id: str = "tenant_a",
    method: str = "lora",
    backend: MeshBrainTrainingBackend | None = None,
    command: list[str] | None = None,
    timeout_seconds: float = 30.0,
    corpus_rows: list[dict[str, Any]] | None = None,
    runtime_sessions: list[dict[str, Any]] | None = None,
    runtime_events: list[dict[str, Any]] | None = None,
) -> PosttrainingProofResult:
    output_path = Path(output_directory).resolve()
    data_path = output_path / "data"
    job_path = output_path / "training_job"
    backend_path = output_path / "backend"
    output_path.mkdir(parents=True, exist_ok=True)
    data_result, context_summary = build_context_training_data_plane(
        tenant_id=tenant_id,
        output_directory=data_path,
        corpus_rows=corpus_rows,
        runtime_sessions=runtime_sessions,
        runtime_events=runtime_events,
    )
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
        metadata={"dataset_context_summary": context_summary.to_dict()},
    )
    if backend is None and not command:
        command = _tiny_lora_sft_command(backend_request)
        backend_request = TrainingBackendRequest(
            job_id=backend_request.job_id,
            method=backend_request.method,
            dataset_manifest_path=backend_request.dataset_manifest_path,
            output_directory=backend_request.output_directory,
            command=command,
            timeout_seconds=backend_request.timeout_seconds,
            metadata=backend_request.metadata,
        )
    backend_result = (backend or LocalSubprocessTrainingBackend()).run(backend_request)
    registered_artifact = None
    adapter_export = None
    adapter_export_paths: dict[str, str] = {}
    eval_job = None
    eval_paths: dict[str, str] = {}
    serving_smoke = None
    serving_path = None
    if backend_result.status == "completed":
        catalog = MeshBrainModelCatalog()
        registered = catalog.register_artifact(training_job.posttraining_run.artifact)
        registered.metadata.update(
            {
                "posttraining_proof_backend": backend_result.backend_name,
                "posttraining_proof_outputs": backend_result.output_manifest.get("outputs", []),
                "dataset_context_summary": context_summary.to_dict(),
                "training_command": list(backend_request.command),
            }
        )
        adapter_files = _adapter_output_files(backend_result)
        if adapter_files:
            export_manifest = build_mlx_lm_lora_export_manifest(
                source_artifact=registered,
                base_model_id=registered.base_artifact_id or "qwen-27b-base",
                adapter_files=adapter_files,
            )
            adapter_export = export_manifest.to_dict()
            adapter_export_paths = write_adapter_export_manifest(
                manifest=export_manifest,
                output_directory=output_path / "adapter_exports" / "mlx_lm_lora",
            )
            registered.metadata["adapter_exports"] = [adapter_export]
        eval_job_result = run_eval_job(
            EvalJobRequest(
                candidate_artifact=registered,
                dataset_bundle=data_result.bundle,
                hardware_tiers=["cpu_edge"],
                policy=ReleaseGatePolicy(task_success_threshold=0.8, latency_p95_budget_ms=1000, cost_per_completed_task_budget=0.1),
                required_backend_techniques=[],
                output_directory=str(output_path / "eval_job"),
            )
        )
        eval_paths = write_eval_job_result(result=eval_job_result, output_directory=output_path / "eval_job")
        registered.eval_report_id = eval_job_result.eval_job_id
        registered_artifact = registered.to_dict()
        eval_job = eval_job_result.to_dict()
        if eval_job_result.release_decision in {"canary", "promote"}:
            serving_smoke = _run_serving_smoke(registered, tenant_id=tenant_id)
            serving_path = output_path / "serving_smoke.json"
            serving_path.write_text(json.dumps(serving_smoke, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    release_decision = eval_job["release_decision"] if eval_job else "block"
    deployment_record = {
        "status": _deployment_status(release_decision, serving_smoke),
        "deployed": False,
        "release_decision": release_decision,
        "registered_artifact_id": registered_artifact["artifact_id"] if registered_artifact else None,
        "adapter_export_id": adapter_export["export_id"] if adapter_export else None,
        "eval_job_id": eval_job["eval_job_id"] if eval_job else None,
        "serving_smoke_status": serving_smoke["status"] if serving_smoke else None,
        "backend_status": backend_result.status,
        "backend_name": backend_result.backend_name,
    }
    artifact_paths = _write_posttraining_proof_artifacts(
        output_path=output_path,
        data_paths=data_result.report.output_files,
        training_paths=training_paths,
        backend_result=backend_result,
        registered_artifact=registered_artifact,
        adapter_export=adapter_export,
        eval_job=eval_job,
        serving_smoke=serving_smoke,
        deployment_record=deployment_record,
        eval_paths=eval_paths,
        adapter_export_paths=adapter_export_paths,
        serving_path=serving_path,
    )
    proof_id = f"mesh_brain_real_training_proof_{stable_digest({'job_id': training_job.job_id, 'backend': backend_result.to_dict(), 'eval': eval_job})[:12]}"
    return PosttrainingProofResult(
        proof_id=proof_id,
        status="completed" if deployment_record["status"] == "smoke_served" else "blocked",
        tenant_id=tenant_id,
        method=method,
        training_job=training_job.to_dict(),
        backend_result=backend_result.to_dict(),
        registered_artifact=registered_artifact,
        adapter_export=adapter_export,
        eval_job=eval_job,
        serving_smoke=serving_smoke,
        deployment_record=deployment_record,
        dataset_context_summary=context_summary.to_dict(),
        artifact_paths=artifact_paths,
    )


def _write_posttraining_proof_artifacts(
    *,
    output_path: Path,
    data_paths: dict[str, str],
    training_paths: dict[str, str],
    backend_result: TrainingBackendResult,
    registered_artifact: dict[str, Any] | None,
    adapter_export: dict[str, Any] | None,
    eval_job: dict[str, Any] | None,
    serving_smoke: dict[str, Any] | None,
    deployment_record: dict[str, Any],
    eval_paths: dict[str, str],
    adapter_export_paths: dict[str, str],
    serving_path: Path | None,
) -> dict[str, str]:
    artifacts = {
        "posttraining_backend_result.json": backend_result.to_dict(),
        "registered_artifact.json": registered_artifact or {},
        "posttraining_adapter_export.json": adapter_export or {},
        "posttraining_eval_job.json": eval_job or {},
        "posttraining_serving_smoke.json": serving_smoke or {},
        "posttraining_deployment_record.json": deployment_record,
    }
    paths = {
        "dataset_manifest": data_paths["dataset_manifest.json"],
        "training_job": training_paths["training_job.json"],
        "training_metrics": training_paths["metrics.json"],
    }
    if "eval_job.json" in eval_paths:
        paths["posttraining_eval_job"] = eval_paths["eval_job.json"]
    if "adapter_export_manifest.json" in adapter_export_paths:
        paths["posttraining_adapter_export_manifest"] = adapter_export_paths["adapter_export_manifest.json"]
    if serving_path is not None:
        paths["posttraining_serving_smoke"] = str(serving_path)
    for name, payload in artifacts.items():
        path = output_path / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        paths[name.removesuffix(".json")] = str(path)
    return paths


def _adapter_output_files(backend_result: TrainingBackendResult) -> list[dict[str, Any]]:
    outputs = backend_result.output_manifest.get("outputs", [])
    if not isinstance(outputs, list):
        return []
    return [
        output
        for output in outputs
        if isinstance(output, dict) and str(output.get("path") or "").strip()
    ]


def _discover_backend_outputs(output_path: Path) -> dict[str, Any]:
    outputs = []
    for path in sorted(output_path.iterdir()):
        if path.is_file() and path.name not in {"stdout.log", "stderr.log"}:
            outputs.append({"name": path.name, "path": str(path), "sha256": stable_digest(path.read_text(encoding="utf-8", errors="replace"))})
    manifest_path = output_path / "tiny_lora_sft_manifest.json"
    metrics_path = output_path / "backend_metrics.json"
    manifest: dict[str, Any] = {"outputs": outputs}
    if manifest_path.exists():
        manifest.update(json.loads(manifest_path.read_text(encoding="utf-8")))
    if metrics_path.exists():
        manifest["metrics_path"] = str(metrics_path)
    return manifest


def _tiny_lora_sft_command(request: TrainingBackendRequest) -> list[str]:
    return [
        sys.executable,
        "-m",
        "mesh_brain.local_lora_sft",
        "--dataset-manifest",
        request.dataset_manifest_path,
        "--output-dir",
        request.output_directory,
        "--job-id",
        request.job_id,
        "--method",
        request.method,
    ]


def _read_float_metrics(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)):
            metrics[str(key)] = float(value)
    return metrics


def _run_serving_smoke(artifact: ModelArtifact, *, tenant_id: str) -> dict[str, Any]:
    serving_artifact = ModelArtifact.from_dict({**artifact.to_dict(), "state": "production"})
    fabric = MeshBrainServingFabric(
        pools=[ServingPool(pool_id="local-cpu-proof", hardware_tier="cpu_edge", backend_name="llama.cpp")],
        artifacts=[serving_artifact],
        quotas={tenant_id: TenantQuota(tenant_id=tenant_id, max_requests_per_minute=5, max_tokens_per_minute=5000)},
    )
    execution = fabric.execute_chat_completion(
        OpenAIChatRequest(
            tenant_id=tenant_id,
            messages=[{"role": "user", "content": "Summarize the safe remediation boundary for search latency."}],
            task_type="crops",
            hardware_tier="cpu_edge",
            risk_level="high",
            model="mesh-brain-posttraining-proof",
            metadata={"served_model": artifact.artifact_id},
        ),
        client=_AdapterRuntimeClient(
            AdapterRuntimeRequest(
                adapter_artifact=artifact,
                base_model_id=artifact.base_artifact_id or "qwen-27b-base",
                serving_backend="llama.cpp",
            )
        ),
    )
    payload = execution.to_dict()
    adapter_runtime = payload["completion"]["raw_response"]["adapter_runtime"]
    return {
        "status": "passed" if payload["completion"].get("content") and adapter_runtime["status"] == "ready" else "failed",
        "artifact_id": artifact.artifact_id,
        "adapter_runtime": adapter_runtime,
        "execution": payload,
    }


def _deployment_status(release_decision: str, serving_smoke: dict[str, Any] | None) -> str:
    if release_decision == "block":
        return "blocked"
    if serving_smoke and serving_smoke.get("status") == "passed":
        return "smoke_served"
    return "eval_passed"


class _AdapterRuntimeClient:
    def __init__(self, request: AdapterRuntimeRequest) -> None:
        self._request = request
        self._runtime = DeterministicAdapterRuntime()

    def complete_chat(self, *, plan: Any, request: OpenAIChatRequest) -> Any:
        return self._runtime.infer(request=self._request, plan=plan, chat_request=request)
