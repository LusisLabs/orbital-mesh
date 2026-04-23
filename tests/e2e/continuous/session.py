"""Continuous chaos-session runner.

# What this does

Runs a chaos-engineering session against a live kind cluster:

1. Takes a baseline steady-state probe.
2. In a loop until the session duration expires:
   a. Ask the scheduler for the next experiment + target.
   b. Run it through the existing :class:`tests.e2e.harness.Harness`
      (one experiment per harness invocation means cleanup + chaos
      revert happen after every one).
   c. Score the result against the portfolio's expected decision.
   d. Every N experiments, take another steady-state probe.
   e. If the circuit breaker trips, halt immediately.
3. Takes a final steady-state probe.
4. Aggregates metrics and evaluates the hypothesis.
5. Writes the session report.

# Why "one harness per experiment" and not "one harness for the session"

The existing :class:`Harness` class assumes one scenario per
instance. Its ``run_scenario`` method starts + stops chaos + clears
state at the boundaries. Reusing those boundaries for each experiment
in the session means:

* Chaos never leaks between experiments (the injector's revert fires
  after every one).
* A stuck or slow individual experiment can't poison the later ones.
* The existing scenario-level report generation is reused — each
  experiment produces its own report alongside the session report,
  which is useful when diagnosing a single bad experiment in a
  50-long session.

Trade-off: harness construction isn't free (~100ms for the Injector
+ tempdir setup). At session length measured in minutes, that's
negligible; at sub-minute sessions we'd notice. Current design wins.

# What the harness construction doesn't repeat

Cluster creation, workload apply, and kubectl keepalive are
session-level concerns — the driver script handles them once at
startup and once at teardown. The session runner assumes a ready
cluster on entry and leaves the chaos reverted on exit.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Any

from tests.e2e.chaos.portfolio import ChaosExperiment, DEFAULT_PORTFOLIO
from tests.e2e.chaos.scheduler import ExperimentScheduler, PriorExperiment
from tests.e2e.chaos.steady_state import CircuitBreaker, ProbeResult, SteadyStateProbe
from tests.e2e.continuous.metrics import (
    ExperimentResult,
    Hypothesis,
    SessionAggregates,
    aggregate,
    evaluate_hypothesis,
    score_experiment,
)
from tests.e2e.harness import Harness


_LOG = logging.getLogger("mesh.e2e.session")


@dataclass
class SessionResult:
    """Everything the session produced, ready for the report.

    Split from :class:`~tests.e2e.continuous.report.SessionReport` so
    the runner can return a pure-data payload and the report rendering
    stays a pure function of it.
    """

    session_id: str
    started_at: float  # wall-clock seconds
    completed_at: float
    duration_seconds: float
    verdict: str  # pass | fail | halted_by_circuit_breaker
    halt_reason: str | None
    hypothesis: Hypothesis
    hypothesis_result: dict[str, Any]
    experiments: list[ExperimentResult]
    probes: list[ProbeResult]
    aggregates: SessionAggregates


class ContinuousChaosSession:
    """Orchestrator for a single chaos session.

    Construct once per session; the runner holds everything it needs
    (scheduler, probe, breaker, target list). Call :meth:`run` to
    block until the session completes. Returns a :class:`SessionResult`
    with the full record.
    """

    def __init__(
        self,
        kube_context: str,
        namespace: str,
        targets: tuple[str, ...],
        duration_seconds: float,
        hypothesis: Hypothesis,
        portfolio: tuple[ChaosExperiment, ...] = DEFAULT_PORTFOLIO,
        *,
        probe_every_n: int = 5,
        min_loop_sleep_seconds: float = 3.0,
        seed: int | None = None,
        log_file: str | None = None,
    ):
        self.kube_context = kube_context
        self.namespace = namespace
        self.targets = targets
        self.duration_seconds = duration_seconds
        self.hypothesis = hypothesis
        self.portfolio = portfolio
        self.probe_every_n = max(1, int(probe_every_n))
        self.min_loop_sleep_seconds = min_loop_sleep_seconds
        self.log_file = log_file

        # The probe uses the first target as the "baseline" — the one
        # we compare against to verify the cluster is still healthy.
        # In a multi-target portfolio this is necessarily imperfect:
        # when the current experiment is torturing ``targets[0]``, the
        # probe will see a degraded baseline and the circuit breaker
        # may trip. Mitigation: put a less-tortured deployment first,
        # or use single-target sessions. The trade-off is noted in the
        # README.
        self._probe = SteadyStateProbe(
            kube_context=kube_context,
            namespace=namespace,
            baseline_deployment=targets[0],
        )
        self._breaker = CircuitBreaker(
            max_consecutive_failures=2,
            max_pipeline_latency_seconds=float(
                hypothesis.max_decision_p95_latency_seconds * 2
            ),  # more lenient than the hypothesis threshold — the probe
               # latency can spike briefly without meaning Mesh is broken.
        )
        self._scheduler = ExperimentScheduler(
            portfolio=portfolio,
            targets=targets,
            seed=seed,
        )

    # ---------------------------------------------------------------- run

    def run(self) -> SessionResult:
        """Execute the full session. Blocks until completion or halt."""
        wall_start = time.time()
        mono_start = time.monotonic()
        _LOG.info(
            "session: starting duration=%ss targets=%s portfolio=%d",
            self.duration_seconds, self.targets, len(self.portfolio),
        )
        experiments: list[ExperimentResult] = []
        probes: list[ProbeResult] = []
        history: list[PriorExperiment] = []

        # --- baseline probe -----------------------------------------
        # If the baseline is already broken, abort before we inject
        # anything. A session that starts from a bad state is not a
        # chaos experiment; it's a flaky test.
        baseline = self._probe.sample("baseline", mono_start)
        probes.append(baseline)
        if not baseline.passed:
            return self._finalize(
                wall_start, mono_start,
                verdict="halted_by_circuit_breaker",
                halt_reason=f"baseline probe failed: {'; '.join(baseline.notes)}",
                experiments=experiments, probes=probes,
            )

        # --- main loop -----------------------------------------------
        deadline = mono_start + self.duration_seconds
        while time.monotonic() < deadline:
            now = time.monotonic() - mono_start

            pick = self._scheduler.pick(history, now)
            if pick is None:
                # All primitives in cooldown; idle briefly and try again.
                # Short sleep — we don't want to oversleep past the
                # deadline either.
                time.sleep(self.min_loop_sleep_seconds)
                continue
            experiment, target = pick

            # Execute the experiment.
            result = self._run_experiment(experiment, target, mono_start)
            experiments.append(result)
            history.append(
                PriorExperiment(
                    experiment_name=experiment.name,
                    deployment=target,
                    severity=experiment.severity,
                    completed_at=time.monotonic() - mono_start,
                )
            )
            # Terminal heartbeat — one line per experiment so the
            # operator watching the session sees progress without
            # having to tail the log file. The log file still has full
            # per-stage detail; this is the "am I still alive" signal.
            elapsed = time.monotonic() - mono_start
            remaining = max(0.0, self.duration_seconds - elapsed)
            passed_count = sum(1 for e in experiments if e.pass_)
            print(
                f"[chaos] #{len(experiments):02d} {result.experiment_name:<18} "
                f"on {result.target_deployment:<12} "
                f"{'PASS' if result.pass_ else 'FAIL'}  "
                f"decision={result.decision_type or '—':<22} "
                f"({passed_count}/{len(experiments)} passed, "
                f"{int(remaining // 60)}m{int(remaining % 60):02d}s left)",
                file=sys.stderr,
                flush=True,
            )

            # Probe at the configured cadence.
            if len(experiments) % self.probe_every_n == 0:
                probe = self._probe.sample(f"after_{len(experiments)}", mono_start)
                probes.append(probe)
                self._breaker.record_result(probe)
                print(
                    f"[chaos] probe: cluster={_ok(probe.cluster_reachable)} "
                    f"baseline={_ok(probe.baseline_ready)} mesh={_ok(probe.mesh_pipeline_ok)} "
                    f"latency={probe.mesh_pipeline_latency_seconds or 0:.2f}s",
                    file=sys.stderr,
                    flush=True,
                )
                if self._breaker.should_halt():
                    return self._finalize(
                        wall_start, mono_start,
                        verdict="halted_by_circuit_breaker",
                        halt_reason=self._breaker.halt_reason(),
                        experiments=experiments, probes=probes,
                    )

        # --- final probe --------------------------------------------
        probes.append(self._probe.sample("final", mono_start))
        return self._finalize(
            wall_start, mono_start,
            verdict="pass",  # overridden inside _finalize based on hypothesis
            halt_reason=None,
            experiments=experiments, probes=probes,
        )

    # ---------------------------------------------------------------- single experiment

    def _run_experiment(
        self,
        experiment: ChaosExperiment,
        target: str,
        mono_start: float,
    ) -> ExperimentResult:
        """Execute one chaos experiment and score the outcome.

        Runs on a fresh :class:`Harness` so chaos revert + state
        cleanup happen exactly once per experiment. Converts the
        scenario-level artifacts (trigger, decision) into an
        :class:`ExperimentResult` with the session's monotonic clock.
        """
        scheduled_at = time.monotonic() - mono_start
        _LOG.info("experiment[%s on %s]: starting", experiment.name, target)

        harness = Harness(
            kube_context=self.kube_context,
            namespace=self.namespace,
            # No log_file here; the session-level log is captured by
            # the driver and this experiment's events are logged into
            # the same stream via the mesh.* logger hierarchy.
        )

        scenario_fn = _make_scenario_fn(experiment, target)
        scenario_run = harness.run_scenario(
            scenario_name=f"{experiment.name}:{target}",
            scenario_fn=scenario_fn,
        )

        # Pull out the fields we care about for the session metrics.
        trigger = scenario_run.trigger
        decision = scenario_run.decision
        trigger_fired = trigger is not None
        decision_type = decision.get("decision_type") if decision else None
        decision_conf = float(decision.get("confidence", 0.0)) if decision else None
        decision_tier = decision.get("autonomy_tier") if decision else None

        # The harness's :class:`ScenarioRun` carries monotonic
        # timestamps only for its own lifecycle; we re-anchor against
        # the session's mono_start so everything in the report shares
        # one time axis.
        now_rel = time.monotonic() - mono_start
        injection = scenario_run.chaos[0] if scenario_run.chaos else None

        result = ExperimentResult(
            experiment_name=experiment.name,
            target_deployment=target,
            namespace=self.namespace,
            severity=experiment.severity,
            tags=tuple(experiment.tags),
            scheduled_at=scheduled_at,
            injected_at=(injection.injected_at - mono_start) if injection else scheduled_at,
            mesh_pipeline_started_at=scheduled_at if trigger_fired or decision else None,
            mesh_pipeline_completed_at=now_rel if decision else None,
            reverted_at=now_rel,
            recovered_at=now_rel if scenario_run.verdict == "pass" else None,
            trigger_fired=trigger_fired,
            decision_type=decision_type,
            decision_confidence=decision_conf,
            decision_autonomy_tier=decision_tier,
            expected_decisions=experiment.expected_decisions,
        )

        passed, reason = score_experiment(result, trigger_fired)
        result.pass_ = passed
        result.failure_reason = reason
        if scenario_run.failure_reason:
            result.notes.append(f"scenario: {scenario_run.failure_reason}")
        _LOG.info(
            "experiment[%s on %s]: %s decision=%s reason=%s",
            experiment.name, target,
            "PASS" if passed else "FAIL",
            decision_type, reason,
        )
        return result

    # ---------------------------------------------------------------- finalize

    def _finalize(
        self,
        wall_start: float,
        mono_start: float,
        verdict: str,
        halt_reason: str | None,
        experiments: list[ExperimentResult],
        probes: list[ProbeResult],
    ) -> SessionResult:
        """Aggregate metrics, evaluate hypothesis, assemble SessionResult.

        Called in two places (end of normal run, circuit-breaker halt)
        so every exit path produces a fully-formed result.
        """
        duration = time.monotonic() - mono_start
        wall_end = time.time()

        probe_pass = sum(1 for p in probes if p.passed)
        aggregates = aggregate(experiments, probes_total=len(probes), probes_passed=probe_pass)
        hypothesis_result = evaluate_hypothesis(self.hypothesis, aggregates)

        # If the session ran to completion but the hypothesis was
        # breached, flip verdict to fail. Circuit-breaker halts stay
        # as-is — the operator should see that halt reason first.
        if verdict == "pass" and not hypothesis_result["passed"]:
            verdict = "fail"

        return SessionResult(
            session_id=f"session_{int(wall_start)}",
            started_at=wall_start,
            completed_at=wall_end,
            duration_seconds=duration,
            verdict=verdict,
            halt_reason=halt_reason,
            hypothesis=self.hypothesis,
            hypothesis_result=hypothesis_result,
            experiments=experiments,
            probes=probes,
            aggregates=aggregates,
        )


# ---------------------------------------------------------------- scenario bridge


def _make_scenario_fn(experiment: ChaosExperiment, target: str):
    """Build a scenario callable the Harness can run.

    The harness's ``run_scenario`` expects ``fn(harness) -> dict``.
    Each experiment needs slightly different boilerplate around the
    same core pattern (inject → pipeline → assert + recover), so we
    assemble it here rather than shipping N scenario modules.

    Returning a closure keeps experiment identity implicit in the
    callable's state, so the harness doesn't need to know which
    experiment it's running. The scenario function just calls
    ``harness.inject(experiment.name, target)`` — the injector's
    ``inject_<name>`` method resolves to the right primitive.
    """

    def scenario(harness: Harness) -> dict:
        # Baseline snapshot so the harness report shows before/after.
        before = harness.snapshot_cluster(target, label="before_chaos")

        harness.inject(experiment.name, target)

        pipeline_result = harness.run_mesh_pipeline(target)

        # Always revert — the harness would do it in finally, but
        # explicit here ensures recovery wait runs against the
        # reverted state rather than racing cleanup.
        harness.injector.revert(target, harness.namespace)
        harness.record_step("chaos:reverted")

        # Wait for recovery, but don't fail the scenario on a
        # timeout — the session's circuit breaker handles chronic
        # recovery failures at the session level.
        try:
            harness.wait_for_deployment_ready(target, timeout_seconds=120)
        except AssertionError as exc:
            harness.record_step("recovery:timed_out", status="failed", reason=str(exc))
            raise
        after = harness.snapshot_cluster(target, label="after_recovery")
        harness.record_step("recovery:verified")

        return {
            "signal": pipeline_result.get("normalized_event"),
            "trigger": pipeline_result.get("trigger"),
            "decision": pipeline_result.get("decision"),
            "evaluation": pipeline_result.get("evaluation"),
            "execution": pipeline_result.get("execution"),
            "feedback": pipeline_result.get("feedback"),
            "cluster_snapshots": {
                "before_chaos": before,
                "after_recovery": after,
            },
        }

    return scenario


def _ok(flag: bool) -> str:
    """Compact status pill for the terminal heartbeat."""
    return "ok" if flag else "FAIL"


__all__ = ["ContinuousChaosSession", "SessionResult"]
