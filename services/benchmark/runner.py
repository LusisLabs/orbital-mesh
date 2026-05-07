from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.mesh_runtime.config import RuntimeConfig

from .backends import (
    BenchmarkBackend,
    CloudOpsBenchBackend,
    MeshBackend,
    MeshControlPlaneBackend,
    OpenSreCliBackend,
    SreGymBackend,
)
from .artifacts import write_compact_run_artifacts
from .models import BenchmarkScorecard, ScenarioBenchmarkResult
from .report import render_markdown_report
from .scenario_loader import load_signal, load_suite
from .scoring import aggregate_scorecard, score_outcome


@dataclass(frozen=True)
class BenchmarkRunConfig:
    suite: str = "golden"
    output_root: Path = Path(".mesh-runtime-state") / "benchmarks"
    scenario_ids: tuple[str, ...] = ()
    scenario_root: Path | None = None
    signal_fixture_root: Path | None = None
    state_directory: Path | None = None
    evaluation_mode: str = "native"
    orchestration_mode: str = "native"
    steering_mode: str = "interruptible_auto"
    agent_fabric_mode: str | None = None
    agent_tasks_mode: str = "blocking"
    agent_lanes: tuple[str, ...] = ()
    agent_task_timeout_seconds: float = 15.0
    deepagents_model: str | None = None
    deepagents_timeout_seconds: float | None = None
    deepagents_max_artifact_chars: int | None = None
    deepagents_max_output_tokens: int | None = None
    repeat: int = 1
    backend: str = "mesh"
    provider: str | None = None
    opensre_command: str = "uvx opensre"
    backend_timeout_seconds: float = 300.0
    control_plane_timeout_seconds: float = 300.0
    attempt_artifact_mode: str = "full"
    runtime_state_mode: str = "full"
    compact_artifacts: bool = False
    cloudopsbench_root: Path | None = None
    cloudopsbench_ground_truth_mode: str = "hidden"
    sregym_server_url: str = "http://localhost:8000"
    sregym_target: str = "local-kind"


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    output_dir: Path
    scorecard: BenchmarkScorecard
    results: list[ScenarioBenchmarkResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "output_dir": str(self.output_dir),
            "scorecard": self.scorecard.to_dict(),
            "results": [result.to_dict() for result in self.results],
        }


def run_benchmark(config: BenchmarkRunConfig | None = None) -> BenchmarkRun:
    config = config or BenchmarkRunConfig()
    if config.repeat <= 0:
        raise ValueError("repeat must be >= 1")
    run_id = datetime.now(timezone.utc).strftime("bench_%Y%m%dT%H%M%S%fZ")
    output_dir = config.output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_ids = set(config.scenario_ids) if config.scenario_ids else None
    scenarios = load_suite(config.suite, scenario_root=config.scenario_root, scenario_ids=scenario_ids)

    results: list[ScenarioBenchmarkResult] = []
    for iteration in range(1, config.repeat + 1):
        state_temp: tempfile.TemporaryDirectory[str] | None = None
        backend_config = config
        if _uses_runtime_state(config) and _runtime_state_mode(config.runtime_state_mode) == "none":
            state_temp = tempfile.TemporaryDirectory(prefix=f"mesh-benchmark-state-{iteration}-")
            backend_config = replace(config, state_directory=Path(state_temp.name))
        backend: BenchmarkBackend | None = None
        try:
            backend = _build_backend(backend_config, output_dir=output_dir, iteration=iteration)
            for scenario in scenarios:
                raw_signal = load_signal(scenario, fixture_root=config.signal_fixture_root)
                start = time.monotonic()
                outcome: dict[str, Any] | None = None
                error: str | None = None
                try:
                    outcome = backend.run_scenario(scenario, raw_signal, iteration=iteration)
                    if isinstance(outcome, dict) and outcome.get("error"):
                        error = str(outcome["error"])
                except Exception as exc:
                    error = str(exc)
                _write_attempt_artifact(
                    output_dir,
                    mode=config.attempt_artifact_mode,
                    iteration=iteration,
                    scenario_id=scenario.scenario_id,
                    outcome=outcome,
                    error=error,
                )
                duration_ms = (time.monotonic() - start) * 1000.0
                results.append(
                    score_outcome(
                        scenario,
                        outcome,
                        duration_ms=duration_ms,
                        iteration=iteration,
                        backend=config.provider or config.backend,
                        error=error,
                    )
                )
        finally:
            if backend is not None:
                close = getattr(backend, "close", None)
                if callable(close):
                    close()
            if state_temp is not None:
                state_temp.cleanup()

    scorecard = aggregate_scorecard(config.suite, run_id, results)
    run = BenchmarkRun(run_id=run_id, output_dir=output_dir, scorecard=scorecard, results=results)
    _write_run(output_dir, run, compact_artifacts=config.compact_artifacts)
    return run


