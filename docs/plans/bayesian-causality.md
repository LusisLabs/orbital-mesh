# Plan: Replace hard-coded causality with learned Bayesian priors

## Problem

Today the decision layer asks the caller to supply `flag_causality_confidence`
as a field on the signal's `related_context`. The `DecisionService` then
branches on hard-coded thresholds (`<= 0.35 → no_action`, `>= 0.7 → upgrade to
reduce_rollout`) and nudges the final confidence by a fixed formula:

```python
# services/decision/service.py
if similar_prior_cases > 0:
    adjusted += min(similar_prior_cases, 3) * 0.01
if flag_causality_confidence is not None:
    adjusted += max(min(float(flag_causality_confidence) - 0.5, 0.2), -0.2) * 0.1
if len(trigger_signals) >= 2:
    adjusted += 0.01
```

Two structural problems:

1. **The caller supplies the very number we should be computing.** Whoever
   emits the signal has to already know how confident we should be that the
   flag caused the regression. That's not telemetry — it's a conclusion.
2. **Confidence never updates from outcomes.** Every run emits a
   `FeedbackRecord` at T+10m / T+30m that says whether the remediation worked.
   Nothing reads that record back into a prior. Mesh has a feedback loop on
   paper, not in code.

## Goal

Turn `flag_causality_confidence` into a **computed** quantity derived from:

- **Evidence fit** — how well the current signal matches patterns that
  historically correlated with flag-caused regressions
- **Learned priors** — Beta-distributed success rates per
  `(flag_key, decision_type)` pair, updated after every `FeedbackRecord`
- **Signal co-occurrence** — the statistical weight of each `trigger_signal`
  (`latency_regression`, `error_regression`, `timeout_regression`) based on its
  past predictive value

The output is a **posterior probability** that flipping this flag will improve
the metric, with a **calibrated confidence interval**. The decision service
consumes the posterior instead of a hard-coded constant.

This keeps the bounded action surface (we never generate new action types),
keeps the audit trail (every posterior update is an event), and keeps the
local-first story (pure Python + stdlib, no scikit-learn).

## Non-goals

- No deep models, no gradient descent, no training pipeline. We want
  closed-form Beta-Bernoulli updates so the state is auditable line-by-line.
- No cross-customer learning. Every mesh instance has its own priors.
- No causal inference in the pearl-graph sense. We correlate outcomes with
  signal shape; we do not prove causation.
- No replacement of the policy gates. Bayesian confidence flows **into**
  evaluation, it does not override protected-tier or rollback policies.

## The math, spelled out

### 1. Base rate per (flag, decision_type)

For every `(flag_key, decision_type)` pair we track a Beta distribution
`Beta(α, β)` representing the posterior over the success rate:

- `α` = 1 + count of feedback outcomes where `outcome == "successful"`
- `β` = 1 + count of feedback outcomes where `outcome ∈ {unsuccessful, rolled_back}`

Starting from `Beta(1, 1)` (uniform prior). After each `FeedbackRecord` arrives
we increment either `α` or `β` and persist. The mean is `α / (α + β)`, the
variance is known in closed form, and we can emit a 90% credible interval
directly from `scipy.stats.beta.ppf` — **except we don't want a scipy dep**, so
we ship a 60-line pure-Python beta quantile using the Wilson–Hilferty
approximation or a bisection method on the regularized incomplete beta.

### 2. Likelihood: `P(signal | flag caused regression)`

Each `trigger_signal` gets its own Beta posterior, but now conditioned on the
historical **outcome given the signal was present**. Concretely, for signal
`s` and decision `d`:

- `α_s,d` = 1 + count of runs where signal `s` was present **and** decision
  `d` succeeded
- `β_s,d` = 1 + count of runs where signal `s` was present **and** decision
  `d` failed

The likelihood ratio for signal `s` is `P(s | caused) / P(s | not caused)`,
estimated from the counters with Laplace smoothing.

### 3. Posterior combination

With multiple signals firing simultaneously (the common case:
`latency_regression + error_regression`), combine under a naive-Bayes
independence assumption:

```
log_posterior = log_prior + Σ_s log_likelihood_ratio(s)
posterior     = sigmoid(log_posterior)
```

This is cheap, order-independent, and empirically stable under sparse data.
The caller gets back both the point estimate and the credible interval from
the underlying Beta.

### 4. Decay

Priors without decay rot: an old flag that was bad a year ago but has since
been rewritten should not hold the new rollout hostage. Apply exponential
decay on every update:

```
α ← max(1, α * exp(-Δt / τ))
β ← max(1, β * exp(-Δt / τ))
```

where `τ` defaults to 30 days. Configurable via env.

## Architecture

### New module: `shared/mesh_runtime/priors.py`

