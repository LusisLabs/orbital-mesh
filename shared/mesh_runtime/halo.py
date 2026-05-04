from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .agent_workers import build_agent_task
from .control_plane_models import AgentTask, RunEvent, RunSession
from .mesh_state_store import MeshStateStore, RunFilters
from .phoenix_trace import build_phoenix_spans


TRACE_FORMAT = "mesh.halo.trace.v1"
OPTIMIZATION_ARTIFACT_KEY = "halo_optimization_cycle"

DEFAULT_HARNESS_ALLOWED_PATHS = [
    "services/",
    "shared/mesh_runtime/",
    "control_plane_server.py",
    "scripts/",
    "tests/",
    "web/src/",
    "docs/",
]

DEFAULT_HARNESS_TEST_COMMANDS = [
    "PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest",
    "RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .",
    "TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'",
    "npm --prefix web run lint",
    "npm --prefix web run build",
]

_SECRET_KEY_PATTERN = re.compile(r"(token|secret|password|credential|api[_-]?key|kubeconfig|private[_-]?key)", re.I)
_MAX_STRING = 4000
_MAX_LIST_ITEMS = 50


@dataclass(frozen=True)
class HaloExportResult:
    trace_count: int
    output_path: str
    run_ids: list[str]


@dataclass(frozen=True)
class HaloRunResult:
    export: HaloExportResult
    command: list[str]
    returncode: int
    report_path: str | None
    stdout: str
    stderr: str


def export_halo_traces(
    state_store: MeshStateStore,
    output_path: str | Path,
    *,
    limit: int = 100,
    status: str | None = None,
    stage: str | None = None,
    goal_id: str | None = None,
) -> HaloExportResult:
    sessions = state_store.list_runs(RunFilters(limit=limit, status=status, stage=stage, goal_id=goal_id))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    run_ids: list[str] = []
    with path.open("w", encoding="utf-8") as fh:
        for session in sessions:
            events = state_store.list_run_events(session.run_id)
            merkle = state_store.get_merkle_snapshot(session.run_id)
            for record in build_halo_span_records(session, events, merkle.to_dict()):
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            run_ids.append(session.run_id)

    return HaloExportResult(trace_count=len(run_ids), output_path=str(path), run_ids=run_ids)


def build_halo_span_records(session: RunSession, events: Iterable[RunEvent], merkle: dict[str, Any]) -> list[dict[str, Any]]:
    event_dicts = [event.to_dict() for event in events]
    artifacts = _redact(session.artifacts)
    root_start = session.created_at or _timestamp()
    root_end = session.updated_at or root_start
    spans = [
        _span_record(
            trace_id=session.run_id,
            span_id=_span_id(session.run_id, "run", 0),
            parent_span_id="",
            name="mesh.run",
            kind="SPAN_KIND_INTERNAL",
            start_time=root_start,
            end_time=root_end,
            status_code=_status_code(session.status, session.error),
            status_message=session.error or str(session.status),
            attributes={
                "mesh.trace_format": TRACE_FORMAT,
                "mesh.project": "orbital-mesh",
                "mesh.source": "mesh-run-history",
                "mesh.run": _run_summary(session),
                "mesh.harness": {
                    "evaluation_mode": session.evaluation_mode,
                    "orchestration_mode": session.orchestration_mode,
                    "steering_mode": session.steering_mode,
                    "auto_mode": session.auto_mode,
                    "pause_points": list(session.pause_points),
                },
                "mesh.artifacts": _artifact_context(artifacts),
                "mesh.failure": _failure_context(session, artifacts),
                "mesh.merkle": _redact(merkle),
            },
        )
    ]
    parent_span_id = spans[0]["span_id"]
    for index, event in enumerate(event_dicts, start=1):
        spans.append(
            _span_record(
                trace_id=session.run_id,
                span_id=_span_id(session.run_id, str(event.get("event_id") or "event"), index),
                parent_span_id=parent_span_id,
                name=str(event.get("event_type") or event.get("stage") or "mesh.event"),
                kind=_span_kind_for_event(event),
                start_time=str(event.get("recorded_at") or root_start),
                end_time=str(event.get("recorded_at") or root_start),
                status_code=_status_code(str(event.get("status") or session.status), None),
                status_message=str(event.get("status") or ""),
                attributes={
                    "mesh.trace_format": TRACE_FORMAT,
                    "mesh.run_id": session.run_id,
                    "mesh.stage": event.get("stage"),
                    "mesh.event_type": event.get("event_type"),
                    "mesh.artifact_key": event.get("artifact_key"),
                    "mesh.integration_name": event.get("integration_name"),
                    "mesh.event": _event_summary(event),
                },
            )
        )
    return spans


