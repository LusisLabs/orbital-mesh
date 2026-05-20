"""Kubernetes deployment-issue signal profile.

K8s was the second signal type wired into Mesh but the evidence
strategy was a structural field-check passthrough until this PR.
``KubernetesLiveEvidenceStrategy`` now runs real read-only kubectl
probes (get pods, get events, describe deployment) when
``MESH_KUBECTL_COMMAND`` is configured. Investigation planner + RCA
builder remain the harness-driven defaults; the other slots
(``ingest_normalizer``, ``trigger_detector``, ``decision_strategy``,
``scenario_analyzer``, ``feedback_strategy``) are still placeholders
for follow-up PRs.
"""

from __future__ import annotations

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.signal_profile import SignalProfile

from ._live_evidence import KubernetesLiveEvidenceStrategy
from ._shared_strategies import (
    HarnessDrivenInvestigationPlanner,
    HarnessDrivenRcaBuilder,
    NotYetWiredStrategy,
)


def build(config: RuntimeConfig | None = None) -> SignalProfile:
    """Construct the Kubernetes signal profile.

    Evidence strategy is ``KubernetesLiveEvidenceStrategy``: runs
    real kubectl probes when configured, falls back to structural
    field-check when not. Deployments without a cluster wired keep
    working unchanged.
    """
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
        evidence_strategy=KubernetesLiveEvidenceStrategy(config=config),
        rca_builder=HarnessDrivenRcaBuilder(),
        decision_strategy=NotYetWiredStrategy("decision_strategy:kubernetes"),
        scenario_analyzer=NotYetWiredStrategy("scenario_analyzer:kubernetes"),
        feedback_strategy=NotYetWiredStrategy("feedback_strategy:kubernetes"),
        signal_source="kubernetes",
        default_severity="high",
        requires_namespace=True,
    )


__all__ = ["build"]
