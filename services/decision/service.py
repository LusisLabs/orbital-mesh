"""Convert a validated trigger into one bounded remediation decision.

The decision stage has three dispatch paths, one per trigger type:

* ``feature_flag_performance_regression`` — original hand-coded branches.
  Feature flag math, protected-scope checks, the full policy-heavy path.
* ``kubernetes_deployment_unhealthy`` — hand-coded symptom matching on event
  reasons and error signatures.
* ``otel_metric_regression`` — the **declarative rule engine**. See
  :mod:`shared.mesh_runtime.metric_action_rules` for the rule format. Rules
  are matched against the incoming signal; when one matches we build a
  ``Decision`` from the rule's ``propose`` block. On no match, we fall
  through to ``escalate`` (a human needs to name the action), which is the
  right default for a signal Mesh has not been taught to handle.

The two hardcoded paths remain because they encode policy nuance (protected
customer tiers, rollback counts) that isn't easy to express in a rule. The
OTel path gets the declarative treatment because the metric surface is
effectively unbounded — we can't ship a Python branch per metric.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.mesh_runtime import Decision, Trigger, load_policy
from shared.mesh_runtime.metric_action_rules import MetricActionMatcher, RuleMatch, load_metric_action_rules

if TYPE_CHECKING:
    from services.decision.llm_fallback import LlmActionProposer
    from shared.mesh_runtime.learning import LearningStore


class DecisionService:
    def __init__(
        self,
        learning_store: LearningStore | None = None,
        metric_action_rules_path: str | None = None,
        llm_proposer: "LlmActionProposer | None" = None,
    ) -> None:
        self.learning_store = learning_store
        # Rules load lazily on first access via the cached loader, so constructing
        # DecisionService is still cheap. Passing an explicit path here is mostly
        # for tests — production uses the default policy file.
        self._metric_action_matcher: MetricActionMatcher = load_metric_action_rules(metric_action_rules_path)
        # Optional Layer 3 fallback. When None, unmatched metrics escalate directly.
        # Injecting the proposer (rather than building it inside DecisionService)
        # keeps the service testable with mock LLMs and zero subprocess overhead.
        self._llm_proposer = llm_proposer

    def decide(self, trigger: Trigger) -> Decision:
        if trigger.trigger_type == "otel_metric_regression":
            return self._decide_otel_metric(trigger)
        if trigger.trigger_type == "kubernetes_deployment_unhealthy":
            return self._decide_kubernetes(trigger)
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
        code_remediation_candidate = bool(trigger.related_context.get("code_remediation_candidate", False))
        repo_path = trigger.related_context.get("repo_path")
        suspected_file = trigger.related_context.get("suspected_file")
        allowed_paths = list(trigger.related_context.get("allowed_paths", []))
        test_commands = list(trigger.related_context.get("test_commands", []))
        patch_template = trigger.related_context.get("patch_template")

        decision_type = "reduce_rollout"
        confidence = 0.82
        risk_level = "medium"
        blast_radius = "single_flag_single_service" if not multi_service_impact else "multi_service"

        if (
            code_remediation_candidate
            and repo_path
            and suspected_file
            and allowed_paths
            and test_commands
            and isinstance(patch_template, dict)
        ):
            decision_type = "investigate_and_patch"
            confidence = 0.78
            risk_level = "medium"
        elif conflicting_signals or high_business_impact:
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

        historical_rate = None
        if self.learning_store is not None:
            historical_rate = self.learning_store.get_historical_success_rate(decision_type, trigger.service)
        confidence = _adjust_confidence(
            confidence,
            similar_prior_cases=similar_prior_cases,
            flag_causality_confidence=flag_causality_confidence,
            trigger_signals=trigger_signals,
            historical_success_rate=historical_rate,
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

    def _decide_otel_metric(self, trigger: Trigger) -> Decision:
        """Decide from an OTel metric regression trigger using the rule engine.

        We reconstruct a minimal signal-shaped dict from the trigger so the
        matcher can run its standard evaluation. When a rule matches we stamp
        its output onto a ``Decision``; when nothing matches we emit
        ``escalate`` with the metric name in the reasoning so a human can add
        a rule.

        The fallthrough is deliberately conservative. Earlier designs returned
        ``no_action`` here, but that silently absorbs unknown metrics — the
        run finishes "successfully" with nothing done. ``escalate`` surfaces
        the gap instead. Operators who want silent handling for specific
        metrics can author a rule that proposes ``no_action``.
        """
        signal_view = _build_signal_view_from_trigger(trigger)
        rule_match = self._metric_action_matcher.match(signal_view)
        if rule_match is not None:
            return self._decision_from_rule_match(trigger, rule_match)

        # Layer 3: the LLM fallback runs only when:
        #   - a proposer was injected at construction time
        #   - no rule matched (we never short-circuit a deterministic rule)
        # LLM failures fall through to escalate; the risk_flags from the
        # proposer are attached to the escalation reasoning so the operator
        # can distinguish "LLM rejected" from "no rules authored".
        llm_risk_flags: list[str] = []
        if self._llm_proposer is not None:
            llm_result = self._llm_proposer.propose(signal_view)
            if llm_result.match is not None:
                return self._decision_from_rule_match(trigger, llm_result.match, llm_risk_flags=llm_result.risk_flags)
            llm_risk_flags = llm_result.risk_flags

        return self._escalate_for_unmatched_metric(trigger, llm_risk_flags=llm_risk_flags)

    def _decision_from_rule_match(
        self,
        trigger: Trigger,
        rule_match: RuleMatch,
        llm_risk_flags: list[str] | None = None,
    ) -> Decision:
        """Materialize a Decision from a matched rule.

        Autonomy tier is derived from the rule's declared risk level. Low-risk
        rules go straight to ``autonomous`` (the approval gate still gates the
        run if the steering mode requires it — the decision stage only sets
        the *floor*, the control plane sets the ceiling).

        Confidence is also taken from the rule, then nudged by observed
        priors: if the same service has seen this pattern before and the
        remediation succeeded, we bump confidence slightly. This is the same
        adjustment we apply to the feature-flag path.
        """
        metric_regression = trigger.related_context.get("metric_regression", {})
        metric_name = metric_regression.get("metric_name", "unknown_metric")
        delta_pct = metric_regression.get("delta_pct")

        autonomy_tier = {
            "low": "autonomous",
            "medium": "approval_required",
            "high": "escalated",
        }.get(rule_match.risk_level, "approval_required")

        historical_rate = None
        if self.learning_store is not None:
            historical_rate = self.learning_store.get_historical_success_rate(
                rule_match.decision_type, trigger.service
            )

        similar_prior_cases = int(trigger.related_context.get("similar_prior_cases", 0))
        confidence = _adjust_confidence(
            rule_match.confidence,
            similar_prior_cases=similar_prior_cases,
            flag_causality_confidence=None,
            trigger_signals=list(trigger.related_context.get("trigger_signals", [])),
            historical_success_rate=historical_rate,
        )

        evidence: list[str] = [
            f"rule {rule_match.rule_name!r} matched metric {metric_name!r}",
        ]
        if delta_pct is not None:
            evidence.append(f"observed delta {delta_pct:.1f}% vs baseline")
        if rule_match.matched_on.get("resource_attributes"):
            attrs_summary = ", ".join(f"{k}={v}" for k, v in rule_match.matched_on["resource_attributes"].items())
            evidence.append(f"resource attributes: {attrs_summary}")
        # When the match came from the LLM fallback, surface the risk flags in
        # the evidence so a reviewer sees "llm_bound_clamped" (or similar) at
        # the decision step rather than having to trace through logs.
        if llm_risk_flags:
            evidence.append(f"llm fallback risk flags: {', '.join(llm_risk_flags)}")

        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type=rule_match.decision_type,
            autonomy_tier=autonomy_tier,
            summary=(
                f"Apply {rule_match.action} on {trigger.service} because rule {rule_match.rule_name!r} "
                f"matched metric {metric_name}."
            ),
            reasoning={
                "primary_hypothesis": (
                    f"{metric_name} regressed on {trigger.service}; rule {rule_match.rule_name!r} "
                    f"proposes {rule_match.decision_type}."
                ),
                "evidence": evidence,
                "evidence_pack": {
                    "matched_rule": rule_match.rule_name,
                    "matched_on": rule_match.matched_on,
                    "metric_regression": metric_regression,
                    "related_metrics": trigger.related_context.get("related_metrics", []),
                    "bounds": rule_match.bounds,
                },
                "alternatives_considered": [
                    "continue with no change",
                    "escalate to human review",
                    rule_match.decision_type,
                ],
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": "<= unchanged (metric-driven action)",
                    "error_rate": "<= unchanged (metric-driven action)",
                },
                "time_to_effect": "10m",
            },
            risk={
                "level": rule_match.risk_level,
                "blast_radius": _metric_blast_radius(rule_match),
                "customer_impact_if_wrong": _customer_impact_if_wrong(rule_match.decision_type),
            },
            confidence=confidence,
            execution_plan={
                "system": rule_match.system,
                "action": rule_match.action,
                "parameters": rule_match.parameters,
                "rollback_plan": rule_match.rollback_plan,
            },
        )
        decision.validate()
        return decision

    def _escalate_for_unmatched_metric(
        self,
        trigger: Trigger,
        llm_risk_flags: list[str] | None = None,
    ) -> Decision:
        """Fall-through when no rule matched and (if enabled) the LLM declined.

        This is the honest response to "Mesh has never been taught what to do
        when metric X regresses". We open an incident and name the metric so a
        human can either act manually or author a rule for next time.

        When the LLM fallback was consulted and also failed, we attach its
        risk flags to the escalation reasoning. That distinction matters for
        operators triaging coverage gaps — "LLM timed out" is an infrastructure
        issue to fix, while "LLM said no action applies" is a real gap that
        deserves a new rule.
        """
        metric_regression = trigger.related_context.get("metric_regression", {})
        metric_name = metric_regression.get("metric_name", "unknown_metric")
        evidence = [
            f"metric {metric_name!r} has no matching rule",
            f"delta {metric_regression.get('delta_pct')}%",
        ]
        if llm_risk_flags:
            evidence.append(f"llm fallback did not produce a usable proposal: {', '.join(llm_risk_flags)}")
        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type="escalate",
            autonomy_tier="escalated",
            summary=(
                f"Escalate {trigger.service}: metric {metric_name} regressed but no "
                "metric-action rule matched."
            ),
            reasoning={
                "primary_hypothesis": (
                    f"Metric {metric_name} on {trigger.service} crossed its threshold, but no rule in the "
                    "metric-action catalog knows how to act on it."
                ),
                "evidence": evidence,
                "evidence_pack": {
                    "metric_regression": metric_regression,
                    "related_metrics": trigger.related_context.get("related_metrics", []),
                    "available_rules": [rule.name for rule in self._metric_action_matcher.rules],
                    "llm_risk_flags": llm_risk_flags or [],
                },
                "alternatives_considered": [
                    "continue with no change",
                    "escalate to human review",
                    "author a metric-action rule and reprocess",
                ],
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": "<= dependent on human response",
                    "error_rate": "<= dependent on human response",
                },
                "time_to_effect": "dependent on operator",
            },
            risk={
                "level": "high",
                "blast_radius": "service_level",
                "customer_impact_if_wrong": _customer_impact_if_wrong("escalate"),
            },
            confidence=0.6,
            execution_plan={
                "system": "incident_service",
                "action": "open_incident",
                "parameters": {
                    "service": trigger.service,
                    "endpoint": trigger.endpoint,
                    "flag_key": None,
                    "environment": trigger.environment,
                    "severity": "medium",
                    "reason": f"metric {metric_name} regressed with no matching rule",
                },
                "rollback_plan": "close the incident if the operator determines no action is needed",
            },
        )
        decision.validate()
        return decision

    def _decide_kubernetes(self, trigger: Trigger) -> Decision:
        error_signatures = list(trigger.related_context.get("error_signatures", []))
        event_reasons = list(trigger.related_context.get("event_reasons", []))
        rollout_status = str(trigger.related_context.get("rollout_status", "degraded"))
        deployment_name = str(trigger.related_context.get("deployment_name", trigger.service))
        namespace = str(trigger.related_context.get("namespace", "default"))
        cluster = str(trigger.related_context.get("cluster", "unknown"))
        image = str(trigger.related_context.get("deployment_image", "unknown"))
        likely_layer = str(trigger.related_context.get("likely_layer", "unknown"))
        code_remediation_candidate = bool(trigger.related_context.get("code_remediation_candidate", False))
        repo_path = trigger.related_context.get("repo_path")
        suspected_file = trigger.related_context.get("suspected_file")
        allowed_paths = list(trigger.related_context.get("allowed_paths", []))
        test_commands = list(trigger.related_context.get("test_commands", []))
        patch_template = trigger.related_context.get("patch_template")
        repeated_rollback = int(trigger.related_context.get("rollbacks_last_24h", 0)) > 0

        if (
            code_remediation_candidate
            and "application_error" in error_signatures
            and repo_path
            and suspected_file
            and allowed_paths
            and test_commands
            and isinstance(patch_template, dict)
        ):
            decision_type = "investigate_and_patch"
            confidence = 0.81
            risk_level = "medium"
            autonomy_tier = "approval_required" if repeated_rollback else "autonomous"
            blast_radius = "single_repo_single_file"
        elif "image_pull_failure" in error_signatures or rollout_status == "failed":
            decision_type = "rollback_deployment"
            confidence = 0.9
            risk_level = "medium"
            autonomy_tier = "autonomous"
            blast_radius = "single_deployment"
        elif "crash_loop" in error_signatures or "probe_failure" in error_signatures or "oom_killed" in error_signatures:
            decision_type = "restart_deployment"
            confidence = 0.78
            risk_level = "medium"
            autonomy_tier = "approval_required" if repeated_rollback else "autonomous"
            blast_radius = "single_deployment"
        else:
            decision_type = "escalate"
            confidence = 0.65
            risk_level = "high"
            autonomy_tier = "escalated"
            blast_radius = "single_deployment"

        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type=decision_type,
            autonomy_tier=autonomy_tier,
            summary=_summary(trigger, decision_type, 0),
            reasoning={
                "primary_hypothesis": (
                    f"Deployment {deployment_name} in {namespace} is unhealthy due to {', '.join(error_signatures or ['unknown runtime symptoms'])}."
                ),
                "evidence": [
                    f"rollout status is {rollout_status}",
                    f"likely failure layer is {likely_layer}",
                    f"event reasons: {', '.join(event_reasons or ['none captured'])}",
                    f"image under analysis: {image}",
                ],
                "evidence_pack": {
                    "error_signatures": error_signatures,
                    "event_reasons": event_reasons,
                    "cluster": cluster,
                    "namespace": namespace,
                    "deployment_name": deployment_name,
                },
                "alternatives_considered": _alternatives(decision_type),
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": "<= unavailable for kubernetes rollout signals",
                    "error_rate": "<= rollout healthy with zero new critical events",
                },
                "time_to_effect": "15m",
            },
            risk={
                "level": risk_level,
                "blast_radius": blast_radius,
                "customer_impact_if_wrong": _customer_impact_if_wrong(decision_type),
            },
            confidence=confidence,
            execution_plan=_execution_plan(trigger, decision_type, 0),
        )
        decision.validate()
        return decision


def _build_signal_view_from_trigger(trigger: Trigger) -> dict:
    """Reconstruct the signal-shaped view the rule matcher expects.

    The trigger carries everything we need — we just reshape it so the
    matcher doesn't have to know about the Trigger model. Keeping the two
    decoupled means the matcher is easy to test directly with signal
    fixtures.
    """
    return {
        "service": trigger.service,
        "endpoint": trigger.endpoint,
        "environment": trigger.environment,
        "metric_regression": trigger.related_context.get("metric_regression", {}),
        "resource_attributes": trigger.related_context.get("resource_attributes", {}),
        "related_metrics": trigger.related_context.get("related_metrics", []),
    }


def _metric_blast_radius(rule_match: RuleMatch) -> str:
    """Name the scope of a metric-action decision for the risk block.

    Distinguishing "single deployment" from "cluster wide" in the decision
    reasoning helps reviewers spot rules that were scoped too broadly. The
    naming is intentionally coarse — the exact blast radius is implicit in
    the bounds.
    """
    if rule_match.system == "kubernetes_service":
        return "single_deployment"
    if rule_match.system == "feature_flag_service":
        return "single_flag"
    return "service_level"


def _delta_pct(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0
    return round(((observed - baseline) / baseline) * 100, 1)


def _ratio(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0 if observed == 0 else float("inf")
    return round(observed / baseline, 2)


def _execution_plan(trigger: Trigger, decision_type: str, target_rollout: int) -> dict[str, object]:
    if decision_type == "rollback_deployment":
        return {
            "system": "kubernetes_service",
            "action": "rollback_deployment",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "namespace": trigger.related_context.get("namespace"),
                "deployment_name": trigger.related_context.get("deployment_name"),
                "revision": trigger.related_context.get("release_id"),
            },
            "rollback_plan": "reapply the unhealthy revision only after human review confirms the rollback was incorrect",
        }
    if decision_type == "restart_deployment":
        return {
            "system": "kubernetes_service",
            "action": "restart_deployment",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "namespace": trigger.related_context.get("namespace"),
                "deployment_name": trigger.related_context.get("deployment_name"),
            },
            "rollback_plan": "rollback deployment to the previous stable revision if restart does not restore readiness",
        }
    if decision_type == "investigate_and_patch":
        patch_template = trigger.related_context.get("patch_template", {})
        return {
            "system": "repo_patch_service",
            "action": "investigate_and_patch",
            "parameters": {
                "repo_path": trigger.related_context.get("repo_path"),
                "allowed_paths": list(trigger.related_context.get("allowed_paths", [])),
                "suspected_file": trigger.related_context.get("suspected_file"),
                "symptom": "search latency regression after semantic rollout change",
                "test_commands": list(trigger.related_context.get("test_commands", [])),
                "patch_template": {
                    "target_file": patch_template.get("target_file"),
                    "find": patch_template.get("find"),
                    "replace": patch_template.get("replace"),
                },
            },
            "rollback_plan": "restore the previous file contents from the saved backup and rerun the bounded verification commands",
        }
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
    if decision_type == "rollback_deployment":
        return (
            f"Rollback Kubernetes deployment {trigger.related_context.get('deployment_name', trigger.service)} in "
            f"{trigger.related_context.get('namespace', 'default')} because the current rollout is unhealthy."
        )
    if decision_type == "restart_deployment":
        return (
            f"Restart Kubernetes deployment {trigger.related_context.get('deployment_name', trigger.service)} in "
            f"{trigger.related_context.get('namespace', 'default')} to clear the unhealthy rollout state."
        )
    if decision_type == "investigate_and_patch":
        return (
            f"Investigate and patch {trigger.related_context.get('suspected_file', trigger.flag_key)} in a bounded repo "
            f"scope to reduce the regression on {trigger.endpoint}."
        )
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
    if decision_type == "rollback_deployment":
        return [
            "restart deployment",
            "open incident",
            "rollback deployment to previous stable revision",
        ]
    if decision_type == "restart_deployment":
        return [
            "rollback deployment",
            "open incident",
            "restart the current deployment revision",
        ]
    if decision_type == "investigate_and_patch":
        return [
            "continue with no change",
            "reduce rollout to 10%",
            "apply a bounded code patch and rerun verification",
        ]
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
    if decision_type in {"rollback_deployment", "restart_deployment"}:
        return "temporary deployment churn or additional recovery time"
    if decision_type == "investigate_and_patch":
        return "temporary service instability from an incorrect bounded patch"
    if decision_type == "disable_flag":
        return "temporary feature unavailability"
    if decision_type == "reduce_rollout":
        return "temporary feature degradation"
    if decision_type == "scale_deployment":
        return "temporary cluster cost increase or capacity pressure if the scaling was unnecessary"
    if decision_type == "patch_resources":
        return "temporary pod restarts and potentially wasted resources if the limits were misjudged"
    if decision_type == "escalate":
        return "continued customer impact until a human operator intervenes"
    return "continued regression exposure"


def _adjust_confidence(
    base_confidence: float,
    *,
    similar_prior_cases: int,
    flag_causality_confidence: float | None,
    trigger_signals: list[str],
    historical_success_rate: float | None = None,
) -> float:
    adjusted = base_confidence
    if similar_prior_cases > 0:
        adjusted += min(similar_prior_cases, 3) * 0.01
    if flag_causality_confidence is not None:
        adjusted += max(min(float(flag_causality_confidence) - 0.5, 0.2), -0.2) * 0.1
    if len(trigger_signals) >= 2:
        adjusted += 0.01
    if historical_success_rate is not None:
        if historical_success_rate >= 0.8:
            adjusted += 0.02
        elif historical_success_rate < 0.4:
            adjusted -= 0.03
    return max(0.5, min(round(adjusted, 2), 0.95))
