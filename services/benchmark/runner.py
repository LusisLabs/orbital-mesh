from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.mesh_runtime.config import RuntimeConfig

from .backends import BenchmarkBackend, MeshBackend, OpenSreCliBackend
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
    repeat: int = 1
    backend: str = "mesh"
    opensre_command: str = "uvx opensre"
    backend_timeout_seconds: float = 300.0


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
    run_id = datetime.now(UTC).strftime("bench_%Y%m%dT%H%M%S%fZ")
    output_dir = config.output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    scenario_ids = set(config.scenario_ids) if config.scenario_ids else None
    scenarios = load_suite(config.suite, scenario_root=config.scenario_root, scenario_ids=scenario_ids)

    results: list[ScenarioBenchmarkResult] = []
    for iteration in range(1, config.repeat + 1):
        backend = _build_backend(config, output_dir=output_dir, iteration=iteration)
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
            duration_ms = (time.monotonic() - start) * 1000.0
            results.append(
                score_outcome(
                    scenario,
                    outcome,
                    duration_ms=duration_ms,
                    iteration=iteration,
                    backend=config.backend,
                    error=error,
                )
            )

    scorecard = aggregate_scorecard(config.suite, run_id, results)
    run = BenchmarkRun(run_id=run_id, output_dir=output_dir, scorecard=scorecard, results=results)
    _write_run(output_dir, run)
    return run


def _build_backend(config: BenchmarkRunConfig, *, output_dir: Path, iteration: int) -> BenchmarkBackend:
    if config.backend == "mesh":
        if config.state_directory is None:
            state_directory = output_dir / f"runtime-state-{iteration}"
        elif config.repeat == 1:
            state_directory = config.state_directory
        else:
            state_directory = config.state_directory / f"iteration-{iteration}"
        runtime_config = RuntimeConfig(
            state_directory=str(state_directory),
            evaluation_mode=config.evaluation_mode,
            orchestration_mode=config.orchestration_mode,
        )
        return MeshBackend(runtime_config=runtime_config)
    if config.backend == "opensre-cli":
        return OpenSreCliBackend(
            command=config.opensre_command,
            timeout_seconds=config.backend_timeout_seconds,
        )
    raise ValueError(f"unknown benchmark backend: {config.backend}")


def _write_run(output_dir: Path, run: BenchmarkRun) -> None:
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
