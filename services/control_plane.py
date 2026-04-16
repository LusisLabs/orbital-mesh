from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.runtime import MeshRuntimeEngine
from services.orchestrator.agent_mesh import AgentMeshService
from services.orchestrator.evo_launcher import EvoLaunchService
from services.scenario_analysis import ScenarioAnalysisService
from shared.mesh_runtime import (
    AGENT_TASK_RECORDED,
    APPROVAL_BLOCKED,
    DECISION_READY,
    EVIDENCE_NODE_RECORDED,
    EVALUATION_READY,
    EXECUTION_RECORDED,
    FEEDBACK_RECORDED,
    INTEGRATION_ARTIFACT_RECORDED,
    INTEGRATION_READINESS_RECORDED,
    MEMORY_COMPACTION_RECORDED,
    NORMALIZED_EVENT,
    NO_TRIGGER,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_QUEUED,
    SCENARIO_ANALYSIS_READY,
    RuntimeConfig,
    STEERING_COMMAND,
    STEERING_REJECTED,
    SUBDECISION_RECORDED,
    TRIGGER_READY,
    Decision,
    ExecutionRecord,
    EvaluationResult,
    Trigger,
    load_fixture,
)
from shared.mesh_runtime.control_plane_models import GoalRecord, RunSession, SteeringCommand
from services.signal_correlator import SignalCorrelator
from services.watch_daemon import WatchDaemon, WatchTarget
from shared.mesh_runtime.context_store import ContextStore
from shared.mesh_runtime.mesh_state_store import MeshStateStore
from shared.mesh_runtime.state_store_factory import build_mesh_state_store
from shared.mesh_runtime.integrations import GitNexusSidecarManager, build_readiness
from shared.mesh_runtime.learning import LearningStore
from shared.mesh_runtime.active_memory import ActiveMemoryStore
from shared.mesh_runtime.research import (
    build_research_corpus_intelligence,
    build_research_session_intelligence,
    sanitize_research_markdown,
)


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
    "launch_evo",
}

# Operator steering is analogous to activation steering: early / late interventions have different
# leverage and failure modes. Decision-changing commands are restricted to pre-execution gates so we
# do not "perturb late layers" after execution has run (incoherent or misleading audit trails).
_STEERING_DECISION_COMMANDS = frozenset({"override_decision", "override_execution_parameters"})
_STEERING_EARLY_STAGES = frozenset({"ingesting", "trigger_ready"})
_STEERING_PAYLOAD_CAP_BYTES = int(os.getenv("MESH_MAX_STEERING_PAYLOAD_BYTES", "65536"))
_LOG = logging.getLogger("mesh.control_plane")


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


