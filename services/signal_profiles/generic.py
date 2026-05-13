"""Generic signal profile — the agentic fallback for unknown signal types.

When a payload arrives with a ``signal_type`` not in the registry,
``SignalProfileRegistry.get_or_generic`` resolves to this profile.
The pipeline runs end-to-end (no silent skips, invariant 1) and the
decision strategy returns ``escalate`` unconditionally (invariant 2 —
unknown sources cannot auto-act).

The profile uses the ``GENERIC_PROFILE_KEY`` sentinel as its
``signal_type`` so it never collides with a real registered type.

PR 1 wires planner + RCA (so unknown signals get the full
agentic-harness diagnostic trail). Later PRs replace the placeholder
strategies with real generic implementations (evidence pass-through,
decision = escalate, etc.).
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import GENERIC_PROFILE_KEY, SignalProfile

from ._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
)


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the generic agentic-fallback profile."""
    return SignalProfile(
        signal_type=GENERIC_PROFILE_KEY,
        # No trigger_type collision possible — the registry's
        # trigger-keyed index never sees this sentinel because
        # registry.register() rejects the generic sentinel.
        trigger_type=GENERIC_PROFILE_KEY,
        # No declared schema — the generic profile accepts any
        # well-formed payload. Per-field validation happens at the
        # ingest stage via duck-typing when a real schema is unknown.
        schema_name="",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:generic"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:generic"),
        investigation_planner=HarnessDrivenInvestigationPlanner(
            signal_type="generic",
            objective_template=(
                "Agentic investigation for unrecognised signal on {service} via "
                "every always-on tool pack (kubectl/prometheus/loki/jaeger/"
                "aws/github/postgres/mcp/topology)."
            ),
        ),
        evidence_strategy=NotYetWiredStrategy("evidence_strategy:generic"),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:generic"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:generic"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:generic"),
        signal_source="generic",
        default_severity="high",
        requires_namespace=False,
    )


__all__ = ["build"]
