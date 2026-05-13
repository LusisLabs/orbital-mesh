"""Generic webhook-alert signal profile.

The webhook profile catches inbound alerts that match the standard
webhook payload shape but don't promote to feature-flag, K8s, OTel,
or Reth. The current pipeline routes them through
``webhook_alert_firing`` and reasons via the deterministic
metric-action rules.

Like the other non-Reth profiles, planner + RCA were silent skips
before this profile existed. The harness-driven defaults now ensure
a complete diagnostic trail.
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import SignalProfile

from ._evidence_strategies import StructuredSignalEvidenceStrategy
from ._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
)


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the generic webhook-alert profile."""
    return SignalProfile(
        signal_type="webhook_alert",
        trigger_type="webhook_alert_firing",
        schema_name="webhook-alert.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:webhook"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:webhook"),
        investigation_planner=HarnessDrivenInvestigationPlanner(
            signal_type="webhook",
            objective_template=(
                "Investigate webhook alert for {service} via the always-on tool packs."
            ),
        ),
        evidence_strategy=StructuredSignalEvidenceStrategy(
            signal_source="webhook",
            required_paths=(
                "signal_type",
                "webhook.action",
                "webhook.severity",
                "webhook.title",
                "related_context.webhook_alert_id",
            ),
        ),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:webhook"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:webhook"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:webhook"),
        signal_source="webhook",
        default_severity="medium",
        requires_namespace=False,
    )


__all__ = ["build"]
