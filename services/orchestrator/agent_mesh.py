from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import replace
from typing import Any, Callable

_LOG = logging.getLogger("mesh.orchestrator.agent_mesh")

from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    RuntimeConfig,
    Trigger,
    resolve_orchestration_topology,
)
from shared.mesh_runtime.agent_workers import DEFAULT_AGENT_WORKERS, build_agent_attempt, build_agent_task
from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentTask
from shared.mesh_runtime.mesh_state_store import MeshStateStore
from .deepagents_adapter import DeepAgentsAdapter
from .latentmas_adapter import LatentMasAdapter


_NATIVE_PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "airflow": {
        "display_name": "Apache Airflow",
        "category": "workflow_engine",
        "best_fit": "data_ml_pipelines",
        "agentic_surface": "dag_scheduling_operators_ui_monitoring",
        "supports_agentic_execution": False,
        "evaluator_signal": "dag_dependency_coverage",
        "integration_contract": ["dag_import", "operator_task_status", "schedule_state", "lineage_metadata"],
    },
    "temporal": {
        "display_name": "Temporal",
        "category": "workflow_engine",
        "best_fit": "durable_execution",
        "agentic_surface": "workflows_and_activities",
        "supports_agentic_execution": True,
        "evaluator_signal": "durability_retry_idempotency",
        "integration_contract": ["workflow_id", "run_id", "activity_attempts", "retry_policy", "failure_history"],
    },
    "dagster": {
        "display_name": "Dagster",
        "category": "data_orchestrator",
        "best_fit": "asset_centric_pipelines",
        "agentic_surface": "asset_lineage_testing_type_safety",
        "supports_agentic_execution": False,
        "evaluator_signal": "asset_lineage_materialization",
        "integration_contract": ["asset_key", "materialization_status", "lineage_edges", "asset_checks"],
    },
    "prefect": {
        "display_name": "Prefect",
        "category": "workflow_engine",
        "best_fit": "python_workflows",
        "agentic_surface": "hybrid_cloud_local_observability",
        "supports_agentic_execution": False,
        "evaluator_signal": "flow_state_observability",
        "integration_contract": ["flow_run_id", "task_run_states", "deployment_name", "work_pool"],
    },
    "flyte": {
        "display_name": "Flyte",
        "category": "ml_workflow",
        "best_fit": "reproducible_ml",
        "agentic_surface": "caching_versioning_kubernetes_native",
        "supports_agentic_execution": False,
        "evaluator_signal": "reproducibility_cache_version",
        "integration_contract": ["project", "domain", "launch_plan", "cache_key", "execution_id"],
    },
    "luigi": {
        "display_name": "Luigi",
        "category": "pipeline_manager",
        "best_fit": "simple_dags",
        "agentic_surface": "lightweight_dependency_graphs",
        "supports_agentic_execution": False,
        "evaluator_signal": "task_dependency_completion",
        "integration_contract": ["task_id", "requires", "output_target", "scheduler_state"],
    },
    "oozie": {
        "display_name": "Apache Oozie",
        "category": "hadoop_orchestrator",
        "best_fit": "big_data_jobs",
        "agentic_surface": "mapreduce_hive_integration",
        "supports_agentic_execution": False,
        "evaluator_signal": "hadoop_job_state",
        "integration_contract": ["coordinator_id", "workflow_id", "action_status", "hive_or_mapreduce_ref"],
    },
    "kubernetes": {
        "display_name": "Kubernetes",
        "category": "container_orchestration",
        "best_fit": "microservices",
        "agentic_surface": "operators_scaling_self_healing_service_mesh",
        "supports_agentic_execution": True,
        "evaluator_signal": "controller_reconciliation_health",
        "integration_contract": ["context", "namespace", "workload_ref", "controller_status", "events"],
    },
    "n8n": {
        "display_name": "n8n",
        "category": "low_code_workflows",
        "best_fit": "automation",
        "agentic_surface": "nodes_ai_visual_builder_integrations",
        "supports_agentic_execution": True,
        "evaluator_signal": "node_execution_trace",
        "integration_contract": ["workflow_id", "execution_id", "node_statuses", "credentials_scope"],
    },
}


