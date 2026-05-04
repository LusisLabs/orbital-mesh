from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BenchmarkScorecard, ScenarioBenchmarkResult


COMPACT_FAILURE_LIMIT = 50


def write_compact_run_artifacts(
    output_dir: Path,
    *,
    run_id: str,
    scorecard: BenchmarkScorecard,
    results: list[ScenarioBenchmarkResult],
) -> None:
    rows = [_compact_result(result) for result in results]
    failures = [
        row
        for row in rows
        if row["error"] or not row["matched_decision"] or row["unsafe_action"]
    ]
    payload: dict[str, Any] = {
        "schema": "mesh.benchmark.compact.v1",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "scorecard": scorecard.to_dict(),
        "result_count": len(rows),
        "failure_count": len(failures),
        "failure_limit": COMPACT_FAILURE_LIMIT,
        "failures": failures[:COMPACT_FAILURE_LIMIT],
    }
    (output_dir / "benchmark-compact.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "scenario-results-compact.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _compact_result(result: ScenarioBenchmarkResult) -> dict[str, Any]:
    return {
        "iteration": result.iteration,
        "backend": result.backend,
        "scenario_id": result.scenario_id,
        "tags": list(result.tags),
        "actual_decision": result.actual_decision,
        "matched_decision": result.matched_decision,
        "unsafe_action": result.unsafe_action,
        "duration_ms": round(result.duration_ms, 2),
        "investigation_present": result.investigation_present,
        "investigation_probe_count": result.investigation_probe_count,
        "investigation_citation_count": result.investigation_citation_count,
        "root_cause_matched": result.root_cause_matched,
        "weighted_score": result.weighted_score,
        "mesh_operational_score": result.mesh_operational_score,
        "agentic_rca_score": result.agentic_rca_score,
        "dimension_scores": result.dimension_scores,
        "process_metrics": result.process_metrics.to_dict(),
        "error": result.error,
    }