```python
@dataclass
class BetaPrior:
    alpha: float = 1.0
    beta: float = 1.0
    updated_at: str | None = None

    @property
    def mean(self) -> float: ...
    def credible_interval(self, width: float = 0.9) -> tuple[float, float]: ...
    def update(self, successful: bool, now: str) -> "BetaPrior": ...

class PriorStore:
    """File-backed storage for (flag, decision) and (signal, decision) priors."""
    def get_flag_decision(self, flag_key: str, decision_type: str) -> BetaPrior: ...
    def get_signal_decision(self, signal: str, decision_type: str) -> BetaPrior: ...
    def record_outcome(
        self,
        flag_key: str,
        decision_type: str,
        signals: list[str],
        successful: bool,
        now: str,
    ) -> None: ...
    def posterior(
        self,
        flag_key: str,
        decision_type: str,
        signals: list[str],
    ) -> CausalityEstimate: ...

@dataclass
class CausalityEstimate:
    posterior: float              # point estimate in [0, 1]
    credible_interval: tuple[float, float]
    sample_size: int              # total α+β across priors touched
    source: str                   # "prior" | "posterior" | "sparse_fallback"
```

Persistence: append-only JSONL at
`.mesh-runtime-state/priors/events.jsonl` (every update, for Merkle-style
audit) plus a materialized view at `.mesh-runtime-state/priors/state.json`
that's rebuilt from events on boot. Materialized view uses `fcntl.flock` like
everything else. JSONL is the source of truth, JSON is a derived cache.

### Integration points

#### 1. `DecisionService.decide()`

Replace the caller-supplied read of `flag_causality_confidence` with a probe
to `PriorStore.posterior()`. Keep the caller-supplied value as an optional
override (so fixtures still work during migration):

```python
# services/decision/service.py
estimate = prior_store.posterior(
    flag_key=trigger.flag_key,
    decision_type=candidate_decision_type,
    signals=trigger_signals,
)
if estimate.source == "sparse_fallback":
    # too few observations — fall back to caller-supplied value if any
    flag_causality_confidence = trigger.related_context.get(
        "flag_causality_confidence", 0.5
    )
else:
    flag_causality_confidence = estimate.posterior
```

The existing if/elif ladder stays. What changes is that
`flag_causality_confidence` is now *real*, and `_adjust_confidence` gets
replaced with a calibrated blend:

```python
adjusted = estimate.posterior
adjusted += min(similar_prior_cases, 3) * 0.01  # historical match bonus kept
adjusted = max(estimate.credible_interval[0], min(adjusted, estimate.credible_interval[1]))
```

The `confidence` field on the Decision becomes the credible-interval-bounded
posterior — **defensible** in a way the hard-coded 0.82 never was.

#### 2. `FeedbackService.record()`

Extend `record()` to write back into the prior store after it persists the
`FeedbackRecord`:

```python
# services/feedback/service.py
feedback = ...  # existing computation
prior_store.record_outcome(
    flag_key=trigger.flag_key,
    decision_type=decision.decision_type,
    signals=trigger.related_context.get("trigger_signals", []),
    successful=(feedback.outcome == "successful"),
    now=feedback.recorded_at,
)
```

One log-line per outcome. Because the outcome is determined at T+30m, the
update trails the decision by 30 minutes. That's fine — it's how Beta-Bernoulli
learning works with delayed rewards.

#### 3. Merkle ledger

Add a new run-event type: `CAUSALITY_UPDATED`, emitted by the control plane
after the feedback write. Payload = the before/after `(α, β)` for every prior
touched + the resulting posterior. This keeps the audit story intact:
operators can replay the entire learning trajectory from the event log.

#### 4. HTTP API

- `GET /api/priors` — list all priors with current mean + credible interval
- `GET /api/priors/flag/:flag_key/:decision_type` — drilldown
- `POST /api/priors/reset` — admin-only, wipe priors (for staging or
  regression tests)
- Inspector tab `priors` in the web UI — table of flags, sparkline of
  posterior drift, sample size indicator

### What stays the same

- Policy gates (`autonomy`, `protected-scope`, `rollback`) are unchanged.
  Bayesian confidence feeds **input** to evaluation; it doesn't override
  rejections.
- The action surface is unchanged: still `no_action`, `reduce_rollout`,
  `disable_flag`, `escalate`, and the Kubernetes set.
- The run lifecycle is unchanged: the posterior updates happen inside
  `FeedbackService.record()`, which is already part of the pipeline.
- The confidence in the Decision contract is still a float in [0, 1]; we just
  compute it honestly now.

## Milestones

### M1 — Read path (no learning, read existing priors)

Files:
- `shared/mesh_runtime/priors.py` (new) — BetaPrior, PriorStore, pure-Python
  beta quantile, file layout
- `tests/test_priors.py` (new) — math correctness: known (α, β) → known mean
  and credible interval, decay math, update semantics
- `services/decision/service.py` — read from PriorStore when available; fall
  back to caller-supplied `flag_causality_confidence` otherwise
- Tests: existing `test_pipeline.py` continues to pass because sparse_fallback
  uses the caller's number

