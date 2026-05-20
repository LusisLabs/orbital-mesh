"""Convert a validated trigger into one bounded remediation decision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.mesh_runtime import Decision, Trigger, load_policy
from shared.mesh_runtime.metric_action_rules import MetricActionMatcher, RuleMatch, load_metric_action_rules
from shared.mesh_runtime.review_blockers import classify_review_reasons


_LOG = logging.getLogger("mesh.decision")

if TYPE_CHECKING:
    from services.decision.hypothesis_engine import HypothesisEngine
    from services.decision.llm_fallback import LlmActionProposer
    from services.decision.llm_reasoning import EscalationReasoner
    from services.observer import LlmObserver
    from services.signal_history import SignalHistoryStore
    from shared.mesh_runtime import ScenarioAnalysis
    from shared.mesh_runtime.learning import LearningStore


# Deploy correlation threshold for the SRE-grade k8s policy. A crash
# starting within this window of a deploy is treated as deploy-caused;
# above the threshold, the bug existed before the rollout and rollback
# would not fix it. 30 minutes is the standard heuristic used by most
# on-call runbooks (Google SRE handbook + the broader incident response
# literature). Operators who want a different threshold can set
# MESH_K8S_DEPLOY_CORRELATION_WINDOW_SECONDS.
import os as _os
_DEPLOY_CORRELATION_WINDOW_SECONDS: int = int(
    _os.getenv("MESH_K8S_DEPLOY_CORRELATION_WINDOW_SECONDS", "1800")
)


_LLM_ALLOWED_ACTIONS = frozenset({
    "reduce_rollout",
    "disable_flag",
    "restart_deployment",
    "rollback_deployment",
    "no_action",
})


class DecisionService:
    def __init__(
        self,
        learning_store: LearningStore | None = None,
        escalation_reasoner: EscalationReasoner | None = None,
        hypothesis_engine: HypothesisEngine | None = None,
        metric_action_rules_path: str | None = None,
        llm_proposer: "LlmActionProposer | None" = None,
        llm_observer: "LlmObserver | None" = None,
        signal_history: "SignalHistoryStore | None" = None,
    ) -> None:
        self.learning_store = learning_store
        self.escalation_reasoner = escalation_reasoner
        self.hypothesis_engine = hypothesis_engine
        # declarative rule matcher for OTel metric-regression signals.
        # Load lazily through the cached loader so constructing DecisionService
        self._metric_action_matcher: MetricActionMatcher = load_metric_action_rules(metric_action_rules_path)
        # optional LLM fallback invoked only when no rule matched.
        # Injected rather than constructed here so tests can pass a mock.
        self._llm_proposer = llm_proposer
        # optional LLM observer that reviews the deterministic
        # decision and can promote (but not demote) toward escalation.
        # See services/observer/ — provider-neutral, OpenAI-compatible.
        self._llm_observer = llm_observer
        # Per-target signal-history store. When present, the decision
        # service can ask "has peer_count been below floor for ≥ N
        # seconds?" instead of judging on a single tick. See S2 in the
        # audit notes — this is what gives the engine memory.
        self.signal_history = signal_history

    def decide(
        self,
        trigger: Trigger,
        scenario_analysis: ScenarioAnalysis | dict | None = None,
        evidence_pack: dict | None = None,
        reasoning_bank_packet: dict | None = None,
        investigation_report: dict | None = None,
    ) -> Decision:
        # Log the branch up front. Readers scanning a server log for
        # "why did Mesh propose X" need to know which decision path ran
        # before they look at the rule registry, the LLM fallback, or
        # the feature-flag heuristics. One line here saves a lot of
        # guessing later.
        _LOG.info(
            "decide: branch trigger_type=%s service=%s trigger_id=%s",
            trigger.trigger_type, trigger.service, trigger.trigger_id,
        )
        if trigger.trigger_type == "otel_metric_regression":
            decision = self._decide_otel_metric(trigger)
            _attach_reasoning_bank_context(decision, reasoning_bank_packet)
            _attach_investigation_report(decision, investigation_report)
            decision.validate()
            _LOG.info(
                "decide: emitted decision_type=%s action=%s confidence=%.2f tier=%s",
                decision.decision_type,
                decision.execution_plan.get("action"),
                decision.confidence,
                decision.autonomy_tier,
            )
            return decision
        if trigger.trigger_type == "kubernetes_deployment_unhealthy":
            decision = self._decide_kubernetes(
                trigger,
                scenario_analysis=scenario_analysis,
                investigation_report=investigation_report,
            )
            _attach_reasoning_bank_context(decision, reasoning_bank_packet)
            _attach_investigation_report(decision, investigation_report)
            decision.validate()
            _LOG.info(
                "decide: emitted decision_type=%s action=%s confidence=%.2f tier=%s",
                decision.decision_type,
                decision.execution_plan.get("action"),
                decision.confidence,
                decision.autonomy_tier,
            )
            return decision
        if trigger.trigger_type == "reth_node_degraded":
            decision = self._decide_reth_node(
                trigger,
                evidence_pack=evidence_pack,
                investigation_report=investigation_report,
            )
            _attach_reasoning_bank_context(decision, reasoning_bank_packet)
            _attach_investigation_report(decision, investigation_report)
            decision.validate()
            _LOG.info(
                "decide: emitted decision_type=%s action=%s confidence=%.2f tier=%s",
                decision.decision_type,
                decision.execution_plan.get("action"),
                decision.confidence,
                decision.autonomy_tier,
            )
            return decision
        if trigger.trigger_type == "webhook_alert_firing":
            decision = self._decide_webhook_alert(trigger)
            _attach_reasoning_bank_context(decision, reasoning_bank_packet)
            _attach_investigation_report(decision, investigation_report)
            decision.validate()
            _LOG.info(
                "decide: emitted decision_type=%s action=%s confidence=%.2f tier=%s",
                decision.decision_type,
                decision.execution_plan.get("action"),
                decision.confidence,
                decision.autonomy_tier,
            )
            return decision
        if trigger.trigger_type == "generic_signal_firing":
            decision = self._decide_generic_signal(
                trigger,
                evidence_pack=evidence_pack,
                investigation_report=investigation_report,
            )
            _attach_reasoning_bank_context(decision, reasoning_bank_packet)
            _attach_investigation_report(decision, investigation_report)
            decision.validate()
            _LOG.info(
                "decide: emitted decision_type=%s action=%s confidence=%.2f tier=%s",
                decision.decision_type,
                decision.execution_plan.get("action"),
                decision.confidence,
                decision.autonomy_tier,
            )
            return decision
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
        flag_rollback_conflict = bool(trigger.related_context.get("flag_rollback_conflict", False))
        high_business_impact = bool(trigger.related_context.get("high_business_impact", False))
        flag_causality_confidence = trigger.related_context.get("flag_causality_confidence")
        active_incidents = int(trigger.related_context.get("active_incidents", 0))
        similar_prior_cases = int(trigger.related_context.get("similar_prior_cases", 0))
        trigger_signals = list(trigger.related_context.get("trigger_signals", []))
        recovery_context = _recovery_context(trigger)
        feature_flag_credentials_available = bool(trigger.related_context.get("feature_flag_credentials_available", True))
        code_remediation_candidate = bool(trigger.related_context.get("code_remediation_candidate", False))
        repo_path = trigger.related_context.get("repo_path")
        suspected_file = trigger.related_context.get("suspected_file")
        allowed_paths = list(trigger.related_context.get("allowed_paths", []))
        test_commands = list(trigger.related_context.get("test_commands", []))
        patch_template = trigger.related_context.get("patch_template")

        decision_type = "escalate"
        confidence = 0.60
        risk_level = "high"
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
        elif high_business_impact or flag_rollback_conflict:
            decision_type = "escalate"
            confidence = 0.64
            risk_level = "high"
        elif flag_causality_confidence is not None and float(flag_causality_confidence) <= 0.35 and timeout_rate < 0.02:
            decision_type = "no_action"
            confidence = 0.79
            risk_level = "low"
        elif timeout_rate >= 0.02 or error_multiplier >= 2 or latency_delta_pct >= 40:
            decision_type = "disable_flag"
            confidence = 0.88
            # ``aa1fbc1`` raised the initial ``risk_level`` to "high" so
            # the unclassified-fallback escalates safely. This branch
            # must reset because ``disable_flag`` is a deterministic,
            # well-understood action — leaving ``risk_level="high"``
            # makes the evaluation's risk gate flag every disable_flag
            # decision and parks the run at ``awaiting_operator`` even
            # in ``interruptible_auto`` mode.
            risk_level = "medium"
        elif latency_delta_pct < 25 and error_multiplier < 1.5:
            decision_type = "no_action"
            confidence = 0.77
            risk_level = "low"
        elif _feature_flag_reduction_supported(
            trigger,
            latency_delta_pct=latency_delta_pct,
            error_multiplier=error_multiplier,
            timeout_rate=timeout_rate,
        ):
            decision_type = "reduce_rollout"
            confidence = 0.82
            risk_level = "medium"
        else:
            _LOG.info(
                "decide: feature-flag fallback escalates; no explicit bounded action matched "
                "latency_delta_pct=%.1f error_multiplier=%.2f timeout_rate=%.3f",
                latency_delta_pct,
                error_multiplier,
                timeout_rate,
            )

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
        confidence_factors = _build_confidence_factors(
            base_confidence=confidence,
            similar_prior_cases=similar_prior_cases,
            flag_causality_confidence=flag_causality_confidence,
            trigger_signals=trigger_signals,
            historical_success_rate=historical_rate,
            recovery_context=recovery_context,
        )
        confidence = _confidence_from_factors(confidence_factors)

        if self.escalation_reasoner and (decision_type == "escalate" or confidence < 0.65):
            reasoning = self.escalation_reasoner.reason(trigger)
            if (
                reasoning.confidence > confidence
                and reasoning.suggested_action != "escalate"
                and reasoning.suggested_action in _LLM_ALLOWED_ACTIONS
            ):
                decision_type = reasoning.suggested_action
                confidence = min(reasoning.confidence, 0.85)
                risk_level = "medium"

        autonomy_tier = "autonomous"
        if decision_type == "escalate":
            autonomy_tier = "escalated"
        elif multi_service_impact or protected_tier or repeated_rollback:
            autonomy_tier = "approval_required"

        target_rollout = 10 if (trigger.current_rollout_pct or 0) >= 10 else 0
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
                    "recovery_context": recovery_context,
                    "confidence_factors": confidence_factors,
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
        decision = _apply_scenario_analysis(decision, trigger, scenario_analysis, target_rollout)
        _attach_reasoning_bank_context(decision, reasoning_bank_packet)
        _attach_investigation_report(decision, investigation_report)
        decision.validate()
        return decision

    def _decide_webhook_alert(self, trigger: Trigger) -> Decision:
        severity = str(trigger.related_context.get("severity") or "warning").lower()
        high_severity = severity in {"critical", "high", "p1", "sev1", "sev2"}
        confidence = 0.84 if high_severity else 0.76
        autonomy_tier = "autonomous" if high_severity else "approval_required"
        return Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            summary=(
                f"Open an incident for webhook alert "
                f"{trigger.related_context.get('webhook_alert_id', 'unknown')} on {trigger.service}."
            ),
            decision_type="escalate",
            autonomy_tier=autonomy_tier,
            reasoning={
                "primary_hypothesis": "A verified external alert fired and should be routed into the bounded incident lane.",
                "evidence": [
                    f"severity={severity}",
                    f"source={trigger.related_context.get('webhook_source_id', 'unknown')}",
                    f"title={trigger.related_context.get('title', 'unknown')}",
                ],
                "evidence_pack": {
                    "labels": trigger.related_context.get("labels", {}),
                    "annotations": trigger.related_context.get("annotations", {}),
                },
                "alternatives_considered": ["record_no_action"],
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": "n/a",
                    "error_rate": "n/a",
                },
                "time_to_effect": "immediate",
            },
            risk={
                "level": "low" if high_severity else "medium",
                "blast_radius": "single_service",
                "customer_impact_if_wrong": "limited to creating an unnecessary human-review incident",
            },
            confidence=confidence,
            execution_plan={
                "system": "incident_service",
                "action": "open_incident",
                "parameters": {
                    "service": trigger.service,
                    "endpoint": trigger.endpoint,
                    "environment": trigger.environment,
                    "severity": "high" if high_severity else "medium",
                    "source": "webhook_alert",
                    "source_id": trigger.related_context.get("webhook_source_id"),
                    "alert_id": trigger.related_context.get("webhook_alert_id"),
                    "summary": trigger.related_context.get("title") or "webhook alert fired",
                    "reason": trigger.related_context.get("description") or "external alert fired",
                    "labels": trigger.related_context.get("labels", {}),
                },
                "rollback_plan": "close or downgrade the incident once an operator confirms the alert is resolved or non-actionable",
            },
        )

    # ------------------------------------------------------------------ OTel

    def _decide_generic_signal(
        self,
        trigger: Trigger,
        evidence_pack: dict | None = None,
        investigation_report: dict | None = None,
    ) -> Decision:
        candidates = (
            investigation_report.get("root_cause_candidates")
            if isinstance(investigation_report, dict)
            else []
        )
        ranked = [item for item in candidates if isinstance(item, dict)][:8] if isinstance(candidates, list) else []
        return Decision(
            decision_id=f"dec_generic_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            summary=(
                f"Escalate unknown signal type for {trigger.service}; no registered profile may auto-act."
            ),
            decision_type="escalate",
            autonomy_tier="escalated",
            reasoning={
                "primary_hypothesis": (
                    "Unknown signal type reached the generic fallback; route to operator review."
                ),
                "evidence": [
                    f"signal_type={trigger.related_context.get('signal_type') or 'unknown'}",
                    f"trigger_type={trigger.trigger_type}",
                    f"evidence_sufficient={(evidence_pack or {}).get('sufficient') if isinstance(evidence_pack, dict) else False}",
                ],
                "evidence_pack": {
                    "source": (evidence_pack or {}).get("source") if isinstance(evidence_pack, dict) else None,
                    "sufficient": (evidence_pack or {}).get("sufficient") if isinstance(evidence_pack, dict) else False,
                    "missing_fields": (evidence_pack or {}).get("missing_fields", []) if isinstance(evidence_pack, dict) else [],
                    "investigation_report": investigation_report if isinstance(investigation_report, dict) else {},
                },
                "ranked_hypotheses": ranked,
                "alternatives_considered": [
                    "auto-act on unknown signal — rejected because no profile is registered",
                    "ignore unknown signal — rejected because silent skips violate the harness contract",
                ],
            },
            expected_outcome={
                "target_metrics": {"p95_latency_ms": "unknown", "error_rate": "unknown"},
                "time_to_effect": "operator_dependent",
            },
            risk={
                "level": "high",
                "blast_radius": "unknown",
                "customer_impact_if_wrong": "Unknown signal semantics require human review.",
            },
            confidence=0.5,
            execution_plan={
                "system": "incident_service",
                "action": "open_incident",
                "parameters": {
                    "service": trigger.service,
                    "endpoint": trigger.endpoint,
                    "environment": trigger.environment,
                    "source": "signal_profile_registry:generic",
                    "trigger_id": trigger.trigger_id,
                },
                "rollback_plan": "no_op",
            },
        )

    def _decide_reth_node(
        self,
        trigger: Trigger,
        evidence_pack: dict | None = None,
        investigation_report: dict | None = None,
    ) -> Decision:
        """Decide on a first-class Reth node health trigger.

        Reth is stateful execution infrastructure, so the safe default differs
        from stateless Kubernetes apps: restart only for bounded process/network
        symptoms, and escalate for storage, JWT/Engine API, or DB-like failures.

        When a hypothesis engine is bound, ranked hypotheses are computed
        from the evidence pack and stamped on the reasoning record. The top
        hypothesis can *promote* a restart to escalate, but never *demote*
        a deterministic escalation — the safety direction is one-way.
        Likewise, if the evidence pack is marked insufficient, the
        decision is forced to escalate regardless of which signatures
        matched.
        """
        signatures = set(trigger.related_context.get("error_signatures", []))
        policy = load_policy("reth-node.policy.json")
        node = trigger.related_context.get("node", {})
        execution = trigger.related_context.get("execution", {})
        consensus = trigger.related_context.get("consensus", {})
        storage = trigger.related_context.get("storage", {})
        resource_attributes = trigger.related_context.get("resource_attributes", {})

        # S2: pull a small set of trend predicates from signal history.
        # When a history store is bound, we ask "has peer_count been
        # below the floor for ≥ X seconds?" instead of trusting a
        # single tick. This is the single biggest false-positive
        # reduction available — most ladder branches over-fire on
        # transient network blips, and "sustained" is exactly the
        # extra evidence that distinguishes blip from real partition.
        history_trends = self._reth_history_trends(trigger, execution)

        # Restart-rate cap. Two sources, max wins:
        #   1. ``systemd_restarts_last_1h`` from the trigger payload —
        #      what the host's systemd remembers. Reliable when the
        #      ingester probed it; missing or stale otherwise.
        #   2. Mesh's own decision history via ``learning_store`` — what
        #      *Mesh* recommended in the last hour. Catches the case
        #      where the host was rebuilt but Mesh's run history shows
        #      "we asked you to restart this thing 5 times today."
        recent_restarts_signal = int(trigger.related_context.get("systemd_restarts_last_1h", 0) or 0)
        recent_restarts_mesh = 0
        window_seconds = int(policy.get("restart_window_seconds", 3600))
        if self.learning_store is not None:
            try:
                recent_restarts_mesh = self.learning_store.count_recent_decisions(
                    decision_type="restart_systemd_service",
                    service=trigger.service,
                    within_seconds=window_seconds,
                )
            except Exception:
                # Never let a learning-store failure break decisions —
                # we have the trigger's count as a fallback.
                _LOG.exception(
                    "decide.reth: learning_store.count_recent_decisions failed; "
                    "falling back to trigger-stamped count",
                )
        recent_restarts = max(recent_restarts_signal, recent_restarts_mesh)
        if recent_restarts >= int(policy["max_restarts_per_window"]):
            signatures.add("restart_frequency_exceeded")

        # Validator-state safety: refuse to even consider an EL restart
        # when the paired CL has imminent attestation/proposal duty.
        # Restarting Reth mid-attestation costs the operator one missed
        # attestation; restarting in the proposer's slot can cost a
        # missed block (worth tens of ETH post-MaxEB). The CL-side
        # exporter stamps these fields; if neither is present we fall
        # through (no opinion) — this guard never *adds* aggressiveness,
        # only conservatism.
        validator_pending = consensus.get("validator_attestation_pending")
        proposer_eta = consensus.get("validator_proposer_within_seconds")
        validator_duty_imminent = bool(validator_pending) or (
            isinstance(proposer_eta, int) and 0 <= proposer_eta <= 30
        )
        if validator_duty_imminent:
            signatures.add("validator_duty_imminent")

        # Doppelganger-protection guard: a CL that just imported keys
        # spends 2 epochs (~13 min) listening for self-attestations
        # before signing. Restarting the EL during that window resets
        # the CL's view of head and forces the doppelganger window to
        # re-arm — costing missed attestations and, worse, masking a
        # genuine duplicate-VC if one exists. Hard rule: any time
        # ``doppelganger_protection_active=true``, refuse to restart.
        if consensus.get("doppelganger_protection_active") is True:
            signatures.add("doppelganger_window_active")

        # Slashing-protection DB freshness guard: a non-null value below
        # the threshold means the operator (or their automation) just
        # restored the slashing-protection DB from backup. Per the
        # research dossier, that's the most common cause of mainnet
        # slashing (EIP-3076 high-watermark not advanced past the last
        # signed slot). We refuse all action — let the operator confirm
        # the DB is consistent with on-chain history before resuming.
        slashing_age = consensus.get("slashing_db_restored_within_seconds")
        if isinstance(slashing_age, (int, float)) and 0 <= slashing_age < 3600:
            signatures.add("slashing_db_recently_restored")

        restartable = signatures & set(policy["restartable_signatures"])
        unsafe = signatures & set(policy["escalation_signatures"])
        # G1: ``node_unreachable`` is special. It's listed in
        # ``escalation_signatures`` so the default safe path is "escalate
        # to a human", but operators can opt into an SSH-based recovery
        # attempt: SSH and JSON-RPC are different network paths, so when
        # the RPC port is dead but SSH still works, the service is wedged
        # on a live host — exactly what ``systemctl restart`` is for.
        # We surface this as a low-confidence approval-required
        # ``restart_systemd_service`` proposal, never autonomous.
        is_node_unreachable = "node_unreachable" in signatures
        recovery_cfg = policy.get("node_unreachable_recovery") or {}
        recovery_mode = str(recovery_cfg.get("mode", "escalate_only"))

        if unsafe:
            decision_type = "escalate"
            confidence = 0.74
            risk_level = "high"
            autonomy_tier = "escalated"
            # If the only unsafe signature is node_unreachable AND policy
            # opts into SSH-based recovery AND we haven't recently tried,
            # downgrade from pure-escalate to a restart proposal that the
            # human can approve. Never autonomous — the host might be
            # truly dead and we don't want to flap.
            if (
                is_node_unreachable
                and unsafe == {"node_unreachable"}
                and recovery_mode == "ssh_restart_with_approval"
                and recent_restarts < int(recovery_cfg.get("max_recovery_attempts_per_window", 1))
            ):
                decision_type = "restart_systemd_service"
                confidence = float(recovery_cfg.get("ssh_restart_confidence", 0.55))
                risk_level = "medium"
                autonomy_tier = "approval_required"
        elif restartable:
            # A restartable signature is only a lead. Reth is stateful, so
            # the signal alone must not choose a process restart; evidence
            # and hypothesis ranking have to defend that action below.
            decision_type = "escalate"
            confidence = 0.62
            risk_level = "medium"
            autonomy_tier = "escalated"
        else:
            decision_type = "no_action"
            confidence = 0.66
            risk_level = "low"
            autonomy_tier = "autonomous"

        # Hypothesis ranking. The engine is optional; when absent, the
        # downstream observer (LLM) reads only the deterministic decision.
        ranked_hypotheses: list[dict] = []
        top_hypothesis: dict | None = None
        if self.hypothesis_engine is not None:
            try:
                hypotheses = self.hypothesis_engine.generate(
                    trigger,
                    evidence_pack=evidence_pack,
                    investigation_report=investigation_report,
                )
                ranked_hypotheses = [h.to_dict() for h in hypotheses]
                if ranked_hypotheses:
                    top_hypothesis = ranked_hypotheses[0]
            except Exception:
                _LOG.exception("hypothesis_engine.generate failed for trigger=%s", trigger.trigger_id)

        # Evidence-backed restart: the only Reth autonomous-ish remediation
        # in this slice is an approval-gated systemd restart, and even that
        # requires a sufficient evidence pack plus a top hypothesis that
        # specifically recommends restart. Raw restartable signatures never
        # get to select this action on their own.
        if (
            restartable
            and not unsafe
            and _reth_restart_supported_by_evidence(top_hypothesis, evidence_pack)
        ):
            decision_type = "restart_systemd_service"
            confidence = max(
                confidence,
                float(top_hypothesis.get("posterior_confidence", 0.72)) if top_hypothesis is not None else 0.72,
            )
            risk_level = "medium"
            autonomy_tier = "approval_required" if policy.get("require_approval_for_restart", True) else "autonomous"

        # One-way promotion: hypothesis can move us toward escalate but
        # never away from it. ``no_action``/``restart_systemd_service`` →
        # ``escalate`` is allowed when the top hypothesis recommends it
        # with high posterior. Anything in the reverse direction is
        # ignored — the deterministic policy is the safety floor.
        if (
            top_hypothesis is not None
            and top_hypothesis.get("recommended_action") == "escalate"
            and float(top_hypothesis.get("posterior_confidence", 0)) >= 0.55
            and decision_type != "escalate"
        ):
            _LOG.info(
                "decide.reth: hypothesis promoted to escalate id=%s posterior=%.2f",
                top_hypothesis.get("hypothesis_id"),
                float(top_hypothesis.get("posterior_confidence", 0)),
            )
            decision_type = "escalate"
            confidence = max(confidence, 0.75)
            risk_level = "high"
            autonomy_tier = "escalated"

        # Evidence sufficiency override: an insufficient pack forces
        # escalation. We act on facts, not on the absence of them.
        if isinstance(evidence_pack, dict) and evidence_pack.get("sufficient") is False:
            if decision_type != "escalate":
                _LOG.info(
                    "decide.reth: insufficient evidence pack forces escalate, missing=%s",
                    evidence_pack.get("missing_fields"),
                )
                decision_type = "escalate"
                confidence = max(confidence, 0.70)
                risk_level = "high"
                autonomy_tier = "escalated"

        # Fast-path override: when the EvidenceService skipped probe
        # assembly because the trigger already named a credential or
        # exposure signature, the only safe outcome is escalate. We
        # do NOT rely on the autonomy/escalation_signatures cross-file
        # invariant here — if a fast-path signature is missing from the
        # policy's escalation list, that's a misconfig that should still
        # not produce ``no_action`` for an unsafe condition. Belt and
        # suspenders.
        fast_path = (
            (evidence_pack or {}).get("fast_path_signatures")
            if isinstance(evidence_pack, dict)
            else None
        )
        if fast_path:
            if decision_type != "escalate":
                _LOG.warning(
                    "decide.reth: fast-path signatures forced escalate (policy "
                    "did not already escalate, possible misconfig); signatures=%s",
                    fast_path,
                )
                decision_type = "escalate"
                confidence = max(confidence, 0.80)
                risk_level = "high"
                autonomy_tier = "escalated"

        evidence = [
            f"reth node role={node.get('role', 'unknown')} network={node.get('network', 'unknown')}",
            f"peer_count={execution.get('peer_count')} block_lag={execution.get('block_lag')} syncing={execution.get('syncing')}",
            f"engine_api_reachable={consensus.get('engine_api_reachable')} forkchoice_recent={consensus.get('forkchoice_updates_recent')}",
            f"disk_used_pct={storage.get('disk_used_pct')}",
        ]
        primary_hypothesis = _reth_primary_hypothesis(trigger, signatures, top_hypothesis)

        # Layer 5: LLM observer review. The observer reads the
        # deterministic snapshot and emits a verdict; only ``escalate``,
        # ``reject_unsafe``, and ``request_more_evidence`` change the
        # outcome, and only in the safer direction. ``approve`` is a
        # no-op. A failed/disabled observer behaves like ``approve``,
        # so the deterministic engine remains the floor.
        observer_verdict_dict: dict | None = None
        if self._llm_observer is not None and self._llm_observer.is_active():
            try:
                deterministic_snapshot = {
                    "decision_type": decision_type,
                    "autonomy_tier": autonomy_tier,
                    "confidence": confidence,
                    "reasoning": {
                        "primary_hypothesis": primary_hypothesis,
                    },
                }
                verdict = self._llm_observer.review(
                    trigger=trigger.to_dict(),
                    evidence_pack=evidence_pack,
                    ranked_hypotheses=ranked_hypotheses,
                    deterministic_decision=deterministic_snapshot,
                    policy_excerpt=policy,
                )
                observer_verdict_dict = verdict.to_dict()
                if verdict.promotes_to_escalate() and decision_type != "escalate":
                    _LOG.info(
                        "decide.reth: observer promoted to escalate verdict=%s reason=%s",
                        verdict.verdict,
                        verdict.reason,
                    )
                    decision_type = "escalate"
                    autonomy_tier = "escalated"
                    risk_level = "high"
                    confidence = max(confidence, 0.75)
            except Exception:
                _LOG.exception("LLM observer raised; deterministic decision stands")

        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type=decision_type,
            autonomy_tier=autonomy_tier,
            summary=_summary(trigger, decision_type, 0),
            reasoning={
                "primary_hypothesis": primary_hypothesis,
                "ranked_hypotheses": ranked_hypotheses,
                "observer_verdict": observer_verdict_dict,
                "evidence": evidence,
                "evidence_pack": {
                    "error_signatures": sorted(signatures),
                    "node": node,
                    "execution": execution,
                    "consensus": consensus,
                    "storage": storage,
                    "resource_attributes": resource_attributes,
                    "history_trends": history_trends,
                    "reth_policy": {
                        "max_restarts_per_window": policy["max_restarts_per_window"],
                        "restart_window_seconds": policy["restart_window_seconds"],
                        "require_approval_for_restart": policy["require_approval_for_restart"],
                    },
                    "evidence_pack_artifact": {
                        "source": (evidence_pack or {}).get("source"),
                        "sufficient": (evidence_pack or {}).get("sufficient"),
                        "missing_fields": (evidence_pack or {}).get("missing_fields", []),
                        "fast_path_signatures": (evidence_pack or {}).get("fast_path_signatures", []),
                    },
                    "trust_boundary": (
                        "systemd restart remains approval-gated; storage, Engine API, JWT, and DB "
                        "conditions are escalation-only in the first Reth integration slice"
                    ),
                },
                "alternatives_considered": _alternatives(decision_type),
            },
            expected_outcome={
                "target_metrics": {
                    "p95_latency_ms": "<= unchanged or lower for RPC requests",
                    "error_rate": "<= current RPC error rate after remediation",
                },
                "time_to_effect": "5m",
            },
            risk={
                "level": risk_level,
                "blast_radius": "single_reth_node",
                "customer_impact_if_wrong": _customer_impact_if_wrong(decision_type),
            },
            confidence=confidence,
            execution_plan=_execution_plan(trigger, decision_type, 0),
        )
        decision.validate()
        return decision

    def _reth_history_trends(
        self,
        trigger: Trigger,
        execution: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute a compact bag of duration-based predicates over the
        target's recent signal history.

        Returns ``{}`` when no history store is bound or no trend window
        applies — the rule ladder treats absence as "no opinion", same
        convention as operator-stamped fields.

        The block is added to the decision's ``evidence_pack`` so the LLM
        observer can read it via the same prompt as other evidence.
        Format intentionally matches what ``Trend.to_summary`` returns,
        plus boolean predicates for quick rule checks. The integer
        seconds counts let the LLM reason about cadence ("4 ticks at
        peer<floor" reads more naturally than a timedelta)."""
        if self.signal_history is None:
            return {}
        try:
            from services.signal_history import derive_target_id
            payload = {"signal_type": "reth_node", "service": trigger.service}
            target_id = derive_target_id(payload)
            if target_id is None:
                return {}
        except Exception:
            return {}

        out: dict[str, Any] = {"target_id": target_id}

        try:
            min_peer_count = int(execution.get("min_peer_count") or 3)
            peer_trend = self.signal_history.trend(
                target_id, "execution.peer_count", window_seconds=600,
            )
            if peer_trend.count > 0:
                duration = peer_trend.duration_at_or_below(float(min_peer_count - 1))
                out["peer_count"] = {
                    **peer_trend.to_summary(),
                    "duration_below_floor_seconds": int(duration.total_seconds()),
                    "sustained_below_floor": duration.total_seconds() >= 60,
                }

            block_lag_trend = self.signal_history.trend(
                target_id, "execution.block_lag", window_seconds=600,
            )
            if block_lag_trend.count > 0 and block_lag_trend.numeric_values:
                max_lag = int(execution.get("max_block_lag") or 32)
                duration = block_lag_trend.duration_at_or_above(float(max_lag))
                out["block_lag"] = {
                    **block_lag_trend.to_summary(),
                    "duration_above_max_seconds": int(duration.total_seconds()),
                    "sustained_above_max": duration.total_seconds() >= 60,
                }

            engine_p99_trend = self.signal_history.trend(
                target_id, "consensus.engine_api_p99_ms", window_seconds=600,
            )
            if engine_p99_trend.count > 0 and engine_p99_trend.numeric_values:
                duration = engine_p99_trend.duration_at_or_above(4000.0)
                out["engine_api_p99_ms"] = {
                    **engine_p99_trend.to_summary(),
                    "duration_critical_seconds": int(duration.total_seconds()),
                    "sustained_critical": duration.total_seconds() >= 60,
                }

            disk_trend = self.signal_history.trend(
                target_id, "storage.disk_used_pct", window_seconds=600,
            )
            if disk_trend.count > 0 and disk_trend.numeric_values:
                out["disk_used_pct"] = disk_trend.to_summary()

        except Exception:
            _LOG.exception("decide.reth: signal_history.trend failed (non-fatal)")
        return out

    def _kubernetes_history_trends(
        self,
        trigger: Trigger,
        namespace: str,
        cluster: str,
        deployment_name: str,
    ) -> dict[str, Any]:
        """Trend predicates for a Kubernetes deployment's signal history.

        The most useful k8s-side temporal questions are:

        * ``rollout_status`` — has the deployment been ``failed`` for ≥
          some duration? Single-tick ``failed`` can be transient
          (controller in the middle of a roll); sustained ``failed`` is
          ProgressDeadlineExceeded territory.
        * ``pods.ready_replicas`` — sustained below desired? That's a
          stuck rollout, not a brief recreate.
        * ``metric_regression.observed_p95_latency_ms`` (when projected
          into k8s context) — trending up over multiple ticks?

        The returned dict goes into ``evidence_pack.history_trends`` so
        the rule ladder and the LLM observer share the same view.
        """
        if self.signal_history is None:
            return {}
        try:
            from services.signal_history import derive_target_id
            payload = {
                "signal_type": "kubernetes_deployment_issue",
                "cluster": cluster,
                "namespace": namespace,
                "deployment": {"name": deployment_name},
                "service": trigger.service,
            }
            target_id = derive_target_id(payload)
            if target_id is None:
                return {}
        except Exception:
            return {}

        out: dict[str, Any] = {"target_id": target_id}
        try:
            # Sustained-failed-rollout: a single ``failed`` is rarely
            # actionable (the controller may be retrying); ≥120s
            # sustained is the ProgressDeadlineExceeded shape. The
            # envelope nests this under ``deployment``.
            rollout_trend = self.signal_history.trend(
                target_id, "deployment.rollout_status", window_seconds=600,
            )
            if rollout_trend.count > 0:
                duration_failed = rollout_trend.duration_equal_to("failed")
                out["rollout_status"] = {
                    "count": rollout_trend.count,
                    "current": rollout_trend.current,
                    "duration_failed_seconds": int(duration_failed.total_seconds()),
                    "sustained_failed": duration_failed.total_seconds() >= 120,
                }

            # Stuck rollout via ready-replica deficit. The k8s envelope
            # exposes ``available_replicas`` (the controller's view of
            # ready+passing-readiness pods) and ``desired_replicas``
            # (the spec target). Sustained deficit is what distinguishes
            # a stuck rollout from a brief pod recreate.
            available_trend = self.signal_history.trend(
                target_id, "deployment.available_replicas", window_seconds=600,
            )
            if available_trend.count > 0 and available_trend.numeric_values:
                # ``desired_replicas`` lives on ``trigger.metrics`` for
                # k8s triggers (see services/trigger/service.py:230),
                # not on related_context.
                desired = trigger.metrics.get("desired_replicas") if isinstance(trigger.metrics, dict) else None
                if isinstance(desired, int) and desired > 0:
                    duration_short = available_trend.duration_at_or_below(float(desired - 1))
                    out["available_replicas"] = {
                        **available_trend.to_summary(),
                        "desired": desired,
                        "duration_below_desired_seconds": int(duration_short.total_seconds()),
                        "sustained_below_desired": duration_short.total_seconds() >= 120,
                    }
        except Exception:
            _LOG.exception("decide.kubernetes: signal_history.trend failed (non-fatal)")
        return out

    def _otel_history_trends(
        self,
        trigger: Trigger,
    ) -> dict[str, Any]:
        """Trend predicates for an OTel metric-regression target.

        The OTel envelope already carries the metric value; the
        history view answers "is this regression sustained or a
        single-tick spike?" One-tick spikes are noise; multi-tick
        upward drift is a real degradation.

        Stamped into the rule-match and escalation decision paths so
        the LLM observer can read the same data downstream.
        """
        if self.signal_history is None:
            return {}
        try:
            from services.signal_history import derive_target_id
            payload = {
                "signal_type": "otel_metric_regression",
                "service": trigger.service,
                "endpoint": trigger.endpoint,
            }
            target_id = derive_target_id(payload)
            if target_id is None:
                return {}
        except Exception:
            return {}

        out: dict[str, Any] = {"target_id": target_id}
        try:
            value_trend = self.signal_history.trend(
                target_id, "metric_regression.observed_value", window_seconds=600,
            )
            if value_trend.count > 0 and value_trend.numeric_values:
                out["observed_value"] = value_trend.to_summary()

            # Delta percentage. Sustained large deltas are the strong
            # cue — a single huge delta could be a sample-size artifact.
            delta_trend = self.signal_history.trend(
                target_id, "metric_regression.delta_pct", window_seconds=600,
            )
            if delta_trend.count > 0 and delta_trend.numeric_values:
                # 10% is a low-bar drift threshold; rule-actionable
                # thresholds usually live in metric_actions.policy.json.
                # We use this only to note "consistently above 10%
                # over the window" to the LLM, not to make decisions.
                duration_above = delta_trend.duration_at_or_above(10.0)
                out["delta_pct"] = {
                    **delta_trend.to_summary(),
                    "duration_above_10pct_seconds": int(duration_above.total_seconds()),
                }
        except Exception:
            _LOG.exception("decide.otel: signal_history.trend failed (non-fatal)")
        return out

    def _decide_otel_metric(self, trigger: Trigger) -> Decision:
        """Decide on an OTel metric-regression trigger.

        Order of precedence:
        1. Declarative rule match (Layer 2)
        2. LLM proposal from the bounded allowlist (Layer 3, if enabled)
        3. Escalate with risk flags naming why neither matched

        Keeping rule-match deterministic and short-circuiting before the LLM
        runs means policy-authored rules always win over non-deterministic
        proposals, which is the invariant that makes Layer 3 safe to enable.
        """
        signal_view = _build_signal_view_from_trigger(trigger)
        rule_match = self._metric_action_matcher.match(signal_view)
        if rule_match is not None:
            _LOG.info(
                "decide(otel): layer2 rule_match rule=%s action=%s",
                rule_match.rule_name, rule_match.action,
            )
            return self._decision_from_rule_match(trigger, rule_match)

        _LOG.info("decide(otel): layer2 no rule matched")
        llm_risk_flags: list[str] = []
        if self._llm_proposer is not None:
            _LOG.info("decide(otel): layer3 consulting LLM proposer")
            llm_result = self._llm_proposer.propose(signal_view)
            if llm_result.match is not None:
                _LOG.info(
                    "decide(otel): layer3 llm proposal accepted action=%s risk_flags=%s",
                    llm_result.match.action, llm_result.risk_flags,
                )
                return self._decision_from_rule_match(
                    trigger, llm_result.match, llm_risk_flags=llm_result.risk_flags
                )
            llm_risk_flags = llm_result.risk_flags
            _LOG.info("decide(otel): layer3 llm did not produce a usable proposal flags=%s", llm_risk_flags)

        _LOG.info("decide(otel): layer4 falling through to escalate (llm_risk_flags=%s)", llm_risk_flags)
        return self._escalate_for_unmatched_metric(trigger, llm_risk_flags=llm_risk_flags)

    def _decision_from_rule_match(
        self,
        trigger: Trigger,
        rule_match: RuleMatch,
        llm_risk_flags: list[str] | None = None,
    ) -> Decision:
        """Materialize a Decision from a matched rule (rule engine or LLM)."""
        metric_regression = trigger.related_context.get("metric_regression", {})
        metric_name = metric_regression.get("metric_name", "unknown_metric")
        delta_pct = metric_regression.get("delta_pct")
        autonomy_tier = {
            "low": "autonomous",
            "medium": "approval_required",
            "high": "escalated",
        }.get(rule_match.risk_level, "approval_required")

        evidence: list[str] = [f"rule {rule_match.rule_name!r} matched metric {metric_name!r}"]
        if delta_pct is not None:
            evidence.append(f"observed delta {delta_pct:.1f}% vs baseline")
        if rule_match.matched_on.get("resource_attributes"):
            attrs_summary = ", ".join(
                f"{k}={v}" for k, v in rule_match.matched_on["resource_attributes"].items()
            )
            evidence.append(f"resource attributes: {attrs_summary}")
        if llm_risk_flags:
            evidence.append(f"llm fallback risk flags: {', '.join(llm_risk_flags)}")

        decision = Decision(
            decision_id=f"dec_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            decision_type=rule_match.decision_type,
            autonomy_tier=autonomy_tier,
            summary=(
                f"Apply {rule_match.action} on {trigger.service} because rule "
                f"{rule_match.rule_name!r} matched metric {metric_name}."
            ),
            reasoning={
                "primary_hypothesis": (
                    f"{metric_name} regressed on {trigger.service}; rule "
                    f"{rule_match.rule_name!r} proposes {rule_match.decision_type}."
                ),
                "evidence": evidence,
                "evidence_pack": {
                    "matched_rule": rule_match.rule_name,
                    "matched_on": rule_match.matched_on,
                    "metric_regression": metric_regression,
                    "bounds": rule_match.bounds,
                    "history_trends": self._otel_history_trends(trigger),
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
                "blast_radius": (
                    "single_deployment"
                    if rule_match.system == "kubernetes_service"
                    else "service_level"
                ),
                "customer_impact_if_wrong": _customer_impact_if_wrong(rule_match.decision_type),
            },
            confidence=rule_match.confidence,
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
        """Escalation path when no rule and no LLM proposal succeeded."""
        metric_regression = trigger.related_context.get("metric_regression", {})
        metric_name = metric_regression.get("metric_name", "unknown_metric")
        evidence = [
            f"metric {metric_name!r} has no matching rule",
            f"delta {metric_regression.get('delta_pct')}%",
        ]
        if llm_risk_flags:
            evidence.append(f"llm fallback: {', '.join(llm_risk_flags)}")
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
                    f"Metric {metric_name} on {trigger.service} crossed its threshold, but no "
                    "rule knows how to act on it."
                ),
                "evidence": evidence,
                "evidence_pack": {
                    "metric_regression": metric_regression,
                    "available_rules": [rule.name for rule in self._metric_action_matcher.rules],
                    "llm_risk_flags": llm_risk_flags or [],
                    "history_trends": self._otel_history_trends(trigger),
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
                "rollback_plan": "close the incident if no action is warranted",
            },
        )
        decision.validate()
        return decision

    def _decide_kubernetes(
        self,
        trigger: Trigger,
        scenario_analysis: ScenarioAnalysis | dict | None = None,
        investigation_report: dict | None = None,
    ) -> Decision:
        """Decide on a Kubernetes deployment trigger using SRE-grade policy.

        The previous version of this function was a flat ``if/elif`` tree
        that treated ``crash_loop``, ``probe_failure``, and ``oom_killed``
        as interchangeable — all routed to ``restart_deployment``. That
        is exactly the naive policy SREs criticize. A real SRE escalation
        ladder branches on:

        1. **Deploy correlation** — did this break right after a deploy?
           If so, rollback. If not, the bug existed before; restart won't
           fix anything and we should escalate for log investigation.
        2. **Resource pressure** — OOMKilled isn't fixed by restarting;
           the new container fills the same limit and OOMs again. Raise
           the limit (``patch_resources``) before considering restart.
        3. **Probe-only failures** — readiness/liveness probes failing
           without a crash usually mean a downstream dependency is sick.
           Restarting the container won't fix that. Escalate.
        4. **Image pull** — definitive supply-chain failure; rollback to
           the prior image is the only sensible response.

        The deploy-correlation threshold (default 30 minutes) is what
        an on-call SRE actually checks first. Below the threshold, the
        deploy is the prior cause hypothesis; above it, the bug existed
        and Mesh shouldn't guess.
        """
        error_signatures = list(trigger.related_context.get("error_signatures", []))
        event_reasons = list(trigger.related_context.get("event_reasons", []))
        rollout_status = str(trigger.related_context.get("rollout_status", "degraded"))
        deployment_name = str(trigger.related_context.get("deployment_name", trigger.service))
        namespace = str(trigger.related_context.get("namespace", "default"))
        cluster = str(trigger.related_context.get("cluster", "unknown"))
        # S2: pull duration-based predicates from the per-deployment
        # signal history. Same generic store as reth uses; the trends
        # surface in evidence_pack.history_trends so the rule ladder
        # and the LLM observer both see "rollout_status=failed for
        # 240s" rather than judging on a single snapshot.
        history_trends = self._kubernetes_history_trends(trigger, namespace, cluster, deployment_name)
        image = str(trigger.related_context.get("deployment_image", "unknown"))
        likely_layer = str(trigger.related_context.get("likely_layer", "unknown"))
        code_remediation_candidate = bool(trigger.related_context.get("code_remediation_candidate", False))
        repo_path = trigger.related_context.get("repo_path")
        suspected_file = trigger.related_context.get("suspected_file")
        allowed_paths = list(trigger.related_context.get("allowed_paths", []))
        test_commands = list(trigger.related_context.get("test_commands", []))
        patch_template = trigger.related_context.get("patch_template")
        repeated_rollback = int(trigger.related_context.get("rollbacks_last_24h", 0)) > 0
        recovery_context = _recovery_context(trigger)

        # SRE rule: deploy correlation is the single most useful piece
        # of evidence. ``seconds_since_deploy`` from the signal collector
        # tells us how recent the most recent rollout was. The 30-minute
        # window (1800s) is the standard "if it broke right after a
        # deploy, the deploy is the cause" threshold used by most teams.
        # Above that, the bug existed before the deploy and rollback
        # won't help.
        seconds_since_deploy = trigger.related_context.get("seconds_since_deploy")
        deploy_correlated = (
            seconds_since_deploy is not None
            and int(seconds_since_deploy) <= _DEPLOY_CORRELATION_WINDOW_SECONDS
        )

        # Generate falsifiable hypotheses early. The top hypothesis is surfaced in
        # the decision reasoning and can upgrade the escalate fallback — but it
        # cannot override concrete rule matches (guardrails intact).
        hypotheses = []
        if self.hypothesis_engine is not None:
            try:
                hypotheses = [
                    h.to_dict()
                    for h in self.hypothesis_engine.generate(
                        trigger,
                        investigation_report=investigation_report,
                    )
                ]
            except Exception:
                hypotheses = []

        # Branch order is significant — earlier branches override later
        # ones when multiple symptoms are present. Ordering reflects
        # which signature is most diagnostic of the root cause:
        #
        #   investigate_and_patch — explicit code-remediation handoff,
        #     only when the operator pre-supplied repo/test/patch context
        #   oom_killed            — memory pressure, raise limit BEFORE restart
        #   image_pull_failure   — supply-chain problem, rollback fixes it
        #   rollout_status=failed — definitive controller verdict, rollback
        #   crash_loop + recent deploy — rollback (deploy is the cause)
        #   crash_loop + no recent deploy — escalate (code investigation)
        #   probe_failure only    — downstream/dependency, escalate
        #   else                  — escalate (Mesh shouldn't guess)
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
        elif "oom_killed" in error_signatures:
            # OOMKilled with restart is a band-aid: the new container
            # fills the same limit and OOMs again within minutes.
            # ``patch_resources`` raises the memory limit, which gives
            # the workload room to either run cleanly (limit was tight)
            # or surface the leak more visibly. Either is more useful
            # than the restart loop kubelet is already running.
            decision_type = "patch_resources"
            confidence = 0.74
            risk_level = "medium"
            # Always require approval — bumping resource limits has
            # cluster-wide cost implications. An SRE should sign off.
            autonomy_tier = "approval_required"
            blast_radius = "single_deployment"
        elif "image_pull_failure" in error_signatures:
            # Image pull failure is the cleanest "rollback fixes it" case.
            # The new image can't be pulled; the prior revision had a
            # working image, so reverting puts us back on our feet.
            decision_type = "rollback_deployment"
            confidence = 0.9
            risk_level = "medium"
            autonomy_tier = "approval_required" if repeated_rollback else "autonomous"
            blast_radius = "single_deployment"
        elif rollout_status == "failed":
            # Deployment controller has given up on this revision —
            # ProgressDeadlineExceeded. Rollback unless we already
            # rolled back recently, in which case we escalate to
            # avoid a flapping rollback loop.
            if repeated_rollback:
                decision_type = "escalate"
                confidence = 0.65
                risk_level = "high"
                autonomy_tier = "escalated"
            else:
                decision_type = "rollback_deployment"
                confidence = 0.85
                risk_level = "medium"
                autonomy_tier = "autonomous"
            blast_radius = "single_deployment"
        elif "crash_loop" in error_signatures and deploy_correlated:
            # Recent deploy + crash loop = the deploy is almost certainly
            # the cause. Rollback to the previous revision.
            decision_type = "rollback_deployment"
            confidence = 0.83
            risk_level = "medium"
            autonomy_tier = "approval_required" if repeated_rollback else "autonomous"
            blast_radius = "single_deployment"
        elif "crash_loop" in error_signatures and not deploy_correlated:
            # Crash loop with NO recent deploy means the bug existed
            # before this revision became active. The standard SRE
            # response is "restart isn't going to fix this — get logs,
            # investigate, fix the code." Escalate rather than guess.
            decision_type = "escalate"
            confidence = 0.7
            risk_level = "high"
            autonomy_tier = "escalated"
            blast_radius = "single_deployment"
        elif "probe_failure" in error_signatures and not (
            "crash_loop" in error_signatures or "oom_killed" in error_signatures
        ):
            # Probe failures without a crash are often transient or
            # dependency-driven. The SRE-correct first move is to wait a
            # bounded interval and re-check, not to restart or page on the
            # first sample. Persistent probe failures will return with the
            # deferral evidence attached and can then escalate.
            decision_type = "defer_until"
            confidence = 0.70
            risk_level = "low"
            autonomy_tier = "autonomous"
            blast_radius = "single_deployment"
        elif "configuration_drift" in error_signatures:
            decision_type = "escalate"
            confidence = 0.64
            risk_level = "medium"
            autonomy_tier = "escalated"
            blast_radius = "single_deployment"
        else:
            # Catch-all: when we can't narrow the cause, escalate
            # rather than guess. The previous policy defaulted to
            # restart_deployment here — an SRE would never accept that.
            #
            # We log the input fingerprint at DEBUG so an operator
            # reading logs can tell apart "we deliberately did not act
            # because no actionable signature was present" from "we
            # missed a signal we should have caught." Without this,
            # the only evidence is an "escalate" decision with no
            # context.
            _LOG.debug(
                "decide(k8s): catch-all escalate — no actionable signature matched; "
                "error_signatures=%s rollout_status=%s seconds_since_deploy=%s "
                "deploy_correlated=%s repeated_rollback=%s",
                error_signatures,
                rollout_status,
                seconds_since_deploy,
                deploy_correlated,
                repeated_rollback,
            )
            decision_type = "escalate"
            confidence = 0.6
            risk_level = "high"
            autonomy_tier = "escalated"
            blast_radius = "single_deployment"

        # Hypothesis-driven bias: if rule fell through to escalate *and* the top
        # hypothesis has high posterior confidence + concrete action, upgrade it.
        hypothesis_upgrade = False
        if decision_type == "escalate" and hypotheses:
            top = hypotheses[0]
            allowed_upgrades = _LLM_ALLOWED_ACTIONS | {"scale_deployment", "restart_pod", "patch_resources"}
            if (
                _hypothesis_has_resolved_evidence(top)
                and top.get("posterior_confidence", 0.0) >= 0.55
                and top.get("recommended_action") in allowed_upgrades
            ):
                decision_type = top["recommended_action"]
                confidence = min(top["posterior_confidence"], 0.82)
                risk_level = "medium"
                autonomy_tier = (
                    "approval_required"
                    if repeated_rollback or str(top.get("hypothesis_id", "")).startswith("h_rca_")
                    else "autonomous"
                )
                blast_radius = "single_deployment"
                hypothesis_upgrade = True

        if self.escalation_reasoner and (decision_type == "escalate" or confidence < 0.65):
            reasoning = self.escalation_reasoner.reason(trigger)
            if (
                reasoning.confidence > confidence
                and reasoning.suggested_action != "escalate"
                and reasoning.suggested_action in _LLM_ALLOWED_ACTIONS
            ):
                decision_type = reasoning.suggested_action
                confidence = min(reasoning.confidence, 0.85)
                risk_level = "medium"
                autonomy_tier = "approval_required" if repeated_rollback else "autonomous"
                blast_radius = "single_deployment"

        correlation = trigger.related_context.get("correlation", {})
        if correlation.get("type") in ("blast_wave", "cascading"):
            autonomy_tier = "approval_required"
        confidence_factors = _build_confidence_factors(
            base_confidence=confidence,
            similar_prior_cases=int(recovery_context.get("related_run_count", 0) or 0),
            flag_causality_confidence=correlation.get("correlation_confidence"),
            trigger_signals=error_signatures,
            historical_success_rate=None,
            recovery_context=recovery_context,
        )
        confidence = _confidence_from_factors(confidence_factors)

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
                    "recovery_context": recovery_context,
                    "confidence_factors": confidence_factors,
                    "hypotheses": hypotheses,
                    "hypothesis_upgrade_applied": hypothesis_upgrade,
                    "history_trends": history_trends,
                    "defer_until": _defer_until_context(trigger, decision_type),
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
        decision = _apply_scenario_analysis(decision, trigger, scenario_analysis, 0)
        decision.validate()
        return decision


