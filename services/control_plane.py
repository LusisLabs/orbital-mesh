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
from services.ingest.webhook_service import (
    WebhookIngestService,
    build_signal_from_alert,
)
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
from shared.mesh_runtime.alert_store import AlertStore
from shared.mesh_runtime.control_plane_models import GoalRecord, RunSession, SteeringCommand
from services.signal_correlator import SignalCorrelator
from services.watch_daemon import WatchDaemon, WatchTarget
from shared.mesh_runtime.context_store import ContextStore
from shared.mesh_runtime.infra_graph import InfraGraph
from shared.mesh_runtime.trust_ladder import TrustLadder
from shared.mesh_runtime.mesh_state_store import MeshStateStore
from shared.mesh_runtime.state_store_factory import build_mesh_state_store
from shared.mesh_runtime.integrations import GitNexusSidecarManager, build_readiness
from shared.mesh_runtime.integrations import resolve_integrations_config
from shared.mesh_runtime.learning import LearningStore
from shared.mesh_runtime.active_memory import ActiveMemoryStore
from shared.mesh_runtime.research import (
    build_research_corpus_intelligence,
    build_research_session_intelligence,
    sanitize_research_markdown,
)
from shared.mesh_runtime.webhook_templates import AlertEvent
from services.orchestrator.hermes_adapter import HermesCliAdapter, NativeHermesAdapter


