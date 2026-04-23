"""Unit tests for the continuous chaos session components.

These tests cover the pure-logic pieces — portfolio lookup, scheduler
eligibility + weighted pick, circuit breaker state machine, experiment
scoring, metric aggregation, hypothesis evaluation. They do **not**
spin up a kind cluster; that's what ``scripts/run_chaos_session.sh``
is for.

The session runner itself is not unit-tested here because its hot
path is the kubectl+harness integration we exercise with the real
cluster. The pieces the runner composes (scheduler, scorer,
aggregator) are fully covered, so a runner bug becomes either a
composition issue (caught by running it) or a kubectl issue (caught
by the e2e smoke run).
"""

from __future__ import annotations

import unittest

from tests.e2e.chaos.portfolio import (
    DEFAULT_PORTFOLIO,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    ChaosExperiment,
    select_by_name,
)
from tests.e2e.chaos.scheduler import ExperimentScheduler, PriorExperiment
from tests.e2e.chaos.steady_state import CircuitBreaker, ProbeResult
from tests.e2e.continuous.metrics import (
    ExperimentResult,
    Hypothesis,
    aggregate,
    evaluate_hypothesis,
    score_experiment,
)


# ---------------------------------------------------------------- portfolio


class PortfolioTests(unittest.TestCase):
    def test_default_portfolio_covers_all_expected_primitives(self) -> None:
        """The scheduler and session runner assume these names exist —
        if someone renames a primitive without updating the portfolio
        the session would just stop firing that injection silently."""
        names = {e.name for e in DEFAULT_PORTFOLIO}
        required = {
            "crash_loop", "bad_image", "readiness_failure",
            "pod_kill_one", "pod_kill_all", "memory_pressure",
            "scale_to_zero", "config_drift",
        }
        self.assertTrue(required.issubset(names), f"missing: {required - names}")

    def test_pod_kill_one_is_a_false_positive_probe(self) -> None:
        """Pod churn on a single pod is noise, not a fault. Mesh is
        expected NOT to fire. The tag drives scoring behavior; losing
        it would turn every session into a detection-rate failure."""
        experiment = select_by_name("pod_kill_one")
        self.assertIn("false_positive_probe", experiment.tags)
        self.assertEqual(experiment.expected_decisions, frozenset())

    def test_select_by_name_raises_on_missing(self) -> None:
        with self.assertRaises(KeyError):
            select_by_name("nonexistent", DEFAULT_PORTFOLIO)


# ---------------------------------------------------------------- scheduler


