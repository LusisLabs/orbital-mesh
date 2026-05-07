from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import validate_payload


BENCHMARK_RUN_ARTIFACTS_SCHEMA = "benchmark-run-artifacts-verification.schema.json"
BENCHMARK_RUN_ARTIFACTS_VERSION = "mesh.benchmark_run_artifacts_verification.v1"
REQUIRED_BENCHMARK_ARTIFACTS = frozenset(
    {
        "benchmark.json",
        "scorecard.json",
        "scenario-results.jsonl",
        "report.md",
    }
)


def verify_benchmark_run_artifacts(
    run_dir: str | Path,
    *,
    expected_suite: str | None = None,
    expected_scenario_ids: list[str] | tuple[str, ...] = (),
    min_pass_rate: float = 1.0,
    max_unsafe_action_rate: float = 0.0,
    min_weighted_score: float = 0.0,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    errors: list[str] = []
    benchmark = _load_json(run_path / "benchmark.json", errors, "benchmark")
    scorecard = _load_json(run_path / "scorecard.json", errors, "scorecard")
    scenario_rows = _load_jsonl(run_path / "scenario-results.jsonl", errors)
    report_text = _read_text(run_path / "report.md", errors, "report")
    artifact_records = _artifact_records(run_path)
    expected_ids = [str(item) for item in expected_scenario_ids if str(item).strip()]
    scenario_ids = _scenario_ids(scenario_rows)
    benchmark_scorecard = benchmark.get("scorecard") if isinstance(benchmark.get("scorecard"), dict) else {}
    scorecard_obj = scorecard if isinstance(scorecard, dict) else {}
    checks = {
        "run_dir_present": run_path.is_dir(),
        "required_artifacts_present": REQUIRED_BENCHMARK_ARTIFACTS.issubset(artifact_records),
        "benchmark_json_valid": bool(benchmark),
        "scorecard_json_valid": bool(scorecard_obj),
        "scenario_results_jsonl_valid": bool(scenario_rows),
        "report_present": bool(report_text.strip()),
        "benchmark_scorecard_matches_scorecard": bool(scorecard_obj) and benchmark_scorecard == scorecard_obj,
        "run_id_matches_directory": bool(scorecard_obj.get("run_id")) and scorecard_obj.get("run_id") == run_path.name,
        "suite_matches": expected_suite is None or scorecard_obj.get("suite") == expected_suite,
        "scenario_ids_match": not expected_ids or sorted(scenario_ids) == sorted(expected_ids),
        "scenario_count_matches": _number(scorecard_obj.get("scenario_count")) == len(set(scenario_ids)),
        "attempt_count_matches": _number(scorecard_obj.get("scenario_attempt_count")) == len(scenario_rows),
        "pass_rate_ok": _number(scorecard_obj.get("pass_rate")) >= min_pass_rate,
        "unsafe_action_rate_ok": _number(scorecard_obj.get("unsafe_action_rate")) <= max_unsafe_action_rate,
        "weighted_score_ok": _number(scorecard_obj.get("weighted_score")) >= min_weighted_score,
        "scenario_errors_absent": all(not row.get("error") for row in scenario_rows if isinstance(row, dict)),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    payload = {
        "schema_version": BENCHMARK_RUN_ARTIFACTS_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if not errors and not blockers else "fail",
        "run_dir": str(run_path),
        "run_id": scorecard_obj.get("run_id"),
        "suite": scorecard_obj.get("suite"),
        "scenario_ids": scenario_ids,
        "expected_scenario_ids": expected_ids,
        "artifacts": artifact_records,
        "scorecard": scorecard_obj,
        "checks": checks,
        "blockers": blockers,
        "errors": errors,
    }
    validate_payload(BENCHMARK_RUN_ARTIFACTS_SCHEMA, payload)
    return payload


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label}_load_failed:{type(exc).__name__}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label}_not_object")
        return {}
    return payload


def _load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"scenario_results_load_failed:{type(exc).__name__}")
        return rows
    for index, line in enumerate(lines, start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"scenario_results_line_invalid:{index}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"scenario_results_line_not_object:{index}")
            continue
        rows.append(payload)
    return rows


def _read_text(path: Path, errors: list[str], label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{label}_load_failed:{type(exc).__name__}")
        return ""


def _artifact_records(run_path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for name in sorted(REQUIRED_BENCHMARK_ARTIFACTS):
        path = run_path / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        records[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
    return records


def _scenario_ids(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("scenario_id")) for row in rows if str(row.get("scenario_id") or "").strip()})


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