PAUSEABLE_STAGES = {"trigger_ready", "decision_ready", "evaluation_ready", "feedback_ready"}
TERMINAL_STAGES = {"completed", "failed", "cancelled", "no_trigger", "recovery_spawned"}
ALLOWED_STEERING_COMMANDS = {
    "approve",
    "cancel",
    "pause_after_stage",
    "resume",
    "set_auto_mode",
    "override_decision",
    "override_execution_parameters",
    "explain_blockers",
    "chat_with_hermes",
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
    if command_type == "explain_blockers":
        effective = session.pending_pause_stage or session.stage
        if effective != "evaluation_ready":
            raise ValueError(
                f"steering command {command_type!r} is not allowed at stage {effective!r} "
                f"(run stage {session.stage!r}). "
                "Hermes explanation is accepted only when the run is paused at evaluation_ready."
            )
        return
    if command_type == "chat_with_hermes":
        effective = session.pending_pause_stage or session.stage
        if effective != "evaluation_ready":
            raise ValueError(
                f"steering command {command_type!r} is not allowed at stage {effective!r} "
                f"(run stage {session.stage!r}). "
                "Hermes blocker chat is accepted only when the run is paused at evaluation_ready."
            )
        message = str(command_payload.get("message", "")).strip()
        if not message:
            raise ValueError("chat_with_hermes requires a non-empty message")
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
        self.infra_graph = InfraGraph(self.config.state_directory)
        self.trust_ladder = TrustLadder(
            self.config.state_directory,
            min_draft_runs=self.config.trust_ladder_min_draft_runs,
            min_approve_runs=self.config.trust_ladder_min_approve_runs,
            min_auto_runs=self.config.trust_ladder_min_auto_runs,
        )
        self.scenario_analysis = ScenarioAnalysisService(
            state_store=self.state_store,
            learning_store=self.learning_store,
            context_store=self.context_store,
            active_memory=self.active_memory,
        )
        self._lock = threading.Lock()
        self.agent_mesh = AgentMeshService(config=self.config, state_store=self.state_store)
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

    # --- Infra graph --------------------------------------------------

    def graph_status(self) -> dict[str, Any]:
        return self.infra_graph.status()

    def graph_refresh(self, *, namespaces: list[str] | None = None) -> dict[str, Any]:
        """Collect cluster topology via kubectl and update the graph."""
        from services.ingest.kubernetes_topology import collect_topology, TopologyCollectionError
        try:
            nodes, edges = collect_topology(
                kubectl_command=self.config.kubectl_command,
                namespaces=namespaces,
            )
        except TopologyCollectionError as exc:
            return {"status": "failed", "error": str(exc)}
        snapshot = self.infra_graph.update_snapshot(nodes, edges)
        return {
            "status": "succeeded",
            "recorded_at": snapshot.recorded_at,
            "node_count": len(snapshot.nodes),
            "edge_count": len(snapshot.edges),
        }

    def graph_snapshot(self) -> dict[str, Any] | None:
        snap = self.infra_graph.snapshot()
        return snap.to_dict() if snap is not None else None

    def graph_node(
        self,
        kind: str,
        name: str,
        namespace: str | None = None,
    ) -> dict[str, Any] | None:
        return self.infra_graph.get_node(kind, name, namespace)

    def graph_neighbors(
        self,
        kind: str,
        name: str,
        namespace: str | None = None,
        *,
        depth: int = 1,
        edge_kinds: list[str] | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        return self.infra_graph.neighbors(
            kind, name, namespace,
            depth=depth,
            edge_kinds=edge_kinds,
            direction=direction,
        )

    def graph_affected_services(
        self,
        deployment_name: str,
        namespace: str,
    ) -> list[str]:
        return self.infra_graph.affected_services(deployment_name, namespace)

    # --- Trust ladder -------------------------------------------------

    def trust_ladder_list(self) -> list[dict[str, Any]]:
        return self.trust_ladder.list_entries()

    def trust_ladder_entry(self, action_class: str, service: str) -> dict[str, Any]:
        return self.trust_ladder.get_entry(action_class, service)

    def trust_ladder_override(
        self,
        action_class: str,
        service: str,
        level: str,
        *,
        reason: str = "operator_override",
    ) -> dict[str, Any]:
        return self.trust_ladder.override_level(action_class, service, level, reason=reason)

    # --- Agent SLO / self-observability -------------------------------

    def agent_slo_report(self) -> dict[str, Any]:
        from shared.mesh_runtime.agent_slo import AgentSLOCalculator
        calculator = AgentSLOCalculator()
        # Pull recent runs to compute (cap at 500 for cost).
        runs = self.state_store.list_run_sessions(limit=500)
        return calculator.compute(runs).to_dict()

    def agent_slo_prometheus(self) -> str:
        from shared.mesh_runtime.agent_slo import AgentSLOCalculator, report_to_prometheus
        calculator = AgentSLOCalculator()
        runs = self.state_store.list_run_sessions(limit=500)
        report = calculator.compute(runs)
        return report_to_prometheus(report)

    def build_readiness(self) -> dict[str, Any]:
        # build_readiness() itself has a module-level TTL cache, so no wrapper
        # state is needed here; this method exists for the HTTP surface.
        return build_readiness(self.config).to_dict()

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

    def query_memory(self, query: str, scope: dict[str, Any] | None = None, limit: int = 10) -> dict[str, Any]:
        return self.state_store.retrieve_memory({"query": query, "scope": scope or {}, "limit": limit})

    def get_memory_claim(self, claim_id: str) -> dict[str, Any] | None:
        return self.state_store.get_claim(claim_id)

    def get_memory_graph(self, service: str | None = None) -> dict[str, Any]:
        scope = {"service": service} if service else {}
        claims = self.state_store.list_claims(scope, {"limit": 200})
        relationships = self.state_store.list_relationships(node_ids=[claim.get("claim_id") for claim in claims if claim.get("claim_id")], scope=scope)
        nodes = [
            {
                "id": claim.get("claim_id"),
                "type": claim.get("tier"),
                "label": claim.get("statement"),
                "state": claim.get("state"),
                "confidence": claim.get("confidence"),
            }
            for claim in claims
        ]
        edges = [
            {
                "id": relationship.get("relationship_id"),
                "source": relationship.get("from_id"),
                "target": relationship.get("to_id"),
                "type": relationship.get("type"),
                "confidence": relationship.get("confidence"),
            }
            for relationship in relationships
        ]
        return {"nodes": nodes, "edges": edges}

    def run_memory_maintenance(self) -> dict[str, Any]:
        return self.state_store.run_memory_maintenance()

    def get_memory_crystallization(self, run_id: str) -> dict[str, Any] | None:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return None
        artifact = session.artifacts.get("memory_crystallization")
        if artifact is None and session.stage == "completed":
            self._record_memory_crystallization(run_id)
            session = self.state_store.get_run_session(run_id)
            if session is not None:
                artifact = session.artifacts.get("memory_crystallization")
        return artifact if isinstance(artifact, dict) else None

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
        if command_type == "explain_blockers":
            self._explain_blockers(run_id, session)
            return self.get_run(run_id) or session.to_dict()
        if command_type == "chat_with_hermes":
            self._chat_with_hermes(run_id, session, str(command_payload.get("message", "")).strip())
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
            infra_graph=self.infra_graph,
            alert_store=self.alert_store,
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
            if self._maybe_launch_recovery_run(
                run_id,
                scenario_key=scenario_key,
                signal_payload=signal_payload,
                trigger=trigger,
                decision=decision,
                evaluation=evaluation,
            ):
                return

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
            self._record_memory_crystallization(run_id)
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

    def _explain_blockers(self, run_id: str, session: RunSession) -> None:
        decision, decision_payload, evaluation_payload, blocking_reasons, existing = self._hermes_blocker_context(run_id, session)
        explanation = self._hermes_adapter().explain_blockers(
            decision,
            evaluation_payload,
            blocking_reasons,
        )
        self._persist_hermes_explanation(
            run_id,
            decision_payload,
            blocking_reasons,
            existing,
            explanation,
        )

    def _chat_with_hermes(self, run_id: str, session: RunSession, user_message: str) -> None:
        decision, decision_payload, evaluation_payload, blocking_reasons, existing = self._hermes_blocker_context(run_id, session)
        history = existing.get("messages", []) if isinstance(existing.get("messages"), list) else []
        reply = self._hermes_adapter().chat_blockers(
            decision,
            evaluation_payload,
            blocking_reasons,
            [
                {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
                for item in history
                if isinstance(item, dict)
            ],
            user_message,
        )
        self._persist_hermes_explanation(
            run_id,
            decision_payload,
            blocking_reasons,
            existing,
            reply,
            user_message=user_message,
        )

    def _hermes_adapter(self):
        resolved = resolve_integrations_config(self.config)
        if resolved.hermes_command:
            return HermesCliAdapter(
                command=resolved.hermes_command,
                timeout_seconds=self.config.hermes_command_timeout_seconds,
            )
        return NativeHermesAdapter(config=self.config)

    def _hermes_blocker_context(
        self,
        run_id: str,
        session: RunSession,
    ) -> tuple[Decision, dict[str, Any], dict[str, Any], list[str], dict[str, Any]]:
        effective_stage = session.pending_pause_stage or session.stage
        if effective_stage != "evaluation_ready":
            raise ValueError("blocked-evaluation explanation is only available at evaluation_ready")
        decision_payload = session.artifacts.get("decision")
        evaluation_payload = session.artifacts.get("evaluation")
        if not isinstance(decision_payload, dict) or not isinstance(evaluation_payload, dict):
            raise ValueError("decision and evaluation artifacts are required before Hermes can explain blockers")
        blocking_reasons_raw = evaluation_payload.get("blocking_reasons")
        blocking_reasons = [str(reason) for reason in blocking_reasons_raw] if isinstance(blocking_reasons_raw, list) else []
        existing = session.artifacts.get("hermes_explanation")
        if not isinstance(existing, dict):
            existing = {}
        return Decision.from_dict(decision_payload), decision_payload, evaluation_payload, blocking_reasons, existing

    def _persist_hermes_explanation(
        self,
        run_id: str,
        decision_payload: dict[str, Any],
        blocking_reasons: list[str],
        existing: dict[str, Any],
        latest: dict[str, Any],
        *,
        user_message: str | None = None,
    ) -> None:
        messages = list(existing.get("messages", [])) if isinstance(existing.get("messages"), list) else []
        if user_message:
            messages.append({"role": "user", "content": user_message, "recorded_at": _timestamp()})
        assistant_reply = str(latest.get("assistant_reply", latest.get("summary", ""))).strip()
        if assistant_reply:
            messages.append({"role": "assistant", "content": assistant_reply, "recorded_at": _timestamp()})
        explanation_payload = {
            **existing,
            **latest,
            "assistant_reply": assistant_reply or latest.get("summary"),
            "blocking_reasons": blocking_reasons,
            "decision_type": decision_payload.get("decision_type"),
            "messages": messages,
        }
        self._set_artifact(run_id, "hermes_explanation", explanation_payload)
        self.state_store.append_run_event(
            run_id,
            stage="awaiting_operator",
            event_type=INTEGRATION_ARTIFACT_RECORDED,
            payload=explanation_payload,
            summary={
                "recommendation": explanation_payload.get("recommendation"),
                "next_action": explanation_payload.get("next_action"),
                "message_count": len(messages),
            },
            artifact_key="hermes_explanation",
            integration_name="hermes",
            status="recorded",
        )

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
            # Trust-ladder update: track per-(action_class, service) graduation
            action_class = decision.decision_type
            if action_class not in ("no_action", "escalate"):
                self.trust_ladder.record_outcome(
                    action_class=action_class,
                    service=trigger.service,
                    outcome=feedback.outcome,
                )
        except Exception:
            _LOG.exception("Learning persistence failed for run %s", run_id)

    def _record_memory_crystallization(self, run_id: str) -> None:
        try:
            from shared.mesh_runtime.memory_lifecycle import MemoryLifecycleService

            crystallization = MemoryLifecycleService(self.state_store).crystallize_run(run_id)
            self._set_artifact(run_id, "memory_crystallization", crystallization)
            self.state_store.append_run_event(
                run_id,
                stage="completed",
                event_type=INTEGRATION_ARTIFACT_RECORDED,
                payload=crystallization,
                summary={
                    "observations_recorded": crystallization.get("observations_recorded"),
                    "claims_recorded": crystallization.get("claims_recorded"),
                },
                artifact_key="memory_crystallization",
                integration_name="memory",
                status="recorded",
            )
        except Exception:
            _LOG.exception("Memory crystallization failed for run %s", run_id)

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

    def _maybe_launch_recovery_run(
        self,
        run_id: str,
        *,
        scenario_key: str | None,
        signal_payload: dict[str, Any],
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> bool:
        with self._lock:
            control = self.controls.get(run_id)
        if control is None or not control.auto_mode:
            return False
        if evaluation.passed and evaluation.final_recommendation == "execute":
            return False
        blocker_analysis = evaluation.stage_results.get("blocker_analysis", {})
        if not isinstance(blocker_analysis, dict) or not blocker_analysis.get("can_auto_remediate"):
            return False
        session = self.state_store.get_run_session(run_id)
        if session is None:
            return False
        existing_recovery = self._existing_recovery_context(session, trigger)
        retry_index = int(existing_recovery.get("retry_index", 0) or 0)
        retry_budget = int(existing_recovery.get("retry_budget", self.config.max_transient_retries) or self.config.max_transient_retries)
        if retry_index >= retry_budget:
            exhausted = {
                "status": "budget_exhausted",
                "parent_run_id": run_id,
                "root_run_id": existing_recovery.get("root_run_id") or run_id,
                "retry_index": retry_index,
                "retry_budget": retry_budget,
                "blocking_reasons": list(evaluation.blocking_reasons),
                "recoverable_blockers": list(blocker_analysis.get("recoverable_blockers", [])),
                "retry_hints": list(blocker_analysis.get("retry_hints", [])),
                "recorded_at": _timestamp(),
            }
            self._set_artifact(run_id, "recovery", exhausted)
            self.state_store.append_run_event(
                run_id,
                stage="evaluation_ready",
                event_type=INTEGRATION_ARTIFACT_RECORDED,
                payload=exhausted,
                summary={"status": "budget_exhausted"},
                artifact_key="recovery",
                integration_name="mesh",
                status="budget_exhausted",
            )
            return False
        child_payload, recovery_artifact = self._build_recovery_child_payload(
            session=session,
            scenario_key=scenario_key,
            signal_payload=signal_payload,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
            blocker_analysis=blocker_analysis,
            retry_index=retry_index,
            retry_budget=retry_budget,
            existing_recovery=existing_recovery,
        )
        child_run = self.create_run(child_payload)
        recovery_artifact["status"] = "launched"
        recovery_artifact["child_run_id"] = child_run["run_id"]
        recovery_artifact["launched_at"] = _timestamp()
        self._set_artifact(run_id, "recovery", recovery_artifact)
        self.state_store.append_run_event(
            run_id,
            stage="evaluation_ready",
            event_type=INTEGRATION_ARTIFACT_RECORDED,
            payload=recovery_artifact,
            summary={"status": "launched", "child_run_id": child_run["run_id"]},
            artifact_key="recovery",
            integration_name="mesh",
            status="launched",
        )
        self._update_session(run_id, stage="recovery_spawned", status="recovery_spawned", pending_pause_stage=None)
        return True

    def _build_recovery_child_payload(
        self,
        *,
        session: RunSession,
        scenario_key: str | None,
        signal_payload: dict[str, Any],
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
        blocker_analysis: dict[str, Any],
        retry_index: int,
        retry_budget: int,
        existing_recovery: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        next_retry_index = retry_index + 1
        evidence = self._collect_recovery_evidence(session.run_id, trigger, decision, evaluation, session)
        child_signal = copy.deepcopy(signal_payload)
        original_signal_id = str(child_signal.get("signal_id") or session.run_id)
        child_signal["signal_id"] = f"{original_signal_id}-retry-{next_retry_index}"
        related_context = child_signal.setdefault("related_context", {})
        prior_attempts = list(existing_recovery.get("previous_attempts", [])) if isinstance(existing_recovery.get("previous_attempts"), list) else []
        prior_attempts.append(
            {
                "run_id": session.run_id,
                "decision_type": decision.decision_type,
                "confidence": decision.confidence,
                "blocking_reasons": list(evaluation.blocking_reasons),
                "recoverable_blockers": list(blocker_analysis.get("recoverable_blockers", [])),
            }
        )
        recovery_context = {
            "root_run_id": existing_recovery.get("root_run_id") or session.run_id,
            "parent_run_id": session.run_id,
            "retry_index": next_retry_index,
            "retry_budget": retry_budget,
            "previous_attempts": prior_attempts[-retry_budget:],
            "prior_attempt_count": len(prior_attempts),
            "latest_decision_type": decision.decision_type,
            "parent_blocking_reasons": list(evaluation.blocking_reasons),
            "recoverable_blockers": list(blocker_analysis.get("recoverable_blockers", [])),
            "retry_hints": list(blocker_analysis.get("retry_hints", [])),
            "original_signal_id": original_signal_id,
            **evidence,
        }
        related_context["recovery_context"] = recovery_context
        related_context["similar_prior_cases"] = max(
            int(related_context.get("similar_prior_cases", 0) or 0),
            int(evidence.get("related_run_count", 0) or 0),
        )
        trigger_signals = list(related_context.get("trigger_signals", []))
        retry_marker = f"recovery_context_retry_{next_retry_index}"
        if retry_marker not in trigger_signals:
            trigger_signals.append(retry_marker)
        related_context["trigger_signals"] = trigger_signals
        child_payload = {
            "goal_id": session.goal_id,
            "scenario_key": scenario_key,
            "signal_payload": child_signal,
            "evaluation_mode": session.evaluation_mode,
            "orchestration_mode": session.orchestration_mode,
            "steering_mode": session.steering_mode,
            "pause_points": session.pause_points,
        }
        recovery_artifact = {
            "status": "queued",
            "root_run_id": recovery_context["root_run_id"],
            "parent_run_id": session.run_id,
            "retry_index": next_retry_index,
            "retry_budget": retry_budget,
            "decision_type": decision.decision_type,
            "blocking_reasons": list(evaluation.blocking_reasons),
            "recoverable_blockers": list(blocker_analysis.get("recoverable_blockers", [])),
            "retry_hints": list(blocker_analysis.get("retry_hints", [])),
            "evidence_summary": {
                key: recovery_context[key]
                for key in (
                    "corroborating_evidence_count",
                    "active_memory_count",
                    "similar_incident_count",
                    "related_run_count",
                    "scenario_evidence_count",
                    "promptfoo_failure_count",
                )
            },
        }
        return child_payload, recovery_artifact

    def _collect_recovery_evidence(
        self,
        run_id: str,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
        session: RunSession,
    ) -> dict[str, Any]:
        active_facts = self.active_memory.active_facts(trigger.service).get("services", {}).get(trigger.service, [])
        error_signatures = trigger.related_context.get("error_signatures", [])
        incident_key = "|".join(error_signatures) if isinstance(error_signatures, list) and error_signatures else decision.decision_type
        similar_incidents = self.context_store.get_similar_incidents(str(incident_key), limit=5)
        related_runs: list[dict[str, Any]] = []
        for related in self.state_store.list_run_sessions(limit=25):
            if related.run_id == run_id:
                continue
            artifacts = related.artifacts if isinstance(related.artifacts, dict) else {}
            related_trigger = artifacts.get("trigger", {})
            if related_trigger.get("service") != trigger.service:
                continue
            related_runs.append(
                {
                    "run_id": related.run_id,
                    "stage": related.stage,
                    "status": related.status,
                    "decision_type": artifacts.get("decision", {}).get("decision_type"),
                    "feedback_outcome": artifacts.get("feedback", {}).get("outcome"),
                }
            )
            if len(related_runs) >= 5:
                break
        promptfoo_artifact = evaluation.stage_results.get("promptfoo_quality", {}).get("artifacts", {})
        assertion_results = promptfoo_artifact.get("assertion_results", []) if isinstance(promptfoo_artifact, dict) else []
        failing_assertions = [
            {
                "name": item.get("name"),
                "reason": item.get("reason"),
            }
            for item in assertion_results
            if isinstance(item, dict) and not item.get("passed", False)
        ]
        scenario_analysis = session.artifacts.get("scenario_analysis", {}) if isinstance(session.artifacts, dict) else {}
        scenario_evidence_refs = scenario_analysis.get("evidence_refs", []) if isinstance(scenario_analysis, dict) else []
        hermes_explanation = session.artifacts.get("hermes_explanation", {}) if isinstance(session.artifacts, dict) else {}
        learning_context = self.learning_store.enrich_context(trigger.service, trigger.endpoint, trigger.flag_key)
        service_context = self.context_store.get_service_context(trigger.service)
        corroborating_evidence_count = sum(
            1
            for count in (
                len(active_facts),
                len(similar_incidents),
                len(related_runs),
                len(scenario_evidence_refs),
                len(failing_assertions),
            )
            if count > 0
        )
        return {
            "corroborating_evidence_count": corroborating_evidence_count,
            "active_memory_count": len(active_facts),
            "similar_incident_count": len(similar_incidents),
            "related_run_count": len(related_runs),
            "scenario_evidence_count": len(scenario_evidence_refs),
            "promptfoo_failure_count": len(failing_assertions),
            "service_context": service_context,
            "learning_context": learning_context,
            "similar_incidents": similar_incidents,
            "related_runs": related_runs,
            "failing_promptfoo_assertions": failing_assertions,
            "hermes_summary": hermes_explanation.get("assistant_reply"),
        }

    def _existing_recovery_context(self, session: RunSession, trigger: Trigger) -> dict[str, Any]:
        raw = trigger.related_context.get("recovery_context")
        if isinstance(raw, dict):
            return dict(raw)
        input_signal = session.artifacts.get("input_signal") if isinstance(session.artifacts, dict) else None
        if isinstance(input_signal, dict):
            related_context = input_signal.get("related_context")
            if isinstance(related_context, dict) and isinstance(related_context.get("recovery_context"), dict):
                return dict(related_context["recovery_context"])
        return {}

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
