from __future__ import annotations

import copy
import json
import shutil
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.runtime import MeshRuntimeEngine
from services.ingest.webhook_service import (
    WebhookIngestService,
    build_signal_from_alert,
)
from shared.mesh_runtime import (
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
    TRIGGER_READY,
    Decision,
    EvaluationResult,
    Trigger,
    load_fixture,
)
from shared.mesh_runtime.alert_store import AlertStore
from shared.mesh_runtime.control_plane_models import GoalRecord, RunSession, SteeringCommand
from shared.mesh_runtime.control_plane_state import ControlPlaneStateStore
from shared.mesh_runtime.integrations import GitNexusSidecarManager, build_readiness
from shared.mesh_runtime.webhook_templates import AlertEvent


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
ALLOWED_STEERING_COMMANDS = {
    "approve",
    "cancel",
    "pause_after_stage",
    "resume",
    "set_auto_mode",
    "override_decision",
    "override_execution_parameters",
    "attach_note",
}


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
        self.sidecar = GitNexusSidecarManager(self.config)
        self.controls: dict[str, RunControl] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.state_store.ensure_default_goal()
        self.alert_store = AlertStore(self.config.state_directory)
        self.webhook_service = WebhookIngestService(
            alert_store=self.alert_store,
            run_factory=self._spawn_run_from_alert,
        )
        # Readiness probes shell out to Promptfoo / Goose / GitNexus, which is
        # slow enough that the UI polling path would dominate our CPU on a busy
        # system. Cache the snapshot with a short TTL — the observable staleness
        # is bounded but calls drop from ~100ms to ~1us for the hot loop.
        self._readiness_cache: tuple[float, dict[str, Any]] | None = None
        self._readiness_ttl_seconds = 10.0
        self._readiness_lock = threading.Lock()

    def ensure_sidecar(self) -> bool:
        return self.sidecar.ensure_running()

    def build_readiness(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._readiness_lock:
            cached = self._readiness_cache
            if not force and cached and now - cached[0] < self._readiness_ttl_seconds:
                return cached[1]
        snapshot = build_readiness(self.config).to_dict()
        with self._readiness_lock:
            self._readiness_cache = (now, snapshot)
        return snapshot

    def invalidate_readiness(self) -> None:
        with self._readiness_lock:
            self._readiness_cache = None

    # ---- webhook surface --------------------------------------------------

    def register_webhook_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.webhook_service.register_source(payload)

    def list_webhook_sources(self) -> list[dict[str, Any]]:
        return self.webhook_service.list_sources()

    def get_webhook_source(self, source_id: str) -> dict[str, Any]:
        return self.webhook_service.get_source(source_id)

    def delete_webhook_source(self, source_id: str) -> None:
        self.webhook_service.delete_source(source_id)

    def ingest_webhook(
        self,
        source_id: str,
        payload: dict[str, Any],
        raw_body: bytes | None = None,
        signature: str | None = None,
    ) -> dict[str, Any]:
        return self.webhook_service.ingest(source_id, payload, raw_body=raw_body, signature=signature)

    def list_alert_events(self, source_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.webhook_service.list_events(source_id, limit=limit)

    def _spawn_run_from_alert(self, event: AlertEvent, record: dict[str, Any]) -> dict[str, Any]:
        signal_payload = build_signal_from_alert(event)
        goal_id = record.get("goal_id") or self.state_store.ensure_default_goal().goal_id
        return self.create_run(
            {
                "goal_id": goal_id,
                "signal_payload": signal_payload,
                "steering_mode": record.get("steering_mode") or self.config.default_steering_mode,
                "evaluation_mode": self.config.evaluation_mode,
                "orchestration_mode": self.config.orchestration_mode,
            }
        )

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

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return None
        return {
            **session.to_dict(),
            "events": [event.to_dict() for event in self.state_store.list_run_events(run_id)],
            "merkle": self.state_store.get_merkle_snapshot(run_id).to_dict(),
        }

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
        scenario_key = payload.get("scenario_key")
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
                "goose_ready": readiness_snapshot["goose"]["ready"],
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
        command = SteeringCommand(
            command_id=f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{len(session.operator_notes) + 1}",
            run_id=run_id,
            command_type=command_type,
            issued_at=_timestamp(),
            payload={key: value for key, value in payload.items() if key != "command"},
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
            self._wait_if_needed(run_id, "trigger_ready", trigger=trigger, decision=None, evaluation=None)

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
            if execution.external_refs.get("goose_review"):
                self._set_artifact(run_id, "goose_review", execution.external_refs["goose_review"])
                self.state_store.append_run_event(
                    run_id,
                    stage="executing",
                    event_type=INTEGRATION_ARTIFACT_RECORDED,
                    payload=execution.external_refs["goose_review"],
                    summary={"approved": execution.external_refs["goose_review"].get("approved")},
                    artifact_key="goose_review",
                    integration_name="goose",
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
        scenario_key = payload.get("scenario_key")
        if scenario_key:
            signal = self._resolve_signal_placeholders(copy.deepcopy(load_fixture("signals", f"{scenario_key}.json")))
            signal["signal_id"] = f"{signal['signal_id']}_{uuid4().hex[:10]}"
            return signal
        raise ValueError("scenario_key or signal_payload is required")

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