def build_halo_trace_record(session: RunSession, events: Iterable[RunEvent], merkle: dict[str, Any]) -> dict[str, Any]:
    event_dicts = [event.to_dict() for event in events]
    task_trace = _task_trace(session, event_dicts)
    artifacts = _redact(session.artifacts)
    return {
        "trace_format": TRACE_FORMAT,
        "trace_id": session.run_id,
        "project": "orbital-mesh",
        "source": "mesh-run-history",
        "created_at": _timestamp(),
        "run": _run_summary(session),
        "harness": {
            "evaluation_mode": session.evaluation_mode,
            "orchestration_mode": session.orchestration_mode,
            "steering_mode": session.steering_mode,
            "auto_mode": session.auto_mode,
            "pause_points": list(session.pause_points),
        },
        "otel": {
            "spans": build_phoenix_spans(task_trace),
        },
        "events": [_event_summary(event) for event in event_dicts],
        "artifacts": _artifact_context(artifacts),
        "failure": _failure_context(session, artifacts),
        "merkle": _redact(merkle),
    }


def _span_record(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str,
    name: str,
    kind: str,
    start_time: str,
    end_time: str,
    status_code: str,
    status_message: str,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": name,
        "kind": kind,
        "start_time": start_time,
        "end_time": end_time,
        "status": {
            "code": status_code,
            "message": status_message,
        },
        "resource": {
            "attributes": {
                "service.name": "orbital-mesh",
                "deployment.environment": "mesh",
            }
        },
        "scope": {
            "name": "mesh.halo.exporter",
            "version": TRACE_FORMAT,
        },
        "attributes": _redact(attributes),
    }


def _span_id(seed: str, label: str, index: int) -> str:
    import hashlib

    return hashlib.sha256(f"{seed}:{label}:{index}".encode("utf-8")).hexdigest()[:16]


def _span_kind_for_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    if event_type in {"evidence_pack_ready", "reasoning_bank_packet"}:
        return "SPAN_KIND_CLIENT"
    if event_type in {"decision_ready", "evaluation_ready", "scenario_analysis_ready"}:
        return "SPAN_KIND_INTERNAL"
    if event_type in {"execution_recorded", "feedback_recorded"}:
        return "SPAN_KIND_PRODUCER"
    return "SPAN_KIND_INTERNAL"


def _status_code(status: str | None, error: str | None) -> str:
    normalized = (status or "").lower()
    if error or normalized in {"failed", "error", "blocked"}:
        return "STATUS_CODE_ERROR"
    return "STATUS_CODE_OK"


def run_halo_engine(
    state_store: MeshStateStore,
    output_path: str | Path,
    *,
    halo_command: str = "halo",
    prompt: str = "Diagnose recurring Mesh harness failure modes and suggest bounded fixes.",
    model: str | None = None,
    max_depth: int | None = None,
    max_turns: int | None = None,
    max_parallel: int | None = None,
    limit: int = 100,
    report_path: str | Path | None = None,
    timeout_seconds: float = 900.0,
    status: str | None = None,
    stage: str | None = None,
    goal_id: str | None = None,
) -> HaloRunResult:
    export = export_halo_traces(
        state_store,
        output_path,
        limit=limit,
        status=status,
        stage=stage,
        goal_id=goal_id,
    )
    command = [halo_command, export.output_path, "-p", prompt]
    if model:
        command.extend(["--model", model])
    if max_depth is not None:
        command.extend(["--max-depth", str(max_depth)])
    if max_turns is not None:
        command.extend(["--max-turns", str(max_turns)])
    if max_parallel is not None:
        command.extend(["--max-parallel", str(max_parallel)])
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except FileNotFoundError as exc:
        returncode = 127
        stdout = ""
        stderr = str(exc)
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else f"HALO command timed out after {timeout_seconds}s"
    report_text = stdout.strip()
    report_file = str(report_path) if report_path is not None else None
    if report_path is not None:
        report = Path(report_path)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(report_text + ("\n" if report_text else ""), encoding="utf-8")
    return HaloRunResult(
        export=export,
        command=command,
        returncode=returncode,
        report_path=report_file,
        stdout=stdout,
        stderr=stderr,
    )


