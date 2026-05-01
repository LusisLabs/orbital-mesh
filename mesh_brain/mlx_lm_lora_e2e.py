from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

from .data_plane import build_context_training_data_plane
from .hardware_profiles import build_mlx_lm_lora_export_manifest, write_adapter_export_manifest
from .run_live_serving_smoke import LiveResponseEvalPolicy, evaluate_live_response
from .runtime import new_model_artifact, stable_digest, utc_now


DEFAULT_MODEL_ID = "mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16"
DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state/mesh-brain/mlx-lm-lora-nemotron")
DEFAULT_LM_STUDIO_IDENTIFIER = "mesh-brain-nemotron-3-nano-4b"


@dataclass(frozen=True)
class MlxLmLoraCommandResult:
    command: list[str]
    status: str
    return_code: int
    stdout_path: str
    stderr_path: str
    started_at: str
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MlxLmLoraE2EResult:
    run_id: str
    status: str
    model_id: str
    output_directory: str
    dataset_directory: str
    adapter_directory: str
    lm_studio_identifier: str
    train: MlxLmLoraCommandResult | None
    native_inference: MlxLmLoraCommandResult | None
    fuse: MlxLmLoraCommandResult | None
    lm_studio_server: MlxLmLoraCommandResult | None
    lm_studio_load: MlxLmLoraCommandResult | None
    native_openai_probe: dict[str, Any] | None
    native_response_eval: dict[str, Any] | None
    openai_probe: dict[str, Any] | None
    backend_compatibility: dict[str, Any]
    adapter_export: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "model_id": self.model_id,
            "output_directory": self.output_directory,
            "dataset_directory": self.dataset_directory,
            "adapter_directory": self.adapter_directory,
            "lm_studio_identifier": self.lm_studio_identifier,
            "train": self.train.to_dict() if self.train else None,
            "native_inference": self.native_inference.to_dict() if self.native_inference else None,
            "fuse": self.fuse.to_dict() if self.fuse else None,
            "lm_studio_server": self.lm_studio_server.to_dict() if self.lm_studio_server else None,
            "lm_studio_load": self.lm_studio_load.to_dict() if self.lm_studio_load else None,
            "native_openai_probe": self.native_openai_probe,
            "native_response_eval": self.native_response_eval,
            "openai_probe": self.openai_probe,
            "backend_compatibility": self.backend_compatibility,
            "adapter_export": self.adapter_export,
            "artifact_paths": dict(self.artifact_paths),
        }


