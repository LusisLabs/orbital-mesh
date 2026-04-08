"""Convert a validated trigger into one bounded remediation decision."""

from __future__ import annotations

from shared.mesh_runtime import Decision, Trigger, load_policy


class DecisionService:
    def decide(self, trigger: Trigger) -> Decision:
        latency_delta_pct = _delta_pct(
            trigger.metrics["baseline_p95_latency_ms"],
            trigger.metrics["observed_p95_latency_ms"],
        )
        error_multiplier = _ratio(
            trigger.metrics["baseline_error_rate"],
            trigger.metrics["observed_error_rate"],
        )
        timeout_rate = trigger.metrics.get("observed_timeout_rate") or 0.0
        multi_service_impact = bool(trigger.related_context.get("multi_service_impact", False))
        protected_tiers = set(load_policy("protected-scope.policy.json")["approval_required_customer_tiers"])
        protected_tier = trigger.segment["customer_tier"] in protected_tiers
        repeated_rollback = trigger.related_context.get("rollbacks_last_24h", 0) > 0
        conflicting_signals = bool(trigger.related_context.get("conflicting_signals", False))
        high_business_impact = bool(trigger.related_context.get("high_business_impact", False))
        flag_causality_confidence = trigger.related_context.get("flag_causality_confidence")
        active_incidents = int(trigger.related_context.get("active_incidents", 0))
        similar_prior_cases = int(trigger.related_context.get("similar_prior_cases", 0))
        trigger_signals = list(trigger.related_context.get("trigger_signals", []))
        feature_flag_credentials_available = bool(trigger.related_context.get("feature_flag_credentials_available", True))

        decision_type = "reduce_rollout"
        confidence = 0.82
        risk_level = "medium"
        blast_radius = "single_flag_single_service" if not multi_service_impact else "multi_service"

        if conflicting_signals or high_business_impact:
            decision_type = "escalate"
            confidence = 0.64
            risk_level = "high" if high_business_impact else "medium"
        elif flag_causality_confidence is not None and float(flag_causality_confidence) <= 0.35 and timeout_rate < 0.02:
            decision_type = "no_action"
            confidence = 0.79
            risk_level = "low"
        elif timeout_rate >= 0.02 or error_multiplier >= 2 or latency_delta_pct >= 40:
            decision_type = "disable_flag"
            confidence = 0.88
        elif latency_delta_pct < 25 and error_multiplier < 1.5:
            decision_type = "no_action"
            confidence = 0.77
            risk_level = "low"

        if decision_type == "no_action" and active_incidents > 0 and (flag_causality_confidence or 0) >= 0.7:
            decision_type = "reduce_rollout"
            confidence = max(confidence, 0.8)
            risk_level = "medium"

        if decision_type in {"disable_flag", "reduce_rollout"} and not feature_flag_credentials_available:
            decision_type = "escalate"
            confidence = min(confidence, 0.7)
            risk_level = "medium"

        confidence = _adjust_confidence(
            confidence,
            similar_prior_cases=similar_prior_cases,
            flag_causality_confidence=flag_causality_confidence,
            trigger_signals=trigger_signals,
        )

        autonomy_tier = "autonomous"
        if decision_type == "escalate":
            autonomy_tier = "escalated"
        elif multi_service_impact or protected_tier or repeated_rollback:
            autonomy_tier = "approval_required"

        target_rollout = 10 if trigger.current_rollout_pct >= 10 else 0
        execution_plan = _execution_plan(trigger, decision_type, target_rollout)
        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type=decision_type,
            autonomy_tier=autonomy_tier,
            summary=_summary(trigger, decision_type, target_rollout),
            reasoning={
                "primary_hypothesis": (
                    f"The {trigger.flag_key} feature path is increasing request latency and error rates on {trigger.endpoint}."
                ),
                "evidence": _evidence(trigger, latency_delta_pct, error_multiplier, timeout_rate),
                "evidence_pack": {
                    "trigger_signals": trigger_signals,
                    "similar_prior_cases": similar_prior_cases,
                    "active_incidents": active_incidents,
                    "flag_causality_confidence": flag_causality_confidence,
                },
                "alternatives_considered": _alternatives(decision_type),
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": f"<= {round(trigger.metrics['baseline_p95_latency_ms'] * 1.12):.0f}",
                    "error_rate": f"<= {trigger.metrics['baseline_error_rate'] * 1.25:.3f}",
                },
                "time_to_effect": "10m",
            },
            risk={
                "level": risk_level,
                "blast_radius": blast_radius,
                "customer_impact_if_wrong": _customer_impact_if_wrong(decision_type),
            },
            confidence=confidence,
            execution_plan=execution_plan,
        )
        decision.validate()
        return decision


