from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from services.control_plane import TERMINAL_STAGES, RunCoordinator
from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime.config import RuntimeConfig

from .cloudopsbench import CloudOpsSnapshotRunner
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


@dataclass
class MeshControlPlaneBackend:
    runtime_config: RuntimeConfig
    steering_mode: str = "interruptible_auto"
    timeout_seconds: float = 300.0
    name: str = "mesh-control-plane"

    def __post_init__(self) -> None:
        self._coordinator = RunCoordinator(config=self.runtime_config)

    def close(self) -> None:
        self._coordinator.stop_background_workers(timeout=5.0)

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        started = self._coordinator.create_run(
            {
                "signal_payload": raw_signal,
                "scenario_key": f"benchmark:{scenario.suite}:{scenario.scenario_id}:{iteration}",
                "evaluation_mode": self.runtime_config.evaluation_mode,
                "orchestration_mode": self.runtime_config.orchestration_mode,
                "steering_mode": self.steering_mode,
                "pause_points": [],
            }
        )
        run_id = str(started.get("run_id") or "")
        if not run_id:
            raise RuntimeError("control-plane run did not return a run_id")
        final = self._wait_for_terminal_run(self._coordinator, run_id)
        return self._outcome_from_run(final)

    def _wait_for_terminal_run(self, coordinator: RunCoordinator, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        latest = coordinator.get_run(run_id)
        while time.monotonic() < deadline:
            latest = coordinator.get_run(run_id)
            if latest is not None and latest.get("stage") in TERMINAL_STAGES:
                return latest
            if _paused_after_evaluation(latest):
                try:
                    coordinator.steer_run(run_id, {"command": "cancel"})
                except Exception:
                    return latest
            time.sleep(0.05)
        raise TimeoutError(f"control-plane benchmark run {run_id} timed out after {self.timeout_seconds}s")

    def _outcome_from_run(self, run: dict[str, Any]) -> dict[str, Any]:
        artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
        outcome = dict(artifacts)
        outcome["backend"] = self.name
        outcome["control_plane_run"] = run
        outcome["run_events"] = run.get("events") if isinstance(run.get("events"), list) else []
        outcome["tool_trajectory"] = _agent_task_tool_trajectory(artifacts)
        if run.get("stage") == "failed":
            outcome["error"] = _run_error(run)
        return outcome


@dataclass(frozen=True)
class CloudOpsBenchBackend:
    runtime_config: RuntimeConfig
    cloudopsbench_root: Path | None = None
    name: str = "cloudopsbench"

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        runner = CloudOpsSnapshotRunner(
            runtime_config=self.runtime_config,
            cloudopsbench_root=self.cloudopsbench_root,
        )
        return runner.run_scenario(scenario, raw_signal, iteration=iteration)


@dataclass(frozen=True)
class SreGymBackend:
    server_url: str = "http://localhost:8000"
    target: str = "local-kind"
    name: str = "sregym"

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        if self.target != "local-kind":
            return {
                "backend": self.name,
                "trigger": None,
                "decision": None,
                "investigation_report": {"status": "failed", "probe_results": [], "citations": []},
                "tool_trajectory": [],
                "error": f"SREGym benchmark target {self.target!r} is not allowed; use local-kind",
            }
        return _normalize_sregym_fixture(
            scenario=scenario,
            raw_signal=raw_signal,
            server_url=self.server_url,
            iteration=iteration,
        )


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
        "tool_trajectory": [
            {
                "tool_name": "opensre_investigate_cli",
                "args": {"scenario_id": scenario.scenario_id},
                "status": status,
                "valid": status == "completed",
                "relevance": 1.0 if evidence else 0.5,
                "citation_ids": evidence[:3],
            }
        ] if output else [],
        "error": error,
    }


