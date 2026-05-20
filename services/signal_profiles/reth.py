"""Reth (blockchain execution node) signal profile.

The Reth path was Mesh's first end-to-end signal type and currently
carries the only real evidence-pack assembly, investigation planner,
and RCA builder. This profile wraps that existing logic so dispatch
flows through ``SignalProfileRegistry`` like every other type.

PR 1 wires:
* ``investigation_planner`` — wraps ``RethInvestigationPlanner`` so it
  always returns a non-None plan (the existing class returns None for
  non-Reth signals, which can't happen inside this profile).
* ``rca_builder`` — wraps ``build_rca_report`` from
  ``services/investigation/rca.py``, but skips the Reth-only guard
  since we're already inside the Reth profile.

The remaining six strategy slots are ``NotYetWiredStrategy``
placeholders — runtime.py still calls the legacy ingest / trigger /
evidence / decision / scenario / feedback services for Reth in PR 1.
PR 2 replaces evidence + decision; PR 3 replaces the rest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from shared.mesh_runtime import Decision, InvestigationPlan, RcaReport, RuntimeConfig, Trigger
from shared.mesh_runtime.signal_profile import SignalProfile

from ._evidence_strategies import RethEvidenceStrategy
from ._shared_strategies import NotYetWiredStrategy


class RethProfileInvestigationPlanner:
    """Wraps ``RethInvestigationPlanner`` for the profile dispatch layer.

    The underlying class returns ``None`` when the trigger is not
    Reth-shaped; that can't happen inside the Reth profile because the
    registry resolves to this profile only for ``signal_type ==
    "reth_node"``. We assert it as a safety net rather than silently
    losing the plan.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        # Imported lazily so this module can be loaded without
        # pulling the LLM client transitively into every consumer.
        from services.investigation.reth_planner import RethInvestigationPlanner

        self._delegate = RethInvestigationPlanner(config)

    def plan(self, *, trigger: Trigger, signal_payload: dict[str, Any]) -> InvestigationPlan:
        plan = self._delegate.plan(trigger=trigger, signal_payload=signal_payload)
        if plan is None:
            # Defensive: the only way this happens is if a non-Reth
            # signal somehow reached this profile. Emit an empty-but-
            # valid plan so the run still has an audited artifact.
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            plan = InvestigationPlan(
                plan_id=f"plan_reth_fallback_{trigger.trigger_id}_{uuid4().hex[:8]}",
                trigger_id=trigger.trigger_id,
                created_at=now,
                objective=(
                    f"Fallback Reth plan for {trigger.service}; underlying planner returned None — "
                    "likely a profile-resolution mismatch."
                ),
                probe_budget={
                    "max_probes": 0,
                    "max_total_latency_ms": 0,
                    "per_probe_timeout_ms": 0,
                    "mode": "reth_fallback",
                    "planner": "fallback",
                },
                probes=[],
            )
            plan.validate()
        return plan


class RethProfileRcaBuilder:
    """Wraps ``build_rca_report`` for the profile dispatch layer.

    The underlying function gates on ``trigger.trigger_type == "reth_node_degraded"``;
    that gate is structurally enforced by the registry — every trigger
    reaching this builder went through ``RethSignalProfile``. We still
    call the wrapped function so its existing field-derivation logic
    is the single source of truth; for the defensive ``None`` case we
    fall back to a minimal RcaReport so the run is never missing an
    artifact.
    """

    def build(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        evidence_pack: dict[str, Any] | None,
    ) -> RcaReport:
        from services.investigation.rca import build_rca_report

        report = build_rca_report(
            trigger=trigger,
            decision=decision,
            evidence_pack=evidence_pack,
        )
        if report is not None:
            return report
        # Defensive fallback identical in shape to the wrapped
        # function's output so downstream consumers see a uniform
        # contract.
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report = RcaReport(
            report_id=f"rca_reth_fallback_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=now,
            likely_cause="unknown",
            confidence=float(decision.confidence),
            supporting_evidence=[],
            disconfirming_evidence=[],
            ruled_out_causes=[],
            unknowns=["reth_rca_builder_returned_none"],
            evidence_checked=[],
            recommended_next_step=decision.decision_type,
            safety_reason="reth rca builder fallback path",
        )
        report.validate()
        return report


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the Reth signal profile."""
    return SignalProfile(
        signal_type="reth_node",
        trigger_type="reth_node_degraded",
        schema_name="reth-node-signal.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:reth"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:reth"),
        investigation_planner=RethProfileInvestigationPlanner(config),
        evidence_strategy=RethEvidenceStrategy(),
        rca_builder=RethProfileRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:reth"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:reth"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:reth"),
        signal_source="blockchain_node",
        default_severity="high",
        requires_namespace=False,
    )


__all__ = [
    "RethProfileInvestigationPlanner",
    "RethProfileRcaBuilder",
    "build",
]