def _apply_scenario_analysis(
    decision: Decision,
    trigger: Trigger,
    scenario_analysis: "ScenarioAnalysis | dict | None",
    target_rollout: int,
) -> Decision:
    if scenario_analysis is None:
        return decision
    analysis = scenario_analysis.to_dict() if hasattr(scenario_analysis, "to_dict") else dict(scenario_analysis)
    review_reasons = list(analysis.get("required_review_reasons") or [])
    suggested = analysis.get("suggested_decision_type")
    autonomy_hint = analysis.get("autonomy_tier_hint")
    confidence = float(analysis.get("confidence", decision.confidence) or decision.confidence)
    risk_level = analysis.get("risk_level")
    review_analysis = classify_review_reasons(review_reasons)

    if (
        review_reasons
        and suggested == "escalate"
        and (review_analysis["terminal_review_reasons"] or review_analysis["unclassified_review_reasons"])
    ):
        decision.decision_type = "escalate"
        decision.summary = _summary(trigger, "escalate", target_rollout)
        decision.execution_plan = _execution_plan(trigger, "escalate", target_rollout)
        decision.risk["customer_impact_if_wrong"] = _customer_impact_if_wrong("escalate")

    if autonomy_hint in {"approval_required", "escalated"}:
        decision.autonomy_tier = str(autonomy_hint)
    elif review_reasons and decision.autonomy_tier == "autonomous":
        decision.autonomy_tier = "approval_required"

    if risk_level in {"medium", "high"}:
        current = str(decision.risk.get("level", "medium"))
        if current == "low" or risk_level == "high":
            decision.risk["level"] = risk_level

    if review_analysis["terminal_review_reasons"] or review_analysis["unclassified_review_reasons"]:
        decision.confidence = min(decision.confidence, confidence, 0.74)
    else:
        decision.confidence = min(max(decision.confidence, confidence), 0.95)

    evidence_pack = decision.reasoning.setdefault("evidence_pack", {})
    evidence_pack["scenario_analysis"] = {
        "analysis_id": analysis.get("analysis_id"),
        "suggested_decision_type": suggested,
        "autonomy_tier_hint": autonomy_hint,
        "required_review_reasons": review_reasons,
        "review_classification": review_analysis,
        "evidence_refs": list(analysis.get("evidence_refs") or []),
        "merkle_root": analysis.get("merkle_root"),
    }
    if review_reasons:
        decision.reasoning.setdefault("evidence", []).append(
            "scenario analysis requires review: " + "; ".join(review_reasons)
        )
    return decision