def _delta_pct(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0
    return round(((observed - baseline) / baseline) * 100, 1)


def _ratio(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0 if observed == 0 else float("inf")
    return round(observed / baseline, 2)


def _execution_plan(trigger: Trigger, decision_type: str, target_rollout: int) -> dict[str, object]:
    if decision_type == "disable_flag":
        return {
            "system": "feature_flag_service",
            "action": "set_rollout",
            "parameters": {
                "flag_key": trigger.flag_key,
                "environment": trigger.environment,
                "rollout_pct": 0,
            },
            "rollback_plan": (
                f"restore previous rollout percentage of {trigger.current_rollout_pct} if follow-up evaluation disproves causality"
            ),
        }
    if decision_type == "reduce_rollout":
        return {
            "system": "feature_flag_service",
            "action": "set_rollout",
            "parameters": {
                "flag_key": trigger.flag_key,
                "environment": trigger.environment,
                "rollout_pct": target_rollout,
            },
            "rollback_plan": (
                f"restore previous rollout percentage of {trigger.current_rollout_pct} if follow-up evaluation disproves causality"
            ),
        }
    if decision_type == "escalate":
        return {
            "system": "incident_service",
            "action": "open_incident",
            "parameters": {
                "service": trigger.service,
                "endpoint": trigger.endpoint,
                "flag_key": trigger.flag_key,
                "environment": trigger.environment,
                "severity": "high",
            },
            "rollback_plan": "close or downgrade the incident once a human owner confirms the system state",
        }
    return {
        "system": "audit_log_sink",
        "action": "record_no_action",
        "parameters": {
            "flag_key": trigger.flag_key,
            "environment": trigger.environment,
            "reason": "regression signal did not justify an automated remediation step",
        },
        "rollback_plan": "no rollback required",
    }


def _summary(trigger: Trigger, decision_type: str, target_rollout: int) -> str:
    if decision_type == "disable_flag":
        return (
            f"Disable {trigger.flag_key} for {trigger.environment} due to sustained latency and error regression "
            f"after rollout increase to {trigger.current_rollout_pct}%."
        )
    if decision_type == "reduce_rollout":
        return (
            f"Reduce {trigger.flag_key} rollout from {trigger.current_rollout_pct}% to {target_rollout}% in "
            f"{trigger.environment} to contain the regression on {trigger.endpoint}."
        )
    if decision_type == "escalate":
        return (
            f"Escalate {trigger.flag_key} regression on {trigger.service} for human review due to conflicting "
            "signals or elevated business impact."
        )
    return (
        f"Record no action for {trigger.flag_key} because the current signal does not justify a bounded automated "
        "feature-flag change."
    )


def _evidence(trigger: Trigger, latency_delta_pct: float, error_multiplier: float, timeout_rate: float) -> list[str]:
    evidence = [
        f"p95 latency increased {latency_delta_pct:.1f}% vs baseline",
        f"error rate increased {error_multiplier:.2f}x vs baseline",
        (
            f"regression began within {trigger.related_context.get('minutes_since_flag_change', 'unknown')} "
            "minutes of rollout increase"
        ),
    ]
    if timeout_rate >= 0.02:
        evidence.append(f"timeout rate reached {timeout_rate * 100:.1f}%")
    return evidence


def _alternatives(decision_type: str) -> list[str]:
    if decision_type == "escalate":
        return [
            "continue with no change",
            "reduce rollout to 10%",
            "escalate to human review",
        ]
    return [
        "continue with no change",
        "reduce rollout to 10%",
        "disable feature flag fully",
    ]


def _customer_impact_if_wrong(decision_type: str) -> str:
    if decision_type == "disable_flag":
        return "temporary feature unavailability"
    if decision_type == "reduce_rollout":
        return "temporary feature degradation"
    if decision_type == "escalate":
        return "continued customer impact until a human operator intervenes"
    return "continued regression exposure"


def _adjust_confidence(
    base_confidence: float,
    *,
    similar_prior_cases: int,
    flag_causality_confidence: float | None,
    trigger_signals: list[str],
) -> float:
    adjusted = base_confidence
    if similar_prior_cases > 0:
        adjusted += min(similar_prior_cases, 3) * 0.01
    if flag_causality_confidence is not None:
        adjusted += max(min(float(flag_causality_confidence) - 0.5, 0.2), -0.2) * 0.1
    if len(trigger_signals) >= 2:
        adjusted += 0.01
    return max(0.5, min(round(adjusted, 2), 0.95))
