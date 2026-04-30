"""Chaos portfolio: weighted catalog of injection primitives with
expected Mesh responses.

# Why a portfolio

The Principles of Chaos tell us to "vary real-world events" and to
prioritize them by impact and frequency. A flat list of primitives
doesn't capture either axis. This module wraps each primitive with:

* A **weight** reflecting how often we want this event to fire in a
  session. High weight = common real-world event (pod kills happen
  constantly in prod); low weight = rare but nasty (OOMKilled bursts).
* A **severity** tag so the session scheduler can refuse to stack two
  destructive experiments back-to-back.
* **Prerequisites** the target deployment must satisfy before the
  injection can run (e.g., memory_pressure needs at least one Running
  pod; scale_to_zero needs replicas > 0).
* **Expected Mesh response** — the decision-type family we expect
  Mesh to emit. The session's per-experiment verdict compares this
  expectation against what Mesh actually did. The *shape* of the
  expectation is a set because "restart_deployment or
  rollback_deployment" is often legitimately either — the scorer
  treats any member as a pass.
* **Cooldown** — minimum seconds before this primitive can fire again
  on the same deployment. Protects against a single flaky primitive
  flooding the session.

# Why expected responses are sets, not single strings

Look at ``crash_loop``: the decision engine can legitimately propose
either ``restart_deployment`` (hope the stuck state clears) or
``rollback_deployment`` (assume the new revision is bad). Both are
defensible given the same signal. Scoring against a set means we
don't flag a legitimate alternative as a false positive.

The session report shows the decision Mesh actually took alongside
the expectation set, so a reader can audit both the pass verdict and
the specific path Mesh chose.

# Adding a new primitive

1. Write the ``inject_<name>`` method on :class:`ChaosInjector`.
2. Add a :class:`ChaosExperiment` entry here with weight/severity/
   expected response.
3. Mention it in the README's chaos section.

The session runner picks up new entries automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# Severity tags. Keep the set small — the scheduler uses these for
# pairing rules ("don't schedule two 'severe' back-to-back") and the
# report uses them for the aggregate breakdown. More tags = more
# configuration surface without proportional signal.
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_SEVERE = "severe"


@dataclass
class ChaosExperiment:
    """One entry in the chaos portfolio.

    The session scheduler and report both read this shape; the
    injector itself doesn't — it only knows primitives. That keeps
    the injector reusable for ad-hoc scenarios while the portfolio
    adds policy on top.
    """

    # Human name. Shown in the session report and log. Match the
    # ``inject_<name>`` method on :class:`ChaosInjector`.
    name: str

    # One-sentence description for the report's hypothesis section.
    description: str

    # Weight for random selection. Higher = more likely to be picked.
    # The scheduler normalizes weights so absolute values don't matter;
    # ratios do. A primitive with weight 5 fires ~5x as often as weight 1.
    weight: float

    # Scheduler uses this to enforce back-to-back pairing rules.
    severity: str

    # Decision-type families that qualify as a "correct" Mesh response.
    # Empty set means "no specific expectation" — useful for false-
    # positive probes where the right answer is ``no_trigger`` or
    # ``no_action``. The scorer handles empty expectations specially.
    expected_decisions: frozenset[str]

    # Seconds before the same primitive can fire again on the same
    # deployment. Applied per-(primitive, deployment) pair so two
    # different deployments can receive the same injection back-to-back.
    cooldown_seconds: int = 60

    # Extra prerequisites beyond "the deployment exists and has a
    # baseline snapshot". A callable returning bool, or None if the
    # primitive has no extra prereq. Kept as a late-bound callable so
    # the portfolio file doesn't import kubectl helpers.
    precondition: Callable[..., bool] | None = None

    # Arbitrary tags for the report's aggregate breakdown. E.g. a
    # "false_positive_probe" tag lets the report group probes that
    # shouldn't trigger.
    tags: frozenset[str] = field(default_factory=frozenset)

    # Capability axes this experiment exercises. The intelligent
    # scheduler uses these to avoid repeatedly proving the same path
    # while leaving other decision surfaces untouched.
    capability_axes: frozenset[str] = field(default_factory=frozenset)

    # Optional per-primitive delay before launching the Mesh observation run.
    # Durable faults use the session-wide hold. Transient faults can override
    # this so Mesh observes the failure while the signal still exists.
    observation_delay_seconds: float | None = None


# The default portfolio. Tuned for a 60-minute session on a 2-worker
# kind cluster; adjust weights if your session duration, cluster size,
# or service mix differs substantially.
#
# Reasoning behind each weight:
#
# - crash_loop, pod_kill_one are everyday events → highest weight.
# - bad_image is frequent in rolling deploys → medium weight.
# - pod_kill_all, memory_pressure, scale_to_zero are less common but
#   more testing per hit → medium weight.
# - readiness_failure and config_drift are rare but subtle — they
#   exercise decision paths the more common primitives don't reach.
DEFAULT_PORTFOLIO: tuple[ChaosExperiment, ...] = (
    ChaosExperiment(
        name="crash_loop",
        description="Container exits non-zero on every start; kubelet backs off into CrashLoopBackOff.",
        weight=3.0,
        severity=SEVERITY_HIGH,
        expected_decisions=frozenset({"restart_deployment", "rollback_deployment"}),
        cooldown_seconds=90,
        capability_axes=frozenset({
            "detect_crash_loop",
            "choose_restart_or_rollback",
            "recover_after_spec_revert",
        }),
    ),
    ChaosExperiment(
        name="bad_image",
        description="Deployment image points at a nonexistent tag; pods stuck in ImagePullBackOff.",
        weight=2.0,
        severity=SEVERITY_HIGH,
        expected_decisions=frozenset({"rollback_deployment"}),
        cooldown_seconds=90,
        capability_axes=frozenset({
            "detect_image_pull_failure",
            "choose_rollback",
            "recover_after_spec_revert",
        }),
    ),
    ChaosExperiment(
        name="readiness_failure",
        description="Readiness probe points at a closed port; pods stay unready.",
        weight=1.0,
        severity=SEVERITY_MEDIUM,
        expected_decisions=frozenset({"restart_deployment", "rollback_deployment", "escalate"}),
        cooldown_seconds=120,
        capability_axes=frozenset({
            "detect_readiness_degradation",
            "distinguish_running_from_ready",
            "choose_restart_or_rollback",
        }),
    ),
    ChaosExperiment(
        name="pod_kill_one",
        description="Delete a single live pod; kubelet recreates it almost immediately.",
        weight=4.0,
        severity=SEVERITY_LOW,
        # A well-behaved Mesh should NOT fire on a single transient
        # pod churn. An empty expectation set means "any trigger here
        # counts as a false positive in the scorer".
        expected_decisions=frozenset(),
        cooldown_seconds=30,
        tags=frozenset({"false_positive_probe"}),
        capability_axes=frozenset({
            "suppress_transient_pod_churn",
            "avoid_false_positive_remediation",
        }),
    ),
    ChaosExperiment(
        name="pod_kill_all",
        description="Delete every pod of the deployment; readyReplicas hits zero.",
        weight=1.5,
        severity=SEVERITY_HIGH,
        expected_decisions=frozenset({"restart_deployment", "rollback_deployment", "escalate"}),
        cooldown_seconds=90,
        capability_axes=frozenset({
            "detect_zero_ready_replicas",
            "separate_transient_from_service_outage",
            "choose_restart_or_rollback",
        }),
        observation_delay_seconds=0.0,
    ),
    ChaosExperiment(
        name="memory_pressure",
        description="Memory limit dropped to 2Mi; container OOMKills on first allocation.",
        weight=1.0,
        severity=SEVERITY_HIGH,
        expected_decisions=frozenset({"restart_deployment", "rollback_deployment"}),
        cooldown_seconds=120,
        capability_axes=frozenset({
            "detect_oom_kill",
            "infer_resource_pressure",
            "choose_restart_or_rollback",
        }),
    ),
    ChaosExperiment(
        name="scale_to_zero",
        description="Deployment scaled to replicas=0; no crashes but zero available backends.",
        weight=0.8,
        severity=SEVERITY_HIGH,
        # Mesh could legitimately escalate (a healthy deployment at
        # replicas=0 is usually a bug) or no_action (someone might
        # have intended the scale-down). Both acceptable.
        expected_decisions=frozenset({"escalate", "restart_deployment", "no_action"}),
        cooldown_seconds=120,
        capability_axes=frozenset({
            "detect_intentional_zero_replicas",
            "avoid_over_remediation",
            "escalate_ambiguous_operator_intent",
        }),
    ),
    ChaosExperiment(
        name="config_drift",
        description="Pod template gains an unexpected label; deployment rolls forward silently.",
        weight=0.5,
        severity=SEVERITY_MEDIUM,
        # Config drift is the subtlest signal — Mesh may not have any
        # visible symptom to act on. no_trigger or no_action are both
        # defensible. If Mesh escalates, that's also fine (a human
        # should look at the drift).
        expected_decisions=frozenset({"escalate", "no_action"}),
        cooldown_seconds=180,
        tags=frozenset({"subtle_fault"}),
        capability_axes=frozenset({
            "detect_configuration_drift",
            "handle_weak_signal",
            "escalate_ambiguous_operator_intent",
        }),
    ),
)


CAPABILITY_AXES: frozenset[str] = frozenset(
    axis for experiment in DEFAULT_PORTFOLIO for axis in experiment.capability_axes
)


def select_by_name(name: str, portfolio: tuple[ChaosExperiment, ...] = DEFAULT_PORTFOLIO) -> ChaosExperiment:
    """Look up an experiment by name. Raises KeyError if not found.

    Used by the scheduler's hash-based stable replay mode (running the
    same session twice with the same seed produces the same sequence)
    and by unit tests that want to assert on a specific primitive's
    metadata.
    """
    for experiment in portfolio:
        if experiment.name == name:
            return experiment
    raise KeyError(f"no experiment named {name!r} in portfolio")


__all__ = [
    "ChaosExperiment",
    "CAPABILITY_AXES",
    "DEFAULT_PORTFOLIO",
    "SEVERITY_HIGH",
    "SEVERITY_LOW",
    "SEVERITY_MEDIUM",
    "SEVERITY_SEVERE",
    "select_by_name",
]