def run_mlx_lm_lora_e2e(
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    model_id: str = DEFAULT_MODEL_ID,
    tenant_id: str = "tenant_a",
    iters: int = 1,
    max_seq_length: int = 512,
    num_layers: int = 2,
    timeout_seconds: float = 1800.0,
    train: bool = True,
    native_inference: bool = True,
    fuse: bool = False,
    lm_studio: bool = False,
    lm_studio_identifier: str = DEFAULT_LM_STUDIO_IDENTIFIER,
    lm_studio_port: int = 1234,
    native_server_base_url: str | None = None,
    native_server_model: str | None = None,
) -> MlxLmLoraE2EResult:
    output_path = Path(output_directory).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    raw_data_path = output_path / "mesh_data_plane"
    mlx_data_path = output_path / "mlx_sft_data"
    adapter_path = output_path / "adapter"
    logs_path = output_path / "logs"
    logs_path.mkdir(parents=True, exist_ok=True)
    adapter_path.mkdir(parents=True, exist_ok=True)

    data_result, context_summary = build_context_training_data_plane(
        tenant_id=tenant_id,
        output_directory=raw_data_path,
    )
    data_paths = prepare_mlx_lm_lora_sft_data(
        mesh_sft_path=Path(data_result.report.output_files["sft.jsonl"]),
        output_directory=mlx_data_path,
    )

    command_plan = {
        "model_id": model_id,
        "train": _train_command(
            model_id=model_id,
            data_directory=mlx_data_path,
            adapter_directory=adapter_path,
            iters=iters,
            max_seq_length=max_seq_length,
            num_layers=num_layers,
            fuse=fuse,
            lm_studio_identifier=lm_studio_identifier if lm_studio else None,
        ),
        "native_inference": _native_inference_command(
            model_id=model_id,
            adapter_directory=adapter_path,
            prompt="Summarize the safe Mesh remediation boundary for search latency.",
        ),
        "fuse": _fuse_command(
            model_id=model_id,
            adapter_directory=adapter_path,
            lm_studio_identifier=lm_studio_identifier if lm_studio else None,
        ),
        "lm_studio_server": ["lms", "server", "start", "--port", str(lm_studio_port), "--bind", "127.0.0.1"],
        "lm_studio_load": ["lms", "load", lm_studio_identifier, "--identifier", lm_studio_identifier, "--gpu", "max", "-y"],
    }
    command_plan_path = output_path / "command_plan.json"
    command_plan_path.write_text(_json(command_plan), encoding="utf-8")

    train_result = None
    native_result = None
    fuse_result = None
    server_result = None
    load_result = None
    native_openai_probe = None
    native_response_eval = None
    openai_probe = None

    if train:
        train_result = _run_command(
            command_plan["train"],
            logs_path=logs_path,
            name="train",
            timeout_seconds=timeout_seconds,
        )
    if native_inference and (not train_result or train_result.status == "completed"):
        native_result = _run_command(
            command_plan["native_inference"],
            logs_path=logs_path,
            name="native_inference",
            timeout_seconds=timeout_seconds,
        )
    if fuse and train_result and train_result.status == "completed":
        fuse_result = train_result
    if lm_studio and (not fuse_result or fuse_result.status == "completed"):
        server_result = _run_command(
            command_plan["lm_studio_server"],
            logs_path=logs_path,
            name="lm_studio_server",
            timeout_seconds=60.0,
        )
        load_result = _run_command(
            command_plan["lm_studio_load"],
            logs_path=logs_path,
            name="lm_studio_load",
            timeout_seconds=300.0,
        )
        openai_probe = _probe_openai_server(
            base_url=f"http://127.0.0.1:{lm_studio_port}",
            model=lm_studio_identifier,
        )
    if native_server_base_url:
        native_openai_probe = _probe_openai_server(
            base_url=native_server_base_url,
            model=native_server_model or model_id,
        )
        native_response_eval = _evaluate_native_probe_response(native_openai_probe)

    adapter_outputs = _adapter_files(adapter_path)
    source_artifact = new_model_artifact(
        artifact_type="tenant_adapter",
        version=f"mlx-lm-lora-{stable_digest({'model': model_id, 'data': data_result.bundle.dataset_version})[:12]}",
        signed_manifest_ref=f"sha256:{stable_digest({'adapter_files': adapter_outputs, 'model': model_id})}",
        tenant_id=tenant_id,
        task_type="crops",
        base_artifact_id=model_id,
        dataset_manifest_ids=[data_result.bundle.dataset_version],
        metadata={"dataset_context_summary": context_summary.to_dict()},
    )
    adapter_export_manifest = build_mlx_lm_lora_export_manifest(
        source_artifact=source_artifact,
        base_model_id=model_id,
        adapter_files=adapter_outputs or [{"name": "pending_adapter", "path": str(adapter_path), "sha256": ""}],
    )
    adapter_export_paths = write_adapter_export_manifest(
        manifest=adapter_export_manifest,
        output_directory=output_path / "adapter_export",
    )
    backend_compatibility = _backend_compatibility(
        train_result=train_result,
        native_result=native_result,
        native_openai_probe=native_openai_probe,
        native_response_eval=native_response_eval,
        lm_studio_load=load_result,
        lm_studio_probe=openai_probe,
        train_requested=train,
        native_requested=native_inference,
        native_server_requested=bool(native_server_base_url),
        lm_studio_requested=lm_studio,
    )
    backend_compatibility_path = output_path / "backend_compatibility.json"
    backend_compatibility_path.write_text(_json(backend_compatibility), encoding="utf-8")
    native_probe_path = output_path / "native_openai_server_probe.json"
    native_probe_path.write_text(_json(native_openai_probe or {"status": "not_run"}), encoding="utf-8")
    native_response_eval_path = output_path / "native_response_eval.json"
    native_response_eval_path.write_text(_json(native_response_eval or {"decision": "not_run"}), encoding="utf-8")
    lm_studio_compatibility_path = output_path / "lm_studio_compatibility.json"
    lm_studio_compatibility_path.write_text(
        _json(
            {
                "status": backend_compatibility["lm_studio"]["status"],
                "reason": backend_compatibility["lm_studio"]["reason"],
                "load": load_result.to_dict() if load_result else None,
                "probe": openai_probe,
                "promotion_blocking": False,
            }
        ),
        encoding="utf-8",
    )

    status = _overall_status(
        train_result=train_result,
        native_result=native_result,
        fuse_result=fuse_result,
        load_result=load_result,
        openai_probe=openai_probe,
        train_requested=train,
        native_requested=native_inference,
        fuse_requested=fuse,
        lm_studio_requested=lm_studio,
    )
    result = MlxLmLoraE2EResult(
        run_id=f"mlx_lm_lora_e2e_{stable_digest({'model': model_id, 'created_at': utc_now()})[:12]}",
        status=status,
        model_id=model_id,
        output_directory=str(output_path),
        dataset_directory=str(mlx_data_path),
        adapter_directory=str(adapter_path),
        lm_studio_identifier=lm_studio_identifier,
        train=train_result,
        native_inference=native_result,
        fuse=fuse_result,
        lm_studio_server=server_result,
        lm_studio_load=load_result,
        native_openai_probe=native_openai_probe,
        native_response_eval=native_response_eval,
        openai_probe=openai_probe,
        backend_compatibility=backend_compatibility,
        adapter_export=adapter_export_manifest.to_dict(),
        artifact_paths={
            "mesh_dataset_manifest": data_result.report.output_files["dataset_manifest.json"],
            "mlx_train_jsonl": data_paths["train.jsonl"],
            "mlx_valid_jsonl": data_paths["valid.jsonl"],
            "mlx_test_jsonl": data_paths["test.jsonl"],
            "command_plan": str(command_plan_path),
            "adapter_export": adapter_export_paths["adapter_export_manifest.json"],
            "backend_compatibility": str(backend_compatibility_path),
            "native_server_probe": str(native_probe_path),
            "native_response_eval": str(native_response_eval_path),
            "lm_studio_compatibility": str(lm_studio_compatibility_path),
            "train_stdout": train_result.stdout_path if train_result else _placeholder_log(logs_path, "train.stdout.log", "train not requested"),
            "train_stderr": train_result.stderr_path if train_result else _placeholder_log(logs_path, "train.stderr.log", "train not requested"),
            "native_inference_stdout": (
                native_result.stdout_path
                if native_result
                else _placeholder_log(logs_path, "native_inference.stdout.log", "native inference not requested")
            ),
            "native_inference_stderr": (
                native_result.stderr_path
                if native_result
                else _placeholder_log(logs_path, "native_inference.stderr.log", "native inference not requested")
            ),
        },
    )
    summary_path = output_path / "run_summary.json"
    summary_path.write_text(_json(result.to_dict()), encoding="utf-8")
    result.artifact_paths["run_summary"] = str(summary_path)
    summary_path.write_text(_json(result.to_dict()), encoding="utf-8")
    return result


