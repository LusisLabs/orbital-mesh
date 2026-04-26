"""Simulation driver — feeds faulted signals through Mesh.

# What this does

For each fault in the catalog (or repeatedly when ``--cron`` mode is on):
1. Generate a ``reth_node`` signal: healthy baseline + fault mutator
2. Push it through ``MeshRuntimeEngine.run_sync`` in-process
3. Capture decision_type, hypothesis ranking, observer verdict, latencies
4. Score against the fault's expected_outcomes — including observer-
   specific quality signals (did the LLM promote to escalate when the
   fault is unsafe, did the LLM cite evidence by path)
5. Append to a ``RunResult`` list

The driver does *not* spin up the HTTP server. We use ``run_sync`` so
each iteration is fully deterministic and there's no race between push
and poll. Real production runs go through ``control_plane.py`` which
has the same wiring; the difference is just the transport.

# Why we measure observer quality, not just decision accuracy

The user's stated focus is AI reasoning. The deterministic engine is
already covered by unit tests; the interesting question is whether the
LLM observer reads the evidence pack and ranked hypotheses, identifies
the right cause, and emits a verdict that's grounded in evidence. So
we surface:

* Did the observer promote to escalate when the fault's only acceptable
  outcome was escalate? (precision-on-promotion)
* Did the observer's reason field cite at least one structured evidence
  path like ``execution.peer_count=0``? (groundedness)
* What was prompt-cache hit rate on Anthropic? (cost / latency win)

# Cron mode vs sweep mode

* **sweep** (default): run every fault in the catalog once, in order.
  Best for "did the LLM handle the catalog correctly today?".
* **cron**: pick faults randomly with a configurable inter-fault delay
  for a configurable total duration. Best for "did the LLM stay sane
  under sustained noise over time?".
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass, field

from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime import RuntimeConfig

from simulation import baseline, fault_catalog
from simulation.fault_catalog import CATALOG, Fault


# Heuristic: an observer reason "cites evidence" if it includes at least
# one path-like reference into the pack — e.g. ``execution.peer_count=0``,
# ``rpc.error_rate=0.12``, ``consensus.engine_api_reachable=false``. We
# don't grade the model's reasoning quality directly; we just check it
# is talking about specific fields rather than vibes.
_EVIDENCE_PATH_RE = re.compile(
    r"\b(execution|consensus|storage|rpc|logs|node)\.[a-z_]+\s*[=:<>]"
)


_PROMOTION_VERDICTS = frozenset({"escalate", "reject_unsafe", "request_more_evidence"})


_LOG = logging.getLogger("mesh.simulation.driver")


@dataclass
class RunResult:
    """Outcome of one simulated fault injection.

    Field grouping (in order):
    1. Identity — fault_id, category, description, expected_outcomes
    2. Mesh's deterministic outcome — decision_type, autonomy_tier, confidence
    3. Hypothesis engine output — primary_hypothesis, ranked count, top_id/cause
    4. Observer (LLM) output — verdict, reason, concerns, confidence,
       latency, prompt-cache token counts
    5. Scoring — matched_expectation, observer_promoted_when_expected,
       observer_cited_evidence
    6. Errors / signatures
    """

    fault_id: str
    category: str
    description: str
    expected_outcomes: tuple[str, ...]
    actual_decision_type: str | None
    actual_autonomy_tier: str | None
    decision_confidence: float | None
    primary_hypothesis: str | None
    ranked_hypothesis_count: int
    triggered: bool
    matched_expectation: bool
    duration_ms: float
    top_hypothesis_id: str | None = None
    top_hypothesis_cause: str | None = None
    observer_verdict: str | None = None
    observer_reason: str | None = None
    observer_concerns: list[str] = field(default_factory=list)
    observer_confidence: float | None = None
    observer_latency_ms: float | None = None
    observer_error: str | None = None
    observer_promoted: bool = False
    observer_cited_evidence: bool = False
    observer_promoted_when_expected: bool | None = None
    error: str | None = None
    error_signatures: list[str] = field(default_factory=list)


def _build_engine() -> MeshRuntimeEngine:
    """Construct the runtime engine from the current process env. The
    observer kicks in automatically if ``MESH_OBSERVER_ENABLED=true``.
    """
    config = RuntimeConfig.from_env()
    return MeshRuntimeEngine(config=config)


def _score(fault: Fault, decision_type: str | None, triggered: bool) -> bool:
    """Did Mesh's outcome fall inside the fault's acceptable set?

    A non-triggered run (signal didn't pass thresholds) maps to
    ``no_action`` for scoring purposes, since the closed-loop intent is
    "leave it alone."
    """
    effective = decision_type if triggered else "no_action"
    return effective in fault.expected_outcomes


def run_one(engine: MeshRuntimeEngine, fault: Fault) -> RunResult:
    """Inject one fault, push it through Mesh, return the scored result."""
    state = fault_catalog.apply_fault(fault, baseline.healthy_state())
    baseline.stamp_signal(state)

    start = time.monotonic()
    try:
        outcome = engine.run_sync(state, scenario_name=f"sim_{fault.fault_id}")
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000.0
        _LOG.exception("simulation run failed for %s", fault.fault_id)
        return RunResult(
            fault_id=fault.fault_id,
            category=fault.category,
            description=fault.description,
            expected_outcomes=fault.expected_outcomes,
            actual_decision_type=None,
            actual_autonomy_tier=None,
            decision_confidence=None,
            primary_hypothesis=None,
            ranked_hypothesis_count=0,
            triggered=False,
            matched_expectation="no_action" in fault.expected_outcomes,
            duration_ms=duration_ms,
            error=str(exc),
        )
    duration_ms = (time.monotonic() - start) * 1000.0

    triggered = outcome.get("trigger") is not None
    decision = outcome.get("decision") or {}
    reasoning = (decision.get("reasoning") or {}) if isinstance(decision, dict) else {}
    observer = reasoning.get("observer_verdict") or {}
    if not isinstance(observer, dict):
        observer = {}

    ranked = reasoning.get("ranked_hypotheses") or []
    top_hypothesis = ranked[0] if ranked else None

    error_signatures: list[str] = []
    trigger = outcome.get("trigger")
    if isinstance(trigger, dict):
        error_signatures = list(
            (trigger.get("related_context") or {}).get("error_signatures", [])
        )

    decision_type = decision.get("decision_type") if isinstance(decision, dict) else None
    matched = _score(fault, decision_type, triggered)

    # Observer-quality scoring. These are observer-only metrics: when
    # the observer didn't run (disabled, errored, no trigger fired)
    # they're left as None or False so the report can distinguish "did
    # not run" from "ran and failed".
    verdict = observer.get("verdict") or None
    observer_reason = observer.get("reason") or ""
    observer_promoted = (
        verdict in _PROMOTION_VERDICTS
        and not observer.get("error")
    )
    observer_cited_evidence = bool(
        observer_reason and _EVIDENCE_PATH_RE.search(observer_reason)
    )
    # "Promoted when expected" is interesting only when the fault demands
    # escalation — the catalog's expected_outcomes is exactly ("escalate",).
    expected_only_escalate = fault.expected_outcomes == ("escalate",)
    if verdict is None or observer.get("error"):
        promoted_when_expected: bool | None = None
    elif expected_only_escalate:
        promoted_when_expected = observer_promoted
    else:
        promoted_when_expected = None  # not applicable — multiple acceptable outcomes

    return RunResult(
        fault_id=fault.fault_id,
        category=fault.category,
        description=fault.description,
        expected_outcomes=fault.expected_outcomes,
        actual_decision_type=decision_type,
        actual_autonomy_tier=decision.get("autonomy_tier") if isinstance(decision, dict) else None,
        decision_confidence=decision.get("confidence") if isinstance(decision, dict) else None,
        primary_hypothesis=reasoning.get("primary_hypothesis"),
        top_hypothesis_id=(top_hypothesis or {}).get("hypothesis_id") if isinstance(top_hypothesis, dict) else None,
        top_hypothesis_cause=(top_hypothesis or {}).get("candidate_cause") if isinstance(top_hypothesis, dict) else None,
        ranked_hypothesis_count=len(ranked),
        triggered=triggered,
        matched_expectation=matched,
        duration_ms=duration_ms,
        observer_verdict=verdict,
        observer_reason=observer_reason or None,
        observer_concerns=list(observer.get("concerns") or []),
        observer_confidence=observer.get("confidence"),
        observer_latency_ms=observer.get("latency_ms"),
        observer_error=observer.get("error"),
        observer_promoted=observer_promoted,
        observer_cited_evidence=observer_cited_evidence,
        observer_promoted_when_expected=promoted_when_expected,
        error_signatures=error_signatures,
    )


def run_sweep(engine: MeshRuntimeEngine | None = None) -> list[RunResult]:
    """Run every fault in the catalog exactly once."""
    engine = engine or _build_engine()
    results: list[RunResult] = []
    for fault in CATALOG:
        results.append(run_one(engine, fault))
    return results


def run_cron(
    *,
    duration_seconds: float,
    interval_seconds: float,
    seed: int = 42,
    engine: MeshRuntimeEngine | None = None,
) -> list[RunResult]:
    """Run faults at random intervals for the configured duration.

    Each iteration picks a fault uniformly at random, injects it, and
    sleeps ``interval_seconds`` (with a small jitter) before the next.
    The whole loop bails out once wall time exceeds ``duration_seconds``.

    For test-friendliness the seed is deterministic. Pass ``seed=None``
    via the CLI for nondeterministic runs.
    """
    engine = engine or _build_engine()
    rng = random.Random(seed)
    results: list[RunResult] = []
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        fault = rng.choice(CATALOG)
        results.append(run_one(engine, fault))
        # Inject jitter: ±20% of interval. Avoids lockstep with any
        # downstream rate-limiter that's sensitive to round numbers.
        sleep_for = interval_seconds * (0.8 + 0.4 * rng.random())
        if time.monotonic() + sleep_for >= deadline:
            break
        time.sleep(sleep_for)
    return results


def observer_active() -> bool:
    """Is the LLM observer wired up via env vars right now?"""
    return os.getenv("MESH_OBSERVER_ENABLED", "").lower() in ("1", "true", "yes")
