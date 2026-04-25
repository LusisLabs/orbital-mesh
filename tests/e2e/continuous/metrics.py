"""Per-experiment records and session-level aggregate metrics.

# Two scales of data

* **Per-experiment** (:class:`ExperimentResult`) — one row per chaos
  injection + Mesh pipeline invocation. Captures timings, Mesh's
  decision, whether the decision matched the expected family, and
  any failures. Rows are what the session report enumerates.

* **Per-session** (:class:`SessionAggregates`) — summary statistics
  over all experiment rows: detection rate, correct-decision rate,
  latency percentiles, pipeline availability. These are what the
  hypothesis is actually checked against.

# Hypothesis scoring

The session defines a :class:`Hypothesis` (typically via the driver
script) and the report compares each predicted metric against the
observed aggregate. A hypothesis passes iff every prediction holds.
A single breached prediction fails the session, even if the rest
succeeded — that matches the chaos-engineering intent ("we predicted
X; did X hold?") better than a weighted pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Hypothesis:
    """Predictions made at the start of a chaos session.

    Each threshold is a lower bound (e.g. ``min_detection_rate=0.95``)
    or an upper bound (``max_decision_p95_latency_seconds=10``). The
    report compares observed aggregates against these; mismatches
    populate ``Hypothesis.breaches`` in the verdict dict.

    Fields align with :class:`SessionAggregates` so adding a new
    metric to the aggregates requires adding a matching threshold
    here (and updating the report scorer).
    """

    # "For the session, Mesh will fire a trigger for at least this
    # fraction of injections that should produce a trigger." Probes
    # tagged ``false_positive_probe`` are excluded from the denominator.
    min_detection_rate: float = 0.9

    # "For triggered experiments, Mesh's decision type will be in the
    # expected_decisions set at least this fraction of the time."
    min_correct_decision_rate: float = 0.85

    # "For ``false_positive_probe`` experiments, Mesh will emit a
    # trigger at most this fraction of the time."
    max_false_positive_rate: float = 0.1

    # "At least this fraction of steady-state probes pass across the
    # whole session."
    min_probe_pass_rate: float = 0.9

    # "P95 latency of Mesh's decision stage stays under this bound."
    max_decision_p95_latency_seconds: float = 10.0

    # "Mesh's pipeline never raises out of the scheduler into the
    # session runner — availability is 100%." Expressed as a rate so
    # the scorer can use the same "observed >= predicted" form as the
    # other thresholds.
    min_pipeline_availability: float = 1.0


@dataclass
class ExperimentResult:
    """Record of one chaos experiment within a session.

    ``pass_`` is the per-experiment verdict: injection succeeded,
    Mesh responded in an expected way (or correctly declined on a
    false-positive probe), and recovery completed. Summed over a
    session these drive the aggregates.
    """

    experiment_name: str
    target_deployment: str
    namespace: str
    severity: str
    tags: tuple[str, ...]

    # Monotonic seconds-since-session-start for every phase.
    scheduled_at: float
    injected_at: float
    mesh_pipeline_started_at: float | None
    mesh_pipeline_completed_at: float | None
    reverted_at: float
    recovered_at: float | None

    # What Mesh did. Trigger may be absent if the signal was ruled out
    # in the trigger stage — that's a valid Mesh response for the
    # false-positive probes, so we don't require it.
    trigger_fired: bool
    decision_type: str | None
    decision_confidence: float | None
    decision_autonomy_tier: str | None

    # What the portfolio predicted.
    expected_decisions: frozenset[str]

    # Did the experiment pass the scoring rules? (See ``score_experiment``
    # in this module.) Populated by the scorer after all the timestamp
    # and decision fields are filled in.
    pass_: bool = False
    failure_reason: str | None = None

    # Anything else worth keeping — signal IDs, exception stacks on
    # pipeline failure, revert errors, etc.
    notes: list[str] = field(default_factory=list)

    @property
    def decision_latency_seconds(self) -> float | None:
        """Seconds from injection to Mesh's decision completion.

        Returns None if the pipeline never completed (crashed or
        timed out). The aggregator skips None values from its
        percentile math — a pipeline crash is its own metric.
        """
        if self.mesh_pipeline_started_at is None or self.mesh_pipeline_completed_at is None:
            return None
        return self.mesh_pipeline_completed_at - self.injected_at

    @property
    def recovery_latency_seconds(self) -> float | None:
        if self.recovered_at is None:
            return None
        return self.recovered_at - self.reverted_at


@dataclass
class SessionAggregates:
    """Session-level summary statistics.

    Computed from a list of :class:`ExperimentResult` by
    :func:`aggregate`. Kept as a dataclass (not a dict) so the
    report's scorer has a typed contract against which to check
    the :class:`Hypothesis`.
    """

    experiments_total: int
    experiments_passed: int
    pipeline_crashes: int

    # Detection metrics — denominator excludes false_positive probes.
    detection_rate: float
    correct_decision_rate: float
    false_positive_rate: float

    decision_latency_p50_seconds: float | None
    decision_latency_p95_seconds: float | None

    probes_total: int
    probes_passed: int
    probe_pass_rate: float

    pipeline_availability: float

    @property
    def pass_rate(self) -> float:
        if self.experiments_total == 0:
            return 0.0
        return self.experiments_passed / self.experiments_total


def score_experiment(result: ExperimentResult, trigger_fired: bool) -> tuple[bool, str | None]:
    """Apply the scoring rules to a single experiment.

    Returns ``(pass_, failure_reason)``. Called by the session runner
    after the pipeline has completed; the runner writes the result
    back onto the :class:`ExperimentResult`.

    Rules:

    1. If the experiment is a ``false_positive_probe``:
       * A fired trigger is a failure ("Mesh reacted to a transient
         blip") unless the decision is ``no_action``.
       * No trigger is a pass.
    2. If ``no_action`` is in ``expected_decisions``, a no-trigger
       outcome is semantically equivalent to "fired and decided
       no_action". Both mean "Mesh correctly concluded nothing is
       wrong." ``config_drift`` and ``scale_to_zero`` fall into this
       category — subtle faults where declining to act is a valid
       response.
    3. Otherwise, a fired trigger with ``decision_type`` in
       ``expected_decisions`` is a pass.
    4. No trigger on a non-probe experiment that doesn't expect
       ``no_action`` is a failure ("Mesh missed the fault"), unless
       the expected set is explicitly empty.
    5. A trigger with a decision outside the expected set is a
       failure ("wrong remediation").
    6. A pipeline crash (``mesh_pipeline_completed_at is None`` and
       ``mesh_pipeline_started_at is not None``) is always a failure.
    """
    # Rule 6 first — a crash masks everything else.
    if result.mesh_pipeline_started_at is not None and result.mesh_pipeline_completed_at is None:
        return False, "mesh pipeline crashed"

    is_false_positive_probe = "false_positive_probe" in result.tags

    if is_false_positive_probe:
        if not trigger_fired:
            return True, None
        if result.decision_type == "no_action":
            return True, None
        return False, (
            f"false-positive probe triggered with decision_type={result.decision_type!r}"
        )

    # Rule 2: ``no_action`` in the expected set treats no-trigger as
    # equivalent to firing and deciding no_action. The motivating case
    # is ``config_drift`` — the drift often produces no visible
    # symptom, so both outcomes ("Mesh didn't see anything" and "Mesh
    # saw it and decided it's benign") are valid operator intent.
    no_action_acceptable = "no_action" in result.expected_decisions

    if not trigger_fired:
        if no_action_acceptable:
            return True, None
        return False, "expected a trigger but Mesh did not fire one"

    if not result.expected_decisions:
        # An empty expectation on a non-probe is a portfolio config
        # error, but the right thing to do is pass: we can't say the
        # operator's intent was violated when the operator didn't
        # declare one.
        return True, None

    if result.decision_type in result.expected_decisions:
        return True, None
    return False, (
        f"decision_type={result.decision_type!r} not in expected={sorted(result.expected_decisions)!r}"
    )


def aggregate(
    experiments: list[ExperimentResult],
    probes_total: int,
    probes_passed: int,
) -> SessionAggregates:
    """Compute :class:`SessionAggregates` from a session's records.

    Kept as a pure function so the report can re-aggregate from
    persisted JSON without re-running the session. ``probes_*`` come
    from the steady-state history; ``experiments`` is the full list
    of :class:`ExperimentResult`.
    """
    total = len(experiments)
    passed = sum(1 for e in experiments if e.pass_)
    pipeline_crashes = sum(
        1 for e in experiments
        if e.mesh_pipeline_started_at is not None and e.mesh_pipeline_completed_at is None
    )

    # Detection denominator excludes false-positive probes — on those
    # the correct behavior is to NOT fire, so counting them in
    # detection would lower the rate spuriously.
    detection_rows = [e for e in experiments if "false_positive_probe" not in e.tags]
    detection_fires = sum(1 for e in detection_rows if e.trigger_fired)
    detection_rate = (detection_fires / len(detection_rows)) if detection_rows else 0.0

    correct_rows = [e for e in detection_rows if e.trigger_fired and e.expected_decisions]
    correct_hits = sum(
        1 for e in correct_rows if e.decision_type in e.expected_decisions
    )
    correct_decision_rate = (correct_hits / len(correct_rows)) if correct_rows else 0.0

    probe_rows = [e for e in experiments if "false_positive_probe" in e.tags]
    false_positive_hits = sum(1 for e in probe_rows if e.trigger_fired and e.decision_type != "no_action")
    false_positive_rate = (false_positive_hits / len(probe_rows)) if probe_rows else 0.0

    latencies = [e.decision_latency_seconds for e in experiments if e.decision_latency_seconds is not None]
    latencies.sort()
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)

    probe_pass_rate = (probes_passed / probes_total) if probes_total else 0.0

    # Pipeline availability: fraction of experiments where Mesh's
    # pipeline started AND completed (regardless of outcome). A
    # started-but-never-completed row counts against availability.
    pipeline_attempts = sum(1 for e in experiments if e.mesh_pipeline_started_at is not None)
    pipeline_completions = sum(1 for e in experiments if e.mesh_pipeline_completed_at is not None)
    pipeline_availability = (
        pipeline_completions / pipeline_attempts
    ) if pipeline_attempts else 1.0

    return SessionAggregates(
        experiments_total=total,
        experiments_passed=passed,
        pipeline_crashes=pipeline_crashes,
        detection_rate=round(detection_rate, 4),
        correct_decision_rate=round(correct_decision_rate, 4),
        false_positive_rate=round(false_positive_rate, 4),
        decision_latency_p50_seconds=p50,
        decision_latency_p95_seconds=p95,
        probes_total=probes_total,
        probes_passed=probes_passed,
        probe_pass_rate=round(probe_pass_rate, 4),
        pipeline_availability=round(pipeline_availability, 4),
    )


def evaluate_hypothesis(
    hypothesis: Hypothesis,
    aggregates: SessionAggregates,
) -> dict[str, Any]:
    """Compare observations against the hypothesis.

    Returns a dict with:

    - ``passed``: bool, True iff every threshold held.
    - ``breaches``: list of (metric, predicted, observed) triples
      for thresholds that were missed.
    - ``metrics``: side-by-side predicted vs observed for the report.
    """
    breaches: list[tuple[str, Any, Any, str]] = []

    def check_min(name: str, predicted: float, observed: float | None, op: str = ">=") -> None:
        if observed is None:
            breaches.append((name, predicted, None, "observed=None"))
            return
        if op == ">=" and observed < predicted:
            breaches.append((name, predicted, observed, "below threshold"))
        elif op == "<=" and observed > predicted:
            breaches.append((name, predicted, observed, "above threshold"))

    check_min("detection_rate", hypothesis.min_detection_rate, aggregates.detection_rate)
    check_min("correct_decision_rate", hypothesis.min_correct_decision_rate, aggregates.correct_decision_rate)
    check_min("false_positive_rate", hypothesis.max_false_positive_rate, aggregates.false_positive_rate, op="<=")
    check_min("probe_pass_rate", hypothesis.min_probe_pass_rate, aggregates.probe_pass_rate)
    check_min(
        "decision_latency_p95_seconds",
        hypothesis.max_decision_p95_latency_seconds,
        aggregates.decision_latency_p95_seconds,
        op="<=",
    )
    check_min("pipeline_availability", hypothesis.min_pipeline_availability, aggregates.pipeline_availability)

    return {
        "passed": len(breaches) == 0,
        "breaches": [
            {"metric": m, "predicted": p, "observed": o, "reason": r} for (m, p, o, r) in breaches
        ],
        "metrics": {
            "detection_rate": {
                "predicted_min": hypothesis.min_detection_rate,
                "observed": aggregates.detection_rate,
            },
            "correct_decision_rate": {
                "predicted_min": hypothesis.min_correct_decision_rate,
                "observed": aggregates.correct_decision_rate,
            },
            "false_positive_rate": {
                "predicted_max": hypothesis.max_false_positive_rate,
                "observed": aggregates.false_positive_rate,
            },
            "probe_pass_rate": {
                "predicted_min": hypothesis.min_probe_pass_rate,
                "observed": aggregates.probe_pass_rate,
            },
            "decision_latency_p95_seconds": {
                "predicted_max": hypothesis.max_decision_p95_latency_seconds,
                "observed": aggregates.decision_latency_p95_seconds,
            },
            "pipeline_availability": {
                "predicted_min": hypothesis.min_pipeline_availability,
                "observed": aggregates.pipeline_availability,
            },
        },
    }


def _percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile. Returns None for empty input.

    We use nearest-rank (not linear interpolation) because small-N
    sessions (< 30 experiments) give better signal with the former
    — interpolating between two very different values produces a
    misleadingly smooth P95 when you have three data points.
    """
    if not values:
        return None
    n = len(values)
    if n == 1:
        return values[0]
    index = min(n - 1, max(0, int(round(p * (n - 1)))))
    return round(values[index], 3)


__all__ = [
    "ExperimentResult",
    "Hypothesis",
    "SessionAggregates",
    "aggregate",
    "evaluate_hypothesis",
    "score_experiment",
]
