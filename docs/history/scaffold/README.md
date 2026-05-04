# Closed Loop Platform Scaffold

Historical note: this scaffold captures the earlier generic multi-stage concept and is no longer the
active runtime contract. The implemented MVP is the bounded feature-flag loop documented in
`first-closed-loop-contract.md`.

## Purpose

This scaffold turns the closed-loop design in `first-closed-loop-contract.md` into a concrete implementation layout without locking the repository into a specific language runtime yet.

The scaffold is organized around stable loop stages:

- ingest and normalize signals
- detect triggers
- diagnose likely causes
- build remediation plans
- evaluate policy and execution readiness
- orchestrate bounded execution
- verify outcomes and write learning back

## Proposed Repository Shape

```text
scaffold/
  README.md
  storage-and-messaging.md
  first-vertical-slice.md
  policy-and-test-strategy.md
  contracts/
    schemas/
      trigger.schema.json
      diagnosis.schema.json
      remediation-plan.schema.json
      evaluation-result.schema.json
      execution-record.schema.json
      feedback-record.schema.json
  services/
    ingest/
    trigger/
    diagnosis/
    planner/
    evaluation/
    orchestrator/
    feedback/
    actuators/
  policies/
  prompts/
  fixtures/
```

## Module Boundaries

### `services/ingest`

Responsibilities:

- collect raw signals from telemetry, deploy systems, feature flags, incidents, and business systems
- validate source-specific payloads
- normalize them into a common event envelope
- publish normalized events downstream

Outputs:

- normalized signal events
- enrichment failures and dead-letter records

### `services/trigger`

Responsibilities:

- consume normalized events
- aggregate evidence over rolling windows
- detect threshold breaches or anomaly clusters
- emit deduplicated `Trigger` objects

Outputs:

- `Trigger`
- suppression and dedupe records

### `services/diagnosis`

Responsibilities:

- gather evidence for a trigger scope
- query world-model and incident history context
- rank hypotheses and candidate remediations
- emit `Diagnosis`

Outputs:

- `Diagnosis`
- evidence packs used for later audit

### `services/planner`

Responsibilities:

- convert `Diagnosis` into bounded single-step or multi-step `RemediationPlan` objects
- attach checkpoints, branch rules, rollback instructions, and stop conditions
- assign autonomy tier

Outputs:

- `RemediationPlan`

### `services/evaluation`

Responsibilities:

- run plan-level policy validation
- run step-level execution readiness checks
- apply prompt-quality and business-risk gates
- emit `EvaluationResult`

Outputs:

- `EvaluationResult`
- human-review recommendations

### `services/orchestrator`

Responsibilities:

- execute approved plans one step at a time
- call approved actuator adapters
- enforce checkpoint verification, rollback, and stop conditions
- emit `ExecutionRecord`

Outputs:

- `ExecutionRecord`
- incident and escalation events

### `services/feedback`

Responsibilities:

- collect post-action metrics and business outcomes
- determine recovery and plan effectiveness
- write world-model and prior updates
- emit `FeedbackRecord`

Outputs:

- `FeedbackRecord`
- learned priors and retrospective summaries

### `services/actuators`

Responsibilities:

- isolate side-effecting integrations behind explicit adapters
- expose only approved actions
- handle idempotency, retries, and adapter-level audit metadata

Initial actuator categories:

- feature flags
- traffic control
- config revert
- service restart
- incident creation

## Shared Supporting Directories

### `contracts/`

Stack-neutral object contracts used across all services. JSON Schema is the first shared format because it can be consumed from TypeScript, Python, or other runtimes.

### `policies/`

Declarative policy inputs for:

- allowed actuator categories
- autonomy tiers
- protected scopes
- rollback requirements
- stop conditions

### `prompts/`

Prompt assets for diagnosis, plan generation, evaluation, and retrospective analysis.

### `fixtures/`

Deterministic sample payloads and expected outputs for trigger, diagnosis, planning, evaluation, execution, and feedback tests.

## Runtime Boundary Recommendations

- Use event-driven boundaries between ingest, trigger, diagnosis, feedback, and long-running orchestration stages.
- Use synchronous boundaries only for short, request-response checks inside evaluation and actuator adapters.
- Keep the shared contract package versioned independently from any future runtime implementation.

## Initial Delivery Shape

The first code implementation should begin as a modular platform scaffold that preserves these boundaries even if deployed as a single process initially. That keeps local development simple while still matching the long-term closed-loop architecture.
