from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime.config import RuntimeConfig

from .models import BenchmarkScenario


class BenchmarkBackend(Protocol):
    name: str

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        ...


@dataclass
class MeshBackend:
    runtime_config: RuntimeConfig
    name: str = "mesh"

    def __post_init__(self) -> None:
        self._engine = MeshRuntimeEngine(config=self.runtime_config)

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        return self._engine.run_sync(raw_signal, scenario_name=f"benchmark_{scenario.scenario_id}_{iteration}")


@dataclass(frozen=True)
class OpenSreCliBackend:
    command: str = "uvx opensre"
    timeout_seconds: float = 300.0
    work_dir: Path | None = None
    name: str = "opensre-cli"

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        alert = _opensre_alert_payload(scenario, raw_signal, iteration)
        with tempfile.TemporaryDirectory(prefix="mesh-opensre-bench-") as tmp:
            input_path = Path(tmp) / f"{scenario.scenario_id}.json"
            output_path = Path(tmp) / f"{scenario.scenario_id}.opensre.json"
            input_path.write_text(_json_dumps(alert), encoding="utf-8")
            command = [
                *shlex.split(self.command),
                "--json",
                "investigate",
                "-i",
                str(input_path),
                "-o",
                str(output_path),
            ]
            completed = subprocess.run(
                command,
                cwd=str(self.work_dir) if self.work_dir else None,
                env=_opensre_env(),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            output_file_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        return _normalize_opensre_output(
            scenario=scenario,
            raw_signal=raw_signal,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            output_file_text=output_file_text,
        )


def _opensre_alert_payload(
    scenario: BenchmarkScenario,
    raw_signal: dict[str, Any],
    iteration: int,
) -> dict[str, Any]:
    return {
        "source": "mesh_benchmark",
        "benchmark": {
            "scenario_id": scenario.scenario_id,
            "suite": scenario.suite,
            "iteration": iteration,
            "tags": list(scenario.tags),
        },
        "alert": {
            "title": scenario.title,
            "service": raw_signal.get("service") or raw_signal.get("deployment", {}).get("name"),
            "environment": raw_signal.get("environment"),
            "observed_at": raw_signal.get("observed_at"),
            "signal_type": raw_signal.get("signal_type", "feature_flag"),
            "severity": "critical",
            "description": _scenario_description(raw_signal),
        },
        "raw_signal": raw_signal,
    }


def _scenario_description(raw_signal: dict[str, Any]) -> str:
    if raw_signal.get("signal_type") == "kubernetes_deployment_issue":
        deployment = raw_signal.get("deployment", {})
        return f"Kubernetes deployment {deployment.get('name')} is {deployment.get('rollout_status')}."
    if raw_signal.get("signal_type") == "otel_metric_regression":
        metric = raw_signal.get("metric_regression", {})
        return (
            f"Metric {metric.get('metric_name')} regressed from "
            f"{metric.get('baseline_value')} to {metric.get('observed_value')}."
        )
    flag = raw_signal.get("feature_flag", {})
    telemetry = raw_signal.get("request_telemetry", {})
    observed = telemetry.get("observed", {})
    baseline = telemetry.get("baseline", {})
    return (
        f"Feature flag {flag.get('flag_key')} changed and service latency/error telemetry regressed: "
        f"p95 {baseline.get('p95_latency_ms')}ms -> {observed.get('p95_latency_ms')}ms."
    )


def _normalize_opensre_output(
    *,
    scenario: BenchmarkScenario,
    raw_signal: dict[str, Any],
    returncode: int,
    stdout: str,
    stderr: str,
    output_file_text: str = "",
) -> dict[str, Any]:
    parsed_output = _parse_json_output(output_file_text) or _parse_json_output(stdout)
    output = _report_text(parsed_output) if parsed_output is not None else "\n".join(
        part for part in (stdout.strip(), stderr.strip()) if part
    )
    decision = _infer_decision(output)
    status = "completed" if returncode == 0 and output else "failed"
    error = None if status == "completed" else (output or f"opensre exited with status {returncode}")
    evidence = _extract_evidence_lines(output)
    return {
        "backend": "opensre-cli",
        "trigger": {
            "trigger_id": f"opensre:{scenario.scenario_id}",
            "trigger_type": raw_signal.get("signal_type", "alert"),
        } if status == "completed" else None,
        "decision": {
            "decision_type": decision,
            "reasoning": {
                "primary_hypothesis": _first_nonempty_line(output),
                "raw_report_excerpt": output[:4000],
                "structured_report": parsed_output,
            },
        } if status == "completed" else None,
        "investigation_report": {
            "status": status,
            "probe_results": [
                {
                    "probe_name": "opensre_investigate_cli",
                    "status": status,
                    "summary": _first_nonempty_line(output),
                    "output_excerpt": output[:4000],
                    "structured_output": parsed_output,
                }
            ] if output else [],
            "citations": evidence,
            "findings": evidence,
            "stop_reason": "opensre_cli_completed" if status == "completed" else "opensre_cli_failed",
        },
        "feedback": {
            "outcome": "external_report_only",
        },
        "run_events": [
            {"artifact_key": "investigation_report", "backend": "opensre-cli"},
            {"artifact_key": "feedback", "backend": "opensre-cli"},
        ],
        "error": error,
    }


def _infer_decision(output: str) -> str:
    text = output.lower()
    if not text:
        return "escalate"
    if re.search(r"\b(disable|turn off)\b.*\b(flag|feature)\b|\bflag\b.*\b(disable|off)\b", text):
        return "disable_flag"
    if "reduce rollout" in text or "rollout percentage" in text:
        return "reduce_rollout"
    if "rollback" in text:
        return "rollback_deployment"
    if "patch" in text or "code fix" in text or "pull request" in text:
        return "investigate_and_patch"
    if "restart" in text and ("systemd" in text or ".service" in text):
        return "restart_systemd_service"
    if "restart" in text:
        return "restart_deployment"
    if re.search(r"\b(no action|do nothing|benign|false positive)\b", text):
        return "no_action"
    return "escalate"


def _parse_json_output(raw: str) -> dict[str, Any] | None:
    if not raw.strip():
        return None
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _report_text(parsed: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "summary",
        "report",
        "final_report",
        "diagnosis",
        "root_cause",
        "recommendation",
        "recommended_action",
        "next_steps",
    ):
        value = parsed.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.append(_json_dumps(value))
    if parts:
        return "\n".join(parts)
    return _json_dumps(parsed)


def _extract_evidence_lines(output: str) -> list[str]:
    lines = []
    for line in output.splitlines():
        compact = line.strip(" -\t")
        if not compact:
            continue
        lowered = compact.lower()
        if any(token in lowered for token in ("evidence", "root cause", "cause", "metric", "log", "trace", "deployment", "pod", "error")):
            lines.append(compact[:500])
        if len(lines) >= 10:
            break
    return lines


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        compact = line.strip()
        if compact:
            return compact[:500]
    return ""


def _opensre_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("OPENSRE_NO_TELEMETRY", "1")
    env.setdefault("OPENSRE_ANALYTICS_DISABLED", "1")
    return env


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
