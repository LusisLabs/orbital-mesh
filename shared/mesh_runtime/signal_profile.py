"""``SignalProfile`` — single source of truth for per-signal-type pipeline behavior.

Adding a new signal type to Mesh is one ``SignalProfile`` registration.
The profile binds every stage of the pipeline (ingest, trigger,
investigation plan, evidence assembly, RCA, decision, scenario
analysis, feedback) to a concrete strategy implementation.

The reasoning behind this design lives in
``docs/architecture/signal-profile-spec.md``. In short:

* Today the pipeline branches on ``signal_type`` in 29 places across 8
  directories. Three of those branches are silent early-returns —
  Kubernetes and OTel runs no-op the investigation planner and the
  RCA builder, so the run "succeeds" with empty diagnostic output.
* The registry funnels every dispatch through one lookup. Strategies
  are typed via Protocol classes in ``signal_profile_protocols.py``.
* Unknown ``signal_type`` resolves to ``GenericSignalProfile``, whose
  decision strategy escalates unconditionally — unknown sources
  cannot auto-act.

The registry is fail-loud on construction (duplicate registration,
incomplete profile) so misconfiguration surfaces at engine start, not
at the moment a signal arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Iterable

from .signal_profile_protocols import (
    DecisionStrategy,
    EvidenceStrategy,
    FeedbackStrategy,
    IngestNormalizer,
    InvestigationPlanner,
    RcaBuilder,
    ScenarioAnalyzer,
    TriggerDetector,
)


# Sentinel value used when a profile applies to any ``signal_type`` /
# ``trigger_type`` not otherwise registered. Reserved for the generic
# profile.
GENERIC_PROFILE_KEY = "*"


class ProfileAlreadyRegistered(Exception):
    """Raised when ``SignalProfileRegistry.register`` sees a duplicate ``signal_type``."""


class IncompleteProfile(Exception):
    """Raised when a profile is missing one of the required strategies."""


@dataclass(frozen=True)
class SignalProfile:
    """Per-signal-type pipeline configuration.

    Every concrete profile must supply all eight strategies. The
    registry validates completeness at construction (see
    ``SignalProfileRegistry.__init__``).

    The ``signal_source`` / ``default_severity`` / ``requires_namespace``
    fields are routing metadata used by the orchestrator and control
    plane in place of the current ``.startswith("kubernetes_")`` chains.
    """

    # Identity
    signal_type: str
    trigger_type: str
    schema_name: str

    # Stage strategies — every profile must supply all of them.
    ingest_normalizer: IngestNormalizer
    trigger_detector: TriggerDetector
    investigation_planner: InvestigationPlanner
    evidence_strategy: EvidenceStrategy
    rca_builder: RcaBuilder
    decision_strategy: DecisionStrategy
    scenario_analyzer: ScenarioAnalyzer
    feedback_strategy: FeedbackStrategy

    # Routing metadata — replaces scattered string-prefix checks.
    signal_source: str = "generic"
    default_severity: str = "medium"
    requires_namespace: bool = False


_REQUIRED_STRATEGY_FIELDS: tuple[str, ...] = (
    "ingest_normalizer",
    "trigger_detector",
    "investigation_planner",
    "evidence_strategy",
    "rca_builder",
    "decision_strategy",
    "scenario_analyzer",
    "feedback_strategy",
)


def _assert_complete(profile: SignalProfile) -> None:
    missing: list[str] = []
    for name in _REQUIRED_STRATEGY_FIELDS:
        if getattr(profile, name, None) is None:
            missing.append(name)
    if missing:
        raise IncompleteProfile(
            f"profile signal_type={profile.signal_type!r} is missing strategies: {missing}"
        )


class SignalProfileRegistry:
    """Lookup table for ``SignalProfile`` instances.

    Build once at engine start. Lookups are by ``signal_type`` (the
    inbound payload's ``"signal_type"`` field) or by ``trigger_type``
    (the normalized trigger's ``trigger_type``). Both reach the same
    profile because each profile owns exactly one of each.

    ``get_or_generic`` is the runtime's default entry point — it never
    returns ``None``. Unknown ``signal_type`` falls back to the
    generic profile, which the pipeline still runs through end-to-end
    (escalating at the decision stage rather than silently skipping).
    """

    def __init__(
        self,
        profiles: Iterable[SignalProfile],
        generic: SignalProfile | None = None,
    ) -> None:
        self._by_signal_type: dict[str, SignalProfile] = {}
        self._by_trigger_type: dict[str, SignalProfile] = {}
        self._generic: SignalProfile | None = None

        for profile in profiles:
            self.register(profile)
        if generic is not None:
            if generic.signal_type != GENERIC_PROFILE_KEY:
                # The generic profile's signal_type is the sentinel —
                # we never want it shadowed by a real-typed lookup,
                # and the sentinel makes "this is the fallback"
                # obvious in event payloads.
                raise IncompleteProfile(
                    f"generic profile must use signal_type={GENERIC_PROFILE_KEY!r}; "
                    f"got {generic.signal_type!r}"
                )
            _assert_complete(generic)
            self._generic = generic

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, profile: SignalProfile) -> None:
        """Add a profile. Validates completeness and uniqueness."""
        _assert_complete(profile)
        if profile.signal_type == GENERIC_PROFILE_KEY:
            raise IncompleteProfile(
                "concrete profiles cannot use the generic signal_type sentinel; "
                "pass them via SignalProfileRegistry(generic=...)"
            )
        if profile.signal_type in self._by_signal_type:
            raise ProfileAlreadyRegistered(
                f"signal_type={profile.signal_type!r} already registered"
            )
        if profile.trigger_type in self._by_trigger_type:
            raise ProfileAlreadyRegistered(
                f"trigger_type={profile.trigger_type!r} already registered "
                f"(by signal_type={self._by_trigger_type[profile.trigger_type].signal_type!r})"
            )
        self._by_signal_type[profile.signal_type] = profile
        self._by_trigger_type[profile.trigger_type] = profile

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def get(self, signal_type: str) -> SignalProfile | None:
        """Strict lookup. Returns ``None`` for unknown types."""
        return self._by_signal_type.get(signal_type)

    def get_for_trigger(self, trigger_type: str) -> SignalProfile | None:
        """Lookup by trigger type (parallel index to signal_type)."""
        return self._by_trigger_type.get(trigger_type)

    def get_or_generic(self, signal_type: str | None) -> SignalProfile:
        """Lookup with generic fallback. Never returns ``None``.

        This is the canonical entry point from ``runtime.py``.
        Resolving an unknown ``signal_type`` to the generic profile is
        the structural defense against silent skips — every stage runs,
        the generic decision strategy escalates, the operator sees the
        unknown signal in the audit trail.
        """
        if signal_type is not None:
            profile = self._by_signal_type.get(signal_type)
            if profile is not None:
                return profile
        if self._generic is None:
            raise IncompleteProfile(
                "no generic profile registered and signal_type "
                f"{signal_type!r} is not in the registry; "
                "either register a profile for this signal_type or supply a generic"
            )
        return self._generic

    def get_or_generic_for_trigger(self, trigger_type: str | None) -> SignalProfile:
        """Trigger-keyed counterpart to ``get_or_generic``."""
        if trigger_type is not None:
            profile = self._by_trigger_type.get(trigger_type)
            if profile is not None:
                return profile
        if self._generic is None:
            raise IncompleteProfile(
                "no generic profile registered and trigger_type "
                f"{trigger_type!r} is not in the registry"
            )
        return self._generic

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def generic(self) -> SignalProfile | None:
        """Return the registered generic profile, or ``None``."""
        return self._generic

    def signal_types(self) -> tuple[str, ...]:
        """Return all registered ``signal_type`` values (excluding the generic sentinel)."""
        return tuple(self._by_signal_type)

    def trigger_types(self) -> tuple[str, ...]:
        """Return all registered ``trigger_type`` values."""
        return tuple(self._by_trigger_type)

    def profiles(self) -> tuple[SignalProfile, ...]:
        """Return all concrete profiles. Generic profile is excluded — fetch via ``.generic``."""
        return tuple(self._by_signal_type.values())


__all__ = [
    "GENERIC_PROFILE_KEY",
    "IncompleteProfile",
    "ProfileAlreadyRegistered",
    "SignalProfile",
    "SignalProfileRegistry",
]