def _attach_reasoning_bank_context(decision: Decision, reasoning_bank_packet: dict | None) -> None:
    if not isinstance(reasoning_bank_packet, dict) or not reasoning_bank_packet:
        return
    claims = list(reasoning_bank_packet.get("claims", []))
    procedures = list(reasoning_bank_packet.get("procedures", []))
    contradictions = list(reasoning_bank_packet.get("contradictions", []))
    context = {
        "packet_id": reasoning_bank_packet.get("packet_id"),
        "strategy_claim_count": len(claims),
        "strategy_procedure_count": len(procedures),
        "contradiction_count": len(contradictions),
        "strategies": [
            {
                "claim_id": item.get("claim_id"),
                "tier": item.get("tier"),
                "statement": item.get("statement"),
                "confidence": item.get("confidence"),
            }
            for item in (procedures + claims)[:5]
            if isinstance(item, dict)
        ],
        "advisory_only": True,
    }
    evidence_pack = decision.reasoning.setdefault("evidence_pack", {})
    evidence_pack["reasoning_bank"] = context
    if context["strategies"]:
        decision.reasoning.setdefault("evidence", []).append(
            "ReasoningBank retrieved advisory strategies; live evidence and policy gates remain authoritative."
        )


def _attach_investigation_report(decision: Decision, investigation_report: dict | None) -> None:
    if not isinstance(investigation_report, dict) or not investigation_report:
        return
    evidence_pack = decision.reasoning.setdefault("evidence_pack", {})
    evidence_pack["investigation_report"] = {
        "report_id": investigation_report.get("report_id"),
        "stop_reason": investigation_report.get("stop_reason"),
        "uncertainty": investigation_report.get("uncertainty"),
        "finding_count": len(investigation_report.get("findings") or []),
        "recommended_next_step": investigation_report.get("recommended_next_step"),
        "citations": list(investigation_report.get("citations") or [])[:8],
        "root_cause_candidates": list(investigation_report.get("root_cause_candidates") or [])[:5],
    }
    if investigation_report.get("stop_reason") == "investigation_failed_existing_path_continues":
        return
    evidence = decision.reasoning.setdefault("evidence", [])
    if isinstance(evidence, list):
        evidence.append(
            "investigation report "
            f"{investigation_report.get('report_id')} completed with "
            f"uncertainty={investigation_report.get('uncertainty')}"
        )


