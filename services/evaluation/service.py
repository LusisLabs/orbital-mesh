"""Evaluate remediation plans through policy checks and a Promptfoo adapter."""

from __future__ import annotations

from shared.mesh_runtime import EvaluationResult, RemediationPlan, RuntimeConfig, load_policy

from .promptfoo_adapter import MockPromptfooAdapter, PromptfooAdapter, PromptfooCliAdapter


class EvaluationService:
    def __init__(self, adapter: PromptfooAdapter | None = None, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()

    def _build_adapter(self) -> PromptfooAdapter:
        if self.config.evaluation_mode == "promptfoo":
            return PromptfooCliAdapter()
        return MockPromptfooAdapter()

    def evaluate(self, plan: RemediationPlan) -> EvaluationResult:
        autonomy_policy = load_policy("autonomy.policy.json")
        protected_scope_policy = load_policy("protected-scope.policy.json")
        rollback_policy = load_policy("rollback.policy.json")

        disallowed_categories = [
            step["category"]
            for step in plan.steps
            if step["category"] not in autonomy_policy["allowed_step_categories"]
        ]
        protected_scope_hit = any(
            step.get("parameters", {}).get("segment") in protected_scope_policy["protected_segments"]
            for step in plan.steps
        )
        missing_required_rollback = [
            step["step_id"]
            for step in plan.steps
            if step["category"] in rollback_policy["require_rollback_for_categories"] and not step.get("rollback")
        ]

        promptfoo_result = self.adapter.evaluate_plan(plan)
        blocking_reasons: list[str] = []

        if disallowed_categories:
            blocking_reasons.append(f"disallowed step categories: {disallowed_categories}")
        if protected_scope_hit:
            blocking_reasons.append("protected scope requires human review")
        if missing_required_rollback:
            blocking_reasons.append(f"missing rollback for steps: {missing_required_rollback}")
        if not promptfoo_result.passed:
            blocking_reasons.append("promptfoo evaluation did not pass")

        passed = not blocking_reasons
        evaluation = EvaluationResult(
            evaluation_id=f"eval_{plan.plan_id}",
            plan_id=plan.plan_id,
            passed=passed,
            final_recommendation="execute_stepwise" if passed else "human_review",
            plan_results={
                "policy_validation": {
                    "passed": not disallowed_categories,
                    "notes": [] if not disallowed_categories else [blocking_reasons[0]],
                },
                "protected_scope_validation": {
                    "passed": not protected_scope_hit,
                    "notes": [] if not protected_scope_hit else ["protected scope detected"],
                },
                "rollback_validation": {
                    "passed": not missing_required_rollback,
                    "notes": [] if not missing_required_rollback else [f"steps missing rollback: {missing_required_rollback}"],
                },
                "promptfoo_quality": {
                    "passed": promptfoo_result.passed,
                    "score": promptfoo_result.score,
                    "notes": promptfoo_result.notes,
                    "mode": promptfoo_result.mode,
                },
            },
            step_results={
                step["step_id"]: {
                    "passed": step["category"] in autonomy_policy["allowed_step_categories"],
                    "notes": [f"category={step['category']}"],
                }
                for step in plan.steps
            },
            blocking_reasons=blocking_reasons,
            review_route="human_review_queue" if not passed else None,
        )
        evaluation.validate()
        return evaluation