def build_halo_patch_task(
    *,
    optimization_id: str,
    report: str | dict[str, Any],
    run_ids: list[str],
    agents: list[str] | None = None,
    allowed_paths: list[str] | None = None,
    test_commands: list[str] | None = None,
) -> AgentTask:
    task = build_agent_task(
        run_id=optimization_id,
        kind="halo_harness_optimization",
        allowed_paths=allowed_paths or DEFAULT_HARNESS_ALLOWED_PATHS,
        test_commands=test_commands or DEFAULT_HARNESS_TEST_COMMANDS,
        memory_scope={"system": "mesh", "loop": "halo_outer_optimizer", "run_ids": list(run_ids)},
        memory_packet={
            "source": "halo",
            "optimization_id": optimization_id,
            "report": _redact(report),
            "run_ids": list(run_ids),
        },
        memory_write_policy={
            "mode": "proposal_only",
            "allowed_record_types": ["observation", "claim", "procedure"],
        },
        open_questions=[
            "Which reported failure modes recur across traces rather than single runs?",
            "Which proposed harness change has a bounded path and verification command?",
            "Does the change preserve Mesh policy ownership over production side effects?",
        ],
        agents=agents or ["codex", "goose", "hermes", "claudecode", "openclaw", "evo"],
    )
    task.status = "queued"
    return task


def record_halo_optimization_cycle(
    state_store: MeshStateStore,
    *,
    export: HaloExportResult,
    report: str | dict[str, Any],
    task: AgentTask | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    optimization_id = task.run_id if task is not None else f"halo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
    artifact = {
        "artifact_key": OPTIMIZATION_ARTIFACT_KEY,
        "optimization_id": optimization_id,
        "recorded_at": _timestamp(),
        "trace_format": TRACE_FORMAT,
        "trace_count": export.trace_count,
        "trace_path": export.output_path,
        "run_ids": list(export.run_ids),
        "report": _redact(report),
        "patch_task": task.to_dict() if task is not None else None,
        "metadata": _redact(metadata or {}),
    }
    state_store.put_artifact(artifact)
    return artifact


def load_halo_report(path: str | Path) -> str | dict[str, Any]:
    report_path = Path(path)
    raw = report_path.read_text(encoding="utf-8")
    if report_path.suffix.lower() == ".json":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return raw


def _task_trace(session: RunSession, events: list[dict[str, Any]]) -> dict[str, Any]:
    artifacts = session.artifacts if isinstance(session.artifacts, dict) else {}
    return {
        "trace_version": TRACE_FORMAT,
        "task": _redact(artifacts.get("input_signal") or {"scenario_key": session.scenario_key}),
        "context": _redact(artifacts.get("scenario_analysis") or artifacts.get("evidence_pack")),
        "decision": _redact(artifacts.get("decision")),
        "evaluation": _redact(artifacts.get("evaluation")),
        "failure_cause": _failure_context(session, artifacts),
        "events": events,
    }


def _run_summary(session: RunSession) -> dict[str, Any]:
    return {
        "run_id": session.run_id,
        "goal_id": session.goal_id,
        "scenario_key": session.scenario_key,
        "stage": session.stage,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "latest_event_id": session.latest_event_id,
        "latest_event_sequence": session.latest_event_sequence,
        "latest_merkle_root": session.latest_merkle_root,
        "error": session.error,
    }


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "sequence": event.get("sequence"),
        "stage": event.get("stage"),
        "event_type": event.get("event_type"),
        "recorded_at": event.get("recorded_at"),
        "artifact_key": event.get("artifact_key"),
        "integration_name": event.get("integration_name"),
        "status": event.get("status"),
        "summary": _redact(event.get("summary")),
        "payload": _redact(event.get("payload")),
    }