def _write_attempt_artifact(
    output_dir: Path,
    *,
    mode: str,
    iteration: int,
    scenario_id: str,
    outcome: dict[str, Any] | None,
    error: str | None,
) -> None:
    artifact_mode = (mode or "full").strip().lower()
    if artifact_mode not in {"full", "errors", "none"}:
        artifact_mode = "full"
    if artifact_mode == "none" or (artifact_mode == "errors" and not error):
        return
    artifact_dir = output_dir / "attempt-artifacts" / f"iteration-{iteration}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = outcome if isinstance(outcome, dict) else {}
    if error:
        payload = {**payload, "error": error}
    (artifact_dir / f"{scenario_id}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _build_backend(config: BenchmarkRunConfig, *, output_dir: Path, iteration: int) -> BenchmarkBackend:
    provider = config.provider or config.backend
    if provider == "mesh":
        state_directory = _state_directory(config, output_dir=output_dir, iteration=iteration)
        runtime_config = _runtime_config(config, state_directory=state_directory)
        return MeshBackend(
            runtime_config=runtime_config,
            cloudopsbench_root=config.cloudopsbench_root,
        )
    if provider in {"mesh-control-plane", "mesh-agentic"}:
        state_directory = _state_directory(config, output_dir=output_dir, iteration=iteration)
        runtime_config = _runtime_config(config, state_directory=state_directory)
        return MeshControlPlaneBackend(
            runtime_config=runtime_config,
            steering_mode=config.steering_mode,
            timeout_seconds=config.control_plane_timeout_seconds,
            name=provider,
        )
    if provider == "opensre-cli":
        return OpenSreCliBackend(
            command=config.opensre_command,
            timeout_seconds=config.backend_timeout_seconds,
        )
    if provider == "sregym":
        return SreGymBackend(
            server_url=config.sregym_server_url,
            target=config.sregym_target,
        )
    if provider == "cloudopsbench":
        state_directory = _state_directory(config, output_dir=output_dir, iteration=iteration)
        return CloudOpsBenchBackend(
            runtime_config=_runtime_config(config, state_directory=state_directory),
            cloudopsbench_root=config.cloudopsbench_root,
            ground_truth_mode=config.cloudopsbench_ground_truth_mode,
        )
    raise ValueError(f"unknown benchmark provider/backend: {provider}")


def _uses_runtime_state(config: BenchmarkRunConfig) -> bool:
    provider = config.provider or config.backend
    return provider in {"mesh", "mesh-control-plane", "mesh-agentic", "cloudopsbench"}


def _runtime_state_mode(mode: str) -> str:
    normalized = (mode or "full").strip().lower()
    if normalized not in {"full", "none"}:
        return "full"
    return normalized


def _state_directory(config: BenchmarkRunConfig, *, output_dir: Path, iteration: int) -> Path:
    if config.state_directory is None:
        return output_dir / f"runtime-state-{iteration}"
    if config.repeat == 1:
        return config.state_directory
    return config.state_directory / f"iteration-{iteration}"


def _runtime_config(config: BenchmarkRunConfig, *, state_directory: Path) -> RuntimeConfig:
    base = RuntimeConfig.from_env()
    return replace(
        base,
        state_directory=str(state_directory),
        research_directory=str(state_directory / "research"),
        vault_path=str(state_directory / "vault"),
        integrations_config_path=str(state_directory / "integrations.json"),
        evaluation_mode=config.evaluation_mode,
        orchestration_mode=config.orchestration_mode,
        default_steering_mode=config.steering_mode,
        run_worker_count=1,
        agent_fabric_mode=config.agent_fabric_mode or base.agent_fabric_mode,
        agent_tasks_mode=config.agent_tasks_mode,
        agent_mesh_agents=config.agent_lanes or base.agent_mesh_agents,
        agent_mesh_task_timeout_seconds=config.agent_task_timeout_seconds,
        mesh_deepagents_model=config.deepagents_model or base.mesh_deepagents_model,
        mesh_deepagents_timeout_seconds=(
            config.deepagents_timeout_seconds
            if config.deepagents_timeout_seconds is not None
            else base.mesh_deepagents_timeout_seconds
        ),
        mesh_deepagents_max_artifact_chars=(
            config.deepagents_max_artifact_chars
            if config.deepagents_max_artifact_chars is not None
            else base.mesh_deepagents_max_artifact_chars
        ),
        mesh_deepagents_max_output_tokens=(
            config.deepagents_max_output_tokens
            if config.deepagents_max_output_tokens is not None
            else base.mesh_deepagents_max_output_tokens
        ),
        mesh_deepagents_workspace_root=str(state_directory / "deepagents"),
        benchmark_export_path=str(state_directory / "benchmarks" / "runs.jsonl"),
    )


def _write_run(output_dir: Path, run: BenchmarkRun, *, compact_artifacts: bool = False) -> None:
    (output_dir / "benchmark.json").write_text(
        json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "scorecard.json").write_text(
        json.dumps(run.scorecard.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "scenario-results.jsonl").open("w", encoding="utf-8") as handle:
        for result in run.results:
            handle.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")
    (output_dir / "report.md").write_text(
        render_markdown_report(run.scorecard, run.results),
        encoding="utf-8",
    )
    if compact_artifacts:
        write_compact_run_artifacts(
            output_dir,
            run_id=run.run_id,
            scorecard=run.scorecard,
            results=run.results,
        )
