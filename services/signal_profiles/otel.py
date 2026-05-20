"""OpenTelemetry metric-regression signal profile.

Like Kubernetes, OTel signals fell through the silent-skip in the
investigation planner + RCA builder today. This profile uses the
shared harness-driven defaults so OTel runs emit complete diagnostic
artifacts.

The eventual specialised planner would fan out probes via the
Prometheus tool pack (baseline lookup over [-1h, -24h, -7d],
correlation with latency + error rate). That lives in a later PR.
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import SignalProfile

from ._live_evidence import OtelLiveEvidenceStrategy
from ._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
)


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the OTel signal profile.

    Evidence strategy is ``OtelLiveEvidenceStrategy``: queries the
    configured Prometheus for the regressed metric's range when
    ``MESH_PROMETHEUS_URL`` is set, falls back to structural
    field-check when not. Range-query data lands as a probe result
    so the hypothesis engine and scenario analyzer get actual time
    series rather than just the summary in the inbound signal.
    """
    return SignalProfile(
        signal_type="otel_metric_regression",
        trigger_type="otel_metric_regression",
        schema_name="otel-metric-signal.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:otel"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:otel"),
        investigation_planner=HarnessDrivenInvestigationPlanner(
            signal_type="otel",
            objective_template=(
                "Investigate metric regression on {service} via the always-on "
                "prometheus/loki/jaeger tool packs."
            ),
        ),
        evidence_strategy=OtelLiveEvidenceStrategy(config=config),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:otel"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:otel"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:otel"),
        signal_source="metrics",
        default_severity="medium",
        requires_namespace=False,
    )


__all__ = ["build"]