class AgentMeshService:
    """Build read-only worker artifacts for a run.

    This first slice defines the full-stack contract that external agents can later
    implement through CLI/API adapters. It intentionally returns proposals only:
    Mesh still owns policy, tests, audit, Kubernetes actuation, and production gates.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        state_store: MeshStateStore | None = None,
        latentmas_adapter: LatentMasAdapter | None = None,
        deepagents_adapter: DeepAgentsAdapter | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store
        self.latentmas_adapter = latentmas_adapter or LatentMasAdapter(self.config)
        self.deepagents_adapter = deepagents_adapter or DeepAgentsAdapter(self.config)

    def build_tasks(
        self,
        *,
        run_id: str,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
        service_agent: dict[str, Any] | None = None,
        integration_readiness: dict[str, Any] | None = None,
    ) -> list[AgentTask]:
        memory_scope = self._memory_scope(run_id, trigger)
        memory_packet = self._memory_packet(memory_scope, trigger)
        candidate_agents = self._agents(trigger=trigger, decision=decision, service_agent=service_agent)
        readiness_snapshot = integration_readiness or {}
        topology = resolve_orchestration_topology(
            profile_path=self.config.orchestration_topology_profile_path,
            trigger=trigger,
            decision=decision,
            candidate_lanes=candidate_agents,
            configured_filter=self.config.agent_mesh_agents,
            service_agent=service_agent,
            readiness_snapshot=readiness_snapshot,
            ownership_registry_path=self.config.ownership_registry_path,
            connector_certification_registry_path=self.config.connector_certification_registry_path,
            policy_lifecycle_manifest_path=self.config.policy_lifecycle_manifest_path,
            threat_model_register_path=self.config.threat_model_register_path,
            state_directory=self.config.state_directory,
        )
        agents = list(topology.get("selected_agents") or candidate_agents)
        task = build_agent_task(
            run_id=run_id,
            kind=self._task_kind(decision),
            allowed_paths=self._allowed_paths(trigger),
            test_commands=self._test_commands(trigger),
            kubernetes_scope=self._kubernetes_scope(trigger, decision),
            memory_scope=memory_scope,
            memory_packet=memory_packet,
            memory_write_policy=self._memory_write_policy(),
            open_questions=self._open_questions(memory_packet),
            agents=agents,
            orchestration_topology=topology,
            lane_routing=topology,
        )
        attempts = self._collect_attempts(task=task, trigger=trigger, decision=decision, evaluation=evaluation)
        successful = [attempt for attempt in attempts if attempt.status == "completed" and not attempt.risk_flags]
        selected_attempt_id = successful[0].attempt_id if successful else attempts[0].attempt_id
        return [
            replace(
                task,
                status="completed",
                updated_at=attempts[-1].completed_at,
                attempts=attempts,
                selected_attempt_id=selected_attempt_id,
            )
        ]

    def _collect_attempts(
        self,
        *,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> list[AgentAttempt]:
        attempt_specs = self._attempt_specs(task=task, trigger=trigger, decision=decision, evaluation=evaluation)
        results: dict[str, AgentAttempt] = {}
        completed_agents: set[str] = set()
        completed_queue: queue.Queue[tuple[str, AgentAttempt]] = queue.Queue()

        def run_attempt(
            agent: str,
            adapter: str,
            builder: Callable[[], AgentAttempt],
        ) -> None:
            try:
                attempt = builder()
            # Broad catch is intentional: proposal lanes run independently and a crash in
            # one adapter must not sink the whole mesh run — we log the stack and record
            # a failed attempt so the run continues with the other lanes' proposals.
            except Exception as exc:  # pragma: no cover - defensive guard for proposal lanes
                _LOG.exception(
                    "agent_mesh proposal lane %s (%s) raised; task_id=%s run_id=%s",
                    agent,
                    adapter,
                    task.task_id,
                    task.run_id,
                )
                attempt = build_agent_attempt(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    agent=agent,
                    adapter=adapter,
                    status="failed",
                    summary=f"{agent} proposal lane failed during agent-task collection: {exc}",
                    risk_flags=["agent_mesh_attempt_failed"],
                    recommended_action="human_review",
                    output={"error": str(exc)},
                )
            completed_queue.put((agent, attempt))

        for spec in attempt_specs:
            worker = threading.Thread(
                target=run_attempt,
                args=(spec["agent"], spec["adapter"], spec["builder"]),
                daemon=True,
            )
            worker.start()

        deadline = time.monotonic() + float(self.config.agent_mesh_task_timeout_seconds)
        while len(completed_agents) < len(attempt_specs):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                agent, attempt = completed_queue.get(timeout=remaining)
            except queue.Empty:
                break
            results[agent] = attempt
            completed_agents.add(agent)

        attempts: list[AgentAttempt] = []
        for spec in attempt_specs:
            attempt = results.get(spec["agent"])
            if attempt is None:
                attempt = build_agent_attempt(
                    task_id=task.task_id,
                    run_id=task.run_id,
                    agent=spec["agent"],
                    adapter=spec["adapter"],
                    status="failed",
                    summary=(
                        f"{spec['agent']} proposal lane timed out after "
                        f"{self.config.agent_mesh_task_timeout_seconds}s during agent-task collection."
                    ),
                    risk_flags=["agent_mesh_timeout"],
                    recommended_action="human_review",
                    output={"timeout_seconds": self.config.agent_mesh_task_timeout_seconds},
                )
            attempts.append(attempt)
        return attempts

    def _attempt_specs(
        self,
        *,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        routed_agents = list(task.agents)
        if self.config.latentmas_enabled and "latentmas" in routed_agents:
            specs.append(
                {
                    "agent": "latentmas",
                    "adapter": "latentmas_http",
                    "builder": lambda: self.latentmas_adapter.build_attempt(
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                        ),
                }
            )
        if self.config.agent_fabric_mode == "deepagents":
            for agent in routed_agents:
                if agent == "latentmas":
                    continue
                specs.append(
                    {
                        "agent": agent,
                        "adapter": "deepagents",
                        "builder": lambda agent=agent: self.deepagents_adapter.build_lane_attempt(
                            agent=agent,
                            task=task,
                            trigger=trigger,
                            decision=decision,
                            evaluation=evaluation,
                        ),
                    }
                )
            return specs
        native_specs = (
            ("goose", "native_contract", lambda: self._goose_attempt(task, trigger, decision, evaluation)),
            ("hermes", "native_contract", lambda: self._hermes_attempt(task, trigger, decision, evaluation)),
            ("codex", "native_contract", lambda: self._codex_attempt(task, trigger, decision, evaluation)),
            ("claudecode", "native_contract", lambda: self._claude_code_attempt(task, trigger, decision, evaluation)),
            ("openclaw", "native_contract", lambda: self._openclaw_attempt(task, trigger, decision, evaluation)),
        )
        for agent, adapter, builder in native_specs:
            if agent in routed_agents:
                specs.append({"agent": agent, "adapter": adapter, "builder": builder})
        for agent in _NATIVE_PLATFORM_PROFILES:
            if agent in routed_agents:
                specs.append(
                    {
                        "agent": agent,
                        "adapter": "native_orchestration_contract",
                        "builder": lambda agent=agent: self._platform_attempt(agent, task, trigger, decision, evaluation),
                    }
                )
        return specs

    def _goose_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        action = decision.execution_plan.get("action")
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="goose",
            adapter="native_contract",
            status="completed",
            summary=(
                f"Operational plan: {action} for {decision.execution_plan.get('system')} "
                f"after evaluation returned {evaluation.final_recommendation}."
            ),
            recommended_action="execute" if evaluation.passed and evaluation.final_recommendation == "execute" else "human_review",
            output={
                "decision_type": decision.decision_type,
                "execution_plan": decision.execution_plan,
                "trigger_type": trigger.trigger_type,
            },
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[_proposal_observation("goose", trigger.service, f"Operational plan proposed for {decision.decision_type}.")],
            memory_actions_requested=["defer"],
        )

    def _hermes_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        context = trigger.related_context
        log_summary = context.get("log_summary") if isinstance(context, dict) else None
        primary_symptom = ""
        if isinstance(log_summary, dict):
            primary_symptom = str(log_summary.get("primary_symptom") or "")
        if not primary_symptom and isinstance(context, dict):
            primary_symptom = str(context.get("primary_symptom") or "")
        summary = primary_symptom or decision.reasoning.get("primary_hypothesis") or decision.summary
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="hermes",
            adapter="native_contract",
            status="completed",
            summary=f"Root-cause hypothesis: {summary}",
            recommended_action="root_cause_review",
            output={
                "reasoning": decision.reasoning,
                "related_context": trigger.related_context,
            },
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[_proposal_observation("hermes", trigger.service, summary)],
            contradictions_detected=list(task.memory_packet.get("contradictions", [])),
            memory_actions_requested=["review"],
        )

    def _codex_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        candidate = bool(trigger.related_context.get("code_remediation_candidate")) if isinstance(trigger.related_context, dict) else False
        risk_flags = [] if candidate and task.allowed_paths and task.test_commands else ["code_write_gate_closed"]
        summary = (
            "Code remediation candidate has bounded paths and tests; open a branch/PR after runtime recovery."
            if not risk_flags
            else "Code write worker is gated until repo path, allowed paths, and tests are present."
        )
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="codex",
            adapter="native_contract",
            status="completed",
            summary=summary,
            risk_flags=risk_flags,
            recommended_action="open_pr" if not risk_flags else "human_review",
            output={
                "allowed_paths": task.allowed_paths,
                "test_commands": task.test_commands,
                "evaluation_blocking_reasons": evaluation.blocking_reasons,
            },
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[
                _proposal_observation(
                    "codex",
                    trigger.service,
                    "Code remediation proposal is bounded by allowed paths and tests.",
                )
            ],
            claims_proposed=[
                {
                    "statement": "Code remediation should remain gated behind verified repository context and tests.",
                    "confidence": 0.62,
                }
            ],
            memory_actions_requested=["review"],
        )

    def _claude_code_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        risk_flags = ["evaluation_failed"] if not evaluation.passed else []
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="claudecode",
            adapter="native_contract",
            status="completed",
            summary=(
                "Review lane: verify blast radius, rollback semantics, and missing tests before promotion."
            ),
            risk_flags=risk_flags,
            recommended_action="review",
            output={
                "risk": decision.risk,
                "blocking_reasons": evaluation.blocking_reasons,
            },
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[
                _proposal_observation(
                    "claudecode",
                    trigger.service,
                    "Review lane validated blast radius, rollback semantics, and test coverage posture.",
                )
            ],
            contradictions_detected=list(task.memory_packet.get("contradictions", [])),
            memory_actions_requested=["review"],
        )

    def _openclaw_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        namespace = task.kubernetes_scope.get("namespace")
        context = task.kubernetes_scope.get("context") or task.kubernetes_scope.get("cluster")
        risk_flags = [] if namespace and context else ["kubernetes_scope_missing"]
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="openclaw",
            adapter="native_contract",
            status="completed",
            summary=(
                f"Staging operator lane scoped to {context}/{namespace}."
                if not risk_flags
                else "Staging operator lane requires explicit Kubernetes context and namespace."
            ),
            risk_flags=risk_flags,
            recommended_action="stage_validation" if not risk_flags else "human_review",
            output={"kubernetes_scope": task.kubernetes_scope},
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[
                _proposal_observation("openclaw", trigger.service, f"Staging scope reviewed for {namespace or 'unknown namespace'}.")
            ],
            memory_actions_requested=["defer"],
        )

    def _platform_attempt(
        self,
        agent: str,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        profile = _NATIVE_PLATFORM_PROFILES[agent]
        risk_flags = self._platform_risk_flags(agent, task)
        recommended_action = "integration_ready_proposal" if not risk_flags else "prepare_integration_scope"
        summary = (
            f"{profile['display_name']} mapped into native orchestration for "
            f"{profile['best_fit']} with evaluator signal {profile['evaluator_signal']}."
        )
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="native_orchestration_contract",
            status="completed",
            summary=summary,
            risk_flags=risk_flags,
            recommended_action=recommended_action,
            output={
                "platform": profile["display_name"],
                "category": profile["category"],
                "best_fit": profile["best_fit"],
                "supports_agentic_execution": profile["supports_agentic_execution"],
                "agentic_surface": profile["agentic_surface"],
                "native_evaluator_signal": profile["evaluator_signal"],
                "integration_contract": profile["integration_contract"],
                "mesh_authority": {
                    "evaluation_policy_authoritative": True,
                    "production_actuation_authoritative": True,
                    "external_platform_authority": "proposal_and_evidence_adapter",
                },
                "decision_type": decision.decision_type,
                "execution_plan": decision.execution_plan,
                "evaluation": {
                    "passed": evaluation.passed,
                    "final_recommendation": evaluation.final_recommendation,
                    "blocking_reasons": evaluation.blocking_reasons,
                },
                "kubernetes_scope": task.kubernetes_scope if agent == "kubernetes" else {},
            },
            citations=task.memory_packet.get("citations", []),
            observations_proposed=[
                _proposal_observation(
                    agent,
                    trigger.service,
                    f"{profile['display_name']} integration can contribute {profile['evaluator_signal']} evidence.",
                )
            ],
            claims_proposed=[
                {
                    "statement": (
                        f"{profile['display_name']} must remain a Mesh-governed adapter; "
                        "external platform state can inform evaluation but cannot override policy."
                    ),
                    "confidence": 0.74,
                }
            ],
            memory_actions_requested=["defer"],
        )

    def _task_kind(self, decision: Decision) -> str:
        if decision.execution_plan.get("system") == "repo_patch_service":
            return "patch"
        if decision.execution_plan.get("system") == "kubernetes_service":
            return "rollback_plan"
        return "root_cause"

    def _allowed_paths(self, trigger: Trigger) -> list[str]:
        related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
        paths = related.get("allowed_paths") or []
        return [str(path) for path in paths] if isinstance(paths, list) else []

    def _test_commands(self, trigger: Trigger) -> list[str]:
        related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
        commands = related.get("test_commands") or []
        return [str(command) for command in commands] if isinstance(commands, list) else []

    def _kubernetes_scope(self, trigger: Trigger, decision: Decision) -> dict[str, Any]:
        related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
        parameters = decision.execution_plan.get("parameters", {})
        return {
            "context": (
                parameters.get("kube_context")
                or related.get("kube_context")
                or parameters.get("cluster")
                or related.get("cluster")
            ),
            "namespace": parameters.get("namespace") or related.get("namespace"),
            "deployment_name": parameters.get("deployment_name") or related.get("deployment_name"),
            "cluster": parameters.get("cluster") or related.get("cluster"),
        }

    def _agents(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        service_agent: dict[str, Any] | None = None,
    ) -> list[str]:
        default_agents = self._known_agents()
        matched_agent = bool((service_agent or {}).get("matched")) if isinstance(service_agent, dict) else False
        if not matched_agent:
            return self._filter_configured_agents(default_agents, default_agents)
        source = _signal_source(trigger)
        routing = {
            "kubernetes": ["goose", "hermes", "codex", "claudecode", "openclaw", "temporal", "kubernetes", "n8n"],
            "otel": ["hermes", "goose", "temporal", "dagster", "prefect", "kubernetes"],
            "feature_flag": ["hermes", "goose", "temporal", "prefect", "n8n"],
            "argocd": ["goose", "hermes", "openclaw", "temporal", "kubernetes"],
            "log": ["hermes", "codex", "claudecode"],
            "data": ["airflow", "dagster", "prefect", "flyte", "luigi", "oozie", "temporal"],
            "ml": ["flyte", "dagster", "airflow", "prefect", "temporal"],
            "workflow": ["temporal", "airflow", "prefect", "dagster", "flyte", "luigi", "oozie", "n8n"],
        }
        agents = list(routing.get(source, default_agents))
        agent_payload = (service_agent or {}).get("agent") if isinstance(service_agent, dict) else None
        preferred = agent_payload.get("preferred_lanes", []) if isinstance(agent_payload, dict) else []
        if preferred:
            preferred_set = {str(item) for item in preferred}
            agents = [agent for agent in agents if agent in preferred_set] or agents
        agents = self._filter_configured_agents(agents, default_agents)
        if decision.decision_type not in {"investigate_and_patch", "repo_patch_service"}:
            agents = [agent for agent in agents if agent != "codex" or self._allowed_paths(trigger)]
        return agents

    def _known_agents(self) -> list[str]:
        agents = list(DEFAULT_AGENT_WORKERS)
        if self.config.latentmas_enabled:
            agents.append("latentmas")
        return agents

    def _platform_risk_flags(self, agent: str, task: AgentTask) -> list[str]:
        if agent != "kubernetes":
            return []
        if task.kubernetes_scope.get("context") and task.kubernetes_scope.get("namespace"):
            return []
        return ["kubernetes_scope_missing"]

    def _filter_configured_agents(self, agents: list[str], known_agents: list[str]) -> list[str]:
        if not self.config.agent_mesh_agents:
            return agents
        requested = [agent for agent in self.config.agent_mesh_agents if agent in known_agents]
        requested_set = set(requested)
        return [agent for agent in agents if agent in requested_set] or requested or agents

    def _memory_scope(self, run_id: str, trigger: Trigger) -> dict[str, Any]:
        return {
            "shared": True,
            "service": trigger.service,
            "run_id": run_id,
            "endpoint": trigger.endpoint,
        }

    def _memory_packet(self, memory_scope: dict[str, Any], trigger: Trigger) -> dict[str, Any]:
        if self.state_store is None:
            return {}
        response = self.state_store.retrieve_memory(
            {
                "query": " ".join(filter(None, [trigger.service, trigger.endpoint, trigger.trigger_type])),
                "scope": memory_scope,
                "limit": 8,
            }
        )
        return dict(response.get("packet", {}))

    def _memory_write_policy(self) -> dict[str, Any]:
        return {
            "shared_memory_mode": "read_mostly",
            "shared_memory_mutation": "proposals_only",
            "procedural_memory_mutation": "forbidden_without_review",
        }

    def _open_questions(self, packet: dict[str, Any]) -> list[str]:
        return [
            f"Resolve contradiction for {item.get('claim_id')}"
            for item in packet.get("contradictions", [])[:3]
            if item.get("claim_id")
        ]

def _proposal_observation(agent: str, service: str, content: str) -> dict[str, Any]:
    return {
        "kind": "agent_observation",
        "service": service,
        "author": agent,
        "content": content,
    }


def _signal_source(trigger: Trigger) -> str:
    context = trigger.related_context if isinstance(trigger.related_context, dict) else {}
    source = str(context.get("signal_source") or context.get("source") or "").lower()
    if trigger.trigger_type.startswith("kubernetes_"):
        return "kubernetes"
    if trigger.trigger_type.startswith("otel_"):
        return "otel"
    if "flag" in trigger.trigger_type:
        return "feature_flag"
    if source:
        return source
    return "default"
