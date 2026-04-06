# Storage And Messaging Design

## Purpose

This document maps the closed-loop platform scaffold to durable storage and inter-service messaging boundaries.

## Design Principles

- append-only records for facts, mutable records for current operational state
- event-driven transitions between long-running loop stages
- synchronous calls only for short validation and adapter interactions
- world-model reads should be queryable without mutating the underlying evidence history

## Storage Layers

### 1. Raw Signal Stream

Purpose:

- hold incoming telemetry and external events before normalization

Examples:

- metrics samples
- deploy events
- feature-flag changes
- incident webhooks
- support or business signals

Characteristics:

- append-only
- short retention acceptable after normalization
- partition by source and time

### 2. Normalized Event Stream

Purpose:

- hold source-agnostic signal envelopes emitted by `services/ingest`

Produced by:

- `services/ingest`

Consumed by:

- `services/trigger`
- `services/feedback` for post-action correlation

Characteristics:

- append-only
- replayable for trigger tuning and backfills
- includes normalized scope keys for dedupe and aggregation

### 3. Loop Event Store

Purpose:

- hold the durable record of each loop object as it changes state

Record families:

- `TriggerCreated`
- `DiagnosisCreated`
- `PlanCreated`
- `PlanEvaluated`
- `StepStarted`
- `StepCompleted`
- `StepRolledBack`
- `FeedbackRecorded`
- `LoopEscalated`

Characteristics:

- append-only
- source of truth for audit and reconstruction
- referenced by all higher-level dashboards and retrospectives

### 4. Operational State Store

Purpose:

- represent the current active state of each loop instance

Examples:

- active trigger status
- current plan state
- current step pointer
- latest checkpoint result
- retry counters
- escalation owner

Characteristics:

- mutable
- optimized for low-latency reads and updates
- rebuilt from the event store if needed

### 5. World Model Store

Purpose:

- hold reusable operational knowledge rather than per-loop transient state

Contents:

- service topology and dependency graph
- historical incident patterns
- prior remediation effectiveness
- protected account and protected scope metadata
- actuator success priors
- diagnosis confidence priors

Characteristics:

- mixed read/write workload
- versioned updates are preferred for learned priors
- can be backed by more than one store over time

### 6. Metrics And Verification Store

Purpose:

- store the time-series data used for trigger detection and post-action verification

Examples:

- latency
- error rate
- queue depth
- saturation
- business health metrics

Characteristics:

- append-only
- queryable by time window and scope
- feeds triggering and feedback verification

## Append-Only Vs Mutable

Append-only data:

- raw signals
- normalized events
- loop event store records
- audit records
- historical verification metrics

Mutable data:

- active loop state
- checkpoint status
- current suppression windows
- current policy snapshots

Versioned-but-logical-mutable data:

- world-model priors
- service topology snapshots
- protected-scope metadata

## Messaging Boundaries

### Event-Driven Boundaries

Use async event boundaries for:

- `ingest -> trigger`
- `trigger -> diagnosis`
- `diagnosis -> planner`
- `planner -> evaluation`
- `orchestrator -> feedback`
- any retrospective or model-improvement writes

Why:

- these stages may take different amounts of time
- they benefit from retries, replay, and independent scaling
- they produce durable artifacts that should survive process restarts

### Synchronous Boundaries

Use synchronous boundaries for:

- evaluation calling policy engines
- orchestrator calling actuator adapters
- orchestrator checking current loop state before starting a step
- feedback querying recent metrics windows

Why:

- these are short-lived validations or side-effecting calls
- they need immediate success/failure results

## Recommended Message Shapes

Each event message should carry:

- object type
- object id
- parent ids such as `trigger_id` or `plan_id`
- schema version
- event timestamp
- minimal summary fields for routing
- pointer or embedded payload for the full contract object

## First Implementation Recommendation

For the first build, use one logical event bus with named topics or channels:

- `raw-signals`
- `normalized-events`
- `triggers`
- `diagnoses`
- `plans`
- `evaluations`
- `execution-events`
- `feedback-events`

This can be implemented as a modular single-process system first, but the topic boundaries should remain explicit so the architecture can scale out later.
