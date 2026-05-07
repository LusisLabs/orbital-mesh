"""Turn execution outcomes into feedback and learning records."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from shared.mesh_runtime import Decision, EventEnvelope, ExecutionRecord, FeedbackRecord, Trigger
from services.ingest.kubernetes_live_signal import collect_kubernetes_signal
from .otel_observer import PrometheusFeedbackObserver, augment_observations


_LOG = logging.getLogger("mesh.feedback")
_QUALITY_MEASUREMENT_FIELDS = {
    "false_positive_reduction",
    "false_positive_reduction_pct",
    "time_to_diagnosis_reduction_seconds",
    "diagnosis_time_reduction_seconds",
    "unsafe_action_reduction",
    "unsafe_actions_prevented",
}
_KUBERNETES_FEEDBACK_ACTIONS = {
    "rollback_deployment",
    "restart_deployment",
    "scale_deployment",
}
_KUBERNETES_FAILING_STATES = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "OOMKilled",
    "Error",
    "ContainerCannotRun",
    "CreateContainerConfigError",
    "CreateContainerError",
}


class KubernetesFeedbackObserver:
    """Re-harvest Kubernetes deployment state after live actuation."""

    def __init__(self, *, kubectl_command: str) -> None:
        self.kubectl_command = kubectl_command

    def observe(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
    ) -> dict[str, dict[str, Any]] | None:
        if not _should_collect_kubernetes_feedback(decision, execution):
            return None
        scope = _kubernetes_feedback_scope(trigger, decision, execution)
        deployment_name = scope.get("deployment_name")
        namespace = scope.get("namespace")
        if not deployment_name or not namespace:
            return None

        signal = collect_kubernetes_signal(
            deployment_name=deployment_name,
            namespace=namespace,
            kube_context=scope.get("kube_context"),
            environment=trigger.environment or "local",
            cluster_label=scope.get("cluster"),
            service=trigger.service,
            kubectl_command=self.kubectl_command,
        )
        return {"30m": _kubernetes_signal_to_observation(signal, trigger)}


class FeedbackService:
    def __init__(
        self,
        observer: PrometheusFeedbackObserver | None = None,
        kubernetes_observer: KubernetesFeedbackObserver | None = None,
        require_live_observations: bool = False,
    ) -> None:
        self.observer = observer
        self.kubernetes_observer = kubernetes_observer
        self.require_live_observations = require_live_observations

    def record(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        normalized_event: EventEnvelope,
    ) -> FeedbackRecord:
        _LOG.info(
            "feedback: record decision=%s execution_status=%s",
            decision.decision_type, execution.status,
        )
        if trigger.trigger_type == "kubernetes_deployment_unhealthy":
            feedback = self._record_kubernetes_feedback(trigger, decision, execution, normalized_event)
            _LOG.info(
                "feedback: outcome=%s recommended_follow_up=%s",
                feedback.outcome, feedback.recommended_follow_up,
            )
            return feedback
        if trigger.trigger_type == "webhook_alert_firing":
            feedback = self._record_webhook_feedback(trigger, decision, execution, normalized_event)
            _LOG.info(
                "feedback: outcome=%s recommended_follow_up=%s",
                feedback.outcome, feedback.recommended_follow_up,
            )
            return feedback
        observations = self._observations(trigger.service, normalized_event)
        check_10m = observations.get("10m", {})
        check_30m = observations.get("30m", {})
        baseline_latency = trigger.metrics["baseline_p95_latency_ms"]
        baseline_error = trigger.metrics["baseline_error_rate"]
        observed_latency = trigger.metrics["observed_p95_latency_ms"]
        observed_error = trigger.metrics["observed_error_rate"]
        post_latency = check_30m.get("p95_latency_ms", observed_latency)
        post_error = check_30m.get("error_rate", observed_error)
        # Reth signals carry latency metrics that can legitimately be
        # ``None`` (RPC degraded → no measurement). Treat ``None < None``
        # as "no improvement observed" rather than crashing the run.
        improved_10m = _safe_lt(
            check_10m.get("p95_latency_ms", observed_latency), observed_latency
        ) and _safe_lt(
            check_10m.get("error_rate", observed_error), observed_error
        )
        review_source, review = _execution_review(execution)
        successful_30m = (
            execution.status == "succeeded"
            and _safe_le(post_latency, _safe_mul(baseline_latency, 1.10))
            and _safe_le(post_error, _safe_mul(baseline_error, 1.20))
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
        if self.require_live_observations and execution.status == "succeeded" and not _has_live_feedback_source(observations):
            return _live_feedback_required_record(
                trigger=trigger,
                decision=decision,
                execution=execution,
                observations=observations,
            )

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
            + ([{"source": review_source, "risk_flags": review.get("risk_flags", [])}] if review else []),
            recommended_follow_up=recommended_follow_up,
            world_model_updates={
                "causal_link_strength": 0.82 if successful_30m else 0.38,
                "flag_risk_score_delta": 0.15 if decision.decision_type == "disable_flag" else 0.08,
                "service_recovery_pattern": _service_recovery_pattern(decision.decision_type, successful_30m),
                "integration_signals": {
                    "evaluation_mode": execution.executor if execution.executor else "unknown",
                    "review_source": review_source,
                    "review_summary": review.get("summary"),
                },
            },
            quality_measurements=_quality_measurements(normalized_event.payload, observations),
        )
        feedback.validate()
        _LOG.info(
            "feedback: outcome=%s recommended_follow_up=%s",
            feedback.outcome, feedback.recommended_follow_up,
        )
        return feedback

    def _record_kubernetes_feedback(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        normalized_event: EventEnvelope,
    ) -> FeedbackRecord:
        observations = self._observations(trigger.service, normalized_event)
        observations = _merge_observations(
            observations,
            self._live_kubernetes_observations(trigger, decision, execution),
        )
        check_30m = observations.get("30m", {})
        review_source, review = _execution_review(execution)
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
        if self.require_live_observations and execution.status == "succeeded" and not _has_live_feedback_source(observations):
            return _live_feedback_required_record(
                trigger=trigger,
                decision=decision,
                execution=execution,
                observations=observations,
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
            + ([{"source": review_source, "risk_flags": review.get("risk_flags", [])}] if review else []),
            world_model_updates={
                "cluster_recovery_pattern": _service_recovery_pattern(decision.decision_type, successful),
                "deployment_name": trigger.related_context.get("deployment_name"),
                "namespace": trigger.related_context.get("namespace"),
                "integration_signals": {
                    "executor": execution.executor,
                    "review_source": review_source,
                    "review_summary": review.get("summary"),
                },
            },
            recommended_follow_up=recommended_follow_up,
            quality_measurements=_quality_measurements(normalized_event.payload, observations),
        )
        feedback.validate()
        return feedback

    def _record_webhook_feedback(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        normalized_event: EventEnvelope,
    ) -> FeedbackRecord:
        observations = self._observations(trigger.service, normalized_event)
        check_30m = observations.get("30m", {})
        review_source, review = _execution_review(execution)
        incident_id = execution.external_refs.get("incident_id") if isinstance(execution.external_refs, dict) else None
        successful = execution.status == "succeeded" and bool(incident_id)
        if self.require_live_observations and execution.status == "succeeded" and not _has_live_feedback_source(observations):
            return _live_feedback_required_record(
                trigger=trigger,
                decision=decision,
                execution=execution,
                observations=observations,
            )
        feedback = FeedbackRecord(
            feedback_id=f"fb_{decision.decision_id}",
            decision_id=decision.decision_id,
            execution_id=execution.execution_id,
            measured_at=check_30m.get("measured_at", datetime.now(timezone.utc).isoformat()),
            window="30m",
            outcome="successful" if successful else "escalated",
            metric_comparison={
                "incident_opened": successful,
                "incident_id": incident_id,
                "severity": trigger.related_context.get("severity"),
            },
            prediction_accuracy={
                "expected_time_to_effect": decision.expected_outcome["time_to_effect"],
                "observed_time_to_effect": "immediate" if successful else "not_achieved",
            },
            side_effects=check_30m.get("side_effects", [])
            + ([{"source": review_source, "risk_flags": review.get("risk_flags", [])}] if review else []),
            world_model_updates={
                "webhook_source_id": trigger.related_context.get("webhook_source_id"),
                "webhook_alert_id": trigger.related_context.get("webhook_alert_id"),
                "incident_routing_pattern": "webhook_alert_opened_incident" if successful else "webhook_alert_failed_to_open_incident",
            },
            recommended_follow_up=None if successful else "human_review",
        )
        feedback.validate()
        return feedback

    def _observations(self, service: str, normalized_event: EventEnvelope) -> dict:
        return augment_observations(
            signal_observations=normalized_event.payload.get("post_action_observations", {}),
            observer=self.observer,
            service=service,
        )

    def _live_kubernetes_observations(
        self,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
    ) -> dict[str, dict[str, Any]]:
        if self.kubernetes_observer is None:
            return {}
        try:
            observations = self.kubernetes_observer.observe(
                trigger=trigger,
                decision=decision,
                execution=execution,
            )
        except Exception:
            _LOG.exception(
                "feedback: live kubernetes observation failed trigger=%s decision=%s",
                trigger.trigger_id,
                decision.decision_id,
            )
            return {}
        return observations or {}


def _should_collect_kubernetes_feedback(decision: Decision, execution: ExecutionRecord) -> bool:
    if execution.status != "succeeded":
        return False
    if not isinstance(execution.external_refs, dict) or execution.external_refs.get("live_execution") is not True:
        return False
    plan = decision.execution_plan if isinstance(decision.execution_plan, dict) else {}
    if plan.get("system") != "kubernetes_service":
        return False
    return str(plan.get("action")) in _KUBERNETES_FEEDBACK_ACTIONS


def _kubernetes_feedback_scope(
    trigger: Trigger,
    decision: Decision,
    execution: ExecutionRecord,
) -> dict[str, str | None]:
    plan = decision.execution_plan if isinstance(decision.execution_plan, dict) else {}
    parameters = plan.get("parameters") if isinstance(plan.get("parameters"), dict) else {}
    refs = execution.external_refs if isinstance(execution.external_refs, dict) else {}
    related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
    return {
        "deployment_name": _first_string(
            refs.get("deployment_name"),
            parameters.get("deployment_name"),
            related.get("deployment_name"),
        ),
        "namespace": _first_string(parameters.get("namespace"), related.get("namespace"), "default"),
        "kube_context": _first_string(refs.get("kube_context"), parameters.get("kube_context"), related.get("kube_context")),
        "cluster": _first_string(parameters.get("cluster"), related.get("cluster")),
    }


def _kubernetes_signal_to_observation(signal: dict[str, Any], trigger: Trigger) -> dict[str, Any]:
    deployment = signal.get("deployment") if isinstance(signal.get("deployment"), dict) else {}
    desired = _to_int(deployment.get("desired_replicas"), trigger.metrics.get("desired_replicas") or 0)
    ready = _to_int(deployment.get("available_replicas"), 0)
    rollout_status = str(deployment.get("rollout_status") or "unknown")
    healthy = rollout_status == "healthy" and ready >= desired
    restart_delta = 0 if healthy else _current_restart_delta(signal)
    return {
        "rollout_status": rollout_status,
        "desired_replicas": desired,
        "ready_replicas": ready,
        "restart_delta": restart_delta,
        "new_error_signatures": [] if healthy else _current_kubernetes_error_signatures(signal),
        "observed_time_to_effect": "immediate" if healthy else "not_achieved",
        "measured_at": str(signal.get("observed_at") or datetime.now(timezone.utc).isoformat()),
        "source": "live_kubernetes_reharvest",
    }


def _current_restart_delta(signal: dict[str, Any]) -> int:
    pods = signal.get("pods") if isinstance(signal.get("pods"), list) else []
    total = 0
    for pod in pods:
        if isinstance(pod, dict):
            total += _to_int(pod.get("restarts"), 0)
    return total


def _current_kubernetes_error_signatures(signal: dict[str, Any]) -> list[str]:
    signatures: set[str] = set()
    pods = signal.get("pods") if isinstance(signal.get("pods"), list) else []
    for pod in pods:
        if not isinstance(pod, dict):
            continue
        status = str(pod.get("container_status") or "")
        last_state = str(pod.get("last_state_reason") or "")
        if status in {"ImagePullBackOff", "ErrImagePull"}:
            signatures.add("image_pull_failure")
        if status == "OOMKilled" or last_state == "OOMKilled":
            signatures.add("oom_killed")
        if status in _KUBERNETES_FAILING_STATES:
            signatures.add("crash_loop")
    logs = signal.get("logs") if isinstance(signal.get("logs"), list) else []
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        message = str(entry.get("message") or "").lower()
        if any(token in message for token in ("modulenotfounderror", "traceback", "exception", "error")):
            signatures.add("application_error")
    events = signal.get("events") if isinstance(signal.get("events"), list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        reason = str(event.get("reason") or "").lower()
        message = str(event.get("message") or "").lower()
        if "backoff" in reason or "back-off restarting" in message:
            signatures.add("crash_loop")
    return sorted(signatures)


def _merge_observations(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    if not override:
        return base
    merged: dict[str, Any] = {}
    for key, value in base.items():
        merged[str(key)] = dict(value) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict):
            existing = merged.get(str(key))
            merged[str(key)] = {**existing, **value} if isinstance(existing, dict) else dict(value)
        else:
            merged[str(key)] = value
    return merged


def _has_live_feedback_source(observations: dict[str, Any]) -> bool:
    if not isinstance(observations, dict):
        return False
    for value in observations.values():
        if not isinstance(value, dict):
            continue
        source = str(value.get("source") or "")
        if source in {"prometheus", "live_kubernetes_reharvest"}:
            return True
    return False


def _live_feedback_required_record(
    *,
    trigger: Trigger,
    decision: Decision,
    execution: ExecutionRecord,
    observations: dict[str, Any],
) -> FeedbackRecord:
    feedback = FeedbackRecord(
        feedback_id=f"fb_{decision.decision_id}",
        decision_id=decision.decision_id,
        execution_id=execution.execution_id,
        measured_at=datetime.now(timezone.utc).isoformat(),
        window="30m",
        outcome="escalated",
        metric_comparison={
            "live_feedback_required": True,
            "live_feedback_source_present": False,
            "observed_sources": sorted(
                {
                    str(window.get("source"))
                    for window in observations.values()
                    if isinstance(window, dict) and window.get("source")
                }
            ),
        },
        prediction_accuracy={
            "expected_time_to_effect": decision.expected_outcome.get("time_to_effect"),
            "observed_time_to_effect": "not_verified",
        },
        side_effects=["pilot feedback requires Prometheus or Kubernetes re-harvest"],
        world_model_updates={
            "service": trigger.service,
            "feedback_gate": "live_feedback_required",
            "action": decision.execution_plan.get("action"),
        },
        recommended_follow_up="human_review",
    )
    feedback.validate()
    return feedback


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _to_int(value: object, default: int = 0) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_lt(a: float | int | None, b: float | int | None) -> bool:
    """``a < b`` that returns False when either side is None.

    Reth-class signals carry latency/error metrics that can be None
    (RPC down, no sample). Treating "no comparison possible" as "no
    improvement observed" is the conservative choice for the
    improvement check.
    """
    if a is None or b is None:
        return False
    return a < b


def _safe_le(a: float | int | None, b: float | int | None) -> bool:
    """``a <= b`` with None-tolerance; returns True when both None."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a <= b


