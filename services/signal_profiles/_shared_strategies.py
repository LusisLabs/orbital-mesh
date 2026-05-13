"""Shared strategy implementations reused across multiple profiles.

Three classes live here because they apply to every concrete profile
that doesn't have a specialised version:

* ``NotYetWiredStrategy`` — placeholder for strategies whose dispatch
  site hasn't migrated to profile-based dispatch yet. Raises
  ``NotYetWired`` when called. Each PR replaces these placeholders
  for the stages it migrates; after PR 4 there should be none left.
* ``HarnessDrivenInvestigationPlanner`` — generic planner that emits
  an empty-but-valid ``InvestigationPlan``. The actual probe
  selection happens inside the investigation harness (planner→critic→
  loop) which already takes a ``LoopPlanner``. This planner exists
  only so the profile dispatch site always produces a plan artifact
  (invariant 1 — no silent skips).
* ``HarnessDrivenRcaBuilder`` — generic RCA builder that synthesises
  a report from ``InvestigationReport.root_cause_candidates``.
  Replaces the silent-skip behaviour of the current Reth-only
  ``build_rca_report`` for K8s / OTel / feature-flag / webhook /
  generic profiles.

All three are intentionally small. Specialised behaviour lives in
each profile module (``reth.py``, ``kubernetes.py``, …) — these are
the fallbacks that ensure no stage ever silently no-ops.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from shared.mesh_runtime import (
    Decision,
    InvestigationPlan,
    RcaReport,
    Trigger,
)


class NotYetWired(NotImplementedError):
    """Raised when a placeholder strategy is invoked before its dispatch site is migrated."""


class NotYetWiredStrategy:
    """Placeholder for a strategy whose dispatch site hasn't been migrated yet.

    Each PR after PR 1 replaces these placeholders for the stages it
    migrates. The placeholder satisfies any strategy Protocol
    structurally (it has every method we'd expect) but raises
    ``NotYetWired`` if any method is actually called.

    The dispatch test suite verifies that strategies wired in the
    current PR are real (not placeholders) and that the runtime
    engine only calls migrated strategies.
    """

    def __init__(self, stage_name: str) -> None:
        self._stage_name = stage_name

    @property
    def stage_name(self) -> str:
        return self._stage_name

    def _raise(self, method: str) -> Any:
        raise NotYetWired(
            f"{self._stage_name}.{method} called before profile dispatch "
            f"is wired for this stage; runtime.py still uses the legacy "
            f"signal-type dispatch path"
        )

    # Methods covering every protocol — only the ones matching the
    # stage's protocol are actually relevant, but providing them all
    # means a single placeholder class works for every unused slot.
    def normalize(self, raw_signal: dict[str, Any]) -> Any:
        return self._raise("normalize")

    def detect(self, envelope: Any) -> Trigger | None:
        return self._raise("detect")

    def plan(self, *, trigger: Trigger, signal_payload: dict[str, Any]) -> InvestigationPlan:
        return self._raise("plan")

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> Any:
        return self._raise("assemble")

    def build(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        evidence_pack: dict[str, Any] | None,
    ) -> RcaReport:
        return self._raise("build")

    def decide(self, **kwargs: Any) -> Decision:
        return self._raise("decide")

    def analyze(self, trigger: Trigger, **kwargs: Any) -> Any:
        return self._raise("analyze")

    def record(self, **kwargs: Any) -> Any:
        return self._raise("record")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class HarnessDrivenInvestigationPlanner:
    """Generic investigation planner that emits an empty plan artifact.

    The actual probe selection happens in the investigation harness
    (``LlmProbeSelector`` / ``NativeProbeSelector``) which receives
    the trigger + signal payload at loop construction time. This
    planner's job is just to produce the audited ``InvestigationPlan``
    artifact so the run timeline records "we entered the investigation
    stage with these intentions" for every signal type — not just
    Reth.

    Profiles whose investigation needs are domain-specific
    (e.g. ``RethSignalProfile.investigation_planner`` builds a
    multi-probe Reth-specific plan) provide their own implementation.
    Everything else uses this.
    """

    def __init__(
        self,
        *,
        signal_type: str,
        objective_template: str = "Generic agentic investigation for {signal_type} on {service}.",
    ) -> None:
        self._signal_type = signal_type
        self._objective_template = objective_template

    def plan(self, *, trigger: Trigger, signal_payload: dict[str, Any]) -> InvestigationPlan:
        objective = self._objective_template.format(
            signal_type=self._signal_type,
            service=getattr(trigger, "service", "unknown"),
        )
        plan = InvestigationPlan(
            plan_id=f"plan_{self._signal_type}_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            objective=objective,
            probe_budget={
                "max_probes": 0,
                "max_total_latency_ms": 0,
                "per_probe_timeout_ms": 0,
                "mode": "harness_driven",
                "planner": "harness",
            },
            # Empty probes list — the harness owns probe selection.
            # The artifact's value is being recorded at all (which
            # the silent-skip path failed to do for non-Reth signals).
            probes=[],
        )
        plan.validate()
        return plan


class HarnessDrivenRcaBuilder:
    """Generic RCA builder that synthesises from harness output.

    Replaces the silent-skip behaviour of ``build_rca_report`` for
    any profile without a domain-specific RCA path. The builder reads
    the decision's ``ranked_hypotheses`` (already populated by the
    hypothesis engine + harness root-cause candidates) and produces a
    valid ``RcaReport`` whose fields reflect the harness output rather
    than being hardcoded to a particular signal type.

    For unknown / generic signals, this ensures the operator gets an
    RCA artifact every run — even when the harness didn't find a
    strong candidate, the report records "investigation completed,
    uncertainty high" rather than the run silently lacking an RCA.
    """

    def build(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        evidence_pack: dict[str, Any] | None,
    ) -> RcaReport:
        ranked = decision.reasoning.get("ranked_hypotheses")
        ranked_list = ranked if isinstance(ranked, list) else []
        top = ranked_list[0] if ranked_list and isinstance(ranked_list[0], dict) else {}

        likely_cause = str(top.get("candidate_cause") or "unknown")
        confidence = _safe_float(top.get("posterior_confidence"), decision.confidence)
        supporting = [str(item) for item in top.get("supporting_evidence", []) if item]
        disconfirming = [str(item) for item in top.get("disconfirming_evidence", []) if item]
        ruled_out = [
            str(item.get("candidate_cause"))
            for item in ranked_list[1:]
            if isinstance(item, dict) and item.get("candidate_cause") and item.get("disconfirming_evidence")
        ][:6]
        evidence_checked = _evidence_checked(evidence_pack)
        unknowns = _unknowns(ranked_list, evidence_pack)
        safety_reason = _safety_reason(decision, evidence_pack, top)

        report = RcaReport(
            report_id=f"rca_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            likely_cause=likely_cause,
            confidence=confidence,
            supporting_evidence=supporting,
            disconfirming_evidence=disconfirming,
            ruled_out_causes=ruled_out,
            unknowns=unknowns,
            evidence_checked=evidence_checked,
            recommended_next_step=decision.decision_type,
            safety_reason=safety_reason,
        )
        report.validate()
        return report


# ----------------------------------------------------------------------
# Internal helpers — lifted from services/investigation/rca.py to keep
# this module self-contained. The Reth-specific RCA builder
# (services/investigation/rca.py) imports the same logic; once Phase
# 2A migrates fully these will become the single source of truth.
# ----------------------------------------------------------------------


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _evidence_checked(evidence_pack: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Mirror ``services/investigation/rca.py:_evidence_checked``.

    Extract the probe results from the evidence pack into the shape
    the ``RcaReport`` contract expects, so the audit trail shows what
    was looked up. Field names match the Reth builder exactly so a
    consumer comparing reports across signal types sees uniform keys.
    """
    if not isinstance(evidence_pack, dict):
        return []
    probes = evidence_pack.get("probe_results")
    if not isinstance(probes, list):
        return []
    checked: list[dict[str, Any]] = []
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        checked.append(
            {
                "name": probe.get("name"),
                "source": probe.get("source"),
                "success": probe.get("success"),
                "latency_ms": probe.get("latency_ms"),
                "citations": list(probe.get("citations") or [])[:4],
            }
        )
    return checked


