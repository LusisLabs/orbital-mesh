"""Turn execution outcomes into feedback and learning records."""

from __future__ import annotations

from datetime import datetime, timezone

from shared.mesh_runtime import Decision, EventEnvelope, ExecutionRecord, FeedbackRecord, Trigger


class FeedbackService:
    def record(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        normalized_event: EventEnvelope,
    ) -> FeedbackRecord:
        observations = normalized_event.payload.get("post_action_observations", {})
        check_10m = observations.get("10m", {})
        check_30m = observations.get("30m", {})
        baseline_latency = trigger.metrics["baseline_p95_latency_ms"]
        baseline_error = trigger.metrics["baseline_error_rate"]
        observed_latency = trigger.metrics["observed_p95_latency_ms"]
        observed_error = trigger.metrics["observed_error_rate"]
        post_latency = check_30m.get("p95_latency_ms", observed_latency)
        post_error = check_30m.get("error_rate", observed_error)
        improved_10m = (
            check_10m.get("p95_latency_ms", observed_latency) < observed_latency
            and check_10m.get("error_rate", observed_error) < observed_error
        )
        goose_review = execution.external_refs.get("goose_review", {}) if isinstance(execution.external_refs, dict) else {}
        successful_30m = (
            execution.status == "succeeded"
            and post_latency <= baseline_latency * 1.10
            and post_error <= baseline_error * 1.20
            and check_30m.get("new_severe_incidents", 0) == 0
        )
        regressions_last_7d = trigger.related_context.get("regressions_last_7d", 0)
        recommended_follow_up = "record_positive_outcome"
        outcome = "successful"
        if execution.status != "succeeded":
            outcome = "escalated"
            recommended_follow_up = "human_review"
        elif not improved_10m:
            outcome = "escalated"
            recommended_follow_up = "human_review"
        elif decision.decision_type == "disable_flag" and check_30m.get("business_guardrail_breached", False):
            outcome = "rolled_back"
            recommended_follow_up = "restore_prior_rollout_and_escalate"
        elif not successful_30m:
            outcome = "unsuccessful"
            recommended_follow_up = "human_review"
        elif regressions_last_7d >= 3:
            recommended_follow_up = "mark_flag_for_human_owned_remediation"

        feedback = FeedbackRecord(
            feedback_id=f"fb_{decision.decision_id}",
            decision_id=decision.decision_id,
            execution_id=execution.execution_id,
            measured_at=check_30m.get("measured_at", datetime.now(timezone.utc).isoformat()),
            window="30m",
            outcome=outcome,
            metric_comparison={
                "baseline_p95_latency_ms": baseline_latency,
                "post_action_p95_latency_ms": post_latency,
                "baseline_error_rate": baseline_error,
                "post_action_error_rate": post_error,
            },
            prediction_accuracy={
                "expected_time_to_effect": decision.expected_outcome["time_to_effect"],
                "observed_time_to_effect": check_30m.get("observed_time_to_effect", "not_achieved"),
            },
            side_effects=check_30m.get("side_effects", [])
            + ([{"source": "goose_review", "risk_flags": goose_review.get("risk_flags", [])}] if goose_review else []),
            recommended_follow_up=recommended_follow_up,
            world_model_updates={
                "causal_link_strength": 0.82 if successful_30m else 0.38,
                "flag_risk_score_delta": 0.15 if decision.decision_type == "disable_flag" else 0.08,
                "service_recovery_pattern": _service_recovery_pattern(decision.decision_type, successful_30m),
                "integration_signals": {
                    "evaluation_mode": execution.executor if execution.executor else "unknown",
                    "goose_review_summary": goose_review.get("summary"),
                },
            },
        )
        feedback.validate()
        return feedback


def _service_recovery_pattern(decision_type: str, successful: bool) -> str:
    if decision_type == "disable_flag":
        return "flag_disable_restores_latency" if successful else "flag_disable_insufficient"
    if decision_type == "reduce_rollout":
        return "rollout_reduction_restores_latency" if successful else "rollout_reduction_insufficient"
    if decision_type == "no_action":
        return "no_automated_change_recorded"
    return "human_review_required"
