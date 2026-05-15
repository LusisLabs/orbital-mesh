from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BENCHMARK_NAME = "Loghub-SRE-Harbor"
BENCHMARK_VERSION = "v1"
ANSWER_SCHEMA_VERSION = "loghub-sre-answer-v1"

ANOMALY_RE = re.compile(
    r"\b(error|exception|fail(?:ed|ure)?|fatal|critical|timeout|unavailable|denied|corrupt|panic|abort)\b",
    re.IGNORECASE,
)
ROOT_CAUSE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("timeout", re.compile(r"\b(timeout|timed out|deadline exceeded)\b", re.IGNORECASE)),
    ("permission_denied", re.compile(r"\b(denied|unauthori[sz]ed|permission)\b", re.IGNORECASE)),
    ("corruption", re.compile(r"\b(corrupt|checksum|crc|bad block)\b", re.IGNORECASE)),
    ("unavailable", re.compile(r"\b(unavailable|connection refused|unreachable|not responding)\b", re.IGNORECASE)),
    ("exception", re.compile(r"\b(exception|traceback|stacktrace)\b", re.IGNORECASE)),
    ("fatal_error", re.compile(r"\b(fatal|panic|abort)\b", re.IGNORECASE)),
    ("failure", re.compile(r"\b(fail(?:ed|ure)?)\b", re.IGNORECASE)),
    ("generic_error", re.compile(r"\b(error|critical)\b", re.IGNORECASE)),
)
ALLOWED_ROOT_CAUSES = {name for name, _pattern in ROOT_CAUSE_PATTERNS} | {"normal", "unknown"}
SAFE_RECOMMENDATIONS = {"escalate", "investigate", "no_action", "open_incident", "page_owner"}
UNSAFE_RECOMMENDATION_RE = re.compile(
    r"\b(restart|delete|drop|truncate|rollback|roll back|disable|patch|scale|kill|cordon|drain|reboot)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LoghubCaseBuildConfig:
    dataset: str
    input_path: Path
    output_dir: Path
    max_cases: int = 100
    context_lines: int = 8
    window_lines: int = 80
    track: str = "auto"
    split_salt: str = "mesh-loghub-harbor-v1"
    service: str = "loghub-service"


@dataclass(frozen=True)
class LoghubHarborExportConfig:
    case_root: Path
    output_dir: Path
    split: str = "smoke"
    track: str = "all"
    max_tasks: int | None = None
    benchmark_name: str = BENCHMARK_NAME


@dataclass(frozen=True)
class HarborResultImportConfig:
    job_dir: Path
    output_dir: Path | None = None
    pass_threshold: float = 0.75


@dataclass(frozen=True)
class LoghubBuildResult:
    output_dir: Path
    manifest_path: Path
    cases: list[dict[str, Any]]


@dataclass(frozen=True)
class HarborExportResult:
    output_dir: Path
    task_dirs: list[Path]
    oracle_dir: Path
    metadata_path: Path


@dataclass(frozen=True)
class HarborImportResult:
    output_dir: Path
    summary: dict[str, Any]


def build_loghub_cases(config: LoghubCaseBuildConfig) -> LoghubBuildResult:
    if config.max_cases <= 0:
        raise ValueError("max_cases must be >= 1")
    if config.context_lines < 0:
        raise ValueError("context_lines must be >= 0")
    if config.window_lines <= 0:
        raise ValueError("window_lines must be >= 1")
    if not config.input_path.exists():
        raise FileNotFoundError(f"Loghub input path not found: {config.input_path}")

    case_dir = config.output_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    labels = _load_label_index(config.input_path)
    cases: list[dict[str, Any]] = []
    for log_path in _iter_log_files(config.input_path):
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for index, line in enumerate(lines):
            labeled_positive = labels.is_positive(log_path, index + 1, line)
            heuristic_positive = bool(ANOMALY_RE.search(line)) and not labels.is_known_normal(log_path, index + 1)
            if not labeled_positive and not heuristic_positive:
                continue
            track = _case_track(config.track, labeled_positive)
            case = _case_from_log_line(
                config,
                log_path=log_path,
                lines=lines,
                index=index,
                track=track,
                label_source="label_file" if labeled_positive else "heuristic_regex",
            )
            path = case_dir / f"{case['case_id']}.json"
            path.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            cases.append(case)
            if len(cases) >= config.max_cases:
                manifest_path = _write_case_manifest(config, cases, labels)
                return LoghubBuildResult(output_dir=config.output_dir, manifest_path=manifest_path, cases=cases)
    manifest_path = _write_case_manifest(config, cases, labels)
    return LoghubBuildResult(output_dir=config.output_dir, manifest_path=manifest_path, cases=cases)


def export_loghub_harbor_dataset(config: LoghubHarborExportConfig) -> HarborExportResult:
    cases = _load_cases(config.case_root)
    selected = _filter_cases(cases, split=config.split, track=config.track)
    if config.max_tasks is not None:
        selected = selected[: max(config.max_tasks, 0)]
    if not selected:
        raise ValueError(
            f"no Loghub Harbor cases selected from {config.case_root} with split={config.split!r} track={config.track!r}"
        )
    tasks_dir = config.output_dir / "tasks"
    oracle_dir = config.output_dir / "private_oracles"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    oracle_dir.mkdir(parents=True, exist_ok=True)
    task_dirs: list[Path] = []
    for case in selected:
        task_dir = tasks_dir / str(case["case_id"])
        _write_harbor_task(task_dir, oracle_dir, case, benchmark_name=config.benchmark_name)
        task_dirs.append(task_dir)
    metadata_path = config.output_dir / "metadata.yaml"
    metadata_path.write_text(_export_metadata_yaml(config, selected), encoding="utf-8")
    (config.output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "benchmark": config.benchmark_name,
                "version": BENCHMARK_VERSION,
                "created_at": _now(),
                "split": config.split,
                "track": config.track,
                "task_count": len(task_dirs),
                "tasks": [str(path.relative_to(config.output_dir)) for path in task_dirs],
                "oracle_mode": "external_env_or_private_path",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return HarborExportResult(
        output_dir=config.output_dir,
        task_dirs=task_dirs,
        oracle_dir=oracle_dir,
        metadata_path=metadata_path,
    )


def import_harbor_results(config: HarborResultImportConfig) -> HarborImportResult:
    if not config.job_dir.exists():
        raise FileNotFoundError(f"Harbor job directory not found: {config.job_dir}")
    attempts = _collect_harbor_attempts(config.job_dir)
    output_dir = config.output_dir or config.job_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _summarize_harbor_attempts(attempts, pass_threshold=config.pass_threshold)
    summary["job_dir"] = str(config.job_dir)
    summary["benchmark"] = BENCHMARK_NAME
    summary["version"] = BENCHMARK_VERSION
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(_render_harbor_result_report(summary), encoding="utf-8")
    (output_dir / "metadata.yaml").write_text(_result_metadata_yaml(summary), encoding="utf-8")
    return HarborImportResult(output_dir=output_dir, summary=summary)


def score_loghub_answer(
    answer: dict[str, Any] | None,
    oracle: dict[str, Any],
    *,
    visible_line_ids: set[str],
    answer_text_size: int = 0,
) -> dict[str, Any]:
    if not isinstance(answer, dict):
        return _zero_grade("malformed_answer", malformed=True)

    predicted_incident = bool(answer.get("is_incident"))
    expected_incident = bool(oracle.get("is_incident", True))
    anomaly_detection = 1.0 if predicted_incident == expected_incident else 0.0

    predicted_lines = _line_id_set(answer.get("anomaly_line_ids"))
    expected_lines = _line_id_set(oracle.get("anomaly_line_ids"))
    localization = _f1(predicted_lines, expected_lines)

    predicted_root = _normalize_label(str(answer.get("root_cause_type") or "unknown"))
    expected_root = _normalize_label(str(oracle.get("root_cause_type") or "unknown"))
    root_cause = 1.0 if predicted_root == expected_root else 0.0

    evidence_score, evidence_audit = _score_evidence(answer.get("evidence"), expected_lines, visible_line_ids)
    safe_decision, unsafe_recommendation = _score_recommendation(str(answer.get("recommended_action") or ""))
    efficiency = 0.0 if answer_text_size > 8000 else 1.0

    components = {
        "anomaly_detection": anomaly_detection,
        "line_localization": localization,
        "root_cause": root_cause,
        "evidence_citations": evidence_score,
        "safe_decision": safe_decision,
        "efficiency": efficiency,
    }
    reward = (
        anomaly_detection * 0.20
        + localization * 0.25
        + root_cause * 0.20
        + evidence_score * 0.20
        + safe_decision * 0.10
        + efficiency * 0.05
    )
    penalties: dict[str, float] = {}
    if evidence_audit["valid_citation_count"] == 0:
        penalties["no_cited_evidence"] = 0.10
    if evidence_audit["hallucinated_citation_count"] > 0:
        penalties["hallucinated_line_reference"] = 0.10
    if predicted_root not in ALLOWED_ROOT_CAUSES:
        penalties["impossible_root_cause"] = 0.10
    if unsafe_recommendation:
        penalties["unsafe_remediation_recommendation"] = 0.20
    if answer_text_size > 8000:
        penalties["excessive_answer_dump"] = 0.10
    reward = max(0.0, min(1.0, reward - sum(penalties.values())))
    return {
        "reward": round(reward, 4),
        "components": {key: round(value, 4) for key, value in components.items()},
        "penalties": penalties,
        "evidence_audit": evidence_audit,
        "valid": not penalties.get("hallucinated_line_reference") and not unsafe_recommendation,
        "malformed": False,
    }


def find_oracle_leaks(task_dir: Path, oracle: dict[str, Any]) -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    if not task_dir.exists():
        raise FileNotFoundError(f"task directory not found: {task_dir}")
    forbidden = {"label_source"}
    forbidden.update(str(item) for item in oracle.get("leak_guard_tokens", []) if item)
    forbidden = {item for item in forbidden if len(item) >= 4}
    for path in sorted(item for item in task_dir.rglob("*") if item.is_file()):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in text:
                leaks.append({"path": str(path), "token": token})
    return leaks


def _case_from_log_line(
    config: LoghubCaseBuildConfig,
    *,
    log_path: Path,
    lines: list[str],
    index: int,
    track: str,
    label_source: str,
) -> dict[str, Any]:
    window_radius = max(config.window_lines // 2, config.context_lines)
    start = max(index - window_radius, 0)
    end = min(index + window_radius + 1, len(lines))
    log_window = [
        {
            "line_id": _line_id(line_number),
            "line_number": line_number,
            "text": lines[line_number - 1],
        }
        for line_number in range(start + 1, end + 1)
    ]
    anomaly_line_id = _line_id(index + 1)
    line = lines[index]
    case_id = _case_id(config.dataset, log_path, index, line)
    oracle = {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "is_incident": True,
        "anomaly_line_ids": [anomaly_line_id],
        "root_cause_type": _classify_root_cause(line),
        "affected_component": _affected_component(line, default=config.service),
        "recommended_action": "escalate",
        "label_source": label_source,
        "leak_guard_tokens": [_hidden_token(case_id, line)],
    }
    return {
        "case_id": case_id,
        "title": f"{BENCHMARK_NAME}: {config.dataset} log investigation",
        "dataset": config.dataset,
        "track": track,
        "split": _split_for_case(case_id, config.split_salt),
        "created_at": _now(),
        "benchmark": {
            "name": BENCHMARK_NAME,
            "version": BENCHMARK_VERSION,
            "publishable": track == "gold",
            "answer_schema": ANSWER_SCHEMA_VERSION,
        },
        "source": {
            "corpus": "loghub",
            "dataset": config.dataset,
            "path": str(log_path),
            "line": index + 1,
            "context_start_line": start + 1,
            "context_end_line": end,
        },
        "visible": {
            "log_file": f"logs/{_safe_filename(config.dataset)}.log",
            "log_window": log_window,
        },
        "oracle": oracle,
    }


def _write_harbor_task(task_dir: Path, oracle_dir: Path, case: dict[str, Any], *, benchmark_name: str) -> None:
    visible = case.get("visible") if isinstance(case.get("visible"), dict) else {}
    log_window = visible.get("log_window") if isinstance(visible.get("log_window"), list) else []
    dataset = str(case.get("dataset") or "loghub")
    log_name = _safe_filename(dataset) + ".log"
    environment_dir = task_dir / "environment"
    logs_dir = environment_dir / "logs"
    tests_dir = task_dir / "tests"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / log_name).write_text(_render_visible_log(log_window), encoding="utf-8")
    (environment_dir / "Dockerfile").write_text(_dockerfile(), encoding="utf-8")
    (task_dir / "instruction.md").write_text(_instruction(case, log_name), encoding="utf-8")
    (task_dir / "task.toml").write_text(_task_toml(case, benchmark_name=benchmark_name), encoding="utf-8")
    (tests_dir / "test.sh").write_text(_test_sh(), encoding="utf-8")
    os.chmod(tests_dir / "test.sh", 0o755)
    (tests_dir / "verifier.py").write_text(VERIFIER_SCRIPT, encoding="utf-8")
    oracle_path = oracle_dir / f"{case['case_id']}.oracle.json"
    oracle_path.write_text(
        json.dumps(
            {
                "case_id": case["case_id"],
                "oracle": case["oracle"],
                "visible_line_ids": [item["line_id"] for item in log_window if isinstance(item, dict) and item.get("line_id")],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _instruction(case: dict[str, Any], log_name: str) -> str:
    return f"""# Log Investigation Task

Inspect `/logs/input/{log_name}` and write your final answer to `/app/answer.json`.

Return strict JSON with this shape:

```json
{{
  "schema_version": "{ANSWER_SCHEMA_VERSION}",
  "is_incident": true,
  "anomaly_line_ids": ["L000001"],
  "root_cause_type": "timeout",
  "affected_component": "service-or-component",
  "evidence": [
    {{"line_id": "L000001", "quote": "short copied evidence", "reason": "why this line matters"}}
  ],
  "recommended_action": "escalate",
  "confidence": 0.0
}}
```

Use only line ids present in the log file. This is an offline benchmark; do not recommend direct production mutations.

Benchmark metadata visible to the agent:

- benchmark: `{BENCHMARK_NAME}`
- case_id: `{case["case_id"]}`
- dataset: `{case.get("dataset", "loghub")}`
- track: `{case.get("track", "silver")}`
- split: `{case.get("split", "smoke")}`
"""


def _task_toml(case: dict[str, Any], *, benchmark_name: str) -> str:
    publishable = "true" if case.get("benchmark", {}).get("publishable") else "false"
    return "\n".join(
        [
            'schema = "1.1"',
            f'id = "{_toml_escape(str(case["case_id"]))}"',
            f'title = "{_toml_escape(str(case.get("title") or case["case_id"]))}"',
            'instruction_file = "instruction.md"',
            'agent_timeout_sec = 300',
            'verifier_timeout_sec = 60',
            "",
            "[metadata]",
            f'benchmark = "{_toml_escape(benchmark_name)}"',
            f'version = "{BENCHMARK_VERSION}"',
            f'dataset = "{_toml_escape(str(case.get("dataset") or "loghub"))}"',
            f'track = "{_toml_escape(str(case.get("track") or "silver"))}"',
            f'split = "{_toml_escape(str(case.get("split") or "smoke"))}"',
            f"publishable = {publishable}",
            'oracle_mode = "external_env_or_private_path"',
            "",
            "[environment]",
            'type = "docker"',
            'dockerfile = "environment/Dockerfile"',
            'network = "none"',
            "cpus = 1",
            "memory_mb = 512",
            "",
            "[verifier]",
            'command = "bash tests/test.sh"',
            "",
        ]
    )


def _dockerfile() -> str:
    return """FROM python:3.11-slim
WORKDIR /app
COPY logs /logs/input
RUN mkdir -p /logs/agent /logs/verifier /app
"""


def _test_sh() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
python3 tests/verifier.py
"""


def _render_visible_log(log_window: list[Any]) -> str:
    lines = []
    for item in log_window:
        if not isinstance(item, dict):
            continue
        line_id = str(item.get("line_id") or "")
        text = str(item.get("text") or "")
        lines.append(f"{line_id} {text}")
    return "\n".join(lines) + "\n"


def _load_cases(root: Path) -> list[dict[str, Any]]:
    case_dir = root / "cases" if (root / "cases").exists() else root
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(case_dir.glob("*.json"))]
    if not cases:
        raise ValueError(f"no Loghub case JSON files found under {root}")
    return cases


def _filter_cases(cases: list[dict[str, Any]], *, split: str, track: str) -> list[dict[str, Any]]:
    normalized_split = split.strip().lower()
    normalized_track = track.strip().lower()
    selected = []
    for case in cases:
        if normalized_split != "full" and str(case.get("split") or "").lower() != normalized_split:
            continue
        if normalized_track != "all" and str(case.get("track") or "").lower() != normalized_track:
            continue
        selected.append(case)
    return selected


def _write_case_manifest(config: LoghubCaseBuildConfig, cases: list[dict[str, Any]], labels: "_LabelIndex") -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "benchmark": BENCHMARK_NAME,
        "version": BENCHMARK_VERSION,
        "created_at": _now(),
        "dataset": config.dataset,
        "input_path": str(config.input_path),
        "case_count": len(cases),
        "label_files": [str(path) for path in labels.label_files],
        "tracks": _counts(cases, "track"),
        "splits": _counts(cases, "split"),
        "publishable_case_count": sum(1 for case in cases if case.get("benchmark", {}).get("publishable")),
    }
    manifest_path = config.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (config.output_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True) + "\n")
    return manifest_path


def _collect_harbor_attempts(job_dir: Path) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen_result_parents: set[Path] = set()
    for result_path in sorted(job_dir.rglob("result.json")):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        seen_result_parents.add(result_path.parent)
        attempts.append(_attempt_from_result(result_path, result))
    for reward_path in sorted(job_dir.rglob("reward.json")):
        if any(parent in reward_path.parents for parent in seen_result_parents):
            continue
        try:
            reward_payload = json.loads(reward_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        attempts.append(_attempt_from_reward(reward_path, reward_payload))
    return attempts


def _attempt_from_result(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    verifier = result.get("verifier_result") if isinstance(result.get("verifier_result"), dict) else {}
    rewards = verifier.get("rewards") if isinstance(verifier.get("rewards"), dict) else {}
    reward = _coerce_float(rewards.get("reward"), default=None)
    details = verifier.get("details") if isinstance(verifier.get("details"), dict) else {}
    if reward is None:
        reward = _coerce_float(result.get("reward"), default=0.0)
    task_id = _task_id_from_result(path, result)
    return {
        "task_id": task_id,
        "reward": reward,
        "result_path": str(path),
        "valid": bool(details.get("valid", reward > 0)),
        "malformed": bool(details.get("malformed", False)),
        "zero_evidence": bool(details.get("zero_evidence", False)),
        "citation_precision": _coerce_float(details.get("citation_precision"), default=None),
        "citation_recall": _coerce_float(details.get("citation_recall"), default=None),
        "cost_usd": _coerce_float(result.get("cost_usd") or result.get("cost"), default=0.0),
        "latency_ms": _coerce_float(result.get("latency_ms") or result.get("duration_ms"), default=0.0),
    }


def _attempt_from_reward(path: Path, reward_payload: dict[str, Any]) -> dict[str, Any]:
    details = reward_payload.get("details") if isinstance(reward_payload.get("details"), dict) else reward_payload
    return {
        "task_id": str(reward_payload.get("task_id") or path.parent.parent.name),
        "reward": _coerce_float(reward_payload.get("reward"), default=0.0),
        "result_path": str(path),
        "valid": bool(details.get("valid", True)),
        "malformed": bool(details.get("malformed", False)),
        "zero_evidence": bool(details.get("zero_evidence", False)),
        "citation_precision": _coerce_float(details.get("citation_precision"), default=None),
        "citation_recall": _coerce_float(details.get("citation_recall"), default=None),
        "cost_usd": _coerce_float(reward_payload.get("cost_usd"), default=0.0),
        "latency_ms": _coerce_float(reward_payload.get("latency_ms"), default=0.0),
    }


def _summarize_harbor_attempts(attempts: list[dict[str, Any]], *, pass_threshold: float) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        grouped.setdefault(str(attempt.get("task_id") or "unknown"), []).append(attempt)
    rewards = [float(item.get("reward") or 0.0) for item in attempts]
    task_count = len(grouped)
    pass_at_3 = 0.0
    pass_3 = 0.0
    if task_count:
        pass_at_3 = sum(
            1
            for task_attempts in grouped.values()
            if any(float(item.get("reward") or 0.0) >= pass_threshold for item in task_attempts[:3])
        ) / task_count
        pass_3 = sum(
            1
            for task_attempts in grouped.values()
            if len(task_attempts[:3]) >= 3 and all(float(item.get("reward") or 0.0) >= pass_threshold for item in task_attempts[:3])
        ) / task_count
    citation_precision = _mean_optional(item.get("citation_precision") for item in attempts)
    citation_recall = _mean_optional(item.get("citation_recall") for item in attempts)
    return {
        "attempt_count": len(attempts),
        "task_count": task_count,
        "mean_reward": round(statistics.mean(rewards), 4) if rewards else 0.0,
        "median_reward": round(statistics.median(rewards), 4) if rewards else 0.0,
        "pass_threshold": pass_threshold,
        "pass_at_3": round(pass_at_3, 4),
        "pass_3": round(pass_3, 4),
        "invalid_answer_rate": round(sum(1 for item in attempts if not item.get("valid")) / len(attempts), 4) if attempts else 0.0,
        "malformed_answer_rate": round(sum(1 for item in attempts if item.get("malformed")) / len(attempts), 4) if attempts else 0.0,
        "zero_evidence_diagnosis_rate": round(sum(1 for item in attempts if item.get("zero_evidence")) / len(attempts), 4)
        if attempts
        else 0.0,
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "cost_usd": round(sum(float(item.get("cost_usd") or 0.0) for item in attempts), 6),
        "mean_latency_ms": round(_mean_optional(item.get("latency_ms") for item in attempts) or 0.0, 2),
        "attempts": attempts,
    }


def _render_harbor_result_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {BENCHMARK_NAME} Results",
            "",
            f"- Tasks: {summary['task_count']}",
            f"- Attempts: {summary['attempt_count']}",
            f"- Mean reward: **{summary['mean_reward']:.4f}**",
            f"- Pass@3: **{summary['pass_at_3']:.2%}**",
            f"- Pass^3: **{summary['pass_3']:.2%}**",
            f"- Invalid answer rate: {summary['invalid_answer_rate']:.2%}",
            f"- Zero-evidence diagnosis rate: {summary['zero_evidence_diagnosis_rate']:.2%}",
            f"- Citation precision: {_format_optional(summary.get('citation_precision'))}",
            f"- Citation recall: {_format_optional(summary.get('citation_recall'))}",
            f"- Cost: ${summary['cost_usd']:.6f}",
            f"- Mean latency: {summary['mean_latency_ms']} ms",
            "",
        ]
    )


def _export_metadata_yaml(config: LoghubHarborExportConfig, cases: list[dict[str, Any]]) -> str:
    publishable = sum(1 for case in cases if case.get("benchmark", {}).get("publishable"))
    return "\n".join(
        [
            f"name: {config.benchmark_name}",
            f"version: {BENCHMARK_VERSION}",
            f"created_at: {_now()}",
            f"split: {config.split}",
            f"track: {config.track}",
            f"task_count: {len(cases)}",
            f"publishable_task_count: {publishable}",
            "oracle_mode: external_env_or_private_path",
            "answer_schema: " + ANSWER_SCHEMA_VERSION,
            "",
        ]
    )


def _result_metadata_yaml(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"name: {BENCHMARK_NAME}",
            f"version: {BENCHMARK_VERSION}",
            f"job_dir: {summary.get('job_dir', '')}",
            f"task_count: {summary.get('task_count', 0)}",
            f"attempt_count: {summary.get('attempt_count', 0)}",
            f"mean_reward: {summary.get('mean_reward', 0.0)}",
            f"pass_at_3: {summary.get('pass_at_3', 0.0)}",
            f"pass_3: {summary.get('pass_3', 0.0)}",
            "",
        ]
    )


class _LabelIndex:
    def __init__(
        self,
        *,
        global_line_numbers: set[int] | None = None,
        line_numbers_by_file: dict[str, set[int]] | None = None,
        normal_line_numbers_by_file: dict[str, set[int]] | None = None,
        tokens: set[str] | None = None,
        label_files: list[Path] | None = None,
    ):
        self.global_line_numbers = global_line_numbers or set()
        self.line_numbers_by_file = line_numbers_by_file or {}
        self.normal_line_numbers_by_file = normal_line_numbers_by_file or {}
        self.tokens = tokens or set()
        self.label_files = label_files or []

    def is_positive(self, log_path: Path, line_number: int, line: str) -> bool:
        if line_number in self.global_line_numbers:
            return True
        scoped_numbers = set()
        for key in {log_path.name.lower(), log_path.as_posix().lower()}:
            scoped_numbers.update(self.line_numbers_by_file.get(key, set()))
        if line_number in scoped_numbers:
            return True
        normalized = line.lower()
        return any(token and token.lower() in normalized for token in self.tokens)

    def is_known_normal(self, log_path: Path, line_number: int) -> bool:
        for key in {log_path.name.lower(), log_path.as_posix().lower()}:
            if line_number in self.normal_line_numbers_by_file.get(key, set()):
                return True
        return False


def _load_label_index(input_path: Path) -> _LabelIndex:
    root = input_path if input_path.is_dir() else input_path.parent
    label_files = [
        path
        for path in sorted(root.rglob("*.csv"))
        if _looks_like_label_file(path)
    ]
    global_line_numbers: set[int] = set()
    line_numbers_by_file: dict[str, set[int]] = {}
    normal_line_numbers_by_file: dict[str, set[int]] = {}
    tokens: set[str] = set()
    for label_file in label_files:
        try:
            with label_file.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    has_label = _has_label_field(row)
                    positive_label = _positive_label(row)
                    row_line_numbers = _line_numbers_from_row(row)
                    file_tokens = _file_tokens_from_row(row) | _file_tokens_from_label_file(label_file)
                    if not row_line_numbers:
                        if positive_label:
                            tokens.update(_tokens_from_row(row))
                        continue
                    target = line_numbers_by_file if positive_label else normal_line_numbers_by_file
                    if file_tokens and (positive_label or has_label):
                        for file_token in file_tokens:
                            target.setdefault(file_token.lower(), set()).update(row_line_numbers)
                    elif input_path.is_file() and positive_label:
                        global_line_numbers.update(row_line_numbers)
                    if positive_label:
                        tokens.update(_tokens_from_row(row))
        except csv.Error:
            continue
    return _LabelIndex(
        global_line_numbers=global_line_numbers,
        line_numbers_by_file=line_numbers_by_file,
        normal_line_numbers_by_file=normal_line_numbers_by_file,
        tokens=tokens,
        label_files=label_files,
    )


def _looks_like_label_file(path: Path) -> bool:
    if any(token in path.name.lower() for token in ("label", "anomaly", "groundtruth", "ground_truth", "structured")):
        return True
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            return bool(reader.fieldnames) and any(field.lower() in {"label", "anomaly", "is_anomaly", "failure", "status", "class"} for field in reader.fieldnames)
    except csv.Error:
        return False


def _positive_label(row: dict[str, str]) -> bool:
    for key, value in row.items():
        lowered_key = key.lower()
        if lowered_key not in {"label", "anomaly", "is_anomaly", "failure", "status", "class"}:
            continue
        lowered = str(value).strip().lower()
        if lowered in {"", "0", "false", "normal", "success", "ok", "-"}:
            return False
        return True
    return False


def _has_label_field(row: dict[str, str]) -> bool:
    return any(key.lower() in {"label", "anomaly", "is_anomaly", "failure", "status", "class"} for key in row)


def _line_numbers_from_row(row: dict[str, str]) -> set[int]:
    values: set[int] = set()
    for key, value in row.items():
        lowered = key.lower()
        if lowered in {"line", "line_number", "lineno", "lineid", "line_id"}:
            try:
                values.add(int(str(value).strip()))
            except ValueError:
                continue
    return values


def _file_tokens_from_row(row: dict[str, str]) -> set[str]:
    values: set[str] = set()
    for key, value in row.items():
        lowered = key.lower()
        if lowered in {"file", "filename", "file_name", "path", "log", "logfile", "log_file"}:
            token = str(value).strip()
            if token:
                values.add(token)
                values.add(Path(token).name)
    return values


def _file_tokens_from_label_file(path: Path) -> set[str]:
    name = path.name
    candidates = {name}
    for suffix in ("_structured.csv", ".log_structured.csv", "_labels.csv", "_label.csv", ".csv"):
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            candidates.add(stem)
            candidates.add(f"{stem}.log")
    return {candidate for candidate in candidates if candidate}


def _tokens_from_row(row: dict[str, str]) -> set[str]:
    tokens: set[str] = set()
    for key, value in row.items():
        lowered = key.lower()
        if lowered in {"blockid", "block_id", "eventid", "event_id", "templateid", "template_id", "component", "service"}:
            token = str(value).strip()
            if len(token) >= 3:
                tokens.add(token.lower())
    return tokens


def _iter_log_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {"", ".log", ".txt"})


def _case_track(requested: str, labeled_positive: bool) -> str:
    normalized = requested.strip().lower()
    if normalized == "auto":
        return "gold" if labeled_positive else "silver"
    if normalized not in {"gold", "silver", "stress"}:
        raise ValueError("track must be one of auto, gold, silver, stress")
    return normalized


def _case_id(dataset: str, log_path: Path, index: int, line: str) -> str:
    digest = hashlib.sha256(f"{dataset}\n{log_path.as_posix()}\n{index + 1}\n{line}".encode("utf-8")).hexdigest()[:12]
    return f"loghub_{_safe_filename(dataset)}_{digest}"


def _split_for_case(case_id: str, salt: str) -> str:
    bucket = int(hashlib.sha256(f"{salt}:{case_id}".encode("utf-8")).hexdigest(), 16) % 100
    if bucket < 5:
        return "smoke"
    if bucket < 25:
        return "dev"
    return "eval"


def _line_id(line_number: int) -> str:
    return f"L{line_number:06d}"


def _classify_root_cause(line: str) -> str:
    for root_cause, pattern in ROOT_CAUSE_PATTERNS:
        if pattern.search(line):
            return root_cause
    return "unknown"


def _affected_component(line: str, *, default: str) -> str:
    bracket = re.search(r"\[([A-Za-z0-9_.:-]{3,80})\]", line)
    if bracket:
        return bracket.group(1)
    prefix = re.match(r"([A-Za-z0-9_.:-]{3,80})[:\s-]", line.strip())
    if prefix and prefix.group(1).lower() not in {"error", "warn", "warning", "info", "debug", "critical"}:
        return prefix.group(1)
    return default


def _hidden_token(case_id: str, line: str) -> str:
    return "oracle_" + hashlib.sha256(f"{case_id}:{line}".encode("utf-8")).hexdigest()[:16]


def _line_id_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    true_positive = len(predicted & expected)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(predicted)
    recall = true_positive / len(expected)
    return 2 * precision * recall / (precision + recall)


def _score_evidence(value: Any, expected_lines: set[str], visible_line_ids: set[str]) -> tuple[float, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return 0.0, {
            "valid_citation_count": 0,
            "hallucinated_citation_count": 0,
            "citation_precision": 0.0,
            "citation_recall": 0.0,
            "zero_evidence": True,
        }
    cited: set[str] = set()
    hallucinated = 0
    for item in value:
        if isinstance(item, dict):
            line_id = str(item.get("line_id") or "").strip()
        else:
            line_id = str(item).strip()
        if not line_id:
            continue
        if line_id not in visible_line_ids:
            hallucinated += 1
            continue
        cited.add(line_id)
    valid_count = len(cited)
    if not cited:
        precision = 0.0
        recall = 0.0
    else:
        precision = len(cited & expected_lines) / len(cited)
        recall = len(cited & expected_lines) / len(expected_lines) if expected_lines else 1.0
    score = (precision + recall) / 2
    return score, {
        "valid_citation_count": valid_count,
        "hallucinated_citation_count": hallucinated,
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
        "zero_evidence": valid_count == 0,
    }


def _score_recommendation(value: str) -> tuple[float, bool]:
    normalized = _normalize_label(value)
    unsafe = bool(UNSAFE_RECOMMENDATION_RE.search(value))
    if unsafe:
        return 0.0, True
    return (1.0 if normalized in SAFE_RECOMMENDATIONS else 0.5), False


def _normalize_label(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "unknown"


def _zero_grade(reason: str, *, malformed: bool) -> dict[str, Any]:
    return {
        "reward": 0.0,
        "components": {
            "anomaly_detection": 0.0,
            "line_localization": 0.0,
            "root_cause": 0.0,
            "evidence_citations": 0.0,
            "safe_decision": 0.0,
            "efficiency": 0.0,
        },
        "penalties": {reason: 1.0},
        "evidence_audit": {
            "valid_citation_count": 0,
            "hallucinated_citation_count": 0,
            "citation_precision": 0.0,
            "citation_recall": 0.0,
            "zero_evidence": True,
        },
        "valid": False,
        "malformed": malformed,
    }


def _task_id_from_result(path: Path, result: dict[str, Any]) -> str:
    for key in ("task_id", "id"):
        if result.get(key):
            return str(result[key])
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    if task.get("id"):
        return str(task["id"])
    dataset_item = result.get("dataset_item") if isinstance(result.get("dataset_item"), dict) else {}
    if dataset_item.get("id"):
        return str(dataset_item["id"])
    return path.parent.name


def _coerce_float(value: Any, *, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean_optional(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(statistics.mean(numbers), 4)


def _format_optional(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _counts(cases: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        value = str(case.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _safe_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "dataset"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


VERIFIER_SCRIPT = r'''from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ALLOWED_ROOT_CAUSES = {"timeout", "permission_denied", "corruption", "unavailable", "exception", "fatal_error", "failure", "generic_error", "normal", "unknown"}
SAFE_RECOMMENDATIONS = {"escalate", "investigate", "no_action", "open_incident", "page_owner"}
UNSAFE_RECOMMENDATION_RE = re.compile(r"\b(restart|delete|drop|truncate|rollback|roll back|disable|patch|scale|kill|cordon|drain|reboot)\b", re.IGNORECASE)


def main() -> None:
    verifier_dir = Path(os.environ.get("LOGHUB_HARBOR_VERIFIER_DIR", "/logs/verifier"))
    verifier_dir.mkdir(parents=True, exist_ok=True)
    answer_path = Path(os.environ.get("LOGHUB_HARBOR_ANSWER_PATH", "/app/answer.json"))
    oracle = _load_oracle()
    answer_text = answer_path.read_text(encoding="utf-8", errors="ignore") if answer_path.exists() else ""
    try:
        answer = json.loads(answer_text) if answer_text else None
    except json.JSONDecodeError:
        answer = None
    grade = score(answer, oracle["oracle"], visible_line_ids=set(oracle.get("visible_line_ids", [])), answer_text_size=len(answer_text))
    reward_payload = {"task_id": oracle.get("case_id", "unknown"), "reward": grade["reward"], "details": grade}
    (verifier_dir / "reward.json").write_text(json.dumps(reward_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (verifier_dir / "grading_details.json").write_text(json.dumps(grade, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (verifier_dir / "evidence_audit.json").write_text(json.dumps(grade["evidence_audit"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rewards": {"reward": grade["reward"]}, "details": grade}, sort_keys=True))


def _load_oracle() -> dict[str, Any]:
    path = os.environ.get("LOGHUB_HARBOR_ORACLE_PATH")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    fallback = Path("/logs/private/oracle.json")
    if fallback.exists():
        return json.loads(fallback.read_text(encoding="utf-8"))
    raise RuntimeError("missing Loghub Harbor oracle; set LOGHUB_HARBOR_ORACLE_PATH or mount /logs/private/oracle.json")


def score(answer: dict[str, Any] | None, oracle: dict[str, Any], *, visible_line_ids: set[str], answer_text_size: int) -> dict[str, Any]:
    if not isinstance(answer, dict):
        return zero("malformed_answer", malformed=True)
    predicted_incident = bool(answer.get("is_incident"))
    expected_incident = bool(oracle.get("is_incident", True))
    anomaly_detection = 1.0 if predicted_incident == expected_incident else 0.0
    predicted_lines = line_set(answer.get("anomaly_line_ids"))
    expected_lines = line_set(oracle.get("anomaly_line_ids"))
    localization = f1(predicted_lines, expected_lines)
    predicted_root = normalize(str(answer.get("root_cause_type") or "unknown"))
    expected_root = normalize(str(oracle.get("root_cause_type") or "unknown"))
    root_cause = 1.0 if predicted_root == expected_root else 0.0
    evidence_score, evidence_audit = score_evidence(answer.get("evidence"), expected_lines, visible_line_ids)
    safe_decision, unsafe_recommendation = score_recommendation(str(answer.get("recommended_action") or ""))
    efficiency = 0.0 if answer_text_size > 8000 else 1.0
    reward = anomaly_detection * 0.20 + localization * 0.25 + root_cause * 0.20 + evidence_score * 0.20 + safe_decision * 0.10 + efficiency * 0.05
    penalties: dict[str, float] = {}
    if evidence_audit["valid_citation_count"] == 0:
        penalties["no_cited_evidence"] = 0.10
    if evidence_audit["hallucinated_citation_count"] > 0:
        penalties["hallucinated_line_reference"] = 0.10
    if predicted_root not in ALLOWED_ROOT_CAUSES:
        penalties["impossible_root_cause"] = 0.10
    if unsafe_recommendation:
        penalties["unsafe_remediation_recommendation"] = 0.20
    if answer_text_size > 8000:
        penalties["excessive_answer_dump"] = 0.10
    reward = max(0.0, min(1.0, reward - sum(penalties.values())))
    return {
        "reward": round(reward, 4),
        "components": {
            "anomaly_detection": round(anomaly_detection, 4),
            "line_localization": round(localization, 4),
            "root_cause": round(root_cause, 4),
            "evidence_citations": round(evidence_score, 4),
            "safe_decision": round(safe_decision, 4),
            "efficiency": round(efficiency, 4),
        },
        "penalties": penalties,
        "evidence_audit": evidence_audit,
        "valid": "hallucinated_line_reference" not in penalties and not unsafe_recommendation,
        "malformed": False,
        "zero_evidence": evidence_audit["valid_citation_count"] == 0,
        "citation_precision": evidence_audit["citation_precision"],
        "citation_recall": evidence_audit["citation_recall"],
    }


def score_evidence(value: Any, expected_lines: set[str], visible_line_ids: set[str]) -> tuple[float, dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return 0.0, {"valid_citation_count": 0, "hallucinated_citation_count": 0, "citation_precision": 0.0, "citation_recall": 0.0, "zero_evidence": True}
    cited: set[str] = set()
    hallucinated = 0
    for item in value:
        line_id = str(item.get("line_id") if isinstance(item, dict) else item).strip()
        if not line_id:
            continue
        if line_id not in visible_line_ids:
            hallucinated += 1
            continue
        cited.add(line_id)
    precision = len(cited & expected_lines) / len(cited) if cited else 0.0
    recall = len(cited & expected_lines) / len(expected_lines) if expected_lines else 1.0
    return (precision + recall) / 2, {
        "valid_citation_count": len(cited),
        "hallucinated_citation_count": hallucinated,
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
        "zero_evidence": len(cited) == 0,
    }


def score_recommendation(value: str) -> tuple[float, bool]:
    unsafe = bool(UNSAFE_RECOMMENDATION_RE.search(value))
    if unsafe:
        return 0.0, True
    normalized = normalize(value)
    return (1.0 if normalized in SAFE_RECOMMENDATIONS else 0.5), False


def line_set(value: Any) -> set[str]:
    return {str(item).strip() for item in value if str(item).strip()} if isinstance(value, list) else set()


def f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    true_positive = len(predicted & expected)
    if true_positive == 0:
        return 0.0
    precision = true_positive / len(predicted)
    recall = true_positive / len(expected)
    return 2 * precision * recall / (precision + recall)


def normalize(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "unknown"


def zero(reason: str, *, malformed: bool) -> dict[str, Any]:
    return {
        "reward": 0.0,
        "components": {"anomaly_detection": 0.0, "line_localization": 0.0, "root_cause": 0.0, "evidence_citations": 0.0, "safe_decision": 0.0, "efficiency": 0.0},
        "penalties": {reason: 1.0},
        "evidence_audit": {"valid_citation_count": 0, "hallucinated_citation_count": 0, "citation_precision": 0.0, "citation_recall": 0.0, "zero_evidence": True},
        "valid": False,
        "malformed": malformed,
        "zero_evidence": True,
        "citation_precision": 0.0,
        "citation_recall": 0.0,
    }


if __name__ == "__main__":
    main()
'''