def _unknowns(ranked: list[dict[str, Any]], evidence_pack: dict[str, Any] | None) -> list[str]:
    """Surface what the investigation didn't learn.

    Mirrors ``services/investigation/rca.py:_unknowns`` — the
    Reth-specific RCA builder uses the same logic, so this stays
    aligned for cross-profile consistency.
    """
    unknown: list[str] = []
    if isinstance(evidence_pack, dict) and evidence_pack.get("sufficient") is False:
        missing = ", ".join(str(item) for item in evidence_pack.get("missing_fields", []))
        unknown.append(f"evidence pack is insufficient: {missing or 'missing required fields'}")
    for hyp in ranked:
        if not isinstance(hyp, dict):
            continue
        predicates = hyp.get("predicates")
        if not isinstance(predicates, list):
            continue
        for predicate in predicates:
            if isinstance(predicate, dict) and predicate.get("result") == "unknown":
                unknown.append(f"{hyp.get('candidate_cause', 'unknown')}: {predicate.get('kind')}")
            if len(unknown) >= 8:
                return unknown
    return unknown


def _safety_reason(
    decision: Decision,
    evidence_pack: dict[str, Any] | None,
    top: dict[str, Any],
) -> str:
    """Why the decision was safe to take (or to defer).

    Mirrors the Reth ``_safety_reason`` for cross-profile consistency.
    The Decision contract has no ``rationale`` field — the reason
    derives from evidence-pack sufficiency, fast-path signatures, and
    the decision's own ``decision_type``.
    """
    if isinstance(evidence_pack, dict):
        if evidence_pack.get("fast_path_signatures"):
            sigs = evidence_pack["fast_path_signatures"]
            return f"fast_path_signatures={sigs}"
        if evidence_pack.get("sufficient") is False:
            missing = ", ".join(str(item) for item in evidence_pack.get("missing_fields", []) or [])
            return f"insufficient evidence: {missing or 'missing required fields'}"
    if decision.decision_type == "escalate":
        top_reason = top.get("recommended_action") if isinstance(top, dict) else None
        if top_reason == "escalate":
            return "top hypothesis recommends escalation; policy keeps production mutation blocked"
        return "decision routes to human review under signal-profile safety policy"
    return "signal-profile safety policy and evaluation gates remain authoritative"


__all__ = [
    "HarnessDrivenInvestigationPlanner",
    "HarnessDrivenRcaBuilder",
    "NotYetWired",
    "NotYetWiredStrategy",
]