def _evidence_graph(analysis: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for evidence in analysis.get("evidence_nodes", []):
        evidence_id = evidence.get("evidence_id")
        if not evidence_id:
            continue
        nodes.append(
            {
                "id": evidence_id,
                "type": "evidence",
                "label": evidence.get("summary", evidence.get("kind", "evidence")),
                "analyzer": evidence.get("analyzer"),
                "confidence": evidence.get("confidence"),
            }
        )
    for subdecision in analysis.get("subdecisions", []):
        subdecision_id = subdecision.get("subdecision_id")
        if not subdecision_id:
            continue
        nodes.append(
            {
                "id": subdecision_id,
                "type": "subdecision",
                "label": subdecision.get("recommendation"),
                "analyzer": subdecision.get("analyzer"),
                "requires_review": subdecision.get("requires_review"),
            }
        )
        for evidence_ref in subdecision.get("evidence_refs", []):
            edges.append({"source": evidence_ref, "target": subdecision_id, "kind": "supports"})
        edges.append({"source": subdecision_id, "target": analysis.get("analysis_id"), "kind": "feeds"})
    nodes.append(
        {
            "id": analysis.get("analysis_id"),
            "type": "scenario_analysis",
            "label": analysis.get("suggested_decision_type"),
            "merkle_root": analysis.get("merkle_root"),
        }
    )
    return {"nodes": nodes, "edges": edges, "merkle_root": analysis.get("merkle_root")}


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
        state_store: MeshStateStore | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or build_mesh_state_store(self.config)
        self.sidecar = GitNexusSidecarManager(self.config)
        self.learning_store = LearningStore(self.config.state_directory, state_store=self.state_store)
        self.context_store = ContextStore(self.config.state_directory)
        self.active_memory = ActiveMemoryStore(self.config.state_directory)
        self.scenario_analysis = ScenarioAnalysisService(
            state_store=self.state_store,
            learning_store=self.learning_store,
            context_store=self.context_store,
            active_memory=self.active_memory,
        )
        self._lock = threading.Lock()
        self.agent_mesh = AgentMeshService(config=self.config)
        self.evo_launcher = EvoLaunchService(self.config)
        self.controls: dict[str, RunControl] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._watch_daemon: WatchDaemon | None = None
        if self.config.watch_enabled and self.config.watch_targets:
            targets = [
                WatchTarget(
                    deployment_name=t["deployment_name"],
                    namespace=t.get("namespace", "default"),
                    kube_context=t.get("kube_context"),
                )
                for t in self.config.watch_targets
            ]
            correlator = None
            if self.config.correlation_enabled:
                correlator = SignalCorrelator(
                    window_seconds=self.config.correlation_window_seconds,
                    min_signals=self.config.correlation_min_signals,
                )
            self._watch_daemon = WatchDaemon(
                coordinator=self,
                targets=targets,
                interval_seconds=self.config.watch_interval_seconds,
                default_cooldown_seconds=self.config.watch_cooldown_seconds,
                correlator=correlator,
            )
        self.state_store.ensure_default_goal()

    def ensure_sidecar(self) -> bool:
        return self.sidecar.ensure_running()

    def start_watch_daemon(self) -> None:
        if self._watch_daemon is not None:
            self._watch_daemon.start()

    def watch_status(self) -> dict[str, Any]:
        if self._watch_daemon is None:
            return {"running": False, "targets": [], "enabled": False}
        return {**self._watch_daemon.status(), "enabled": True}

    def watch_start(self) -> dict[str, Any]:
        if self._watch_daemon is not None:
            self._watch_daemon.start()
        return self.watch_status()

    def watch_stop(self) -> dict[str, Any]:
        if self._watch_daemon is not None:
            self._watch_daemon.stop()
        return self.watch_status()

    def stop_watch_daemon(self) -> None:
        if self._watch_daemon is not None:
            self._watch_daemon.stop()

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

    def list_research_sessions(self) -> list[dict[str, Any]]:
        research_root = Path(self.config.research_directory)
        if not research_root.is_dir():
            return []
        sessions: list[dict[str, Any]] = []
        for session_dir in sorted((p for p in research_root.iterdir() if p.is_dir()), reverse=True):
            manifest_path = session_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            final_report = session_dir / "synthesis" / "final-report.md"
            intelligence = build_research_session_intelligence(session_dir, manifest)
            sessions.append({
                **manifest,
                "has_final_report": final_report.is_file(),
                "research_intelligence": intelligence,
            })
        return sessions

    def get_research_session(self, session_id: str) -> dict[str, Any] | None:
        research_root = Path(self.config.research_directory)
        session_dir = research_root / session_id
        if not session_dir.is_dir():
            return None
        manifest_path = session_dir / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        final_report_path = session_dir / "synthesis" / "final-report.md"
        final_report_markdown: str | None = None
        if final_report_path.is_file():
            raw = final_report_path.read_text(encoding="utf-8", errors="replace")
            final_report_markdown = sanitize_research_markdown(raw)
        intelligence = build_research_session_intelligence(session_dir, manifest)
        return {
            **manifest,
            "final_report_markdown": final_report_markdown,
            "research_intelligence": intelligence,
        }

    def get_research_corpus(self) -> dict[str, Any]:
        research_root = Path(self.config.research_directory)
        return build_research_corpus_intelligence(research_root)

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

    def get_scenario_analysis(self, run_id: str) -> dict[str, Any] | None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return None
        artifact = session.artifacts.get("scenario_analysis")
        return artifact if isinstance(artifact, dict) else None

    def get_evidence_graph(self, run_id: str) -> dict[str, Any] | None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return None
        artifact = session.artifacts.get("evidence_graph")
        return artifact if isinstance(artifact, dict) else None

    def get_active_memory(self, service: str | None = None) -> dict[str, Any]:
        return self.active_memory.active_facts(service)

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
        signal_payload = self._resolve_signal(payload)
        scenario_key = payload.get("scenario_key")
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
        with self._lock:
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
        with self._lock:
            self._threads[session.run_id] = worker
        worker.start()
        return self.get_run(session.run_id) or session.to_dict()

    def steer_run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        command_type = payload.get("command")
        if command_type not in ALLOWED_STEERING_COMMANDS:
            raise ValueError(f"unsupported steering command: {command_type}")
        session = self.state_store.get_run_session(run_id)
        with self._lock:
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
        command_event = self.state_store.append_run_event(
            run_id,
            stage=session.stage,
            event_type=STEERING_COMMAND,
            payload=command.to_dict(),
            summary={"command": command_type},
            artifact_key="operator_command",
            status="received",
        )
        self.state_store.record_approval(
            run_id,
            {
                "event_id": command_event.event_id,
                "command_id": command.command_id,
                "command_type": command.command_type,
                "issued_at": command.issued_at,
                "payload": command.payload,
            },
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
        engine = MeshRuntimeEngine(
            config=run_config,
            state_store=self.state_store.runtime_store,
            learning_store=self.learning_store,
            context_store=self.context_store,
        )
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
                self.state_store.append_run_event(
                    run_id,
                    stage="no_trigger",
                    event_type=NO_TRIGGER,
                    payload={"reason": "signal did not satisfy trigger thresholds"},
                    summary={"status": "completed"},
                    status="completed",
                )
                self._update_session(run_id, stage="no_trigger", status="completed")
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
                    self.state_store.append_run_event(
                        run_id,
                        stage="cancelled",
                        event_type=RUN_CANCELLED,
                        payload={"reason": "operator_cancelled"},
                        summary={"status": "cancelled"},
                        status="cancelled",
                    )
                    self._update_session(run_id, stage="cancelled", status="cancelled")
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

            scenario_analysis = None
            try:
                scenario_analysis = self._record_scenario_analysis(run_id, trigger)
            except Exception as exc:
                self.state_store.append_run_event(
                    run_id,
                    stage="scenario_analysis_ready",
                    event_type=SCENARIO_ANALYSIS_READY,
                    payload={"error": str(exc), "fallback": "existing_decision_service"},
                    summary={"status": "failed"},
                    artifact_key="scenario_analysis",
                    status="failed",
                )
                _LOG.exception("Scenario analysis failed for run %s", run_id)

            decision = engine.decision.decide(trigger, scenario_analysis=scenario_analysis)
            evaluation = self._record_decision_and_evaluation(run_id, engine, trigger, decision)

            while True:
                outcome = self._wait_if_needed(run_id, "evaluation_ready", trigger=trigger, decision=decision, evaluation=evaluation)
                if outcome["action"] == "continue":
                    break
                if outcome["action"] == "cancel":
                    self.state_store.append_run_event(
                        run_id,
                        stage="cancelled",
                        event_type=RUN_CANCELLED,
                        payload={"reason": "operator_cancelled"},
                        summary={"status": "cancelled"},
                        status="cancelled",
                    )
                    self._update_session(run_id, stage="cancelled", status="cancelled")
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
            review_artifact = self._execution_review_artifact(execution)
            if review_artifact:
                artifact_key, integration_name, payload = review_artifact
                self._set_artifact(run_id, artifact_key, payload)
                self.state_store.append_run_event(
                    run_id,
                    stage="executing",
                    event_type=INTEGRATION_ARTIFACT_RECORDED,
                    payload=payload,
                    summary={"approved": payload.get("approved")},
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
                    self.state_store.append_run_event(
                        run_id,
                        stage="cancelled",
                        event_type=RUN_CANCELLED,
                        payload={"reason": "operator_cancelled"},
                        summary={"status": "cancelled"},
                        status="cancelled",
                    )
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
            self.state_store.append_run_event(
                run_id,
                stage="completed",
                event_type=RUN_COMPLETED,
                payload={"execution_status": execution.status, "feedback_outcome": feedback.outcome},
                summary={"status": "completed"},
                status="completed",
            )
            self._update_session(run_id, stage="completed", status="completed")
            self._record_learning(trigger, decision, feedback, run_id)
        except Exception as exc:
            self.state_store.append_run_event(
                run_id,
                stage="failed",
                event_type=RUN_FAILED,
                payload={"error": str(exc)},
                summary={"status": "failed"},
                status="failed",
            )
            self._update_session(run_id, stage="failed", status="failed", error=str(exc))
        finally:
            with self._lock:
                self._threads.pop(run_id, None)

    def _execution_review_artifact(self, execution: ExecutionRecord) -> tuple[str, str, dict[str, Any]] | None:
        if not isinstance(execution.external_refs, dict):
            return None
        for artifact_key, integration_name in (("hermes_review", "hermes"), ("goose_review", "goose")):
            payload = execution.external_refs.get(artifact_key)
            if isinstance(payload, dict):
                return artifact_key, integration_name, payload
        return None

    def _record_learning(
        self,
        trigger: Trigger,
        decision: Decision,
        feedback: Any,
        run_id: str,
    ) -> None:
        try:
            self.learning_store.record_outcome(
                decision_type=decision.decision_type,
                service=trigger.service,
                endpoint=trigger.endpoint,
                outcome=feedback.outcome,
                world_model_updates=feedback.world_model_updates if hasattr(feedback, "world_model_updates") else {},
            )
            completed_session = self.state_store.get_run_session(run_id)
            if completed_session:
                self.context_store.update_from_run(completed_session.to_dict())
        except Exception:
            _LOG.exception("Learning persistence failed for run %s", run_id)

    def _record_scenario_analysis(self, run_id: str, trigger: Trigger):
        self._update_session(run_id, stage="scenario_analysis_ready", status="running")
        analysis, memory_compaction = self.scenario_analysis.analyze(trigger, run_id=run_id)
        merkle_event_ids: list[str] = []
        for evidence in analysis.evidence_nodes:
            event = self.state_store.append_run_event(
                run_id,
                stage="scenario_analysis_ready",
                event_type=EVIDENCE_NODE_RECORDED,
                payload=evidence,
                summary={"analyzer": evidence.get("analyzer"), "kind": evidence.get("kind")},
                artifact_key="scenario_analysis",
                status="recorded",
            )
            merkle_event_ids.append(event.event_id)
        for subdecision in analysis.subdecisions:
            event = self.state_store.append_run_event(
                run_id,
                stage="scenario_analysis_ready",
                event_type=SUBDECISION_RECORDED,
                payload=subdecision,
                summary={
                    "analyzer": subdecision.get("analyzer"),
                    "recommendation": subdecision.get("recommendation"),
                    "requires_review": subdecision.get("requires_review"),
                },
                artifact_key="scenario_analysis",
                status="recorded",
            )
            merkle_event_ids.append(event.event_id)

        merkle = self.state_store.get_merkle_snapshot(run_id)
        analysis.merkle_root = merkle.root_hash
        analysis.merkle_event_ids = merkle_event_ids
        analysis.validate()
        analysis_payload = analysis.to_dict()
        self._set_artifact(run_id, "scenario_analysis", analysis_payload)
        self._set_artifact(run_id, "evidence_graph", _evidence_graph(analysis_payload))
        self.state_store.append_run_event(
            run_id,
            stage="scenario_analysis_ready",
            event_type=SCENARIO_ANALYSIS_READY,
            payload=analysis_payload,
            summary={
                "suggested_decision_type": analysis.suggested_decision_type,
                "required_review_count": len(analysis.required_review_reasons),
            },
            artifact_key="scenario_analysis",
            status="recorded",
        )

        if memory_compaction is not None:
            memory_compaction.merkle_root = merkle.root_hash
            memory_payload = memory_compaction.to_dict()
            self._set_artifact(run_id, "memory_compaction", memory_payload)
            self.state_store.append_run_event(
                run_id,
                stage="scenario_analysis_ready",
                event_type=MEMORY_COMPACTION_RECORDED,
                payload=memory_payload,
                summary={
                    "active_facts": len(memory_compaction.active_facts),
                    "suppressed_facts": len(memory_compaction.suppressed_facts),
                },
                artifact_key="memory_compaction",
                status="recorded",
            )
        return analysis

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
        live_signal = payload.get("live_signal")
        if isinstance(live_signal, dict) and live_signal.get("source") == "kubernetes":
            return self._collect_live_kubernetes_signal(live_signal, payload)
        scenario_key = payload.get("scenario_key")
        if isinstance(scenario_key, str) and scenario_key.startswith("live_kubernetes:"):
            remainder = scenario_key[len("live_kubernetes:") :].strip()
            if "/" not in remainder:
                raise ValueError(
                    f"invalid live_kubernetes scenario_key {scenario_key!r}: "
                    "expected live_kubernetes:<namespace>/<deployment_name>"
                )
            namespace, deployment_name = remainder.split("/", 1)
            namespace = namespace.strip()
            deployment_name = deployment_name.strip()
            if not namespace or not deployment_name:
                raise ValueError(
                    f"invalid live_kubernetes scenario_key {scenario_key!r}: "
                    "namespace and deployment_name must be non-empty"
                )
            extras = payload.get("live_kubernetes")
            kube_context = None
            environment = "staging"
            if isinstance(extras, dict):
                kube_context = extras.get("kube_context")
                environment = str(extras.get("environment") or environment)
            kube_context = kube_context or payload.get("kube_context")
            environment = str(payload.get("environment") or environment)
            if not kube_context:
                raise ValueError(
                    "live_kubernetes scenario_key requires kube_context "
                    '(e.g. \"kube_context\": \"k3d-mesh-e2e\" or '
                    '\"live_kubernetes\": {\"kube_context\": \"...\"})'
                )
            return self._collect_live_kubernetes_signal(
                {
                    "source": "kubernetes",
                    "deployment_name": deployment_name,
                    "namespace": namespace,
                    "kube_context": kube_context,
                    "environment": environment,
                },
                payload,
            )
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

    def _collect_live_kubernetes_signal(self, live_signal: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        from services.ingest.kubernetes_live_signal import collect_kubernetes_signal

        signal = collect_kubernetes_signal(
            deployment_name=live_signal["deployment_name"],
            namespace=live_signal.get("namespace", "default"),
            kube_context=live_signal.get("kube_context"),
            environment=live_signal.get("environment", "local"),
            kubectl_command=self.config.kubectl_command,
        )
        ns = live_signal.get("namespace", "default")
        name = live_signal["deployment_name"]
        payload["scenario_key"] = f"live_kubernetes:{ns}/{name}"
        return signal

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
