# Policy And Test Strategy

## Purpose

This document defines the governance and fixture strategy needed before runtime code scaffolding begins.

## Policy Design Goals

- keep autonomy bounded and reviewable
- make unsafe actions impossible through configuration, not just convention
- separate policy decisions from planner logic
- make policy changes testable with fixtures and regression cases

## Policy Domains

### 1. Actuator Policy

Controls:

- which actuator categories are allowed
- which systems each category may target
- which actions require approval
- retry budgets and rollback requirements

Example questions this policy answers:

- may the platform reduce a feature rollout automatically?
- may it call traffic control for this service?
- may it execute a restart in production?

### 2. Scope Protection Policy

Controls:

- protected services
- protected customer tiers
- protected accounts or segments
- maintenance windows and freeze windows

This policy should force escalation when protected scope is touched.

### 3. Autonomy Tier Policy

Controls:

- when a plan may run autonomously
- when approval is required
- when immediate escalation is mandatory

Inputs:

- blast radius
- confidence
- customer impact
- actuator class
- prior failure patterns

### 4. Stop And Rollback Policy

Controls:

- required checkpoint cadence
- rollback requirements by step category
- max failed checkpoints before escalation
- drift conditions that require re-diagnosis

### 5. Feedback Learning Policy

Controls:

- what learning writes are allowed automatically
- when a diagnosis prior may be updated
- which retrospective events require human review before changing priors

## Policy File Strategy

When code scaffolding begins, policies should live in declarative files under `scaffold/policies/` and later move into a runtime-accessible policy package.

Recommended policy files:

- `actuators.policy.json`
- `protected-scope.policy.json`
- `autonomy.policy.json`
- `rollback.policy.json`
- `feedback-learning.policy.json`

## Fixture Strategy

Fixtures should be the primary development driver for the first implementation.

Create fixture families for:

- normalized signal inputs
- trigger outputs
- diagnosis evidence packs
- diagnosis outputs
- remediation plan outputs
- evaluation pass cases
- evaluation fail cases
- execution checkpoint pass cases
- execution checkpoint fail cases
- feedback learning outcomes

## Fixture Layout

Recommended structure:

```text
scaffold/
  fixtures/
    signals/
    triggers/
    diagnoses/
    plans/
    evaluations/
    executions/
    feedback/
```

Each fixture should include:

- input payloads
- expected contract object
- notes about why the case matters

## Test Types

### Contract Tests

Validate that every generated object matches the shared JSON Schemas.

### Policy Tests

Validate that:

- allowed actions pass
- disallowed actuator use fails
- protected scopes escalate
- missing rollback definitions fail

### Flow Tests

Use one fixture set to drive an end-to-end loop:

- normalized signal
- trigger
- diagnosis
- plan
- evaluation
- execution
- feedback

### Regression Tests

Preserve high-value cases such as:

- repeated false positives
- conflicting diagnosis evidence
- checkpoint failure after an approved step
- rollback required for a partial recovery

## Initial Test Priority

Start with these checks before real integrations:

1. schema validation for all six contract objects
2. policy pass/fail cases for the first actuator categories
3. one full happy-path infrastructure-healing fixture
4. one escalation-path fixture
5. one rollback-path fixture

## Exit Criteria Before Runtime Expansion

Do not expand actuator surfaces or domains until:

- contract tests are stable
- policy tests cover all allowed step categories
- the first vertical slice passes end-to-end with fixtures
- escalation and rollback paths are both validated