def _build_signal_view_from_trigger(trigger: Trigger) -> dict:
    """Reshape a Trigger into the signal-shaped dict the rule matcher expects.

    The matcher is deliberately decoupled from the Trigger model so it can be
    unit-tested with plain dicts. Keeping this translation in one place means
    the rule engine's inputs stay stable when trigger internals change.
    """
    return {
        "service": trigger.service,
        "endpoint": trigger.endpoint,
        "environment": trigger.environment,
        "metric_regression": trigger.related_context.get("metric_regression", {}),
        "resource_attributes": trigger.related_context.get("resource_attributes", {}),
        "related_metrics": trigger.related_context.get("related_metrics", []),
    }


def _reth_primary_hypothesis(
    trigger: Trigger,
    signatures: set[str],
    top_hypothesis: dict | None,
) -> str:
    if top_hypothesis and top_hypothesis.get("hypothesis_id") != "h_unknown":
        description = top_hypothesis.get("description")
        if isinstance(description, str) and description:
            return description
    return (
        f"Reth node {trigger.service} is degraded due to "
        f"{', '.join(sorted(signatures) or ['unknown symptoms'])}."
    )


def _reth_restart_supported_by_evidence(
    top_hypothesis: dict | None,
    evidence_pack: dict | None,
) -> bool:
    if evidence_pack is None and top_hypothesis is None:
        # Direct unit/integration callers that use DecisionService without
        # MeshRuntimeEngine do not have the evidence stage wired. Preserve
        # the legacy approval-gated restart behavior there; runtime paths
        # pass an explicit evidence_pack and remain evidence-gated.
        return True
    if not isinstance(evidence_pack, dict) or evidence_pack.get("sufficient") is False:
        return False
    if top_hypothesis is None:
        return False
    if top_hypothesis.get("recommended_action") != "restart_systemd_service":
        return False
    if float(top_hypothesis.get("posterior_confidence", 0.0)) < 0.55:
        return False
    return _hypothesis_has_resolved_evidence(top_hypothesis)