def prepare_mlx_lm_lora_sft_data(*, mesh_sft_path: Path, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    records = []
    for row in _read_jsonl(mesh_sft_path):
        if row.get("excluded_from_training"):
            continue
        payload = dict(row.get("payload") or {})
        context = str(payload.get("context") or "").strip()
        instruction = str(payload.get("instruction") or "Answer using Mesh policy boundaries.").strip()
        expected = str(payload.get("expected_response") or "").strip()
        prompt = f"{instruction}\n\nContext:\n{context}".strip()
        records.append(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are Mesh Brain. Preserve tenant boundaries, cite evidence, and require approval before protected actions.",
                    },
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": expected},
                ],
                "mesh_row_id": row.get("row_id"),
                "provenance_pointer": row.get("provenance_pointer"),
            }
        )
    if not records:
        raise ValueError("MLX-LM-LoRA data prep requires at least one trainable SFT row")
    splits = {
        "train.jsonl": records,
        "valid.jsonl": records[:1],
        "test.jsonl": records[:1],
    }
    written = {}
    for name, rows in splits.items():
        path = output_path / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        written[name] = str(path)
    manifest = {
        "format": "mlx_lm_lora_sft_messages.v1",
        "created_at": utc_now(),
        "source": str(mesh_sft_path),
        "counts": {name: len(rows) for name, rows in splits.items()},
    }
    manifest_path = output_path / "dataset_manifest.json"
    manifest_path.write_text(_json(manifest), encoding="utf-8")
    written["dataset_manifest.json"] = str(manifest_path)
    return written


def _train_command(
    *,
    model_id: str,
    data_directory: Path,
    adapter_directory: Path,
    iters: int,
    max_seq_length: int,
    num_layers: int,
    fuse: bool,
    lm_studio_identifier: str | None,
) -> list[str]:
    command = [
        "mlx_lm_lora.train",
        "--model",
        model_id,
        "--train",
        "--train-mode",
        "sft",
        "--train-type",
        "lora",
        "--data",
        str(data_directory),
        "--adapter-path",
        str(adapter_directory),
        "--iters",
        str(iters),
        "--batch-size",
        "1",
        "--gradient-accumulation-steps",
        "1",
        "--val-batches",
        "1",
        "--num-layers",
        str(num_layers),
        "--max-seq-length",
        str(max_seq_length),
        "--learning-rate",
        "1e-5",
        "--steps-per-report",
        "1",
        "--steps-per-eval",
        "1",
        "--save-every",
        "1",
        "--seed",
        "7",
    ]
    if fuse:
        command.append("--fuse")
        if lm_studio_identifier:
            command.extend(["--lm-studio-name", lm_studio_identifier])
    return command


