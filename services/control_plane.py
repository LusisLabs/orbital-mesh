from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.runtime import MeshRuntimeEngine
from services.ingest.kubernetes_live_signal import collect_kubernetes_signal
from services.orchestrator.agent_mesh import AgentMeshService
from services.orchestrator.evo_launcher import EvoLaunchService
from shared.mesh_runtime import (
    AGENT_TASK_RECORDED,
    APPROVAL_BLOCKED,
    DECISION_READY,
    EVALUATION_READY,
    EXECUTION_RECORDED,
    FEEDBACK_RECORDED,
    INTEGRATION_ARTIFACT_RECORDED,
    INTEGRATION_READINESS_RECORDED,
    NORMALIZED_EVENT,
    NO_TRIGGER,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    RuntimeConfig,
    STEERING_COMMAND,
    STEERING_REJECTED,
    TRIGGER_READY,
    Decision,
    EvaluationResult,
    Trigger,
    load_fixture,
)
from shared.mesh_runtime.control_plane_models import GoalRecord, RunSession, SteeringCommand
from shared.mesh_runtime.control_plane_state import ControlPlaneStateStore
from shared.mesh_runtime.integrations import build_readiness
from shared.mesh_runtime.research import (
    build_research_corpus_intelligence,
    build_research_session_intelligence,
    sanitize_research_markdown,
)


ALLOWED_STAGES = {
    "queued",
    "ingesting",
    "trigger_ready",
    "no_trigger",
    "decision_ready",
    "evaluation_ready",
    "awaiting_operator",
    "executing",
    "feedback_ready",
    "completed",
    "failed",
    "cancelled",
}

PAUSEABLE_STAGES = {"trigger_ready", "decision_ready", "evaluation_ready", "feedback_ready"}
TERMINAL_STAGES = {"completed", "failed", "cancelled", "no_trigger"}
_RESEARCH_SESSION_ID_OK = re.compile(r"^[a-zA-Z0-9_.-]+$")

ALLOWED_STEERING_COMMANDS = {
    "approve",
    "cancel",
    "pause_after_stage",
    "resume",
    "set_auto_mode",
    "override_decision",
    "override_execution_parameters",
    "attach_note",
    "launch_evo",
}

# Operator steering is analogous to activation steering: early / late interventions have different
# leverage and failure modes. Decision-changing commands are restricted to pre-execution gates so we
# do not "perturb late layers" after execution has run (incoherent or misleading audit trails).
_STEERING_DECISION_COMMANDS = frozenset({"override_decision", "override_execution_parameters"})
_STEERING_EARLY_STAGES = frozenset({"ingesting", "trigger_ready"})
_STEERING_PAYLOAD_CAP_BYTES = int(os.getenv("MESH_MAX_STEERING_PAYLOAD_BYTES", "65536"))


def _steering_command_payload_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))


def _validate_steering_command(session: RunSession, command_type: str, command_payload: dict[str, Any]) -> None:
    if _steering_command_payload_bytes(command_payload) > _STEERING_PAYLOAD_CAP_BYTES:
        raise ValueError(
            f"steering payload exceeds {_STEERING_PAYLOAD_CAP_BYTES} bytes "
            "(cap from MESH_MAX_STEERING_PAYLOAD_BYTES)"
        )
    if session.stage in TERMINAL_STAGES:
        if command_type == "launch_evo" and session.stage == "completed":
            return
        if command_type != "attach_note":
            raise ValueError(
                f"steering command {command_type!r} is not allowed after run is {session.stage!r}; "
                "only attach_note is permitted."
            )
        return
    if command_type == "launch_evo":
        effective = session.pending_pause_stage or session.stage
        if effective != "evaluation_ready":
            raise ValueError(
                f"steering command {command_type!r} is not allowed at stage {effective!r} "
                f"(run stage {session.stage!r}). "
                "Evo launch is accepted only when the run is paused at evaluation_ready or after completion."
            )
        return
    effective = session.pending_pause_stage or session.stage
    if command_type not in _STEERING_DECISION_COMMANDS:
        return
    if effective in _STEERING_EARLY_STAGES or effective == "feedback_ready" or session.stage in {
        "executing",
        "feedback_ready",
    }:
        raise ValueError(
            f"steering command {command_type!r} is not allowed at stage {effective!r} "
            f"(run stage {session.stage!r}). "
            "Decision and execution-parameter overrides are only accepted when the run is paused at "
            "evaluation_ready, before actuation."
        )


class RunControl:
    def __init__(self, auto_mode: bool, pause_points: list[str]):
        self.condition = threading.Condition()
        self.commands: deque[SteeringCommand] = deque()
        self.auto_mode = auto_mode
        self.pause_points = set(pause_points)