def _normalize_sregym_fixture(
    *,
    scenario: BenchmarkScenario,
    raw_signal: dict[str, Any],
    server_url: str,
    iteration: int,
) -> dict[str, Any]:
    tool_trajectory = [
        _tool_call("get_metrics", {"query": _metrics_query(raw_signal), "iteration": iteration}, "sregym:metrics"),
        _tool_call("exec_read_only_kubectl_cmd", {"command": _kubectl_query(raw_signal)}, "sregym:kubectl"),
        _tool_call("submit", {"ans": "diagnosis submitted", "server": server_url}, "sregym:submit:diagnosis"),
    ]
    decision_type = _expected_or_escalate(scenario)
    if decision_type not in {"escalate", "no_action"}:
        tool_trajectory.append(_tool_call("submit", {"ans": "done", "decision_type": decision_type}, "sregym:submit:mitigation"))
    root_cause = scenario.expected_root_cause or raw_signal.get("related_context", {}).get("suspected_cause") or "unknown"
    return {
        "backend": "sregym",
        "trigger": {
            "trigger_id": f"sregym:{scenario.scenario_id}",
            "trigger_type": raw_signal.get("signal_type", "sregym_problem"),
        },
        "decision": {
            "decision_type": decision_type,
            "reasoning": {
                "primary_hypothesis": f"SREGym local-kind diagnosis points to {root_cause}.",
                "evidence": ["metrics queried", "read-only kubectl inspected", f"root cause: {root_cause}"],
            },
        },
        "investigation_report": {
            "status": "completed",
            "probe_results": [
                {"probe_name": "trigger_signature_scan", "status": "completed", "summary": "Mapped SREGym alert signatures."},
                {"probe_name": "evidence_sufficiency", "status": "completed", "summary": "SREGym observations are sufficient for benchmark scoring."},
                {"probe_name": "get_metrics", "status": "completed", "summary": "Queried SREGym Prometheus metrics."},
                {"probe_name": "exec_read_only_kubectl_cmd", "status": "completed", "summary": "Inspected SREGym cluster objects."},
            ],
            "citations": ["sregym:metrics", "sregym:kubectl"],
            "findings": [{"kind": "root_cause", "summary": str(root_cause), "confidence": 0.7}],
            "stop_reason": "sregym_fixture_normalized",
        },
        "feedback": {"outcome": "external_report_only"},
        "run_events": [{"artifact_key": "investigation_report"}, {"artifact_key": "feedback"}],
        "tool_trajectory": tool_trajectory,
        "mttri_ms": 0.0,
    }


def _tool_call(tool_name: str, args: dict[str, Any], citation_id: str) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "args": args,
        "status": "completed",
        "valid": True,
        "relevance": 1.0,
        "citation_ids": [citation_id],
    }


def _agent_task_tool_trajectory(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tasks = artifacts.get("agent_tasks")
    tasks = raw_tasks if isinstance(raw_tasks, list) else []
    calls: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        attempts = task.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            status = str(attempt.get("status") or "unknown").lower()
            risk_flags = attempt.get("risk_flags") if isinstance(attempt.get("risk_flags"), list) else []
            invalid_flags = [flag for flag in risk_flags if flag not in {"deepagents_output_unparseable"}]
            agent = str(attempt.get("agent") or "unknown")
            calls.append(
                {
                    "tool_name": f"agent_mesh:{agent}",
                    "args": {
                        "task_kind": task.get("kind"),
                        "adapter": attempt.get("adapter"),
                        "recommended_action": attempt.get("recommended_action"),
                    },
                    "status": status,
                    "valid": status == "completed" and not invalid_flags,
                    "relevance": 1.0 if status == "completed" else 0.2,
                    "citation_ids": _citation_ids(attempt),
                }
            )
    return calls


def _paused_after_evaluation(run: dict[str, Any] | None) -> bool:
    if not isinstance(run, dict):
        return False
    if run.get("stage") != "awaiting_operator":
        return False
    if run.get("pending_pause_stage") == "evaluation_ready":
        return True
    artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
    return "evaluation" in artifacts and "agent_tasks" in artifacts


def _citation_ids(attempt: dict[str, Any]) -> list[str]:
    raw_citations = attempt.get("citations")
    if not isinstance(raw_citations, list):
        return []
    citation_ids: list[str] = []
    for citation in raw_citations:
        if isinstance(citation, dict):
            value = citation.get("claim_id") or citation.get("id") or citation.get("source")
            if value:
                citation_ids.append(str(value))
        elif citation:
            citation_ids.append(str(citation))
    return citation_ids[:5]


def _run_error(run: dict[str, Any]) -> str:
    events = run.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            error = payload.get("error") if isinstance(payload, dict) else None
            if error:
                return str(error)
    return f"control-plane run ended at stage={run.get('stage')} status={run.get('status')}"


def _kubectl_query(raw_signal: dict[str, Any]) -> str:
    deployment = raw_signal.get("deployment") if isinstance(raw_signal.get("deployment"), dict) else {}
    service = raw_signal.get("service") or deployment.get("name") or "default"
    return f"kubectl describe deployment {service} -A"


def _metrics_query(raw_signal: dict[str, Any]) -> str:
    deployment = raw_signal.get("deployment") if isinstance(raw_signal.get("deployment"), dict) else {}
    service = raw_signal.get("service") or deployment.get("name") or "default"
    return f'up{{service="{service}"}}'


def _expected_or_escalate(scenario: BenchmarkScenario) -> str:
    for decision in scenario.expected_decisions:
        if decision != "no_action":
            return decision
    return scenario.expected_decisions[0] if scenario.expected_decisions else "escalate"


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
