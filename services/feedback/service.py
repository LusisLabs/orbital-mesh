"""Turn execution outcomes into feedback and learning records."""

from __future__ import annotations

from datetime import datetime, timezone

from shared.mesh_runtime import Diagnosis, ExecutionRecord, FeedbackRecord, RemediationPlan, Trigger


class FeedbackService:
    def record(
        self,
        trigger: Trigger,
        diagnosis: Diagnosis,
        plan: RemediationPlan,
        execution: ExecutionRecord,
    ) -> FeedbackRecord:
        latency_symptom = next(item for item in trigger.symptoms if item["metric"] == "p95_latency_ms")
        error_symptom = next(item for item in trigger.symptoms if item["metric"] == "error_rate")
        recovered = execution.status == "completed"

        feedback = FeedbackRecord(
            feedback_id=f"fb_{plan.plan_id}",
            trigger_id=trigger.trigger_id,
            plan_id=plan.plan_id,
            execution_id=execution.execution_id,
            measured_at=datetime.now(timezone.utc).isoformat(),
            window="stabilization",
            outcome="successful" if recovered else "escalated",
            metric_comparison={
                "baseline_p95_latency_ms": latency_symptom["baseline"],
                "post_action_p95_latency_ms": round(latency_symptom["baseline"] * 1.08, 2),
                "baseline_error_rate": error_symptom["baseline"],
                "post_action_error_rate": round(error_symptom["baseline"] * 1.12, 4),
            },
            diagnosis_accuracy={
                "primary_hypothesis_id": diagnosis.hypotheses[0]["hypothesis_id"],
                "supported_by_outcome": recovered,
                "confidence_adjustment": 0.05 if recovered else -0.05,
            },
            plan_effectiveness={
                "steps_executed": len([step for step in execution.step_history if step["status"] == "succeeded"]),
                "steps_skipped": len([step for step in execution.step_history if step["status"] == "skipped"]),
                "time_to_effect": "8m" if recovered else None,
                "side_effects": [],
            },
            recommended_follow_up="increase_prior_for_feature_flag_change" if recovered else "human_review_required",
            world_model_updates={
                "causal_link_strength": 0.84 if recovered else 0.4,
                "actuator_success_prior": {"feature_flag_change": 0.79 if recovered else 0.3},
                "service_incident_pattern": f"{trigger.scope['service']} regression linked to recent rollout activity",
            },
        )
        feedback.validate()
        return feedback
