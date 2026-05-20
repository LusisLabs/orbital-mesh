"""Strategy protocols for per-signal-type pipeline dispatch.

A ``SignalProfile`` (see ``signal_profile.py``) binds a concrete
implementation of each protocol to a particular ``signal_type``. The
pipeline (``runtime.py``, ``decision/service.py``, etc.) calls the
methods on the active profile's strategies rather than dispatching on
``signal_type`` directly.

Two design choices worth knowing about:

* **Always return an artifact, never ``None`` from required stages.**
  The only legitimate silent skip in the pipeline is
  ``TriggerDetector.detect`` (a non-incident is a valid outcome). Every
  other strategy emits a typed artifact even when the strategy has
  nothing useful to add — the artifact's ``status`` field reflects
  that. This is invariant 1 from ``docs/architecture/signal-profile-spec.md``.
* **Strategies are pure with respect to the runtime engine.** They
  receive contracts and return contracts. Side effects (state-store
  writes, event recording) belong to the engine. This keeps strategies
  testable without mocking the world.

The protocols intentionally use ``typing.Protocol`` rather than ABCs
so existing concrete classes can be retro-fitted without inheritance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .contracts import (
    Decision,
    EvaluationResult,
    ExecutionRecord,
    FeedbackRecord,
    InvestigationPlan,
    InvestigationReport,
    RcaReport,
    ScenarioAnalysis,
    Trigger,
)


@runtime_checkable
class IngestNormalizer(Protocol):
    """Normalize a raw inbound payload into a Mesh ``EventEnvelope``.

    Implementations must validate the payload against the profile's
    declared ``schema_name`` before normalizing. A malformed payload
    raises ``ValueError`` — the caller (``IngestService``) maps that
    into a typed ingest failure event, not a crash.
    """

    def normalize(self, raw_signal: dict[str, Any]) -> Any:
        """Return an ``EventEnvelope``-shaped object.

        ``Any`` rather than the concrete ``EventEnvelope`` because the
        envelope type lives in ``services/ingest/`` which depends on
        this module — keeping it loose avoids a circular import.
        """
        ...


@runtime_checkable
class TriggerDetector(Protocol):
    """Decide whether a normalized event is an incident.

    The ONE legitimate silent skip in the pipeline. A non-incident
    (e.g., a metric that recovered before persistence threshold) is a
    valid outcome — return ``None`` and the runtime emits a
    ``no_trigger`` terminal event.
    """

    def detect(self, envelope: Any) -> Trigger | None:
        """Return a ``Trigger`` for an incident, or ``None`` for noise."""
        ...


@runtime_checkable
class InvestigationPlanner(Protocol):
    """Build the read-only probe plan for a trigger.

    Always returns a non-None plan. Even if no domain-specific probes
    apply, the planner emits an empty-but-validated plan so the
    audit trail is uniform across signal types.

    Generic-profile planners assemble probes from the always-on tool
    packs (kubectl, prometheus, loki, etc.) via the LLM selector.
    """

    def plan(
        self, *, trigger: Trigger, signal_payload: dict[str, Any]
    ) -> InvestigationPlan:
        """Return an ``InvestigationPlan`` (always non-None)."""
        ...


@runtime_checkable
class EvidenceStrategy(Protocol):
    """Assemble the audited evidence pack for a signal.

    Per-strategy responsibilities:
    * pre-fast-path scans (regex over log lines, posture checks, etc.)
      that stamp escalation signatures on the trigger
    * fast-path escalation when an unsafe signature is present
    * probe-runner invocation when normal-path evidence assembly is
      needed
    * sufficiency check — does the pack carry the fields downstream
      stages need?

    Output shape is the same ``EvidencePack`` for every strategy so
    the rest of the pipeline reads it uniformly.
    """

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> Any:
        """Return an ``EvidencePack``.

        ``Any`` because ``EvidencePack`` is a ``services/evidence``
        dataclass — keeping the return type loose at the protocol
        level avoids a service→shared dependency.
        """
        ...


@runtime_checkable
class RcaBuilder(Protocol):
    """Build the RCA report attached to the run's decision.

    Always returns a non-None ``RcaReport``. Profiles without
    specialised RCA logic build a generic report from the
    investigation harness's findings rather than returning ``None``.
    """

    def build(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        evidence_pack: dict[str, Any] | None,
    ) -> RcaReport:
        """Return an ``RcaReport`` (always non-None)."""
        ...


@runtime_checkable
class DecisionStrategy(Protocol):
    """Decide what action to take for a trigger.

    Each strategy enforces a bounded action surface for its signal
    type. The generic strategy returns ``escalate`` unconditionally —
    unknown signal types cannot auto-act (invariant 2).

    The ``DecisionService`` wraps the call to apply invariant 5
    (one-way safety promotion) — a strategy cannot demote an
    escalation that an upstream stage set.
    """

    def decide(
        self,
        *,
        trigger: Trigger,
        scenario_analysis: ScenarioAnalysis,
        evidence_pack: dict[str, Any] | None,
        investigation_report: dict[str, Any] | None,
    ) -> Decision:
        """Return a bounded ``Decision``."""
        ...


@runtime_checkable
class ScenarioAnalyzer(Protocol):
    """Cross-run scenario context.

    Looks up recent similar runs, projects active memory, builds
    modular subdecisions. The generic analyzer returns a minimal
    pass-through (no cross-run lookup) so unknown signal types still
    produce a uniform artifact.
    """

    def analyze(
        self,
        trigger: Trigger,
        *,
        investigation_report: dict[str, Any] | None = None,
    ) -> tuple[ScenarioAnalysis, Any]:
        """Return ``(ScenarioAnalysis, MemoryCompactionRecord | None)``."""
        ...


@runtime_checkable
class FeedbackStrategy(Protocol):
    """Record post-action outcome observations (T+10m, T+30m).

    Per-signal-type: Reth checks RPC reachability, K8s checks pod
    readiness, OTel checks metric recovery. The generic strategy
    records a stub event noting that the profile does not auto-act so
    feedback is not applicable.
    """

    def record(
        self,
        *,
        trigger: Trigger,
        decision: Decision,
        execution: ExecutionRecord,
        evaluation: EvaluationResult,
        normalized_event: Any,
    ) -> FeedbackRecord:
        """Return a ``FeedbackRecord`` (always non-None)."""
        ...


__all__ = [
    "DecisionStrategy",
    "EvidenceStrategy",
    "FeedbackStrategy",
    "IngestNormalizer",
    "InvestigationPlanner",
    "RcaBuilder",
    "ScenarioAnalyzer",
    "TriggerDetector",
]