def _artifact_context(artifacts: Any) -> dict[str, Any]:
    if not isinstance(artifacts, dict):
        return {}
    agent_tasks = artifacts.get("agent_tasks")
    return {
        "keys": sorted(str(key) for key in artifacts.keys()),
        "input_signal": artifacts.get("input_signal"),
        "trigger": artifacts.get("trigger"),
        "evidence_pack": artifacts.get("evidence_pack"),
        "scenario_analysis": artifacts.get("scenario_analysis"),
        "decision": artifacts.get("decision"),
        "evaluation": artifacts.get("evaluation"),
        "agent_tasks": _agent_task_summary(agent_tasks),
        "reconciliation": artifacts.get("reconciliation"),
        "execution": artifacts.get("execution"),
        "feedback": artifacts.get("feedback"),
        "benchmark_score": artifacts.get("benchmark_score"),
    }


def _agent_task_summary(agent_tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(agent_tasks, list):
        return []
    summary: list[dict[str, Any]] = []
    for task in agent_tasks[:_MAX_LIST_ITEMS]:
        if not isinstance(task, dict):
            continue
        attempts = task.get("attempts") if isinstance(task.get("attempts"), list) else []
        summary.append(
            {
                "task_id": task.get("task_id"),
                "kind": task.get("kind"),
                "status": task.get("status"),
                "agents": task.get("agents", []),
                "selected_attempt_id": task.get("selected_attempt_id"),
                "attempts": [
                    {
                        "agent": attempt.get("agent"),
                        "adapter": attempt.get("adapter"),
                        "status": attempt.get("status"),
                        "recommended_action": attempt.get("recommended_action"),
                        "risk_flags": attempt.get("risk_flags", []),
                        "summary": attempt.get("summary"),
                    }
                    for attempt in attempts[:_MAX_LIST_ITEMS]
                    if isinstance(attempt, dict)
                ],
            }
        )
    return summary


def _failure_context(session: RunSession, artifacts: Any) -> dict[str, Any]:
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    evaluation = artifacts.get("evaluation") if isinstance(artifacts.get("evaluation"), dict) else {}
    feedback = artifacts.get("feedback") if isinstance(artifacts.get("feedback"), dict) else {}
    benchmark = artifacts.get("benchmark_score") if isinstance(artifacts.get("benchmark_score"), dict) else {}
    agent_tasks = artifacts.get("agent_tasks") if isinstance(artifacts.get("agent_tasks"), list) else []
    agent_risk_flags: list[str] = []
    for task in agent_tasks:
        if not isinstance(task, dict):
            continue
        for attempt in task.get("attempts", []) if isinstance(task.get("attempts"), list) else []:
            if isinstance(attempt, dict):
                agent_risk_flags.extend(str(flag) for flag in attempt.get("risk_flags", []) if flag)
    return {
        "terminal_status": session.status,
        "terminal_stage": session.stage,
        "run_error": session.error,
        "evaluation_recommendation": evaluation.get("final_recommendation"),
        "blocking_reasons": evaluation.get("blocking_reasons", []),
        "feedback_status": feedback.get("status"),
        "benchmark_passed": benchmark.get("passed"),
        "benchmark_score": benchmark.get("score"),
        "agent_risk_flags": sorted(set(agent_risk_flags)),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY_PATTERN.search(str(key)):
                cleaned[str(key)] = "[REDACTED]"
            else:
                cleaned[str(key)] = _redact(item)
        return cleaned
    if isinstance(value, list):
        trimmed = value[:_MAX_LIST_ITEMS]
        output = [_redact(item) for item in trimmed]
        if len(value) > _MAX_LIST_ITEMS:
            output.append({"truncated_items": len(value) - _MAX_LIST_ITEMS})
        return output
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "...[TRUNCATED]"
    return deepcopy(value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
