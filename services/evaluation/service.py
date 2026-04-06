"""Evaluate remediation plans through policy checks and a Promptfoo adapter."""

from __future__ import annotations

from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    RuntimeConfig,
    RuntimeStateStore,
    Trigger,
    load_policy,
    resolve_integrations_config,
)

from .promptfoo_adapter import NativePromptfooAdapter, PromptfooAdapter, PromptfooCliAdapter


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
        if self.config.evaluation_mode == "promptfoo":
            resolved = resolve_integrations_config(self.config)
            return PromptfooCliAdapter(command=resolved.promptfoo_command)
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
        except Exception as exc:
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
        multi_service = decision.risk["blast_radius"] != "single_flag_single_service"
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
        if decision.decision_type == "escalate":
            business_notes.append("decision routes to human review")
            blocking_reasons.append("decision routes to human review")

        promptfoo_result = self.adapter.evaluate_decision(trigger, decision)
        if not promptfoo_result.passed:
            blocking_reasons.append("promptfoo quality gate did not pass")

        rollback_required = decision.decision_type in rollback_policy["require_rollback_plan_for_decision_types"]
        rollback_present = bool(decision.execution_plan.get("rollback_plan"))
        credentials_available = self._credentials_available(trigger, system)
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

        passed = not blocking_reasons
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
            },
            blocking_reasons=blocking_reasons,
            review_route="human_review" if not passed and not reject else None,
        )
        evaluation.validate()
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
        if system == "feature_flag_service":
            return feature_flag_credentials and audit_logging_available
        if system == "incident_service":
            return incident_credentials and audit_logging_available
        return audit_logging_available
