"""Kubernetes deployment-issue signal profile.

K8s was the second signal type wired into Mesh but never had a real
investigation planner or RCA builder — both stages silently no-op'd
for K8s today. This profile fills that gap using the shared
``HarnessDrivenInvestigationPlanner`` and ``HarnessDrivenRcaBuilder``
so the run timeline records full diagnostic artifacts for K8s
incidents going forward.

PR 1 wires planner + RCA (now non-silent for K8s). Later PRs lift
K8s-specific evidence assembly, decision logic, scenario analysis,
and feedback into proper strategies; for now those slots use
``NotYetWiredStrategy`` placeholders.
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
    """Construct the Kubernetes signal profile."""
    return SignalProfile(
        signal_type="kubernetes_deployment_issue",
        trigger_type="kubernetes_deployment_unhealthy",
        schema_name="kubernetes-signal.schema.json",
        ingest_normalizer=NotYetWiredStrategy("ingest_normalizer:kubernetes"),
        trigger_detector=NotYetWiredStrategy("trigger_detector:kubernetes"),
        investigation_planner=HarnessDrivenInvestigationPlanner(
            signal_type="kubernetes",
            objective_template=(
                "Investigate Kubernetes regression on {service} via the always-on "
                "kubectl/topology/loki tool packs."
            ),
        ),
        evidence_strategy=NotYetWiredStrategy("evidence_strategy:kubernetes"),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:kubernetes"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:kubernetes"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:kubernetes"),
        signal_source="kubernetes",
        default_severity="high",
        requires_namespace=True,
    )


__all__ = ["build"]
