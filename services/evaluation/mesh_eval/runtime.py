"""Runtime helpers for native Mesh evaluation."""

from __future__ import annotations

from typing import Any

from shared.mesh_runtime import Decision, Trigger

from services.evaluation.mesh_evaluator import evaluate_trajectory

from .config import MeshEvalConfig


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
    artifact_payload["mesh_eval"] = mesh_eval_config.to_artifact()
    return evaluate_trajectory(
        trigger=trigger,
        decision=decision,
        evaluation=evaluation,
        execution=execution,
        feedback=feedback,
        run_events=run_events,
        artifacts=artifact_payload,
    )
