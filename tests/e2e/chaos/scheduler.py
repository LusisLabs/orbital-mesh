"""Experiment scheduler for continuous chaos sessions.

# The job

Pick the next experiment to run, honoring:

* **Weights** from the portfolio (some events are more common than others).
* **Cooldowns** per (experiment, deployment) pair — the same primitive
  shouldn't fire on the same target twice inside its cooldown window.
* **Severity pairing rules** — never two severe experiments back-to-back
  without a cooldown in between.
* **Deterministic replay** — seeded PRNG so a failed session can be
  rerun with the exact same sequence to aid diagnosis.

Keeping the scheduler pure (takes history in, returns next choice)
means it's trivially testable. The session runner supplies the history
as a list of prior :class:`~tests.e2e.continuous.metrics.ExperimentResult`
and a monotonic "now" — the scheduler returns either a next
experiment or None ("nothing is eligible, the session should idle a
few seconds before asking again").

# Why not just random.choices with a weights vector?

Weighted random picks from the portfolio doesn't honor cooldowns or
severity pairing. A naive implementation re-runs crash_loop five
times in a row on the same deployment because it has the highest
weight. We need filtering + weighted sampling from the *eligible*
subset, not the whole portfolio.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Sequence

from tests.e2e.chaos.portfolio import (
    ChaosExperiment,
    DEFAULT_PORTFOLIO,
    SEVERITY_HIGH,
    SEVERITY_SEVERE,
)


_LOG = logging.getLogger("mesh.e2e.scheduler")


# After a high/severe experiment, insert a minimum cooldown before the
# next high/severe experiment fires on *any* target. This prevents
# the session from landing two destructive experiments in a window
# where the first one's recovery is still in progress.
_SEVERE_PAIR_COOLDOWN_SECONDS = 60


@dataclass
class PriorExperiment:
    """Slim record the scheduler reads to enforce cooldowns.

    The session runner builds this from full
    :class:`~tests.e2e.continuous.metrics.ExperimentResult` records —
    the scheduler only needs timing + identity fields, so keeping the
    scheduler input narrow means unit tests don't have to fabricate
    an entire ExperimentResult.
    """

    experiment_name: str
    deployment: str
    severity: str
    completed_at: float  # monotonic seconds since session start


class ExperimentScheduler:
    """Pick the next chaos experiment.

    Stateless across calls — pass the full prior-experiment list on
    every invocation. Cheap enough (N usually < 50 per session) that
    a dict of indexed lookups isn't worth the complexity.
    """

    def __init__(
        self,
        portfolio: Sequence[ChaosExperiment] = DEFAULT_PORTFOLIO,
        targets: Sequence[str] = ("search-api",),
        seed: int | None = None,
    ):
        if not portfolio:
            raise ValueError("scheduler needs a non-empty portfolio")
        if not targets:
            raise ValueError("scheduler needs at least one deployment target")
        self.portfolio = tuple(portfolio)
        self.targets = tuple(targets)
        # A seeded Random instance keeps the scheduler deterministic
        # without touching the module-level random state (which would
        # interfere with other tests running in the same process).
        self._rng = random.Random(seed)

    def pick(
        self,
        history: Sequence[PriorExperiment],
        now: float,
    ) -> tuple[ChaosExperiment, str] | None:
        """Return (experiment, target_deployment) or None.

        None means "no eligible experiment right now" — the session
        runner should sleep briefly (few seconds) before trying again.
        This is common in the final minute of a session when cooldowns
        back up.
        """
        # Build a list of eligible (experiment, target) pairs.
        eligible = self._build_eligible(history, now)
        if not eligible:
            _LOG.debug("scheduler: no eligible (experiment, target) at t=%.1f", now)
            return None

        # Weighted pick over the eligible pairs. We flatten (experiment,
        # target) into a single list and weight each entry by the
        # experiment's portfolio weight — a two-target cluster naturally
        # gives the experiment twice as many chances to fire, which is
        # the right behavior (more targets = more opportunities).
        weights = [pair[0].weight for pair in eligible]
        index = self._weighted_index(weights)
        chosen = eligible[index]
        _LOG.info(
            "scheduler: picked %s on %s (weight=%.1f, severity=%s)",
            chosen[0].name, chosen[1], chosen[0].weight, chosen[0].severity,
        )
        return chosen

    # ---------------------------------------------------------------- internals

    def _build_eligible(
        self,
        history: Sequence[PriorExperiment],
        now: float,
    ) -> list[tuple[ChaosExperiment, str]]:
        """Filter (experiment, target) pairs to only those that pass all gates.

        Three filters, in cheap-to-expensive order:

        1. Primitive cooldown — has this primitive run on this target
           recently enough that we should wait?
        2. Severe pairing — did a high/severe experiment finish in the
           last ``_SEVERE_PAIR_COOLDOWN_SECONDS``? If so, block the
           next high/severe pick.
        3. Precondition — if the experiment declares a callable
           precondition, call it. (None of the current portfolio does,
           but the hook is there for additions.)
        """
        last_high_or_severe = self._last_high_completion(history)

        eligible: list[tuple[ChaosExperiment, str]] = []
        for experiment in self.portfolio:
            # (2) Severe pair gate — global, not per-target.
            if experiment.severity in (SEVERITY_HIGH, SEVERITY_SEVERE):
                if (
                    last_high_or_severe is not None
                    and now - last_high_or_severe < _SEVERE_PAIR_COOLDOWN_SECONDS
                ):
                    continue

            for target in self.targets:
                # (1) Per-(experiment, target) cooldown.
                if self._in_cooldown(experiment, target, history, now):
                    continue
                # (3) Precondition callable, if any.
                if experiment.precondition is not None:
                    try:
                        if not experiment.precondition():
                            continue
                    except Exception:  # noqa: BLE001 — callback must not crash the scheduler
                        continue
                eligible.append((experiment, target))
        return eligible

    @staticmethod
    def _in_cooldown(
        experiment: ChaosExperiment,
        target: str,
        history: Sequence[PriorExperiment],
        now: float,
    ) -> bool:
        """True if the experiment last ran on ``target`` within its cooldown."""
        for prior in reversed(history):
            if prior.experiment_name == experiment.name and prior.deployment == target:
                elapsed = now - prior.completed_at
                return elapsed < experiment.cooldown_seconds
        return False

    @staticmethod
    def _last_high_completion(history: Sequence[PriorExperiment]) -> float | None:
        """Timestamp of the most recent high/severe experiment, or None."""
        for prior in reversed(history):
            if prior.severity in (SEVERITY_HIGH, SEVERITY_SEVERE):
                return prior.completed_at
        return None

    def _weighted_index(self, weights: list[float]) -> int:
        """Pick an index proportional to weights using the seeded RNG.

        Avoids ``random.choices`` so the seeded Random instance stays
        fully in control. ``random.choices`` internally uses
        ``random._inst`` which we don't want polluted.
        """
        total = sum(weights)
        if total <= 0:
            return self._rng.randrange(len(weights))
        r = self._rng.uniform(0, total)
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                return i
        return len(weights) - 1  # float-precision fallback


__all__ = ["ExperimentScheduler", "PriorExperiment"]
