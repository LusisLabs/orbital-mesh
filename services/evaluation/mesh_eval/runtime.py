"""Runtime helpers for native Mesh evaluation."""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import asdict, is_dataclass
from typing import Any

from shared.mesh_runtime import Decision, Trigger
from shared.mesh_runtime.phoenix_trace import build_phoenix_spans

from services.evaluation.evaluation_stack import build_evaluation_stack
from services.evaluation.mesh_evaluator import evaluate_trajectory

from .config import MeshEvalConfig

_LOG = logging.getLogger("mesh.evaluation.mesh_eval")


def mesh_eval_artifact(config: MeshEvalConfig | None = None) -> dict[str, Any]:
    return (config or MeshEvalConfig.from_env()).to_artifact()


def evaluate_native_mesh(
    *,
    trigger: Trigger | dict[str, Any] | None,
    decision: Decision | dict[str, Any] | None,
    evaluation: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    feedback: dict[str, Any] | None = None,
    run_events: list[Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    config: MeshEvalConfig | None = None,
) -> dict[str, Any]:
    mesh_eval_config = config or MeshEvalConfig.from_env()
    artifact_payload = dict(artifacts or {})
    artifact_payload["mesh_eval"] = mesh_eval_artifact_with_probe(
        config=mesh_eval_config,
        trigger=trigger,
        decision=decision,
    )
    result = evaluate_trajectory(
        trigger=trigger,
        decision=decision,
        evaluation=evaluation,
        execution=execution,
        feedback=feedback,
        run_events=run_events,
        artifacts=artifact_payload,
    )
    phoenix_spans = build_phoenix_spans(result["task_trace"])
    result["phoenix_spans"] = phoenix_spans
    result["evaluation_stack"] = build_evaluation_stack(
        requested_lanes=mesh_eval_config.integration_lanes,
        trace=result["task_trace"],
        stage_results={
            "trajectory_quality": result["trajectory_score"],
            "verifier_output": result["verifier_output"],
        },
        phoenix_spans=phoenix_spans,
    )
    return result


def mesh_eval_artifact_with_probe(
    *,
    config: MeshEvalConfig,
    trigger: Trigger | dict[str, Any] | None,
    decision: Decision | dict[str, Any] | None,
) -> dict[str, Any]:
    artifact = config.to_artifact()
    artifact["latent_mesh"]["tokenizer_probe"] = run_latentmas_tokenizer_probe(
        config=config,
        text=_probe_text(trigger, decision),
    )
    return artifact


def run_latentmas_tokenizer_probe(*, config: MeshEvalConfig, text: str) -> dict[str, Any]:
    if not config.latentmas_command:
        return {
            "status": "not_configured",
            "notes": ["set MESH_EVAL_LATENTMAS_COMMAND to enable Rust tokenizer probes"],
        }
    command = [
        *shlex.split(config.latentmas_command),
        *config.latentmas_args(),
        "--tokenize-text",
        text,
        "--tokenize-keep",
        "tail",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.latentmas_timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _LOG.warning("LatentMAS tokenizer probe failed: %s", exc)
        return {
            "status": "error",
            "notes": [str(exc)],
        }
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "LatentMAS tokenizer probe exited non-zero"
        return {
            "status": "error",
            "returncode": completed.returncode,
            "notes": [stderr],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "notes": [f"LatentMAS tokenizer probe returned invalid JSON: {exc}"],
        }
    payload["status"] = "ok"
    return payload


def _probe_text(trigger: Trigger | dict[str, Any] | None, decision: Decision | dict[str, Any] | None) -> str:
    trigger_payload = _model_to_dict(trigger)
    decision_payload = _model_to_dict(decision)
    parts = [
        str(trigger_payload.get("trigger_type") or ""),
        str(trigger_payload.get("service") or ""),
        str(trigger_payload.get("endpoint") or ""),
        str(decision_payload.get("summary") or ""),
    ]
    return " ".join(part for part in parts if part).strip()


def _model_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {}