class SchedulerEligibilityTests(unittest.TestCase):
    """Cooldowns and severity pairing — the invariants that prevent
    a flaky primitive or a severe-double-tap from dominating a session."""

    def _single_experiment_portfolio(self) -> tuple[ChaosExperiment, ...]:
        return (
            ChaosExperiment(
                name="crash_loop",
                description="",
                weight=1.0,
                severity=SEVERITY_HIGH,
                expected_decisions=frozenset({"restart_deployment"}),
                cooldown_seconds=60,
            ),
        )

    def test_empty_history_allows_any_experiment(self) -> None:
        sched = ExperimentScheduler(
            portfolio=self._single_experiment_portfolio(),
            targets=("svc",),
            seed=0,
        )
        pick = sched.pick(history=[], now=0.0)
        self.assertIsNotNone(pick)
        self.assertEqual(pick[0].name, "crash_loop")

    def test_cooldown_blocks_same_primitive_on_same_target(self) -> None:
        sched = ExperimentScheduler(
            portfolio=self._single_experiment_portfolio(),
            targets=("svc",),
            seed=0,
        )
        history = [PriorExperiment("crash_loop", "svc", SEVERITY_HIGH, completed_at=10.0)]
        # Still inside the 60s cooldown — no eligible pick.
        self.assertIsNone(sched.pick(history, now=30.0))
        # Past the cooldown — eligible again.
        self.assertIsNotNone(sched.pick(history, now=75.0))

    def test_cooldown_is_per_target(self) -> None:
        """A cooldown on ``svc-a`` should not block firing on ``svc-b``.

        Using a low-severity primitive here isolates the per-target
        cooldown from the severe-pairing rule, which is intentionally
        global (it would block both targets) and has its own test below.
        """
        portfolio = (
            ChaosExperiment(
                name="pod_kill_one",
                description="",
                weight=1.0,
                severity=SEVERITY_LOW,
                expected_decisions=frozenset(),
                cooldown_seconds=60,
            ),
        )
        sched = ExperimentScheduler(portfolio=portfolio, targets=("svc-a", "svc-b"), seed=0)
        history = [PriorExperiment("pod_kill_one", "svc-a", SEVERITY_LOW, completed_at=10.0)]
        pick = sched.pick(history, now=30.0)
        self.assertIsNotNone(pick)
        self.assertEqual(pick[1], "svc-b")

    def test_severe_pairing_cooldown_blocks_consecutive_high(self) -> None:
        """Two high/severe experiments back-to-back must be refused
        for ``_SEVERE_PAIR_COOLDOWN_SECONDS`` regardless of which
        primitives they are."""
        portfolio = (
            ChaosExperiment("high_a", "", 1.0, SEVERITY_HIGH, frozenset({"restart_deployment"}), cooldown_seconds=5),
            ChaosExperiment("high_b", "", 1.0, SEVERITY_HIGH, frozenset({"restart_deployment"}), cooldown_seconds=5),
        )
        sched = ExperimentScheduler(portfolio=portfolio, targets=("svc",), seed=0)
        history = [PriorExperiment("high_a", "svc", SEVERITY_HIGH, completed_at=0.0)]
        # Primitive cooldown passed (5s) but severe pair cooldown hasn't.
        self.assertIsNone(sched.pick(history, now=20.0))
        # Past severe pair cooldown (60s default) — eligible.
        self.assertIsNotNone(sched.pick(history, now=65.0))

    def test_low_severity_is_exempt_from_severe_pairing(self) -> None:
        """A low-severity probe (like pod_kill_one) should fire even
        if a high experiment just completed — it's not destructive."""
        portfolio = (
            ChaosExperiment("high_a", "", 1.0, SEVERITY_HIGH, frozenset({"restart_deployment"}), cooldown_seconds=5),
            ChaosExperiment("low_a", "", 1.0, SEVERITY_LOW, frozenset(), cooldown_seconds=5),
        )
        sched = ExperimentScheduler(portfolio=portfolio, targets=("svc",), seed=0)
        history = [PriorExperiment("high_a", "svc", SEVERITY_HIGH, completed_at=0.0)]
        pick = sched.pick(history, now=10.0)
        self.assertIsNotNone(pick)
        self.assertEqual(pick[0].severity, SEVERITY_LOW)


class SchedulerWeightingTests(unittest.TestCase):
    """Weighted picks respect the distribution across many trials.

    We don't assert on exact counts (PRNG) — we assert the weighted
    primitive wins most of the time, which is the only contract the
    scheduler actually owes the session runner."""

    def test_heavy_weight_wins_majority_over_many_picks(self) -> None:
        portfolio = (
            ChaosExperiment("heavy", "", 9.0, SEVERITY_LOW, frozenset(), cooldown_seconds=0),
            ChaosExperiment("light", "", 1.0, SEVERITY_LOW, frozenset(), cooldown_seconds=0),
        )
        sched = ExperimentScheduler(portfolio=portfolio, targets=("svc",), seed=42)
        counts = {"heavy": 0, "light": 0}
        for _ in range(1000):
            pick = sched.pick(history=[], now=0.0)
            counts[pick[0].name] += 1
        # 9:1 expected; allow a loose 7:1 floor so the test doesn't
        # fail on PRNG variance.
        self.assertGreater(counts["heavy"], counts["light"] * 7)


# ---------------------------------------------------------------- circuit breaker


