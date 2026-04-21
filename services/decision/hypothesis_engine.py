"""Hypothesis engine — generate candidate causes and falsify against evidence.

Replaces the single ``primary_hypothesis`` f-string with a ranked list of
hypotheses, each with falsification predicates that get tested against the
infra graph, change timeline (AlertStore), and service history.

Pipeline:
    1. Generate hypotheses from built-in templates (keyed on error signatures).
       Optionally augment with an LLM call if configured.
    2. For each hypothesis, evaluate each predicate.
    3. Update posterior confidence:
           posterior = prior * (1 + 0.2 * supports - 0.3 * disconfirms)
    4. Return ranked hypotheses.

The top hypothesis's ``recommended_action`` biases the rule engine but
never overrides a concrete rule result — guardrails intact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from shared.mesh_runtime import Trigger
    from shared.mesh_runtime.alert_store import AlertStore
    from shared.mesh_runtime.context_store import ContextStore
    from shared.mesh_runtime.infra_graph import InfraGraph


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------


@dataclass
class FalsificationPredicate:
    """A queryable claim about the world, either supporting or disconfirming."""

    kind: str                # e.g. "recent_deploy", "upstream_unhealthy"
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str | None = None       # "supported" | "disconfirmed" | "unknown"
    evidence_ref: str | None = None
    weight: float = 1.0             # relative influence on posterior

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Hypothesis:
    hypothesis_id: str
    description: str
    candidate_cause: str             # canonical cause label, e.g. "recent_deploy"
    recommended_action: str           # maps to decision_type
    prior_confidence: float
    posterior_confidence: float = 0.0
    predicates: list[FalsificationPredicate] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    disconfirming_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "description": self.description,
            "candidate_cause": self.candidate_cause,
            "recommended_action": self.recommended_action,
            "prior_confidence": round(self.prior_confidence, 3),
            "posterior_confidence": round(self.posterior_confidence, 3),
            "predicates": [p.to_dict() for p in self.predicates],
            "supporting_evidence": list(self.supporting_evidence),
            "disconfirming_evidence": list(self.disconfirming_evidence),
        }


# ----------------------------------------------------------------------
# Built-in hypothesis templates, keyed by error signature
# ----------------------------------------------------------------------


def _crash_loop_templates() -> list[Hypothesis]:
    return [
        Hypothesis(
            hypothesis_id="h_crash_recent_deploy",
            description="A recent deploy introduced a bug causing the crash loop",
            candidate_cause="recent_deploy",
            recommended_action="rollback_deployment",
            prior_confidence=0.55,
            predicates=[
                FalsificationPredicate(kind="recent_deploy", arguments={"within_seconds": 900}),
                FalsificationPredicate(kind="service_has_past_rollback_success", arguments={}),
            ],
        ),
        Hypothesis(
            hypothesis_id="h_crash_config_change",
            description="A configmap or secret change is breaking startup",
            candidate_cause="config_change",
            recommended_action="rollback_deployment",
            prior_confidence=0.45,
            predicates=[
                FalsificationPredicate(kind="configmap_or_secret_change_nearby", arguments={"within_seconds": 900}),
            ],
        ),
        Hypothesis(
            hypothesis_id="h_crash_transient",
            description="Transient pod failure that will heal on restart",
            candidate_cause="transient",
            recommended_action="restart_deployment",
            prior_confidence=0.40,
            predicates=[
                FalsificationPredicate(kind="no_recent_deploy", arguments={"within_seconds": 3600}, weight=0.7),
                FalsificationPredicate(kind="recovered_from_restart_before", arguments={}, weight=1.0),
            ],
        ),
    ]


def _oom_killed_templates() -> list[Hypothesis]:
    return [
        Hypothesis(
            hypothesis_id="h_oom_undersized",
            description="Memory limit is too low for current workload",
            candidate_cause="memory_undersize",
            recommended_action="scale_deployment",
            prior_confidence=0.55,
            predicates=[
                FalsificationPredicate(kind="service_has_past_scale_success", arguments={}),
                FalsificationPredicate(kind="no_recent_deploy", arguments={"within_seconds": 3600}, weight=0.6),
            ],
        ),
        Hypothesis(
            hypothesis_id="h_oom_leak_from_deploy",
            description="A recent deploy introduced a memory leak",
            candidate_cause="recent_deploy",
            recommended_action="rollback_deployment",
            prior_confidence=0.50,
            predicates=[
                FalsificationPredicate(kind="recent_deploy", arguments={"within_seconds": 1800}),
            ],
        ),
    ]


def _image_pull_failure_templates() -> list[Hypothesis]:
    return [
        Hypothesis(
            hypothesis_id="h_image_tag_missing",
            description="Image tag does not exist in registry (bad deploy)",
            candidate_cause="bad_image_tag",
            recommended_action="rollback_deployment",
            prior_confidence=0.75,
            predicates=[
                FalsificationPredicate(kind="recent_deploy", arguments={"within_seconds": 1800}),
            ],
        ),
        Hypothesis(
            hypothesis_id="h_registry_outage",
            description="Registry is unreachable",
            candidate_cause="registry_outage",
            recommended_action="escalate",
            prior_confidence=0.30,
            predicates=[
                FalsificationPredicate(kind="multi_service_image_pull_failure", arguments={}),
            ],
        ),
    ]


def _probe_failure_templates() -> list[Hypothesis]:
    return [
        Hypothesis(
            hypothesis_id="h_probe_startup_slow",
            description="Startup is slower than the readiness probe threshold",
            candidate_cause="slow_startup",
            recommended_action="restart_deployment",
            prior_confidence=0.50,
            predicates=[
                FalsificationPredicate(kind="recent_deploy", arguments={"within_seconds": 600}),
            ],
        ),
        Hypothesis(
            hypothesis_id="h_probe_dependency_down",
            description="An upstream dependency the probe checks is unhealthy",
            candidate_cause="upstream_outage",
            recommended_action="escalate",
            prior_confidence=0.40,
            predicates=[
                FalsificationPredicate(kind="upstream_service_degraded", arguments={}),
            ],
        ),
    ]


_TEMPLATES_BY_SIGNATURE: dict[str, Callable[[], list[Hypothesis]]] = {
    "crash_loop": _crash_loop_templates,
    "oom_killed": _oom_killed_templates,
    "image_pull_failure": _image_pull_failure_templates,
    "probe_failure": _probe_failure_templates,
}


# ----------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------


class HypothesisEngine:
    """Generate and falsify hypotheses for a given trigger."""

    def __init__(
        self,
        *,
        infra_graph: InfraGraph | None = None,
        alert_store: AlertStore | None = None,
        context_store: ContextStore | None = None,
    ) -> None:
        self.infra_graph = infra_graph
        self.alert_store = alert_store
        self.context_store = context_store

    def generate(self, trigger: Trigger) -> list[Hypothesis]:
        """Return ranked hypotheses (highest posterior first)."""
        error_signatures = list(trigger.related_context.get("error_signatures", []))
        hypotheses: list[Hypothesis] = []
        seen_ids: set[str] = set()
        for sig in error_signatures:
            template_fn = _TEMPLATES_BY_SIGNATURE.get(sig)
            if template_fn is None:
                continue
            for hypothesis in template_fn():
                if hypothesis.hypothesis_id in seen_ids:
                    continue
                seen_ids.add(hypothesis.hypothesis_id)
                hypotheses.append(hypothesis)
        if not hypotheses:
            # Fallback: unknown signature → single "unknown" hypothesis
            hypotheses.append(Hypothesis(
                hypothesis_id="h_unknown",
                description="Unrecognized error signature — route to human review",
                candidate_cause="unknown",
                recommended_action="escalate",
                prior_confidence=0.50,
            ))

        # Falsify each hypothesis
        for hypothesis in hypotheses:
            self._evaluate(hypothesis, trigger)
            hypothesis.posterior_confidence = self._posterior(hypothesis)

        hypotheses.sort(key=lambda h: h.posterior_confidence, reverse=True)
        return hypotheses

    def top_hypothesis(self, trigger: Trigger) -> Hypothesis | None:
        hypotheses = self.generate(trigger)
        return hypotheses[0] if hypotheses else None

    # ------------------------------------------------------------------
    # Predicate evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, hypothesis: Hypothesis, trigger: Trigger) -> None:
        for predicate in hypothesis.predicates:
            result, evidence_ref = self._test_predicate(predicate, trigger)
            predicate.result = result
            predicate.evidence_ref = evidence_ref
            if result == "supported":
                hypothesis.supporting_evidence.append(
                    f"{predicate.kind}: {evidence_ref or 'matched'}"
                )
            elif result == "disconfirmed":
                hypothesis.disconfirming_evidence.append(
                    f"{predicate.kind}: {evidence_ref or 'not matched'}"
                )

    def _test_predicate(
        self,
        predicate: FalsificationPredicate,
        trigger: Trigger,
    ) -> tuple[str, str | None]:
        kind = predicate.kind
        args = predicate.arguments or {}

        if kind == "recent_deploy":
            return self._check_recent_deploy(trigger, within_seconds=int(args.get("within_seconds", 900)))
        if kind == "no_recent_deploy":
            result, ref = self._check_recent_deploy(trigger, within_seconds=int(args.get("within_seconds", 3600)))
            # Invert
            if result == "supported":
                return "disconfirmed", ref
            if result == "disconfirmed":
                return "supported", ref
            return "unknown", ref
        if kind == "configmap_or_secret_change_nearby":
            return self._check_config_change(trigger, within_seconds=int(args.get("within_seconds", 900)))
        if kind == "service_has_past_rollback_success":
            return self._check_past_success("rollback_deployment", trigger)
        if kind == "service_has_past_scale_success":
            return self._check_past_success("scale_deployment", trigger)
        if kind == "recovered_from_restart_before":
            return self._check_past_success("restart_deployment", trigger)
        if kind == "upstream_service_degraded":
            return self._check_upstream_degraded(trigger)
        if kind == "multi_service_image_pull_failure":
            return self._check_multi_service_pull_failure(trigger)
        return "unknown", None

    # Individual checks -------------------------------------------------

    def _check_recent_deploy(
        self,
        trigger: Trigger,
        *,
        within_seconds: int,
    ) -> tuple[str, str | None]:
        if self.alert_store is None:
            # Fall back to signal-provided flag
            if trigger.related_context.get("recent_deploy_within_window"):
                return "supported", "signal.recent_deploy_within_window=true"
            return "unknown", None
        # Look at recent alert events tagged as deploy
        events = self.alert_store.list_events(limit=50)
        for event in events:
            severity = (getattr(event, "labels", {}) or {}).get("event_category", "")
            if severity in ("deploy", "deployment", "rollout") or getattr(event, "action", "") == "deploy":
                age = _age_seconds(event)
                if age is not None and age <= within_seconds:
                    return "supported", f"alert:{event.alert_id}"
        # Also check trigger.related_context directly
        if trigger.related_context.get("minutes_since_flag_change") is not None:
            minutes = trigger.related_context["minutes_since_flag_change"]
            if isinstance(minutes, (int, float)) and minutes * 60 <= within_seconds:
                return "supported", f"trigger.minutes_since_flag_change={minutes}"
        return "disconfirmed", None

    def _check_config_change(
        self,
        trigger: Trigger,
        *,
        within_seconds: int,
    ) -> tuple[str, str | None]:
        if self.alert_store is None:
            if trigger.related_context.get("config_change_within_window"):
                return "supported", "signal.config_change_within_window=true"
            return "unknown", None
        events = self.alert_store.list_events(limit=50)
        for event in events:
            labels = (getattr(event, "labels", {}) or {})
            if labels.get("event_category") in ("configmap_change", "secret_change"):
                age = _age_seconds(event)
                if age is not None and age <= within_seconds:
                    return "supported", f"alert:{event.alert_id}"
        return "disconfirmed", None

    def _check_past_success(
        self,
        action_class: str,
        trigger: Trigger,
    ) -> tuple[str, str | None]:
        if self.context_store is None:
            return "unknown", None
        ctx = self.context_store.get_service_context(trigger.service)
        if not ctx:
            return "unknown", None
        last_decision = ctx.get("last_decision_type")
        success_rate = ctx.get("success_rate")
        # Direct evidence: the last successful decision for this service matched this action class
        if last_decision == action_class and success_rate is not None and success_rate >= 0.5:
            return "supported", f"context.last_decision_type={action_class} @ rate={success_rate}"
        if success_rate is not None and success_rate < 0.3:
            return "disconfirmed", f"context.service.success_rate={success_rate}"
        return "unknown", None

    def _check_upstream_degraded(self, trigger: Trigger) -> tuple[str, str | None]:
        if self.infra_graph is None:
            return "unknown", None
        deployment_name = trigger.related_context.get("deployment_name")
        namespace = trigger.related_context.get("namespace")
        if not deployment_name or not namespace:
            return "unknown", None
        # Look at neighbors via upstream_dependencies
        deps = self.infra_graph.upstream_dependencies(trigger.service, namespace=namespace)
        if deps:
            return "supported", f"graph.upstream_deps={len(deps)}"
        return "disconfirmed", None

    def _check_multi_service_pull_failure(self, trigger: Trigger) -> tuple[str, str | None]:
        # Supported only if signal correlation flagged a blast wave
        correlation = trigger.related_context.get("correlation", {}) or {}
        if correlation.get("type") == "blast_wave":
            return "supported", "correlation.type=blast_wave"
        return "disconfirmed", None

    # ------------------------------------------------------------------
    # Posterior computation
    # ------------------------------------------------------------------

    @staticmethod
    def _posterior(hypothesis: Hypothesis) -> float:
        support_weight = sum(
            p.weight for p in hypothesis.predicates if p.result == "supported"
        )
        disconfirm_weight = sum(
            p.weight for p in hypothesis.predicates if p.result == "disconfirmed"
        )
        adjusted = hypothesis.prior_confidence * (
            1 + 0.2 * support_weight - 0.3 * disconfirm_weight
        )
        # Clamp to [0.05, 0.95]
        return max(0.05, min(round(adjusted, 3), 0.95))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _age_seconds(event: Any) -> float | None:
    """Return seconds since event.received_at (or timestamp)."""
    from datetime import datetime, timezone
    recorded = getattr(event, "received_at", None) or getattr(event, "timestamp", None)
    if not recorded:
        return None
    try:
        # event.received_at is stored as ISO string
        when = datetime.fromisoformat(str(recorded).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds()
    except (ValueError, TypeError):
        return None