def _safe_mul(a: float | int | None, factor: float) -> float | None:
    if a is None:
        return None
    return a * factor


def _execution_review(execution: ExecutionRecord) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(execution.external_refs, dict):
        return None, {}
    for review_source in ("hermes_review", "goose_review"):
        review = execution.external_refs.get(review_source)
        if isinstance(review, dict):
            return review_source, review
    return None, {}


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


def _quality_measurements(payload: dict[str, Any], observations: dict[str, Any]) -> dict[str, object] | None:
    measurements: dict[str, object] = {}
    evidence_refs: list[str] = []
    for source_name, source in (
        ("signal", payload),
        ("post_action_observations", observations),
        ("post_action_observations.10m", observations.get("10m", {}) if isinstance(observations, dict) else {}),
        ("post_action_observations.30m", observations.get("30m", {}) if isinstance(observations, dict) else {}),
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if str(key).lower() in _QUALITY_MEASUREMENT_FIELDS:
                measurements[str(key)] = value
                evidence_refs.append(f"{source_name}.{key}")
        nested = source.get("quality_measurements")
        if isinstance(nested, dict):
            for key, value in nested.items():
                if str(key).lower() in _QUALITY_MEASUREMENT_FIELDS:
                    measurements[str(key)] = value
                    evidence_refs.append(f"{source_name}.quality_measurements.{key}")
    if not measurements:
        return None
    measurements["evidence_refs"] = tuple(sorted(evidence_refs))
    return measurements