class CircuitBreakerTests(unittest.TestCase):
    def test_single_failure_does_not_trip(self) -> None:
        breaker = CircuitBreaker(max_consecutive_failures=2)
        breaker.record_result(ProbeResult(0, "t", False, True, True, None, ["cluster down"]))
        self.assertFalse(breaker.should_halt())

    def test_two_consecutive_failures_trip(self) -> None:
        breaker = CircuitBreaker(max_consecutive_failures=2)
        for i in range(2):
            breaker.record_result(ProbeResult(i, "t", False, True, True, None, ["cluster down"]))
        self.assertTrue(breaker.should_halt())
        self.assertIn("consecutive probe failures", breaker.halt_reason() or "")

    def test_pass_between_failures_resets_counter(self) -> None:
        breaker = CircuitBreaker(max_consecutive_failures=2)
        breaker.record_result(ProbeResult(0, "t", False, True, True, None, ["x"]))
        breaker.record_result(ProbeResult(1, "t", True, True, True, 0.1, []))
        breaker.record_result(ProbeResult(2, "t", False, True, True, None, ["y"]))
        # Two failures total but non-consecutive — breaker is fine.
        self.assertFalse(breaker.should_halt())

    def test_single_slow_probe_trips_latency_bound(self) -> None:
        breaker = CircuitBreaker(max_consecutive_failures=2, max_pipeline_latency_seconds=1.0)
        breaker.record_result(ProbeResult(0, "t", True, True, False, 5.0, []))
        self.assertTrue(breaker.should_halt())
        self.assertIn("latency", breaker.halt_reason() or "")


# ---------------------------------------------------------------- scorer


class ExperimentScorerTests(unittest.TestCase):
    def _row(self, **kwargs) -> ExperimentResult:
        defaults = dict(
            experiment_name="x", target_deployment="svc", namespace="ns",
            severity=SEVERITY_HIGH, tags=(),
            scheduled_at=0.0, injected_at=1.0,
            mesh_pipeline_started_at=2.0, mesh_pipeline_completed_at=3.0,
            reverted_at=3.5, recovered_at=4.0,
            trigger_fired=True, decision_type="restart_deployment",
            decision_confidence=0.8, decision_autonomy_tier="autonomous",
            expected_decisions=frozenset({"restart_deployment"}),
        )
        defaults.update(kwargs)
        return ExperimentResult(**defaults)

    def test_expected_decision_passes(self) -> None:
        r = self._row()
        passed, reason = score_experiment(r, trigger_fired=True)
        self.assertTrue(passed)
        self.assertIsNone(reason)

    def test_wrong_decision_fails(self) -> None:
        r = self._row(decision_type="no_action")
        passed, reason = score_experiment(r, trigger_fired=True)
        self.assertFalse(passed)
        self.assertIn("not in expected", reason or "")

    def test_missing_trigger_on_regular_experiment_fails(self) -> None:
        r = self._row(trigger_fired=False, decision_type=None)
        passed, reason = score_experiment(r, trigger_fired=False)
        self.assertFalse(passed)
        self.assertIn("expected a trigger", reason or "")

    def test_false_positive_probe_no_trigger_passes(self) -> None:
        r = self._row(
            tags=("false_positive_probe",),
            trigger_fired=False, decision_type=None,
            expected_decisions=frozenset(),
        )
        passed, _ = score_experiment(r, trigger_fired=False)
        self.assertTrue(passed)

    def test_false_positive_probe_no_action_passes(self) -> None:
        """A trigger that resolves to no_action on a probe is still a
        pass — Mesh saw the pod churn, reasoned about it, and correctly
        decided not to act."""
        r = self._row(
            tags=("false_positive_probe",),
            trigger_fired=True, decision_type="no_action",
            expected_decisions=frozenset(),
        )
        passed, _ = score_experiment(r, trigger_fired=True)
        self.assertTrue(passed)

    def test_false_positive_probe_with_remediation_fails(self) -> None:
        r = self._row(
            tags=("false_positive_probe",),
            trigger_fired=True, decision_type="restart_deployment",
            expected_decisions=frozenset(),
        )
        passed, reason = score_experiment(r, trigger_fired=True)
        self.assertFalse(passed)
        self.assertIn("false-positive", reason or "")

    def test_pipeline_crash_always_fails(self) -> None:
        r = self._row(mesh_pipeline_completed_at=None)
        passed, reason = score_experiment(r, trigger_fired=True)
        self.assertFalse(passed)
        self.assertIn("crashed", reason or "")


