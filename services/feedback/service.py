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
        if trigger.trigger_type == "kubernetes_deployment_unhealthy":
            return self._record_kubernetes_feedback(trigger, decision, execution, normalized_event)
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

    def _record_kubernetes_feedback(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        normalized_event: EventEnvelope,
    ) -> FeedbackRecord:
        observations = normalized_event.payload.get("post_action_observations", {})
        check_30m = observations.get("30m", {})
        if not check_30m:
            check_30m = _kubernetes_feedback_fallback(execution)
        goose_review = execution.external_refs.get("goose_review", {}) if isinstance(execution.external_refs, dict) else {}
        desired = int(check_30m.get("desired_replicas", trigger.metrics.get("desired_replicas") or 0))
        ready = int(check_30m.get("ready_replicas", 0))
        restart_delta = int(check_30m.get("restart_delta", trigger.metrics.get("restart_count_total") or 0))
        rollout_status = check_30m.get("rollout_status", "unknown")
        new_error_signatures = list(check_30m.get("new_error_signatures", []))
        successful = (
            execution.status == "succeeded"
            and rollout_status == "healthy"
            and ready >= desired
            and restart_delta == 0
            and not new_error_signatures
        )
        outcome = "successful" if successful else "escalated"
        recommended_follow_up = "record_rollout_recovery" if successful else "human_review"
        feedback = FeedbackRecord(
            feedback_id=f"fb_{decision.decision_id}",
            decision_id=decision.decision_id,
            execution_id=execution.execution_id,
            measured_at=check_30m.get("measured_at", datetime.now(timezone.utc).isoformat()),
            window="30m",
            outcome=outcome,
            metric_comparison={
                "desired_replicas": desired,
                "ready_replicas": ready,
                "restart_delta": restart_delta,
                "rollout_status": rollout_status,
            },
            prediction_accuracy={
                "expected_time_to_effect": decision.expected_outcome["time_to_effect"],
                "observed_time_to_effect": check_30m.get("observed_time_to_effect", "not_achieved"),
            },
            side_effects=new_error_signatures
            + ([{"source": "goose_review", "risk_flags": goose_review.get("risk_flags", [])}] if goose_review else []),
            world_model_updates={
                "cluster_recovery_pattern": _service_recovery_pattern(decision.decision_type, successful),
                "deployment_name": trigger.related_context.get("deployment_name"),
                "namespace": trigger.related_context.get("namespace"),
                "integration_signals": {
                    "executor": execution.executor,
                    "goose_review_summary": goose_review.get("summary"),
                },
            },
            recommended_follow_up=recommended_follow_up,
        )
        feedback.validate()
        return feedback


def _service_recovery_pattern(decision_type: str, successful: bool) -> str:
    if decision_type == "rollback_deployment":
        return "deployment_rollback_restores_health" if successful else "deployment_rollback_insufficient"
    if decision_type == "restart_deployment":
        return "deployment_restart_restores_health" if successful else "deployment_restart_insufficient"
    if decision_type == "investigate_and_patch":
        return "bounded_code_patch_restores_latency" if successful else "bounded_code_patch_insufficient"
    if decision_type == "disable_flag":
        return "flag_disable_restores_latency" if successful else "flag_disable_insufficient"
    if decision_type == "reduce_rollout":
        return "rollout_reduction_restores_latency" if successful else "rollout_reduction_insufficient"
    if decision_type == "no_action":
        return "no_automated_change_recorded"
    return "human_review_required"


def _kubernetes_feedback_fallback(execution: ExecutionRecord) -> dict:
    if not isinstance(execution.external_refs, dict):
        return {}
    deployment_after = execution.external_refs.get("deployment_after")
    if not isinstance(deployment_after, dict):
        return {}
    desired = int(deployment_after.get("desired_replicas") or 0)
    available = int(deployment_after.get("available_replicas") or 0)
    unavailable = int(deployment_after.get("unavailable_replicas") or 0)
    rollout_status = "healthy" if desired > 0 and available >= desired and unavailable == 0 else "degraded"
    return {
        "measured_at": execution.external_refs.get("observed_at", datetime.now(timezone.utc).isoformat()),
        "desired_replicas": desired,
        "ready_replicas": available,
        "restart_delta": 0,
        "rollout_status": rollout_status,
        "new_error_signatures": [],
        "observed_time_to_effect": "immediate_post_action_snapshot",
    }
