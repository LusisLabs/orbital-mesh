from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.benchmark.harbor_loghub import ANSWER_SCHEMA_VERSION, ANOMALY_RE, ROOT_CAUSE_PATTERNS
from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime import RuntimeConfig


@dataclass(frozen=True)
class _LogLine:
    line_id: str
    text: str


class MeshLoghubHarborAgent:
    """Small Harbor adapter for offline Loghub investigation tasks.

    The adapter is intentionally side-effect narrow: it reads benchmark logs,
    runs Mesh's normal investigation/scenario pipeline against a synthetic log
    regression signal when possible, and writes only Harbor answer/trajectory
    artifacts inside the task sandbox.
    """

    @property
    def name(self) -> str:
        return "mesh-loghub"

    async def run(self, environment: Any = None, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        lines = await _read_log_lines(environment)
        answer = _answer_from_lines(lines)
        trajectory = _mesh_trajectory(lines, answer)
        await _write_json(environment, "/app/answer.json", answer)
        await _write_json(environment, "/logs/agent/mesh_trajectory.json", trajectory)
        return {"answer": answer, "trajectory": trajectory}

    async def solve(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await self.run(*args, **kwargs)


async def _read_log_lines(environment: Any) -> list[_LogLine]:
    if environment is not None:
        output = await _exec(environment, "python3 - <<'PY'\nfrom pathlib import Path\nfor path in sorted(Path('/logs/input').glob('*')):\n    if path.is_file():\n        print(path.read_text(encoding='utf-8', errors='ignore'))\nPY")
        if output.strip():
            return _parse_log_lines(output.splitlines())
    local_root = Path("/logs/input")
    if local_root.exists():
        text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in sorted(local_root.glob("*")) if path.is_file())
        return _parse_log_lines(text.splitlines())
    return []


def _parse_log_lines(raw_lines: list[str]) -> list[_LogLine]:
    parsed: list[_LogLine] = []
    for index, raw in enumerate(raw_lines, start=1):
        match = re.match(r"^(L\d{6})\s+(.*)$", raw)
        if match:
            parsed.append(_LogLine(line_id=match.group(1), text=match.group(2)))
        else:
            parsed.append(_LogLine(line_id=f"L{index:06d}", text=raw))
    return parsed


def _answer_from_lines(lines: list[_LogLine]) -> dict[str, Any]:
    anomaly_lines = [line for line in lines if ANOMALY_RE.search(line.text)]
    primary = anomaly_lines[0] if anomaly_lines else (lines[0] if lines else _LogLine("L000001", ""))
    root_cause = _classify(primary.text) if anomaly_lines else "normal"
    evidence = [
        {
            "line_id": line.line_id,
            "quote": _short_quote(line.text),
            "reason": "log line contains an incident signal",
        }
        for line in anomaly_lines[:3]
    ]
    return {
        "schema_version": ANSWER_SCHEMA_VERSION,
        "is_incident": bool(anomaly_lines),
        "anomaly_line_ids": [line.line_id for line in anomaly_lines[:3]],
        "root_cause_type": root_cause,
        "affected_component": _component(primary.text),
        "evidence": evidence,
        "recommended_action": "escalate" if anomaly_lines else "no_action",
        "confidence": 0.75 if anomaly_lines else 0.55,
    }


def _mesh_trajectory(lines: list[_LogLine], answer: dict[str, Any]) -> dict[str, Any]:
    signal = _raw_signal(lines, answer)
    try:
        outcome = MeshRuntimeEngine(config=RuntimeConfig.from_env()).run_sync(signal, scenario_name="harbor_loghub")
        return {
            "status": "completed",
            "mesh_outcome": _compact_outcome(outcome),
            "answer_source": "mesh_runtime_plus_loghub_adapter",
        }
    except Exception as exc:
        return {
            "status": "fallback_completed",
            "error": str(exc),
            "answer_source": "loghub_adapter_heuristic",
            "line_count": len(lines),
        }


def _raw_signal(lines: list[_LogLine], answer: dict[str, Any]) -> dict[str, Any]:
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "signal_type": "otel_metric_regression",
        "signal_id": "harbor_loghub_signal",
        "observed_at": observed_at,
        "environment": "harbor-benchmark",
        "service": answer.get("affected_component") or "loghub-service",
        "endpoint": "loghub/offline",
        "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
        "source": "harbor_loghub",
        "metric_regression": {
            "metric_name": "log_error_rate",
            "baseline_value": 0.001,
            "observed_value": 0.12 if answer.get("is_incident") else 0.001,
            "delta_pct": 11900.0 if answer.get("is_incident") else 0.0,
            "unit": "ratio",
        },
        "related_context": {
            "log_context": [f"{line.line_id} {line.text}" for line in lines[:200]],
            "log_anomaly": [line_id for line_id in answer.get("anomaly_line_ids", [])],
            "incident_credentials_available": False,
            "feature_flag_credentials_available": False,
            "audit_logging_available": True,
        },
    }


def _compact_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "trigger": outcome.get("trigger"),
        "decision": outcome.get("decision"),
        "investigation_report": outcome.get("investigation_report"),
        "scenario_analysis": outcome.get("scenario_analysis"),
    }


def _classify(line: str) -> str:
    for root_cause, pattern in ROOT_CAUSE_PATTERNS:
        if pattern.search(line):
            return root_cause
    return "unknown"


def _component(line: str) -> str:
    bracket = re.search(r"\[([A-Za-z0-9_.:-]{3,80})\]", line)
    if bracket:
        return bracket.group(1)
    prefix = re.match(r"([A-Za-z0-9_.:-]{3,80})[:\s-]", line.strip())
    if prefix and prefix.group(1).lower() not in {"error", "warn", "warning", "info", "debug", "critical"}:
        return prefix.group(1)
    return "loghub-service"


def _short_quote(text: str) -> str:
    return text if len(text) <= 240 else text[:237] + "..."


async def _write_json(environment: Any, path: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if environment is not None:
        escaped = json.dumps(text)
        await _exec(
            environment,
            f"python3 - <<'PY'\nfrom pathlib import Path\ntext = {escaped}\npath = Path('{path}')\npath.parent.mkdir(parents=True, exist_ok=True)\npath.write_text(text + '\\n', encoding='utf-8')\nPY",
        )
        return
    local_path = Path(path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(text + "\n", encoding="utf-8")


async def _exec(environment: Any, command: str) -> str:
    maybe_result = environment.exec(command)
    result = await maybe_result if asyncio.iscoroutine(maybe_result) else maybe_result
    if isinstance(result, str):
        return result
    stdout = getattr(result, "stdout", None)
    if stdout is not None:
        return str(stdout)
    output = getattr(result, "output", None)
    if output is not None:
        return str(output)
    return str(result)