# ---------------------------------------------------------------- aggregator


class AggregatorTests(unittest.TestCase):
    def _exp(self, pass_=True, tags=(), trigger=True, decision="restart_deployment", latency=(1.0, 2.0)):
        started, completed = latency
        return ExperimentResult(
            experiment_name="x", target_deployment="svc", namespace="ns",
            severity=SEVERITY_HIGH, tags=tuple(tags),
            scheduled_at=0.0, injected_at=started,
            mesh_pipeline_started_at=started if trigger or decision else None,
            mesh_pipeline_completed_at=completed if decision else None,
            reverted_at=completed or started, recovered_at=completed,
            trigger_fired=trigger, decision_type=decision,
            decision_confidence=0.8, decision_autonomy_tier="autonomous",
            expected_decisions=frozenset({"restart_deployment"}),
            pass_=pass_,
        )

    def test_detection_excludes_probes_from_denominator(self) -> None:
        experiments = [
            self._exp(tags=("false_positive_probe",), trigger=False, decision=None),
            self._exp(trigger=True, decision="restart_deployment"),
        ]
        agg = aggregate(experiments, probes_total=2, probes_passed=2)
        # 1 regular experiment fired / 1 regular experiment total = 1.0
        self.assertEqual(agg.detection_rate, 1.0)

    def test_pipeline_availability_counts_crashes(self) -> None:
        experiments = [
            self._exp(trigger=True, decision="restart_deployment"),
            # started but never completed — crash
            self._exp(latency=(1.0, None), trigger=True, decision=None),
        ]
        # Override the second experiment to have started but not completed.
        experiments[1].mesh_pipeline_started_at = 1.0
        experiments[1].mesh_pipeline_completed_at = None
        agg = aggregate(experiments, probes_total=2, probes_passed=2)
        # 1 of 2 pipeline attempts completed.
        self.assertEqual(agg.pipeline_availability, 0.5)
        self.assertEqual(agg.pipeline_crashes, 1)

    def test_false_positive_rate_only_counts_triggered_probes(self) -> None:
        experiments = [
            # Probe with trigger=True AND non-no_action decision → FP.
            self._exp(tags=("false_positive_probe",), trigger=True,
                      decision="restart_deployment"),
            # Probe with trigger=False → not a FP.
            self._exp(tags=("false_positive_probe",), trigger=False, decision=None),
            # Probe with trigger+no_action → not a FP.
            self._exp(tags=("false_positive_probe",), trigger=True,
                      decision="no_action"),
        ]
        agg = aggregate(experiments, probes_total=3, probes_passed=3)
        # 1 of 3 probes counted as FP.
        self.assertAlmostEqual(agg.false_positive_rate, 1 / 3, places=3)


class HypothesisEvaluationTests(unittest.TestCase):
    def test_all_thresholds_met_passes(self) -> None:
        agg = aggregate(
            [
                ExperimentResult(
                    "x", "svc", "ns", SEVERITY_HIGH, (),
                    0.0, 0.0, 0.0, 0.5, 0.5, 0.5,
                    True, "restart_deployment", 0.8, "autonomous",
                    frozenset({"restart_deployment"}),
                    pass_=True,
                )
            ],
            probes_total=5, probes_passed=5,
        )
        result = evaluate_hypothesis(Hypothesis(), agg)
        self.assertTrue(result["passed"])
        self.assertEqual(result["breaches"], [])

    def test_breached_threshold_is_reported(self) -> None:
        # Zero experiments → detection_rate=0.0, which breaches the
        # 0.9 default threshold.
        agg = aggregate([], probes_total=5, probes_passed=5)
        result = evaluate_hypothesis(Hypothesis(), agg)
        self.assertFalse(result["passed"])
        metrics = {b["metric"] for b in result["breaches"]}
        self.assertIn("detection_rate", metrics)


if __name__ == "__main__":
    unittest.main()