Deliverable: priors directory exists, decision service consults it, zero
behavior change for existing fixtures.

**Estimate: ~1.5 days. Risk: low.**

### M2 — Write path (learn from feedback)

Files:
- `services/feedback/service.py` — call `prior_store.record_outcome()` after
  persisting the feedback record
- `services/control_plane.py` — emit `CAUSALITY_UPDATED` run event
- `shared/mesh_runtime/run_events.py` — add the new event type
- `tests/test_learning_cycle.py` (new) — end-to-end: run 20 synthetic signals,
  assert posterior converges toward the seeded truth, assert credible
  interval tightens

Deliverable: run the same scenario 10 times with a reliable outcome, and the
11th run's decision has a provably higher confidence than the 1st.

**Estimate: ~2 days. Risk: medium — need careful test isolation because
priors are mutated in-place.**

### M3 — Signal likelihood ratios

Until now we've only updated flag-level priors. Add the per-signal likelihood
ratios and combine under naive-Bayes.

Files:
- `shared/mesh_runtime/priors.py` — add `posterior()` method that combines
  flag prior and signal likelihood ratios
- `tests/test_priors.py` — add tests for signal-level combining, especially
  the edge case where all signals are novel (sparse → uniform fallback)

**Estimate: ~1 day. Risk: low, math is simple.**

### M4 — Observability

Files:
- `control_plane_server.py` — three new routes under `/api/priors`
- `web/src/Inspector.tsx` — new "priors" tab
- `web/src/api.ts` + `web/src/types.ts` — typed client
- `shared/mesh_runtime/vault.py` — write a "Priors.md" note per flag for the
  Obsidian mirror

Deliverable: operator can open a run, click "priors", see exactly why mesh
chose this confidence and which historical runs contributed.

**Estimate: ~1.5 days. Risk: low, UI work.**

### M5 — Decay + admin controls

Files:
- `shared/mesh_runtime/priors.py` — exponential decay on update, configurable
  half-life
- `shared/mesh_runtime/config.py` — `MESH_PRIOR_HALFLIFE_DAYS` env (default 30)
- `control_plane_server.py` — `POST /api/priors/reset` (admin only, guarded by
  a config flag `MESH_PRIORS_ADMIN_ENABLED`)
- Tests: decay math, reset endpoint

**Estimate: ~1 day. Risk: low.**

## Total estimate

~7 working days for a full end-to-end Bayesian causality layer with UI,
tests, and audit coverage. Each milestone ships independently and the
existing pipeline keeps working throughout.

## Open questions

1. **Cold-start policy.** First run on a brand new flag with zero history —
   the posterior is `Beta(1, 1)` which means `mean = 0.5, CI = [0.05, 0.95]`.
   Do we (a) use 0.5 and let evaluation gate it, (b) require operator
   approval for the first N runs, or (c) seed priors from nearest-neighbor
   flags in the same service? Recommendation: start with (a), upgrade to
   (c) in M5 if the data supports it.

2. **Multi-tenant priors.** If mesh ever runs across multiple services with
   different regression patterns, do we namespace by `(service, flag_key)` or
   just `flag_key`? Recommendation: namespace by `(service, flag_key)`
   initially; collapse to `flag_key` only if cross-service correlation proves
   valuable.

3. **Decision type granularity.** `reduce_rollout` with target 10% behaves
   differently from `reduce_rollout` with target 50%. Do we learn separately?
   Recommendation: start granular (`(flag, decision_type, target_bucket)`),
   collapse buckets only if buckets stay sparse past M5.

4. **Integration with the new investigation layer.** If we eventually build
   the LLM-backed hypothesis generator (from the last conversation), the
   posterior becomes one of the features the LLM sees rather than the final
   answer. M5+ territory.

## Non-obvious risk

**The existing test suite will break subtly.** `test_pipeline.py` asserts
specific confidence values (0.88 for `disable_flag`). Once the confidence
becomes a posterior, those assertions need to become ranges. I'll migrate
tests in M1 to use `assertAlmostEqual` with a tolerance the Beta CI
guarantees.

## File summary

New:
- `shared/mesh_runtime/priors.py`
- `tests/test_priors.py`
- `tests/test_learning_cycle.py`
- `docs/plans/bayesian-causality.md` (this file)

Modified:
- `services/decision/service.py` — consume PriorStore
- `services/feedback/service.py` — write to PriorStore
- `services/control_plane.py` — emit `CAUSALITY_UPDATED` events
- `shared/mesh_runtime/run_events.py` — new event type
- `shared/mesh_runtime/config.py` — prior halflife
- `shared/mesh_runtime/__init__.py` — export PriorStore, CausalityEstimate
- `control_plane_server.py` — `/api/priors` routes
- `web/src/Inspector.tsx`, `api.ts`, `types.ts` — priors tab
- Several existing tests — convert confidence assertions to ranges
