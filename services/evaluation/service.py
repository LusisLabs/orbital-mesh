"""Evaluate remediation plans through policy checks and a Promptfoo adapter."""

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
    build_readiness,
    log_runtime_event,
    load_policy,
    resolve_integrations_config,
)
from shared.mesh_runtime.review_blockers import classify_blocking_reasons

from .promptfoo_adapter import NativePromptfooAdapter, PromptfooAdapter, PromptfooCliAdapter


_LOG = logging.getLogger("mesh.evaluation")


class EvaluationService:
    def __init__(
        self,
        adapter: PromptfooAdapter | None = None,
        config: RuntimeConfig | None = None,
        state_store: RuntimeStateStore | None = None,
    ):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()
        self.state_store = state_store or RuntimeStateStore(self.config.state_directory)

    def _build_adapter(self) -> PromptfooAdapter:
        mode = (self.config.evaluation_mode or "auto").lower()
        if mode == "native":
            return NativePromptfooAdapter()
        if mode == "promptfoo":
            resolved = resolve_integrations_config(self.config)
            return PromptfooCliAdapter(command=resolved.promptfoo_command)
        # auto: prefer Promptfoo when it can actually run, otherwise fall back
        # to the in-process heuristic so offline/dev setups still work.
        readiness = build_readiness(self.config)
        if readiness.promptfoo.ready:
            resolved = resolve_integrations_config(self.config)
            log_runtime_event("evaluation_adapter_selected", adapter="promptfoo", reason="auto_ready")
            return PromptfooCliAdapter(command=resolved.promptfoo_command)
        log_runtime_event(
            "evaluation_adapter_selected",
            adapter="native",
            reason="auto_fallback",
            detail=readiness.promptfoo.detail,
        )
        return NativePromptfooAdapter()

    def evaluate(
        self,
        trigger: Trigger,
        decision: Decision,
        allow_rereevaluation: bool = False,
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

        promptfoo_result = self.adapter.evaluate_decision(trigger, decision)
        if not promptfoo_result.passed:
            blocking_reasons.append("promptfoo quality gate did not pass")

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

        scenario_review_reasons = _scenario_review_reasons(decision)
        blocker_analysis = classify_blocking_reasons(
            blocking_reasons,
            scenario_review_reasons=scenario_review_reasons,
        )
        passed = not blocking_reasons
        log_runtime_event(
            "evaluation_completed",
            mode=self.config.evaluation_mode,
            decision_id=decision.decision_id,
            passed=passed,
            recommendation="reject" if reject else ("execute" if passed else "human_review"),
            blocking_reasons=blocking_reasons,
            auto_recovery=blocker_analysis["can_auto_remediate"],
        )
        evaluation = EvaluationResult(
            evaluation_id=f"eval_{decision.decision_id}",
            decision_id=decision.decision_id,
            passed=passed,
            final_recommendation="reject" if reject else ("execute" if passed else "human_review"),
            stage_results={
                "schema_validation": schema_validation,
                "policy_validation": {
                    "passed": decision_allowed
                    and system_allowed
                    and action_allowed
                    and (allow_rereevaluation or not duplicate_trigger),
                    "notes": policy_notes,
                },
                "promptfoo_quality": {
                    "passed": promptfoo_result.passed,
                    "score": promptfoo_result.score,
                    "notes": promptfoo_result.notes,
                    "mode": promptfoo_result.mode,
                    "artifacts": promptfoo_result.artifacts,
                },
                "business_rules": {
                    "passed": not business_notes,
                    "notes": business_notes or ["single-service scope", "no cooldown conflict"],
                },
                "execution_readiness": {
                    "passed": (
                        credentials_available
                        and (not rollback_required or rollback_present)
                        and idempotent
                        and decision.confidence >= rollback_policy["minimum_confidence"]
                        and decision.risk["level"] != "high"
                        and repo_patch_ready
                        and systemd_ready
                    ),
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
                },
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
