from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, Trigger, build_evo_status
from shared.mesh_runtime.agent_workers import build_agent_attempt, build_agent_task
from shared.mesh_runtime.control_plane_models import AgentTask
from .deepagents_adapter import DeepAgentsAdapter
from .latentmas_adapter import LatentMasAdapter


class AgentMeshService:
    """Build read-only worker artifacts for a run.

    This first slice defines the full-stack contract that external agents can later
    implement through CLI/API adapters. It intentionally returns proposals only:
    Mesh still owns policy, tests, audit, Kubernetes actuation, and production gates.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        latentmas_adapter: LatentMasAdapter | None = None,
        deepagents_adapter: DeepAgentsAdapter | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.latentmas_adapter = latentmas_adapter or LatentMasAdapter(self.config)
        self.deepagents_adapter = deepagents_adapter or DeepAgentsAdapter(self.config)

    def build_tasks(
        self,
        *,
        run_id: str,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> list[AgentTask]:
        task = build_agent_task(
            run_id=run_id,
            kind=self._task_kind(decision),
            allowed_paths=self._allowed_paths(trigger),
            test_commands=self._test_commands(trigger),
            kubernetes_scope=self._kubernetes_scope(trigger, decision),
            agents=self._agents(),
        )
        attempts = []
        if self.config.latentmas_enabled:
            attempts.append(
                self.latentmas_adapter.build_attempt(
                    task=task,
                    trigger=trigger,
                    decision=decision,
                    evaluation=evaluation,
                )
            )
        if self.config.agent_fabric_mode == "deepagents":
            attempts.extend(
                [
                    self.deepagents_adapter.build_lane_attempt(
                        agent="goose",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                    self.deepagents_adapter.build_lane_attempt(
                        agent="hermes",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                    self.deepagents_adapter.build_lane_attempt(
                        agent="codex",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                    self.deepagents_adapter.build_lane_attempt(
                        agent="claudecode",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                    self.deepagents_adapter.build_lane_attempt(
                        agent="openclaw",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                    self.deepagents_adapter.build_lane_attempt(
                        agent="evo",
                        task=task,
                        trigger=trigger,
                        decision=decision,
                        evaluation=evaluation,
                    ),
                ]
            )
        else:
            attempts.extend([
                self._goose_attempt(task, trigger, decision, evaluation),
                self._hermes_attempt(task, trigger, decision, evaluation),
                self._codex_attempt(task, trigger, decision, evaluation),
                self._claude_code_attempt(task, trigger, decision, evaluation),
                self._openclaw_attempt(task, trigger, decision, evaluation),
                self._evo_attempt(task, trigger, decision, evaluation),
            ])
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
        )

    def _openclaw_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        namespace = task.kubernetes_scope.get("namespace")
        context = task.kubernetes_scope.get("context")
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
        )

    def _evo_attempt(
        self,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ):
        related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
        parameters = decision.execution_plan.get("parameters", {})
        repo_path = str(parameters.get("repo_path") or related.get("repo_path") or "")
        evo_status = build_evo_status(self.config)
        workspace_detected = self._evo_workspace_detected(repo_path)
        code_candidate = (
            task.kind == "patch"
            and decision.execution_plan.get("system") == "repo_patch_service"
            and bool(related.get("code_remediation_candidate"))
        )

        risk_flags: list[str] = []
        if not evo_status.ready:
            risk_flags.append("evo_cli_missing")
        if not workspace_detected:
            risk_flags.append("evo_workspace_missing")
        if not task.allowed_paths:
            risk_flags.append("allowed_paths_missing")
        if not task.test_commands:
            risk_flags.append("test_commands_missing")
        if not code_candidate:
            risk_flags.append("non_code_task")

        if not code_candidate or not evo_status.ready:
            recommended_action = "human_review"
        elif task.allowed_paths and task.test_commands:
            recommended_action = "evo_discover_candidate"
        else:
            recommended_action = "prepare_benchmark"

        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="evo",
            adapter="native_contract",
            status="completed",
            summary=self._evo_summary(
                ready=evo_status.ready,
                workspace_detected=workspace_detected,
                recommended_action=recommended_action,
            ),
            risk_flags=risk_flags,
            recommended_action=recommended_action,
            output={
                "evo_ready": evo_status.ready,
                "workspace_detected": workspace_detected,
                "recommended_bootstrap_command": self._evo_bootstrap_command(workspace_detected),
                "required_allowed_paths": task.allowed_paths,
                "required_test_commands": task.test_commands,
                "risk_flags": risk_flags,
                "repo_path": repo_path or None,
                "evo_command": evo_status.command,
                "evo_detail": evo_status.detail,
                "evaluation_blocking_reasons": evaluation.blocking_reasons,
            },
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
            "context": parameters.get("kube_context") or related.get("kube_context"),
            "namespace": parameters.get("namespace") or related.get("namespace"),
            "deployment_name": parameters.get("deployment_name") or related.get("deployment_name"),
            "cluster": parameters.get("cluster") or related.get("cluster"),
        }

    def _agents(self) -> list[str]:
        agents = ["goose", "hermes", "codex", "claudecode", "openclaw", "evo"]
        if self.config.latentmas_enabled:
            return ["latentmas", *agents]
        return agents

    def _evo_workspace_detected(self, repo_path: str) -> bool:
        if not repo_path:
            return False
        return (Path(repo_path) / ".evo" / "meta.json").is_file()

    def _evo_bootstrap_command(self, workspace_detected: bool) -> str:
        return "evo status" if workspace_detected else "$evo discover"

    def _evo_summary(
        self,
        *,
        ready: bool,
        workspace_detected: bool,
        recommended_action: str,
    ) -> str:
        if not ready:
            return "Evo proposal lane is gated until evo-hq-cli is configured."
        if recommended_action == "evo_discover_candidate":
            if workspace_detected:
                return "Evo workspace is present; bounded optimization can be reviewed from the existing benchmark."
            return "Bounded code-remediation task has paths and tests; run Evo discovery before optimization."
        if recommended_action == "prepare_benchmark":
            return "Evo needs benchmark gates before this task can enter experiment-driven optimization."
        return "Evo is limited to bounded code-remediation tasks with explicit repo, path, and test gates."