def _native_inference_command(*, model_id: str, adapter_directory: Path, prompt: str) -> list[str]:
    return [
        "mlx_lm.generate",
        "--model",
        model_id,
        "--adapter-path",
        str(adapter_directory),
        "--prompt",
        prompt,
        "--max-tokens",
        "96",
        "--temp",
        "0.0",
        "--verbose",
        "False",
    ]


def _fuse_command(*, model_id: str, adapter_directory: Path, lm_studio_identifier: str | None) -> list[str]:
    command = [
        "mlx_lm_lora.train",
        "--model",
        model_id,
        "--train",
        "--train-mode",
        "sft",
        "--train-type",
        "lora",
        "--data",
        str(adapter_directory),
        "--adapter-path",
        str(adapter_directory),
        "--iters",
        "0",
        "--fuse",
    ]
    if lm_studio_identifier:
        command.extend(["--lm-studio-name", lm_studio_identifier])
    return command


def _run_command(command: list[str], *, logs_path: Path, name: str, timeout_seconds: float) -> MlxLmLoraCommandResult:
    started_at = utc_now()
    stdout_path = logs_path / f"{name}.stdout.log"
    stderr_path = logs_path / f"{name}.stderr.log"
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        stderr = f"{stderr}\ncommand timed out after {timeout_seconds}s".strip()
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return MlxLmLoraCommandResult(
        command=command,
        status="completed" if return_code == 0 else "failed",
        return_code=return_code,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        started_at=started_at,
        completed_at=utc_now(),
    )


def _placeholder_log(logs_path: Path, name: str, message: str) -> str:
    path = logs_path / name
    if not path.exists():
        path.write_text(message + "\n", encoding="utf-8")
    return str(path)


def _probe_openai_server(*, base_url: str, model: str) -> dict[str, Any]:
    request_payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return one sentence about Mesh approval boundaries."}],
        "max_tokens": 64,
        "temperature": 0,
    }
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "status": "completed" if content else "failed",
                "http_status": getattr(response, "status", 200),
                "content": content,
                "raw_response": payload,
            }
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


def _evaluate_native_probe_response(probe: dict[str, Any] | None) -> dict[str, Any]:
    if not probe or probe.get("status") != "completed":
        return {
            "decision": "block",
            "passed": False,
            "score": 0.0,
            "checks": {},
            "reasons": ["native_openai_probe_failed"],
            "text_sha256": "",
            "policy": {},
        }
    return evaluate_live_response(
        text=str(probe.get("content") or ""),
        policy=LiveResponseEvalPolicy(min_score=0.8),
    ).to_dict()


def _adapter_files(adapter_path: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(adapter_path.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "sha256": _sha256_file(path),
                }
            )
    return files


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overall_status(
    *,
    train_result: MlxLmLoraCommandResult | None,
    native_result: MlxLmLoraCommandResult | None,
    fuse_result: MlxLmLoraCommandResult | None,
    load_result: MlxLmLoraCommandResult | None,
    openai_probe: dict[str, Any] | None,
    train_requested: bool,
    native_requested: bool,
    fuse_requested: bool,
    lm_studio_requested: bool,
) -> str:
    required = []
    if train_requested:
        required.append(train_result)
    if native_requested:
        required.append(native_result)
    if fuse_requested:
        required.append(fuse_result)
    if lm_studio_requested:
        required.append(load_result)
    if any(result is None or result.status != "completed" for result in required):
        return "failed"
    if lm_studio_requested and (not openai_probe or openai_probe.get("status") != "completed"):
        return "failed"
    return "completed"