class RunCoordinator:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        state_store: ControlPlaneStateStore | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or ControlPlaneStateStore(self.config)
        self.agent_mesh = AgentMeshService(config=self.config)
        self.evo_launcher = EvoLaunchService(self.config)
        self.controls: dict[str, RunControl] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.state_store.ensure_default_goal()

    def ensure_sidecar(self) -> bool:
        return False

    def build_readiness(self) -> dict[str, Any]:
        return build_readiness(self.config).to_dict()

    def list_scenarios(self) -> list[dict[str, Any]]:
        fixtures_root = Path(__file__).resolve().parents[1] / "fixtures" / "signals"
        scenarios: list[dict[str, Any]] = []
        for path in sorted(fixtures_root.glob("*.json")):
            payload = json.loads(path.read_text())
            if payload.get("signal_type") == "kubernetes_deployment_issue":
                deployment = payload["deployment"]
                summary = {
                    "service": payload["service"],
                    "endpoint": f"deployment/{deployment['name']}",
                    "flag_key": deployment["revision"],
                    "latency_delta_ms": sum(int(pod.get("restarts", 0)) for pod in payload["pods"]),
                }
            else:
                observed = payload["request_telemetry"]["observed"]
                baseline = payload["request_telemetry"]["baseline"]
                summary = {
                    "service": payload["service"],
                    "endpoint": payload["endpoint"],
                    "flag_key": payload["feature_flag"]["flag_key"],
                    "latency_delta_ms": observed["p95_latency_ms"] - baseline["p95_latency_ms"],
                }
            scenarios.append(
                {
                    "key": path.stem,
                    "title": path.stem.replace("_", " ").title(),
                    "file": path.name,
                    "summary": summary,
                }
            )
        return scenarios

    def list_goals(self) -> list[dict[str, Any]]:
        return [goal.to_dict() for goal in self.state_store.list_goals()]

    def create_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = _timestamp()
        goal = GoalRecord(
            goal_id=payload.get("goal_id") or f"goal_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{len(self.state_store.list_goals()) + 1}",
            title=payload["title"],
            objective=payload.get("objective", payload.get("title", "")),
            success_criteria=list(payload.get("success_criteria", [])),
            status=payload.get("status", "active"),
            created_at=payload.get("created_at", now),
            updated_at=now,
            tags=list(payload.get("tags", [])),
        )
        return self.state_store.save_goal(goal).to_dict()

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return [session.to_dict() for session in self.state_store.list_run_sessions(limit=limit)]

    def list_research_sessions(self, limit: int = 40) -> list[dict[str, Any]]:
        """Goose/MiniMax autoresearch sessions under research_directory (filesystem, not Mesh pipeline runs)."""
        root = Path(self.config.research_directory)
        if not root.is_dir():
            return []
        rows: list[tuple[float, dict[str, Any]]] = []
        for path in root.iterdir():
            if not path.is_dir():
                continue
            manifest_path = path / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except json.JSONDecodeError:
                continue
            synth = path / "synthesis" / "final-report.md"
            mtime = synth.stat().st_mtime if synth.is_file() else manifest_path.stat().st_mtime
            sid = str(manifest.get("session_id") or path.name)
            intelligence = build_research_session_intelligence(path, manifest, max_chars=120_000)
            rows.append(
                (
                    mtime,
                    {
                        "session_id": sid,
                        "directory": path.name,
                        "question": str(manifest.get("question", ""))[:500],
                        "status": str(manifest.get("status", "")),
                        "minimax_model": manifest.get("minimax_model"),
                        "minimax_route": manifest.get("minimax_route"),
                        "goose": manifest.get("goose"),
                        "updated_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                        "has_final_report": synth.is_file(),
                        "research_intelligence": {
                            "classification": intelligence["classification"],
                            "repo_grounding_score": intelligence["repo_grounding_score"],
                            "off_domain_score": intelligence["off_domain_score"],
                            "flags": intelligence["flags"],
                            "anchors": intelligence["anchors"][:4],
                        },
                    },
                )
            )
        rows.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in rows[:limit]]

    def get_research_corpus(self) -> dict[str, Any]:
        root = Path(self.config.research_directory)
        return build_research_corpus_intelligence(root)

    def get_research_session(self, session_id: str) -> dict[str, Any] | None:
        if not session_id or not _RESEARCH_SESSION_ID_OK.match(session_id):
            return None
        root = Path(self.config.research_directory)
        if not root.is_dir():
            return None
        for path in root.iterdir():
            if not path.is_dir():
                continue
            manifest_path = path / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except json.JSONDecodeError:
                continue
            sid = str(manifest.get("session_id") or path.name)
            if sid != session_id and path.name != session_id:
                continue
            synth = path / "synthesis" / "final-report.md"
            report: str | None = None
            if synth.is_file():
                report = sanitize_research_markdown(synth.read_text(encoding="utf-8", errors="replace"))
                if len(report) > 800_000:
                    report = report[:800_000] + "\n\n[truncated]\n"
            intelligence = build_research_session_intelligence(path, manifest)
            return {
                "session_id": sid,
                "directory": path.name,
                "manifest": manifest,
                "final_report_markdown": report,
                "final_report_relative": "synthesis/final-report.md" if synth.is_file() else None,
                "research_intelligence": intelligence,
            }
        return None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return None
        return {
            **session.to_dict(),
            "events": [event.to_dict() for event in self.state_store.list_run_events(run_id)],
            "merkle": self.state_store.get_merkle_snapshot(run_id).to_dict(),
        }

    def list_agent_tasks(self, run_id: str) -> list[dict[str, Any]]:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            raise KeyError(run_id)
        tasks = session.artifacts.get("agent_tasks", [])
        return list(tasks) if isinstance(tasks, list) else []

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        steering_mode = payload.get("steering_mode", self.config.default_steering_mode)
        auto_mode = steering_mode == "interruptible_auto"
        raw_pause_points = (
            payload["pause_points"]
            if "pause_points" in payload
            else ([] if auto_mode else [self.config.default_operator_pause_point])
        )
        pause_points = self._normalize_pause_points(raw_pause_points)
        goal_id = payload.get("goal_id") or self.state_store.ensure_default_goal().goal_id
        scenario_key = self._resolve_run_label(payload)
        signal_payload = self._resolve_signal(payload)
        run_config = replace(
            self.config,
            evaluation_mode=payload.get("evaluation_mode", self.config.evaluation_mode),
            orchestration_mode=payload.get("orchestration_mode", self.config.orchestration_mode),
        )
        readiness_snapshot = build_readiness(run_config).to_dict()
        session = self.state_store.create_run_session(
            goal_id=goal_id,
            scenario_key=scenario_key,
            steering_mode=steering_mode,
            auto_mode=auto_mode,
            pause_points=pause_points,
            evaluation_mode=run_config.evaluation_mode,
            orchestration_mode=run_config.orchestration_mode,
            artifacts={"input_signal": signal_payload, "integration_readiness": readiness_snapshot},
        )
        self.controls[session.run_id] = RunControl(auto_mode=auto_mode, pause_points=pause_points)
        self.state_store.append_run_event(
            session.run_id,
            stage="queued",
            event_type=RUN_QUEUED,
            payload={
                "scenario_key": scenario_key,
                "goal_id": goal_id,
                "steering_mode": steering_mode,
                "pause_points": pause_points,
            },
            summary={"status": "queued"},
            status="queued",
        )
        self.state_store.append_run_event(
            session.run_id,
            stage="queued",
            event_type=INTEGRATION_READINESS_RECORDED,
            payload=readiness_snapshot,
            summary={
                "promptfoo_ready": readiness_snapshot["promptfoo"]["ready"],
                "hermes_ready": readiness_snapshot["hermes"]["ready"],
                "goose_ready": readiness_snapshot["goose"]["ready"],
                "evo_ready": readiness_snapshot["evo"]["ready"],
            },
            artifact_key="integration_readiness",
            status="captured",
        )
        worker = threading.Thread(
            target=self._execute_run,
            args=(session.run_id, run_config, signal_payload, scenario_key),
            daemon=True,
        )
        self._threads[session.run_id] = worker
        worker.start()
        return self.get_run(session.run_id) or session.to_dict()

    def steer_run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        command_type = payload.get("command")
        if command_type not in ALLOWED_STEERING_COMMANDS:
            raise ValueError(f"unsupported steering command: {command_type}")
        session = self.state_store.get_run_session(run_id)
        control = self.controls.get(run_id)
        if session is None or control is None:
            raise KeyError(run_id)
        command_payload = {key: value for key, value in payload.items() if key != "command"}
        _validate_steering_command(session, command_type, command_payload)
        command = SteeringCommand(
            command_id=f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{len(session.operator_notes) + 1}",
            run_id=run_id,
            command_type=command_type,
            issued_at=_timestamp(),
            payload=command_payload,
        )
        self.state_store.append_run_event(
            run_id,
            stage=session.stage,
            event_type=STEERING_COMMAND,
            payload=command.to_dict(),
            summary={"command": command_type},
            artifact_key="operator_command",
            status="received",
        )
        if command_type == "launch_evo":
            self._launch_evo(run_id, session, command_payload)
            return self.get_run(run_id) or session.to_dict()
        if command_type == "attach_note" and command.payload.get("note"):
            session.operator_notes.append(command.payload["note"])
            session.updated_at = _timestamp()
            self.state_store.save_run_session(session)
        with control.condition:
            control.commands.append(command)
            control.condition.notify_all()
        return self.get_run(run_id) or session.to_dict()

    def _execute_run(
        self,
        run_id: str,
        run_config: RuntimeConfig,
        signal_payload: dict[str, Any],
        scenario_key: str | None,
    ) -> None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return
        engine = MeshRuntimeEngine(config=run_config, state_store=self.state_store.runtime_store)
        try:
            self._update_session(run_id, stage="ingesting", status="running")
            normalized_event = engine.ingest.normalize_signal(copy.deepcopy(signal_payload))
            self._set_artifact(run_id, "normalized_event", normalized_event.to_dict())
            self.state_store.append_run_event(
                run_id,
                stage="ingesting",
                event_type=NORMALIZED_EVENT,
                payload=normalized_event.to_dict(),
                summary=normalized_event.summary,
                artifact_key="normalized_event",
                status="recorded",
            )

            trigger = engine.trigger.detect(normalized_event)
            if trigger is None:
                self._update_session(run_id, stage="no_trigger", status="completed")
                self.state_store.append_run_event(
                    run_id,
                    stage="no_trigger",
                    event_type=NO_TRIGGER,
                    payload={"reason": "signal did not satisfy trigger thresholds"},
                    summary={"status": "completed"},
                    status="completed",
                )
                self._update_session(run_id, stage="completed", status="completed")
                return

            self._set_artifact(run_id, "trigger", trigger.to_dict())
            self._update_session(run_id, stage="trigger_ready", status="running")
            self.state_store.append_run_event(
                run_id,
                stage="trigger_ready",
                event_type=TRIGGER_READY,
                payload=trigger.to_dict(),
                summary={"trigger_type": trigger.trigger_type},
                artifact_key="trigger",
                status="recorded",
            )
            while True:
                trigger_wait = self._wait_if_needed(
                    run_id, "trigger_ready", trigger=trigger, decision=None, evaluation=None
                )
                if trigger_wait["action"] == "cancel":
                    self._update_session(run_id, stage="cancelled", status="cancelled")
                    self.state_store.append_run_event(
                        run_id,
                        stage="cancelled",
                        event_type=RUN_CANCELLED,
                        payload={"reason": "operator_cancelled"},
                        summary={"status": "cancelled"},
                        status="cancelled",
                    )
                    return
                if trigger_wait["action"] == "override":
                    self.state_store.append_run_event(
                        run_id,
                        stage="trigger_ready",
                        event_type=STEERING_REJECTED,
                        payload={
                            "reason": "override_before_decision",
                            "detail": (
                                "Decision overrides are not valid before evaluation_ready; "
                                "command drained from queue."
                            ),
                        },
                        summary={"status": "rejected"},
                        status="rejected",
                    )
                    continue
                break

            decision = engine.decision.decide(trigger)
            evaluation = self._record_decision_and_evaluation(run_id, engine, trigger, decision)

            while True:
                outcome = self._wait_if_needed(run_id, "evaluation_ready", trigger=trigger, decision=decision, evaluation=evaluation)
                if outcome["action"] == "continue":
                    break
                if outcome["action"] == "cancel":
                    self._update_session(run_id, stage="cancelled", status="cancelled")
                    self.state_store.append_run_event(
                        run_id,
                        stage="cancelled",
                        event_type=RUN_CANCELLED,
                        payload={"reason": "operator_cancelled"},
                        summary={"status": "cancelled"},
                        status="cancelled",
                    )
                    return
                if outcome["action"] == "override":
                    decision = self._apply_override(decision, outcome["payload"])
                    evaluation = self._record_decision_and_evaluation(
                        run_id,
                        engine,
                        trigger,
                        decision,
                        allow_rereevaluation=True,
                    )
                    continue

            self._update_session(run_id, stage="executing", status="running")
            execution = engine.orchestrator.execute(decision, evaluation)
            self._set_artifact(run_id, "execution", execution.to_dict())
            self.state_store.append_run_event(
                run_id,
                stage="executing",
                event_type=EXECUTION_RECORDED,
                payload=execution.to_dict(),
                summary={"status": execution.status},
                artifact_key="execution",
                integration_name=run_config.orchestration_mode if run_config.orchestration_mode != "native" else None,
                status=execution.status,
            )
            for artifact_key, integration_name in (("goose_review", "goose"), ("hermes_review", "hermes")):
                review = execution.external_refs.get(artifact_key)
                if review:
                    self._set_artifact(run_id, artifact_key, review)
                    self.state_store.append_run_event(
                        run_id,
                        stage="executing",
                        event_type=INTEGRATION_ARTIFACT_RECORDED,
                        payload=review,
                        summary={"approved": review.get("approved")},
                        artifact_key=artifact_key,
                        integration_name=integration_name,
                        status="recorded",
                    )

            feedback = engine.feedback.record(trigger, decision, execution, normalized_event)
            self._set_artifact(run_id, "feedback", feedback.to_dict())
            self._update_session(run_id, stage="feedback_ready", status="running")
            self.state_store.append_run_event(
                run_id,
                stage="feedback_ready",
                event_type=FEEDBACK_RECORDED,
                payload=feedback.to_dict(),
                summary={"outcome": feedback.outcome},
                artifact_key="feedback",
                status=feedback.outcome,
            )
            while True:
                wait_feedback = self._wait_if_needed(
                    run_id,
                    "feedback_ready",
                    trigger=trigger,
                    decision=decision,
                    evaluation=evaluation,
                )
                if wait_feedback["action"] == "cancel":
                    self._update_session(run_id, stage="cancelled", status="cancelled")
                    return
                if wait_feedback["action"] == "override":
                    self.state_store.append_run_event(
                        run_id,
                        stage="feedback_ready",
                        event_type=STEERING_REJECTED,
                        payload={
                            "reason": "override_after_execution",
                            "detail": (
                                "Decision-changing steering after actuation is rejected "
                                "(late intervention would corrupt the run record)."
                            ),
                        },
                        summary={"status": "rejected"},
                        status="rejected",
                    )
                    continue
                break
            self._update_session(run_id, stage="completed", status="completed")
            self.state_store.append_run_event(
                run_id,
                stage="completed",
                event_type=RUN_COMPLETED,
                payload={"execution_status": execution.status, "feedback_outcome": feedback.outcome},
                summary={"status": "completed"},
                status="completed",
            )
        except Exception as exc:
            self._update_session(run_id, stage="failed", status="failed", error=str(exc))
            self.state_store.append_run_event(
                run_id,
                stage="failed",
                event_type=RUN_FAILED,
                payload={"error": str(exc)},
                summary={"status": "failed"},
                status="failed",
            )

    def _record_decision_and_evaluation(
        self,
        run_id: str,
        engine: MeshRuntimeEngine,
        trigger: Trigger,
        decision: Decision,
        allow_rereevaluation: bool = False,
    ) -> EvaluationResult:
        self._set_artifact(run_id, "decision", decision.to_dict())
        self._update_session(run_id, stage="decision_ready", status="running")
        self.state_store.append_run_event(
            run_id,
            stage="decision_ready",
            event_type=DECISION_READY,
            payload=decision.to_dict(),
            summary={"decision_type": decision.decision_type, "autonomy_tier": decision.autonomy_tier},
            artifact_key="decision",
            status="recorded",
        )
        evaluation = engine.evaluation.evaluate(
            trigger,
            decision,
            allow_rereevaluation=allow_rereevaluation,
        )
        self._set_artifact(run_id, "evaluation", evaluation.to_dict())
        self._update_session(run_id, stage="evaluation_ready", status="running")
        self.state_store.append_run_event(
            run_id,
            stage="evaluation_ready",
            event_type=EVALUATION_READY,
            payload=evaluation.to_dict(),
            summary={
                "recommendation": evaluation.final_recommendation,
                "passed": evaluation.passed,
            },
            artifact_key="evaluation",
            integration_name=engine.config.evaluation_mode if engine.config.evaluation_mode != "native" else None,
            status=evaluation.final_recommendation,
        )
        promptfoo_artifact = evaluation.stage_results.get("promptfoo_quality", {}).get("artifacts")
        if promptfoo_artifact:
            self._set_artifact(run_id, "promptfoo_artifact", promptfoo_artifact)
            self.state_store.append_run_event(
                run_id,
                stage="evaluation_ready",
                event_type=INTEGRATION_ARTIFACT_RECORDED,
                payload=promptfoo_artifact,
                summary={"passed": evaluation.stage_results["promptfoo_quality"]["passed"]},
                artifact_key="promptfoo_artifact",
                integration_name="promptfoo",
                status="recorded",
            )
        tasks = self.agent_mesh.build_tasks(
            run_id=run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
        )
        task_payload = [task.to_dict() for task in tasks]
        self._set_artifact(run_id, "agent_tasks", task_payload)
        self.state_store.append_run_event(
            run_id,
            stage="evaluation_ready",
            event_type=AGENT_TASK_RECORDED,
            payload={"tasks": task_payload},
            summary={
                "tasks": len(task_payload),
                "agents": sum(len(task.get("attempts", [])) for task in task_payload),
            },
            artifact_key="agent_tasks",
            integration_name="agent_mesh",
            status="recorded",
        )
        return evaluation

    def _wait_if_needed(
        self,
        run_id: str,
        stage: str,
        trigger: Trigger | None,
        decision: Decision | None,
        evaluation: EvaluationResult | None,
    ) -> dict[str, Any]:
        session = self.state_store.get_run_session(run_id)
        control = self.controls[run_id]
        if session is None:
            return {"action": "cancel"}

        requires_pause = stage in control.pause_points or (stage == "evaluation_ready" and not control.auto_mode)
        can_auto_continue = (
            stage == "evaluation_ready"
            and control.auto_mode
            and evaluation is not None
            and evaluation.passed
            and evaluation.final_recommendation == "execute"
            and stage not in control.pause_points
        ) or (stage == "feedback_ready" and stage not in control.pause_points)

        if not requires_pause and can_auto_continue:
            return {"action": "continue"}
        if not requires_pause and stage not in {"evaluation_ready", "feedback_ready"}:
            return {"action": "continue"}

        self._update_session(run_id, stage="awaiting_operator", status="awaiting_operator", pending_pause_stage=stage)
        with control.condition:
            while True:
                while not control.commands:
                    control.condition.wait(timeout=0.5)
                    current = self.state_store.get_run_session(run_id)
                    if current and current.status in {"cancelled", "failed"}:
                        return {"action": "cancel"}
                    if stage == "evaluation_ready" and control.auto_mode and evaluation and evaluation.passed and evaluation.final_recommendation == "execute":
                        self._update_session(run_id, stage=stage, status="running", pending_pause_stage=None)
                        return {"action": "continue"}
                command = control.commands.popleft()
                if command.command_type == "attach_note":
                    continue
                if command.command_type == "pause_after_stage":
                    pause_stage = command.payload.get("stage")
                    if pause_stage in PAUSEABLE_STAGES:
                        control.pause_points.add(pause_stage)
                        self._update_session(run_id, pause_points=sorted(control.pause_points))
                    continue
                if command.command_type == "set_auto_mode":
                    control.auto_mode = bool(command.payload.get("enabled", True))
                    self._update_session(run_id, auto_mode=control.auto_mode)
                    if stage == "evaluation_ready" and control.auto_mode and evaluation and evaluation.passed and evaluation.final_recommendation == "execute":
                        self._update_session(run_id, stage=stage, status="running", pending_pause_stage=None)
                        return {"action": "continue"}
                    continue
                if command.command_type == "cancel":
                    return {"action": "cancel"}
                if command.command_type in {"resume", "approve"}:
                    if stage == "evaluation_ready" and (evaluation is None or not evaluation.passed or evaluation.final_recommendation != "execute"):
                        self.state_store.append_run_event(
                            run_id,
                            stage="awaiting_operator",
                            event_type=APPROVAL_BLOCKED,
                            payload={
                                "reason": "evaluation did not pass",
                                "final_recommendation": evaluation.final_recommendation if evaluation else None,
                                "blocking_reasons": list(evaluation.blocking_reasons) if evaluation else [],
                            },
                            summary={
                                "status": "blocked",
                                "recommendation": evaluation.final_recommendation if evaluation else "unknown",
                            },
                            status="blocked",
                        )
                        continue
                    self._update_session(run_id, stage=stage, status="running", pending_pause_stage=None)
                    return {"action": "continue"}
                if command.command_type in {"override_decision", "override_execution_parameters"}:
                    self._update_session(run_id, stage="awaiting_operator", status="awaiting_operator")
                    return {"action": "override", "payload": {"type": command.command_type, **command.payload}}

    def _apply_override(self, decision: Decision, payload: dict[str, Any]) -> Decision:
        data = decision.to_dict()
        if payload["type"] == "override_decision":
            for key in ("decision_type", "summary", "autonomy_tier", "confidence"):
                if key in payload:
                    data[key] = payload[key]
            if "risk" in payload and isinstance(payload["risk"], dict):
                data["risk"] = {**data["risk"], **payload["risk"]}
            if "execution_plan" in payload and isinstance(payload["execution_plan"], dict):
                execution_plan = {**data["execution_plan"], **payload["execution_plan"]}
                if isinstance(data["execution_plan"].get("parameters"), dict) and isinstance(
                    payload["execution_plan"].get("parameters"), dict
                ):
                    execution_plan["parameters"] = {
                        **data["execution_plan"]["parameters"],
                        **payload["execution_plan"]["parameters"],
                    }
                data["execution_plan"] = execution_plan
        else:
            parameters = payload.get("parameters", {})
            data["execution_plan"]["parameters"] = {**data["execution_plan"]["parameters"], **parameters}
            if "rollback_plan" in payload:
                data["execution_plan"]["rollback_plan"] = payload["rollback_plan"]
        return Decision.from_dict(data)

    def _launch_evo(self, run_id: str, session: RunSession, payload: dict[str, Any]) -> None:
        launch_request = self._validate_evo_launch_request(run_id, session, payload)
        launch_id = f"evo_{run_id}_{uuid4().hex[:8]}"
        queued = {
            "launch_id": launch_id,
            "action": "status" if launch_request["workspace_detected"] else "discover_bootstrap",
            "status": "queued",
            "requested_at": _timestamp(),
            "repo_path": launch_request["repo_path"],
            "target_path": launch_request["target_path"],
            "benchmark_command": launch_request["benchmark_command"],
            "metric": launch_request["metric"],
            "instrumentation_mode": launch_request["instrumentation_mode"],
            "gate_command": launch_request["gate_command"],
            "workspace_detected": launch_request["workspace_detected"],
            "dashboard_url": None,
            "steps": [],
            "error": None,
        }
        self._upsert_evo_launch(run_id, queued)
        self.state_store.append_run_event(
            run_id,
            stage=session.stage,
            event_type=INTEGRATION_ARTIFACT_RECORDED,
            payload=queued,
            summary={"status": "queued", "action": queued["action"]},
            artifact_key="evo_launches",
            integration_name="evo",
            status="queued",
        )

        def runner() -> None:
            running = {**queued, "status": "running", "started_at": _timestamp()}
            self._upsert_evo_launch(run_id, running)
            current = self.state_store.get_run_session(run_id)
            self.state_store.append_run_event(
                run_id,
                stage=current.stage if current else session.stage,
                event_type=INTEGRATION_ARTIFACT_RECORDED,
                payload=running,
                summary={"status": "running", "action": running["action"]},
                artifact_key="evo_launches",
                integration_name="evo",
                status="running",
            )
            finished = self.evo_launcher.run_launch(
                run_id=run_id,
                repo_path=launch_request["repo_path"],
                target_path=launch_request["target_path"],
                benchmark_command=launch_request["benchmark_command"],
                metric=launch_request["metric"],
                instrumentation_mode=launch_request["instrumentation_mode"],
                gate_command=launch_request["gate_command"],
                note=launch_request["note"],
            )
            finished["launch_id"] = launch_id
            self._upsert_evo_launch(run_id, finished)
            latest = self.state_store.get_run_session(run_id)
            self.state_store.append_run_event(
                run_id,
                stage=latest.stage if latest else session.stage,
                event_type=INTEGRATION_ARTIFACT_RECORDED,
                payload=finished,
                summary={"status": finished["status"], "action": finished["action"]},
                artifact_key="evo_launches",
                integration_name="evo",
                status=finished["status"],
            )

        threading.Thread(target=runner, daemon=True).start()

    def _validate_evo_launch_request(
        self,
        run_id: str,
        session: RunSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        readiness = build_readiness(self.config)
        if not readiness.evo.ready:
            raise ValueError(f"Evo is not ready: {readiness.evo.detail}")
        decision_payload = session.artifacts.get("decision") if isinstance(session.artifacts, dict) else None
        if not isinstance(decision_payload, dict):
            raise ValueError("run does not have a decision artifact")
        trigger_payload = session.artifacts.get("trigger") if isinstance(session.artifacts, dict) else None
        input_payload = session.artifacts.get("input_signal") if isinstance(session.artifacts, dict) else None
        related_context: dict[str, Any] = {}
        for candidate in (trigger_payload, input_payload):
            if isinstance(candidate, dict) and isinstance(candidate.get("related_context"), dict):
                related_context = candidate["related_context"]
                break
        execution_plan = decision_payload.get("execution_plan")
        if not isinstance(execution_plan, dict) or execution_plan.get("system") != "repo_patch_service":
            raise ValueError("Evo launch is only supported for repo_patch_service runs")
        parameters = execution_plan.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("run decision is missing execution parameters")
        repo_path = str(parameters.get("repo_path") or related_context.get("repo_path") or "").strip()
        if not repo_path:
            raise ValueError("run does not define a repo_path for Evo")
        allowed_paths_raw = parameters.get("allowed_paths") if isinstance(parameters.get("allowed_paths"), list) else related_context.get("allowed_paths") or []
        allowed_paths = [str(path) for path in allowed_paths_raw if str(path).strip()]
        if not allowed_paths:
            raise ValueError("run does not define allowed_paths for Evo")
        test_commands_raw = parameters.get("test_commands") if isinstance(parameters.get("test_commands"), list) else related_context.get("test_commands") or []
        test_commands = [str(command) for command in test_commands_raw if str(command).strip()]
        if not test_commands:
            raise ValueError("run does not define test_commands for Evo")
        target_path = str(payload.get("target_path") or allowed_paths[0]).strip()
        if target_path not in allowed_paths:
            raise ValueError("target_path must be one of the run's allowed_paths")
        repo = Path(repo_path).resolve()
        if not repo.exists():
            raise ValueError("repo_path does not exist")
        workspace_detected = (repo / ".evo" / "meta.json").is_file()
        benchmark_command = str(payload.get("benchmark_command") or "").strip() or None
        if not workspace_detected and not benchmark_command:
            raise ValueError("benchmark_command is required when the repo does not already contain an Evo workspace")
        metric = str(payload.get("metric") or "max").strip()
        if metric not in {"max", "min"}:
            raise ValueError("metric must be `max` or `min`")
        instrumentation_mode = str(payload.get("instrumentation_mode") or "inline").strip()
        if instrumentation_mode not in {"sdk", "inline"}:
            raise ValueError("instrumentation_mode must be `sdk` or `inline`")
        gate_command = str(payload.get("gate_command") or test_commands[0]).strip()
        if not gate_command:
            raise ValueError("gate_command is required")
        return {
            "run_id": run_id,
            "repo_path": str(repo),
            "target_path": target_path,
            "benchmark_command": benchmark_command,
            "metric": metric,
            "instrumentation_mode": instrumentation_mode,
            "gate_command": gate_command,
            "workspace_detected": workspace_detected,
            "note": str(payload.get("note") or "mesh: bounded discover bootstrap").strip(),
        }

    def _upsert_evo_launch(self, run_id: str, launch: dict[str, Any]) -> None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return
        artifact = session.artifacts.get("evo_launches")
        launches = artifact.get("launches", []) if isinstance(artifact, dict) else []
        updated: list[dict[str, Any]] = []
        found = False
        for existing in launches:
            if isinstance(existing, dict) and existing.get("launch_id") == launch.get("launch_id"):
                updated.append(launch)
                found = True
            elif isinstance(existing, dict):
                updated.append(existing)
        if not found:
            updated.insert(0, launch)
        session.artifacts["evo_launches"] = {"launches": updated}
        session.updated_at = _timestamp()
        self.state_store.save_run_session(session)

    def _set_artifact(self, run_id: str, key: str, value: dict[str, Any]) -> None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return
        session.artifacts[key] = value
        session.updated_at = _timestamp()
        self.state_store.save_run_session(session)

    def _update_session(self, run_id: str, **updates: Any) -> None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return
        for key, value in updates.items():
            setattr(session, key, value)
        session.updated_at = _timestamp()
        self.state_store.save_run_session(session)

    def _normalize_pause_points(self, pause_points: list[str]) -> list[str]:
        return [stage for stage in pause_points if stage in PAUSEABLE_STAGES]

    def _resolve_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("signal_payload"), dict):
            return self._resolve_signal_placeholders(copy.deepcopy(payload["signal_payload"]))
        live_kubernetes = payload.get("live_signal")
        if isinstance(live_kubernetes, dict) and live_kubernetes.get("source") == "kubernetes":
            return self._resolve_live_kubernetes_signal(live_kubernetes)
        scenario_key = payload.get("scenario_key")
        if scenario_key:
            fixture_name = f"{scenario_key}.json"
            try:
                raw = copy.deepcopy(load_fixture("signals", fixture_name))
            except FileNotFoundError as exc:
                raise ValueError(
                    f"unknown scenario_key {scenario_key!r}: missing fixtures/signals/{fixture_name}"
                ) from exc
            signal = self._resolve_signal_placeholders(raw)
            signal["signal_id"] = f"{signal['signal_id']}_{uuid4().hex[:10]}"
            return signal
        raise ValueError("scenario_key or signal_payload is required")

    def _resolve_live_kubernetes_signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        deployment_name = str(payload.get("deployment_name") or "").strip()
        if not deployment_name:
            raise ValueError("live kubernetes signal requires deployment_name")
        namespace = str(payload.get("namespace") or "default").strip() or "default"
        patch_template = payload.get("patch_template")
        if patch_template is not None and not isinstance(patch_template, dict):
            raise ValueError("live kubernetes patch_template must be an object when provided")
        try:
            signal = collect_kubernetes_signal(
                deployment_name=deployment_name,
                namespace=namespace,
                kube_context=payload.get("kube_context"),
                environment=str(payload.get("environment") or self.config.environment),
                cluster_label=payload.get("cluster_label"),
                service=payload.get("service"),
                kubectl_command=str(payload.get("kubectl_command") or self.config.kubectl_command),
                tail_lines=int(payload.get("tail_lines") or 20),
                max_log_pods=int(payload.get("max_log_pods") or 3),
                repo_path=payload.get("repo_path"),
                suspected_file=payload.get("suspected_file"),
                allowed_paths=list(payload.get("allowed_paths") or []),
                test_commands=list(payload.get("test_commands") or []),
                patch_template={
                    "target_file": patch_template.get("target_file"),
                    "find": patch_template.get("find"),
                    "replace": patch_template.get("replace"),
                }
                if isinstance(patch_template, dict)
                else None,
            )
        except RuntimeError as exc:
            raise ValueError(f"live kubernetes signal collection failed: {exc}") from exc
        return self._resolve_signal_placeholders(signal)

    def _resolve_run_label(self, payload: dict[str, Any]) -> str | None:
        scenario_key = payload.get("scenario_key")
        if isinstance(scenario_key, str) and scenario_key:
            return scenario_key
        live_kubernetes = payload.get("live_signal")
        if isinstance(live_kubernetes, dict) and live_kubernetes.get("source") == "kubernetes":
            namespace = str(live_kubernetes.get("namespace") or "default")
            deployment_name = str(live_kubernetes.get("deployment_name") or "deployment")
            return f"live_kubernetes:{namespace}/{deployment_name}"
        return None

    def _resolve_signal_placeholders(self, signal: dict[str, Any]) -> dict[str, Any]:
        related_context = signal.get("related_context")
        if not isinstance(related_context, dict):
            return signal
        if related_context.get("repo_path") == "__FIXTURE_REPO__":
            resolved_repo_path = self._resolve_fixture_repo_path()
            if resolved_repo_path:
                related_context["repo_path"] = resolved_repo_path
        return signal

    def _resolve_fixture_repo_path(self) -> str | None:
        candidates = [
            Path("/workspace/mesh-intelligence/fixtures/codebases/search_service"),
            Path(__file__).resolve().parents[1] / "fixtures" / "codebases" / "search_service",
        ]
        for candidate in candidates:
            if candidate.exists():
                workspace_root = Path(self.config.state_directory) / "fixture-workspaces" / uuid4().hex
                destination = workspace_root / candidate.name
                workspace_root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(candidate, destination)
                return str(destination)
        return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
