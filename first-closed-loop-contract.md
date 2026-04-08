# First Closed Loop Contract

## Purpose

This document defines the first end-to-end autonomous decision loop for the mesh intelligence MVP.

## Chosen MVP Loop

The first loop targets performance remediation for a newly exposed feature flag.

Why this loop first:

- it is driven by telemetry the system already expects to ingest
- it has a narrow and reversible action surface
- it produces measurable results within minutes
- it fits the existing Promptfoo quality-gate and Goose execution model

## Loop Goal

When a feature rollout causes a material regression in latency or errors for a specific service,
endpoint, or user segment, the system decides whether to:

- continue with no change
- reduce rollout percentage
- disable the feature flag
- escalate to human review

The MVP does not generate arbitrary remediation plans. It operates within a fixed, audited action
set.

## Contract Summary

### 1. Trigger Contract

Trigger objective:
Create a decision opportunity only when the system detects a statistically meaningful regression
tied to a feature flag exposure.

Required inputs:

- request telemetry with `timestamp`, `service`, `endpoint`, `latency_ms`, `status_code`
- feature flag exposure events with `flag_key`, `variant`, `rollout_pct`, `user_id` or `account_id`
- deployment metadata with `release_id`, `service`, `started_at`
- segment metadata with `environment`, `customer_tier`, `region`

Trigger conditions:

- a feature flag changed state or rollout percentage within the last 30 minutes
- the affected slice has at least `N >= 500` requests since the change
- one of these regressions is present against baseline:
  - `p95_latency_ms` worsens by `>= 25%`
  - `error_rate` worsens by `>= 1.5x`
  - `timeout_rate` crosses `>= 2%`
- the regression persists for at least 2 consecutive evaluation windows of 5 minutes
- no active suppression exists for the same `service + endpoint + flag_key`

Trigger output contract:

```json
{
  "trigger_id": "trg_01HRY...",
  "trigger_type": "feature_flag_performance_regression",
  "triggered_at": "2026-04-06T10:30:00Z",
  "environment": "production",
  "service": "api-gateway",
  "endpoint": "POST /search",
  "flag_key": "semantic_search_v2",
  "current_rollout_pct": 50,
  "comparison_window": {
    "baseline": "2026-04-06T09:30:00Z/2026-04-06T10:00:00Z",
    "observed": "2026-04-06T10:20:00Z/2026-04-06T10:30:00Z"
  },
  "segment": {
    "customer_tier": "enterprise",
    "region": "us-east-1"
  },
  "metrics": {
    "baseline_p95_latency_ms": 420,
    "observed_p95_latency_ms": 615,
    "baseline_error_rate": 0.012,
    "observed_error_rate": 0.026,
    "sample_size": 1840
  },
  "related_context": {
    "release_id": "rel_2026_04_06_01",
    "active_incidents": 0,
    "similar_prior_cases": 3
  }
}
```

Trigger rejection rules:

- traffic is below the minimum sample size
- the flag is already under rollback
- the incident is already open and owned by a human
- degradation is caused by a known upstream outage unrelated to the flag

### 2. Decision Contract

Decision objective:
Convert a validated trigger plus current world state into a single bounded remediation proposal.

Allowed decision types:

- `no_action`
- `reduce_rollout`
- `disable_flag`
- `escalate`

Autonomy tiers:

- `autonomous`: reduce rollout or disable flag in production when blast radius is limited to one
  flag and one service
- `approval_required`: any action affecting multiple services, premium tiers only, or repeated
  rollback within 24 hours
- `escalated`: insufficient evidence, conflicting signals, or high business impact

Decision invariants:

- exactly one decision per trigger
- exactly one primary action
- no free-form code changes in the MVP
- every decision must include explicit `expected_outcome`, `risk`, and `rollback_plan`
- every decision must be deterministic enough to audit after the fact

### 3. Evaluation Contract

Evaluation objective:
Block unsafe, low-confidence, or non-compliant decisions before execution.

Evaluation stages:

- `schema_validation`
- `policy_validation`
- `promptfoo_quality`
- `business_rules`
- `execution_readiness`

Pass criteria:

- schema valid
- confidence `>= 0.75`
- `risk.level != high`
- action is idempotent
- rollback parameters are present
- no blocking policy violation

Failure routing rules:

- send to `human_review` if confidence `< 0.75`
- send to `human_review` if `risk.level == high`
- reject directly if the action falls outside the allowed action set
- suppress duplicate evaluations for the same `trigger_id`

### 4. Execution Contract

Execution objective:
Execute only the approved bounded action and capture a verifiable result.

Allowed execution surface:

- feature flag provider API
- incident or ticketing API
- audit log sink

Never:

- modify source code
- change infrastructure config
- write to production databases directly
- execute arbitrary shell commands against production

Execution preconditions:

- evaluation result is `passed: true`
- action parameters match the evaluated payload exactly
- idempotency key is present
- audit record is created before the side effect

Failure rules:

- on transient API failure, retry up to 2 times within 60 seconds
- on repeated failure, open an incident and route to human review
- never partially execute more than one action
- if audit logging fails, do not execute

### 5. Feedback Contract

Feedback objective:
Measure whether the action improved the target metrics and whether the system should learn,
rollback, or escalate.

Observation windows:

- `T+10m`: immediate stabilization check
- `T+30m`: primary success decision
- `T+24h`: learning-only retrospective for recurrence patterns

Success rules at `T+30m`:

- `p95_latency_ms` is within 10% of baseline
- `error_rate` returns to within 20% of baseline
- no new severe incident was opened for the same scope

Rollback and escalation rules:

- if metrics do not improve by `T+10m`, escalate for human review
- if disabling the flag causes a worse business issue, restore the prior rollout and escalate
- if the same flag triggers `>= 3` regressions in 7 days, mark it for human-owned remediation
  before further rollout

Learning writes after feedback:

- feature flag risk score
- service and endpoint incident history
- prior-success priors for similar rollback decisions
- Promptfoo and evaluation fixtures

## Implementation Boundary

The first closed loop is complete only if it supports all of the following:

- emits a structured trigger from telemetry
- generates one bounded decision in a stable JSON shape
- evaluates that decision through a blocking quality gate
- executes through a restricted actuator surface
- measures post-action impact and writes the result back into the world model

Anything beyond this, including code remediation, infrastructure mutation, or open-ended planning,
stays out of the MVP.