def _backend_compatibility(
    *,
    train_result: MlxLmLoraCommandResult | None,
    native_result: MlxLmLoraCommandResult | None,
    native_openai_probe: dict[str, Any] | None,
    native_response_eval: dict[str, Any] | None,
    lm_studio_load: MlxLmLoraCommandResult | None,
    lm_studio_probe: dict[str, Any] | None,
    train_requested: bool,
    native_requested: bool,
    native_server_requested: bool,
    lm_studio_requested: bool,
) -> dict[str, Any]:
    return {
        "mlx_lm_lora_train": {
            "status": _command_status(train_result, requested=train_requested),
            "reason": _command_reason(train_result, requested=train_requested),
        },
        "mlx_lm_generate": {
            "status": _command_status(native_result, requested=native_requested),
            "reason": _command_reason(native_result, requested=native_requested),
        },
        "mlx_lm_server": {
            "status": _probe_status(native_openai_probe, requested=native_server_requested),
            "reason": _probe_reason(native_openai_probe, requested=native_server_requested),
        },
        "native_response_eval": {
            "status": _response_eval_status(native_response_eval, requested=native_server_requested),
            "reason": _response_eval_reason(native_response_eval, requested=native_server_requested),
        },
        "lm_studio": {
            "status": _lm_studio_status(lm_studio_load, lm_studio_probe, requested=lm_studio_requested),
            "reason": _lm_studio_reason(lm_studio_load, lm_studio_probe, requested=lm_studio_requested),
        },
    }


def _command_status(result: MlxLmLoraCommandResult | None, *, requested: bool) -> str:
    if not requested:
        return "not_run"
    if result is None:
        return "failed"
    return "pass" if result.status == "completed" else "failed"


def _command_reason(result: MlxLmLoraCommandResult | None, *, requested: bool) -> str:
    if not requested:
        return "not requested"
    if result is None:
        return "command did not run"
    return f"return_code={result.return_code}"


def _probe_status(probe: dict[str, Any] | None, *, requested: bool) -> str:
    if not requested:
        return "not_run"
    if probe and probe.get("status") == "completed":
        return "pass"
    return "failed"


def _probe_reason(probe: dict[str, Any] | None, *, requested: bool) -> str:
    if not requested:
        return "not requested"
    if not probe:
        return "probe did not run"
    return str(probe.get("error") or probe.get("http_status") or probe.get("status"))


def _response_eval_status(eval_result: dict[str, Any] | None, *, requested: bool) -> str:
    if not requested:
        return "not_run"
    return "pass" if eval_result and eval_result.get("decision") == "pass" else "failed"


def _response_eval_reason(eval_result: dict[str, Any] | None, *, requested: bool) -> str:
    if not requested:
        return "not requested"
    if not eval_result:
        return "response eval did not run"
    reasons = eval_result.get("reasons")
    if isinstance(reasons, list) and reasons:
        return ",".join(str(reason) for reason in reasons)
    return str(eval_result.get("decision") or "unknown")


def _lm_studio_status(
    load_result: MlxLmLoraCommandResult | None,
    probe: dict[str, Any] | None,
    *,
    requested: bool,
) -> str:
    if not requested:
        return "not_run"
    if load_result and load_result.status == "completed" and probe and probe.get("status") == "completed":
        return "pass"
    return "blocked"


def _lm_studio_reason(
    load_result: MlxLmLoraCommandResult | None,
    probe: dict[str, Any] | None,
    *,
    requested: bool,
) -> str:
    if not requested:
        return "not requested"
    if load_result and load_result.status != "completed":
        return f"lms load return_code={load_result.return_code}"
    if probe and probe.get("status") != "completed":
        return str(probe.get("error") or "OpenAI-compatible probe failed")
    return "LM Studio accepted model"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mesh Brain MLX-LM-LoRA Nemotron e2e.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIRECTORY))
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--tenant-id", default="tenant_a")
    parser.add_argument("--iters", type=int, default=1)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-native-inference", action="store_true")
    parser.add_argument("--fuse", action="store_true")
    parser.add_argument("--lm-studio", action="store_true")
    parser.add_argument("--lm-studio-identifier", default=DEFAULT_LM_STUDIO_IDENTIFIER)
    parser.add_argument("--lm-studio-port", type=int, default=1234)
    parser.add_argument("--native-server-base-url")
    parser.add_argument("--native-server-model")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_mlx_lm_lora_e2e(
        output_directory=args.output,
        model_id=args.model,
        tenant_id=args.tenant_id,
        iters=args.iters,
        max_seq_length=args.max_seq_length,
        num_layers=args.num_layers,
        timeout_seconds=args.timeout_seconds,
        train=not args.skip_train,
        native_inference=not args.skip_native_inference,
        fuse=args.fuse or args.lm_studio,
        lm_studio=args.lm_studio,
        lm_studio_identifier=args.lm_studio_identifier,
        lm_studio_port=args.lm_studio_port,
        native_server_base_url=args.native_server_base_url,
        native_server_model=args.native_server_model,
    )
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        print(_json(result.to_dict()))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