def _hypothesis_has_resolved_evidence(hypothesis: dict) -> bool:
    return bool(
        hypothesis.get("supporting_evidence")
        or hypothesis.get("disconfirming_evidence")
    )


def _feature_flag_reduction_supported(
    trigger: Trigger,
    *,
    latency_delta_pct: float,
    error_multiplier: float,
    timeout_rate: float,
) -> bool:
    if not trigger.flag_key or trigger.current_rollout_pct is None:
        return False
    if trigger.current_rollout_pct <= 0:
        return False
    return (
        latency_delta_pct >= 25
        or error_multiplier >= 1.5
        or timeout_rate > 0
    )


def _defer_until_context(trigger: Trigger, decision_type: str) -> dict[str, object]:
    if decision_type != "defer_until":
        return {}
    error_signatures = list(trigger.related_context.get("error_signatures", []))
    condition = ", ".join(error_signatures or ["runtime symptoms"])
    return {
        "defer_seconds": int(trigger.related_context.get("defer_seconds", 300) or 300),
        "condition": f"{condition} on {trigger.endpoint}",
        "original_trigger_id": trigger.trigger_id,
        "recheck_signal_type": trigger.trigger_type,
        "on_persist": "escalate",
        "on_clear": "no_action",
    }


def _delta_pct(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0
    return round(((observed - baseline) / baseline) * 100, 1)


def _ratio(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0 if observed == 0 else float("inf")
    return round(observed / baseline, 2)


def _execution_plan(trigger: Trigger, decision_type: str, target_rollout: int) -> dict[str, object]:
    if decision_type == "defer_until":
        defer_context = _defer_until_context(trigger, decision_type)
        return {
            "system": "audit_log_sink",
            "action": "record_defer_until",
            "parameters": {
                "trigger_id": trigger.trigger_id,
                "service": trigger.service,
                "endpoint": trigger.endpoint,
                "environment": trigger.environment,
                **defer_context,
            },
            "rollback_plan": "no infrastructure mutation was performed; cancel the scheduled recheck if the alert is manually resolved",
        }
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
    if decision_type == "restart_pod":
        return {
            "system": "kubernetes_service",
            "action": "restart_pod",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "namespace": trigger.related_context.get("namespace"),
                "pod_name": trigger.related_context.get("pod_name"),
            },
            "rollback_plan": (
                "if recreated pod remains unhealthy, restart the owning deployment or rollback"
            ),
        }
    if decision_type == "scale_deployment":
        return {
            "system": "kubernetes_service",
            "action": "scale_deployment",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "namespace": trigger.related_context.get("namespace"),
                "deployment_name": trigger.related_context.get("deployment_name"),
                "replicas": trigger.related_context.get("target_replicas") or trigger.related_context.get("replicas"),
            },
            "rollback_plan": (
                f"scale back to previous replica count "
                f"{trigger.related_context.get('previous_replicas', 'unknown')} if scaling does not restore health"
            ),
        }
    if decision_type == "patch_resources":
        # Default memory bump: double the previous limit if the
        # operator gave us one in related_context, otherwise pick a
        # conservative absolute target. The SRE-grade default for an
        # OOMKill response is "give it more headroom and watch" — not
        # uncapped growth. The actuator clamps via its allowlist.
        previous_memory = trigger.related_context.get("memory_limit")
        target_memory = trigger.related_context.get("target_memory_limit") or "1Gi"
        return {
            "system": "kubernetes_service",
            "action": "patch_resources",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "namespace": trigger.related_context.get("namespace"),
                "deployment_name": trigger.related_context.get("deployment_name"),
                "container": trigger.related_context.get("container") or trigger.service,
                "limits": {"memory": target_memory},
            },
            "rollback_plan": (
                f"restore the previous memory limit ({previous_memory or 'unknown'}) "
                "if the new ceiling does not stop OOM kills within 15 minutes"
            ),
        }
    if decision_type == "cordon_node":
        return {
            "system": "kubernetes_service",
            "action": "cordon_node",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "node_name": trigger.related_context.get("node_name"),
            },
            "rollback_plan": "kubectl uncordon the node once underlying hardware issue is resolved",
        }
    if decision_type == "drain_node":
        return {
            "system": "kubernetes_service",
            "action": "drain_node",
            "parameters": {
                "cluster": trigger.related_context.get("cluster"),
                "kube_context": trigger.related_context.get("kube_context"),
                "node_name": trigger.related_context.get("node_name"),
                "grace_period_seconds": int(trigger.related_context.get("grace_period_seconds", 60)),
            },
            "rollback_plan": "kubectl uncordon the node; pods will reschedule naturally",
        }
    if decision_type == "argocd_sync":
        return {
            "system": "argocd_service",
            "action": "sync_application",
            "parameters": {
                "application": trigger.related_context.get("argocd_application"),
                "revision": trigger.related_context.get("argocd_revision"),
                "prune": bool(trigger.related_context.get("argocd_prune", False)),
            },
            "rollback_plan": "argocd rollback application to the previous synced revision if sync destabilizes the deployment",
        }
    if decision_type == "argocd_rollback":
        return {
            "system": "argocd_service",
            "action": "rollback_application",
            "parameters": {
                "application": trigger.related_context.get("argocd_application"),
                "target_revision": trigger.related_context.get("argocd_target_revision"),
            },
            "rollback_plan": "re-sync the application to the original revision once the underlying defect is fixed",
        }
    if decision_type == "restart_systemd_service":
        attrs = trigger.related_context.get("resource_attributes", {})
        node = trigger.related_context.get("node", {})
        fleet = trigger.related_context.get("fleet", {})
        return {
            "system": "systemd_service",
            "action": "restart_systemd_service",
            "parameters": {
                "host": (
                    attrs.get("mesh.node.host")
                    or trigger.related_context.get("host")
                ),
                "service": (
                    attrs.get("mesh.node.service")
                    or trigger.related_context.get("systemd_service")
                ),
                "reason": ", ".join(trigger.related_context.get("error_signatures", [])),
                "lb_target_id": attrs.get("mesh.lb.target_id") or node.get("lb_target_id"),
                "lb_pool": attrs.get("mesh.lb.pool") or node.get("lb_pool"),
                "lb_provider": attrs.get("mesh.lb.provider") or node.get("lb_provider"),
                "fleet_id": attrs.get("mesh.fleet.id") or fleet.get("fleet_id") or node.get("fleet_id"),
                "fleet_min_healthy": fleet.get("min_healthy") or node.get("fleet_min_healthy"),
                "fleet_healthy_count": fleet.get("healthy_count") or node.get("fleet_healthy_count"),
            },
            "rollback_plan": (
                "no automatic rollback for a systemd restart; escalate if peers, block lag, "
                "or RPC health do not recover within the feedback window"
            ),
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
    if decision_type == "defer_until":
        context = _defer_until_context(trigger, decision_type)
        return (
            f"Defer action on {trigger.service} for {context['defer_seconds']}s and re-check "
            f"whether {context['condition']} persists."
        )
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
    if decision_type == "restart_pod":
        return (
            f"Restart pod {trigger.related_context.get('pod_name', 'unknown')} in "
            f"{trigger.related_context.get('namespace', 'default')} to recover from a single-pod failure."
        )
    if decision_type == "scale_deployment":
        return (
            f"Scale Kubernetes deployment {trigger.related_context.get('deployment_name', trigger.service)} "
            f"to {trigger.related_context.get('target_replicas', trigger.related_context.get('replicas', '?'))} replicas "
            f"to relieve capacity pressure."
        )
    if decision_type == "patch_resources":
        target_memory = trigger.related_context.get('target_memory_limit') or '1Gi'
        return (
            f"Raise memory limit on {trigger.related_context.get('deployment_name', trigger.service)} "
            f"in {trigger.related_context.get('namespace', 'default')} to {target_memory} — "
            f"the workload is OOMKilling and a restart loop will keep recurring at the current limit."
        )
    if decision_type == "cordon_node":
        return (
            f"Cordon node {trigger.related_context.get('node_name', 'unknown')} to prevent new pod scheduling "
            f"while the underlying issue is diagnosed."
        )
    if decision_type == "drain_node":
        return (
            f"Drain node {trigger.related_context.get('node_name', 'unknown')} to safely evacuate workloads "
            f"before maintenance or hardware replacement."
        )
    if decision_type == "argocd_sync":
        return (
            f"Trigger ArgoCD sync for application "
            f"{trigger.related_context.get('argocd_application', 'unknown')} to reconcile the live cluster state."
        )
    if decision_type == "argocd_rollback":
        return (
            f"Rollback ArgoCD application "
            f"{trigger.related_context.get('argocd_application', 'unknown')} to a prior revision."
        )
    if decision_type == "restart_systemd_service":
        return (
            f"Restart systemd service {trigger.related_context.get('systemd_service', 'unknown')} on "
            f"{trigger.related_context.get('host', 'unknown')} to recover the degraded node process."
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
        if trigger.trigger_type == "reth_node_degraded":
            return (
                f"Escalate Reth node {trigger.service}: symptoms "
                f"{', '.join(trigger.related_context.get('error_signatures', ['unknown']))} require human review."
            )
        return (
            f"Escalate {trigger.flag_key} regression on {trigger.service} for human review due to conflicting "
            "signals or elevated business impact."
        )
    if trigger.trigger_type == "reth_node_degraded":
        return f"Record no action for Reth node {trigger.service}; current symptoms do not justify remediation."
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
    if decision_type == "defer_until":
        return [
            "act immediately",
            "escalate to human review",
            "defer and re-check before deciding",
        ]
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
    if decision_type == "restart_systemd_service":
        return [
            "continue observing node health",
            "open incident for manual node operations",
            "restart the bounded allowlisted systemd service",
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
    if decision_type == "restart_pod":
        return "brief request loss for one pod's share of traffic"
    if decision_type == "scale_deployment":
        return "transient capacity shift; over/under-scaling may amplify latency or cost"
    if decision_type == "cordon_node":
        return "new pods won't schedule on this node until uncordoned"
    if decision_type == "drain_node":
        return "workloads briefly reschedule elsewhere; capacity pressure if cluster is tight"
    if decision_type in {"argocd_sync", "argocd_rollback"}:
        return "temporary Argo-managed state drift during reconciliation"
    if decision_type == "restart_systemd_service":
        return "brief execution node unavailability; consensus/RPC clients may observe degraded service during restart"
    if decision_type == "investigate_and_patch":
        return "temporary service instability from an incorrect bounded patch"
    if decision_type == "disable_flag":
        return "temporary feature unavailability"
    if decision_type == "reduce_rollout":
        return "temporary feature degradation"
    if decision_type == "escalate":
        return "continued customer impact until a human operator intervenes"
    return "continued regression exposure"


def _build_confidence_factors(
    *,
    base_confidence: float,
    similar_prior_cases: int,
    flag_causality_confidence: float | None,
    trigger_signals: list[str],
    historical_success_rate: float | None = None,
    recovery_context: dict[str, object] | None = None,
) -> dict[str, float]:
    factors: dict[str, float] = {"base_confidence": round(base_confidence, 2)}
    if similar_prior_cases > 0:
        factors["similar_prior_cases"] = round(min(similar_prior_cases, 3) * 0.01, 2)
    if flag_causality_confidence is not None:
        factors["flag_causality_confidence"] = round(
            max(min(float(flag_causality_confidence) - 0.5, 0.2), -0.2) * 0.1,
            2,
        )
    if len(trigger_signals) >= 2:
        factors["trigger_signal_consensus"] = 0.01
    if historical_success_rate is not None:
        if historical_success_rate >= 0.8:
            factors["historical_success_rate"] = 0.02
        elif historical_success_rate < 0.4:
            factors["historical_success_rate"] = -0.03
    recovery = recovery_context or {}
    corroborating_evidence_count = int(recovery.get("corroborating_evidence_count", 0) or 0)
    active_memory_count = int(recovery.get("active_memory_count", 0) or 0)
    similar_incident_count = int(recovery.get("similar_incident_count", 0) or 0)
    related_run_count = int(recovery.get("related_run_count", 0) or 0)
    if corroborating_evidence_count > 0:
        factors["corroborating_recovery_evidence"] = round(min(corroborating_evidence_count, 4) * 0.015, 2)
    if active_memory_count > 0:
        factors["active_memory_support"] = round(min(active_memory_count, 3) * 0.01, 2)
    if similar_incident_count > 0:
        factors["similar_incident_support"] = round(min(similar_incident_count, 3) * 0.01, 2)
    if related_run_count > 0:
        factors["related_run_support"] = round(min(related_run_count, 4) * 0.005, 2)
    return factors


def _confidence_from_factors(factors: dict[str, float]) -> float:
    return max(0.5, min(round(sum(float(value) for value in factors.values()), 2), 0.95))


def _recovery_context(trigger: Trigger) -> dict[str, object]:
    raw = trigger.related_context.get("recovery_context")
    return dict(raw) if isinstance(raw, dict) else {}
