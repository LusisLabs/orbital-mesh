"""Feature-flag performance-regression signal profile.

Feature-flag triggers come in via the same ``webhook_alert`` payload
shape as generic alerts but resolve to the dedicated
``feature_flag_performance_regression`` trigger type when the
ScenarioAnalysisService recognises a flag-rollout pattern. This
profile is keyed on the trigger type because the *signal* type stays
``webhook_alert`` — the registry's ``get_for_trigger`` resolves
correctly.

Today the feature-flag path uses scenario-analysis subdecisions for
its reasoning; the investigation planner + RCA stages silently skip.
This profile fills both with harness-driven defaults.
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import SignalProfile

from ._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
)


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the feature-flag signal profile."""
    return SignalProfile(
        # The codebase emits ``signal_type="feature_flag"`` for any
        # signal that falls through ``IngestService._dispatch_normalize``
        # (see ``services/ingest/service.py:71`` — the default when no
        # explicit signal_type is set) and the fixtures in
        # ``fixtures/signals/`` follow the same convention. The profile
        # must match exactly or real feature-flag signals route to the
        # generic agentic-fallback profile and lose their specialised
        # decision logic + scenario analysis.
        signal_type="feature_flag",
        trigger_type="feature_flag_performance_regression",
        # No dedicated schema today — feature-flag signals ride the
        # generic webhook payload. The schema field stays for
        # forward-compat with per-type validation in PR 4.
        schema_name="webhook-alert.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:feature_flag"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:feature_flag"),
        investigation_planner=HarnessDrivenInvestigationPlanner(
            signal_type="feature_flag",
            objective_template=(
                "Investigate feature-flag regression on {service} via the "
                "always-on tool packs."
            ),
        ),
        evidence_strategy=NotYetWiredStrategy("evidence_strategy:feature_flag"),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:feature_flag"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:feature_flag"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:feature_flag"),
        signal_source="feature_flag",
        default_severity="medium",
        requires_namespace=False,
    )


__all__ = ["build"]
