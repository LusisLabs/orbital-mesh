"""Evaluate remediation plans through deterministic contracts and trajectory scoring."""

from __future__ import annotations

import logging
from pathlib import Path

from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    RuntimeConfig,
    RuntimeStateStore,
    SchemaValidationError,
    Trigger,
    log_runtime_event,
    load_policy,
)
from shared.mesh_runtime.evidence_sufficiency import evaluate_evidence_sufficiency
from shared.mesh_runtime.review_blockers import classify_blocking_reasons
from shared.mesh_runtime.remediation_safety import evaluate_remediation_safety, safety_blocking_reason
from shared.mesh_runtime.phoenix_trace import build_phoenix_spans

from .mesh_eval import MeshEvalConfig
from .mesh_eval.runtime import mesh_eval_artifact_with_probe
from .mesh_evaluator import BehavioralScorer, ContractCheckAdapter, TrajectoryEvaluator, Verifier, temperature_policy_for_trace
from .sre_judge import LlmSreJudge, LlmSreJudgeConfig, MultiModelSreJudge, NativeSreJudge, SreJudge


_LOG = logging.getLogger("mesh.evaluation")


class EvaluationService:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        state_store: RuntimeStateStore | None = None,
        sre_judge: SreJudge | None = None,
    ):
        self.config = config or RuntimeConfig.from_env()
        self.state_store = state_store or RuntimeStateStore(self.config.state_directory)
        self.contracts = ContractCheckAdapter()
        self.trajectory = TrajectoryEvaluator()
        self.scorer = BehavioralScorer()
        self.verifier = Verifier()
        self.mesh_eval_config = MeshEvalConfig.from_env()
        self.sre_judge = sre_judge or self._build_sre_judge()
        self._sre_judge_enforces = sre_judge is not None or self.config.sre_judge_enabled

    def _build_sre_judge(self) -> SreJudge:
        if not self.config.sre_judge_enabled:
            return NativeSreJudge()
        primary = LlmSreJudge(
            LlmSreJudgeConfig(
                enabled=True,
                provider=self.config.sre_judge_provider,
                base_url=self.config.sre_judge_base_url,
                api_key=self.config.sre_judge_api_key,
                model=self.config.sre_judge_model,
                timeout_seconds=self.config.observer_timeout_seconds,
                prompt_cache_enabled=self.config.observer_prompt_cache_enabled,
                prompt_cache_mode=self.config.observer_prompt_cache_mode,
                prompt_cache_ttl=self.config.observer_prompt_cache_ttl,
            )
        )
        secondary = None
        if self.config.sre_judge_secondary_model:
            secondary = LlmSreJudge(
                LlmSreJudgeConfig(
                    enabled=True,
                    provider=self.config.sre_judge_secondary_provider or self.config.sre_judge_provider,
                    base_url=self.config.sre_judge_secondary_base_url or self.config.sre_judge_base_url,
                    api_key=self.config.sre_judge_secondary_api_key or self.config.sre_judge_api_key,
                    model=self.config.sre_judge_secondary_model,
                    timeout_seconds=self.config.observer_timeout_seconds,
                    prompt_cache_enabled=self.config.observer_prompt_cache_enabled,
                    prompt_cache_mode=self.config.observer_prompt_cache_mode,
                    prompt_cache_ttl=self.config.observer_prompt_cache_ttl,
                )
            )
        return MultiModelSreJudge(primary, secondary)

    def evaluate(
        self,
        trigger: Trigger,
        decision: Decision,
        allow_rereevaluation: bool = False,
        run_id: str | None = None,
        run_events: list[object] | None = None,
        artifacts: dict[str, object] | None = None,
    ) -> EvaluationResult:
        autonomy_policy = load_policy("autonomy.policy.json")
        protected_scope_policy = load_policy("protected-scope.policy.json")
        rollback_policy = load_policy("rollback.policy.json")
        blocking_reasons: list[str] = []
        reject = False

        try:
            trigger.validate()
            decision.validate()
            schema_validation = {"passed": True}
        except SchemaValidationError as exc:
            schema_validation = {"passed": False, "notes": [str(exc)]}
            blocking_reasons.append(str(exc))

        system = decision.execution_plan["system"]
        action = decision.execution_plan["action"]
        decision_allowed = decision.decision_type in autonomy_policy["allowed_decision_types"]
        system_allowed = system in autonomy_policy["allowed_execution_systems"]
        action_allowed = action in autonomy_policy["allowed_execution_actions"].get(system, [])
        idempotent = action in autonomy_policy["idempotent_actions"]
        policy_notes: list[str] = []
        if not decision_allowed:
            policy_notes.append("decision type falls outside the allowed action set")
            blocking_reasons.append("decision type falls outside the allowed action set")
            reject = True
        if not system_allowed or not action_allowed:
            policy_notes.append("execution plan falls outside the allowed action set")
            blocking_reasons.append("execution plan falls outside the allowed action set")
            reject = True
        duplicate_trigger = False
        if schema_validation["passed"]:
            registration = self.state_store.register_evaluation(trigger.trigger_id, decision.decision_id)
            duplicate_trigger = not registration.accepted
            if duplicate_trigger and not allow_rereevaluation:
                policy_notes.append("duplicate evaluation suppressed for trigger_id")
                blocking_reasons.append("duplicate evaluation suppressed for trigger_id")
                reject = True

        protected_tier = trigger.segment["customer_tier"] in protected_scope_policy["approval_required_customer_tiers"]
        repeated_rollback = trigger.related_context.get("rollbacks_last_24h", 0) > 0
        cooldown_conflict = repeated_rollback and decision.autonomy_tier == "autonomous"
        multi_service = str(decision.risk["blast_radius"]).startswith("multi_")
        business_notes: list[str] = []
        if decision.autonomy_tier == "autonomous" and (protected_tier or repeated_rollback or multi_service):
            business_notes.append("scope requires approval before execution")
            blocking_reasons.append("scope requires approval before execution")
        if decision.autonomy_tier == "approval_required":
            business_notes.append("approval required before execution")
            blocking_reasons.append("approval required before execution")
        if cooldown_conflict:
            business_notes.append("recent rollback cooldown conflict")
            blocking_reasons.append("recent rollback cooldown conflict")
        if decision.decision_type == "escalate" and trigger.trigger_type != "webhook_alert_firing":
            business_notes.append("decision routes to human review")
            blocking_reasons.append("decision routes to human review")

        rollback_required = decision.decision_type in rollback_policy["require_rollback_plan_for_decision_types"]
        rollback_present = bool(decision.execution_plan.get("rollback_plan"))
        credentials_available = self._credentials_available(trigger, system)
        repo_patch_ready, repo_patch_notes = self._repo_patch_ready(decision)
        systemd_ready, systemd_notes = self._systemd_service_ready(decision)
        readiness_notes: list[str] = []
        if decision.confidence < rollback_policy["minimum_confidence"]:
            readiness_notes.append("confidence below minimum threshold")
            blocking_reasons.append("confidence below minimum threshold")
        if decision.risk["level"] == "high":
            readiness_notes.append("risk level is high")
            blocking_reasons.append("risk level is high")
        if not idempotent:
            readiness_notes.append("action is not idempotent")
            blocking_reasons.append("action is not idempotent")
        if rollback_required and not rollback_present:
            readiness_notes.append("rollback parameters are missing")
            blocking_reasons.append("rollback parameters are missing")
        if not credentials_available:
            readiness_notes.append("required credentials are unavailable")
            blocking_reasons.append("required credentials are unavailable")
        if not repo_patch_ready:
            readiness_notes.extend(repo_patch_notes)
            blocking_reasons.extend(repo_patch_notes)
        if not systemd_ready:
            readiness_notes.extend(systemd_notes)
            blocking_reasons.extend(systemd_notes)
        evidence_sufficiency = evaluate_evidence_sufficiency(trigger, decision)
        if not evidence_sufficiency["passed"]:
            blocking_reasons.append("evidence sufficiency gate did not pass")

        policy_passed = decision_allowed and system_allowed and action_allowed and (allow_rereevaluation or not duplicate_trigger)
        readiness_passed = (
            credentials_available
            and (not rollback_required or rollback_present)
            and idempotent
            and decision.confidence >= rollback_policy["minimum_confidence"]
            and decision.risk["level"] != "high"
            and repo_patch_ready
            and systemd_ready
        )
        safety_case = evaluate_remediation_safety(
            trigger,
            decision,
            state_store=self.state_store,
            prior_blocking_reasons=blocking_reasons,
            promptfoo_passed=True,
            schema_passed=bool(schema_validation["passed"]),
            policy_passed=policy_passed,
            readiness_passed=readiness_passed,
        )
        safety_reason = safety_blocking_reason(safety_case)
        if safety_reason is not None:
            blocking_reasons.append(safety_reason)

        business_rules = {
            "passed": not business_notes,
            "notes": business_notes or ["single-service scope", "no cooldown conflict"],
        }
        execution_readiness = {
            "passed": readiness_passed,
            "notes": readiness_notes
            or [
                (
                    "feature flag credentials available"
                    if system == "feature_flag_service"
                    else (
                        "incident credentials available"
                        if system == "incident_service"
                        else "audit logging available"
                    )
                ),
                "rollback value present",
            ],
        }
        policy_validation = {
            "passed": policy_passed,
            "notes": policy_notes,
        }
        contract_checks = self.contracts.summarize(
            schema_validation=schema_validation,
            policy_validation=policy_validation,
            business_rules=business_rules,
            execution_readiness=execution_readiness,
            remediation_safety=safety_case.to_dict(),
        )
        artifact_payload = dict(artifacts or {})
        artifact_payload["mesh_eval"] = mesh_eval_artifact_with_probe(
            config=self.mesh_eval_config,
            trigger=trigger,
            decision=decision,
        )
        if run_id is not None:
            artifact_payload.update(_artifacts_for_run(self.state_store, run_id))
            artifact_payload["mesh_eval"] = mesh_eval_artifact_with_probe(
                config=self.mesh_eval_config,
                trigger=trigger,
                decision=decision,
            )
        trace = self.trajectory.build_trace(
            trigger=trigger,
            decision=decision,
            run_events=run_events or _events_for_run(self.state_store, run_id),
            artifacts=artifact_payload,
        )
        trace["temperature_policy"] = temperature_policy_for_trace(trace)
        trajectory_score = self.scorer.score(trace)
        verifier_output = self.verifier.verify(trace)
        if not trajectory_score.passed:
            blocking_reasons.append("trajectory quality gate did not pass")

        scenario_review_reasons = _scenario_review_reasons(decision)
        blocker_analysis = classify_blocking_reasons(
            blocking_reasons,
            scenario_review_reasons=scenario_review_reasons,
        )
        preliminary_stage_results = {
            "schema_validation": schema_validation,
            "policy_validation": policy_validation,
            "contract_checks": contract_checks,
            "trajectory_quality": {
                "passed": trajectory_score.passed,
                "score": trajectory_score.score,
                "notes": trajectory_score.notes,
                "artifacts": trajectory_score.artifacts,
            },
            "behavioral_scores": trajectory_score.artifacts,
            "verifier": verifier_output,
            "business_rules": business_rules,
            "execution_readiness": execution_readiness,
            "evidence_sufficiency": evidence_sufficiency,
            "remediation_safety": safety_case.to_dict(),
            "blocker_analysis": blocker_analysis,
        }
        sre_judgment = self.sre_judge.evaluate(
            trigger=trigger,
            decision=decision,
            stage_results=preliminary_stage_results,
            blocking_reasons=list(blocking_reasons),
        )
        if self._sre_judge_enforces and sre_judgment.recommendation in {"human_review", "defer"} and not blocking_reasons:
            blocking_reasons.append(f"sre judge recommends {sre_judgment.recommendation}")
        if self._sre_judge_enforces and sre_judgment.recommendation == "reject":
            blocking_reasons.append("sre judge rejected decision")
            reject = True
        blocker_analysis = classify_blocking_reasons(
            blocking_reasons,
            scenario_review_reasons=scenario_review_reasons,
        )
        passed = not blocking_reasons
        final_recommendation = "reject" if reject else ("execute" if passed else "human_review")
        if self._sre_judge_enforces and not reject and sre_judgment.recommendation == "defer":
            final_recommendation = "human_review"
        log_runtime_event(
            "evaluation_completed",
            mode=self.config.evaluation_mode,
            decision_id=decision.decision_id,
            passed=passed,
            recommendation=final_recommendation,
            blocking_reasons=blocking_reasons,
            auto_recovery=blocker_analysis["can_auto_remediate"],
        )
        evaluation = EvaluationResult(
            evaluation_id=f"eval_{decision.decision_id}",
            decision_id=decision.decision_id,
            passed=passed,
            final_recommendation=final_recommendation,
            stage_results={
                **preliminary_stage_results,
                "sre_judgment": sre_judgment.to_dict(),
                "blocker_analysis": blocker_analysis,
            },
            blocking_reasons=blocking_reasons,
            review_route="human_review" if not passed and not reject else None,
        )
        evaluation.validate()
        # One-line summary at the end so readers can see the evaluation
        # outcome without reading the whole stage_results tree. The tree
        # is still in the JSON/markdown report for detail.
        _LOG.info(
            "evaluate: decision=%s recommendation=%s passed=%s blocking_reasons=%s",
            decision.decision_type,
            evaluation.final_recommendation,
            evaluation.passed,
            evaluation.blocking_reasons,
        )
        return evaluation

    def evaluate_trace(
        self,
        *,
        trigger: Trigger | dict[str, object] | None,
        decision: Decision | dict[str, object] | None,
        evaluation: dict[str, object] | None = None,
        execution: dict[str, object] | None = None,
        feedback: dict[str, object] | None = None,
        run_events: list[object] | None = None,
        artifacts: dict[str, object] | None = None,
    ) -> dict[str, object]:
        artifact_payload = dict(artifacts or {})
        artifact_payload["mesh_eval"] = mesh_eval_artifact_with_probe(
            config=self.mesh_eval_config,
            trigger=trigger,
            decision=decision,
        )
        trace = self.trajectory.build_trace(
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
            execution=execution,
            feedback=feedback,
            run_events=run_events,
            artifacts=artifact_payload,
        )
        trace["temperature_policy"] = temperature_policy_for_trace(trace)
        trajectory_score = self.scorer.score(trace)
        verifier_output = self.verifier.verify(trace)
        return {
            "task_trace": trace,
            "trajectory_score": {
                "passed": trajectory_score.passed,
                "score": trajectory_score.score,
                "notes": trajectory_score.notes,
                "artifacts": trajectory_score.artifacts,
            },
            "verifier_output": verifier_output,
            "phoenix_spans": build_phoenix_spans(trace),
        }

    def _credentials_available(self, trigger: Trigger, system: str) -> bool:
        feature_flag_credentials = trigger.related_context.get(
            "feature_flag_credentials_available",
            self.config.feature_flag_credentials_available,
        )
        incident_credentials = trigger.related_context.get(
            "incident_credentials_available",
            self.config.incident_credentials_available,
        )
        audit_logging_available = trigger.related_context.get(
            "audit_logging_available",
            self.config.audit_logging_available,
        )
        cluster_access_available = trigger.related_context.get("cluster_access_available", True)
        if system == "feature_flag_service":
            return feature_flag_credentials and audit_logging_available
        if system == "incident_service":
            return incident_credentials and audit_logging_available
        if system == "kubernetes_service":
            return bool(cluster_access_available) and audit_logging_available
        return audit_logging_available

    def _repo_patch_ready(self, decision: Decision) -> tuple[bool, list[str]]:
        if decision.execution_plan["system"] != "repo_patch_service":
            return True, []
        parameters = decision.execution_plan.get("parameters", {})
        notes: list[str] = []
        repo_path = parameters.get("repo_path")
        allowed_paths = parameters.get("allowed_paths")
        patch_template = parameters.get("patch_template")
        test_commands = parameters.get("test_commands")
        if not isinstance(repo_path, str) or not repo_path or not Path(repo_path).exists():
            notes.append("repo path is missing or does not exist")
        if not isinstance(allowed_paths, list) or not allowed_paths:
            notes.append("allowed repo patch paths are missing")
        if not isinstance(test_commands, list) or not test_commands:
            notes.append("bounded test commands are missing")
        if not isinstance(patch_template, dict):
            notes.append("patch template is missing")
        else:
            for key in ("target_file", "find", "replace"):
                if not isinstance(patch_template.get(key), str) or not patch_template.get(key):
                    notes.append(f"patch template field `{key}` is missing")
        return not notes, notes

    def _systemd_service_ready(self, decision: Decision) -> tuple[bool, list[str]]:
        if decision.execution_plan["system"] != "systemd_service":
            return True, []
        parameters = decision.execution_plan.get("parameters", {})
        notes: list[str] = []
        host = parameters.get("host")
        service = parameters.get("service")
        if not isinstance(host, str) or not host:
            notes.append("systemd host is missing")
        if not isinstance(service, str) or not service:
            notes.append("systemd service is missing")
        if not self.config.ssh_allowed_hosts:
            notes.append("systemd host allowlist is empty")
        elif isinstance(host, str) and host.split("@", 1)[-1].strip() not in self.config.ssh_allowed_hosts:
            notes.append("systemd host is not allowlisted")
        if not self.config.ssh_allowed_services:
            notes.append("systemd service allowlist is empty")
        elif isinstance(service, str):
            canonical = service if service.endswith(".service") else f"{service}.service"
            if service not in self.config.ssh_allowed_services and canonical not in self.config.ssh_allowed_services:
                notes.append("systemd service is not allowlisted")
        return not notes, notes


def _scenario_review_reasons(decision: Decision) -> list[str]:
    evidence_pack = decision.reasoning.get("evidence_pack", {})
    scenario_analysis = evidence_pack.get("scenario_analysis", {})
    reasons = scenario_analysis.get("required_review_reasons", [])
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


def _events_for_run(state_store: object, run_id: str | None) -> list[object]:
    if run_id is None or not hasattr(state_store, "list_run_events"):
        return []
    try:
        events = state_store.list_run_events(run_id)  # type: ignore[attr-defined]
    except Exception:
        _LOG.exception("trajectory event lookup failed for run %s", run_id)
        return []
    return list(events) if isinstance(events, list) else []


def _artifacts_for_run(state_store: object, run_id: str | None) -> dict[str, object]:
    if run_id is None or not hasattr(state_store, "get_run_session"):
        return {}
    try:
        session = state_store.get_run_session(run_id)  # type: ignore[attr-defined]
    except Exception:
        _LOG.exception("trajectory artifact lookup failed for run %s", run_id)
        return {}
    artifacts = getattr(session, "artifacts", None)
    return dict(artifacts) if isinstance(artifacts, dict) else {}
