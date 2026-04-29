# Remediation Safety Loop

Mesh now evaluates every remediation decision through a deterministic safety
case before execution.

The safety case does not replace schema validation, policy validation,
Mesh-native trajectory quality checks, business rules, or execution readiness. It is
layered after those checks and can only add blockers. It cannot make a blocked
action executable.

## Scorecard

The score is weighted across eight components:

| Component | Weight | Meaning |
| --- | ---: | --- |
| `policy` | 0.18 | Schema and policy checks passed. |
| `quality` | 0.12 | Contract and trajectory quality gates passed. |
| `readiness` | 0.14 | Credentials, rollback, idempotency, and actuator readiness passed. |
| `evidence` | 0.18 | Trigger metrics, related context, decision evidence, evidence pack, and provenance refs are present. |
| `action` | 0.14 | Action has rollback, adequate confidence, and acceptable risk. |
| `blast_radius` | 0.10 | Scope is single-service and not protected-tier autonomous execution. |
| `history` | 0.08 | Historical success rate for this service/action supports the action. |
| `recovery` | 0.06 | Expected or observed recovery evidence exists. |

Default execution threshold: `0.72`.

## Hard Stops

Any hard stop forces `human_review` regardless of score:

- Existing evaluation blockers are already present.
- Schema validation failed.
- Policy validation failed.
- Execution readiness failed.
- Autonomous high-risk action.
- Autonomous multi-service action.
- Autonomous protected-tier action.
- Severe signatures routed to non-escalation actions.
- Mutating action with insufficient evidence.
- Mutating action with a weak historical success prior.

Severe signatures currently include disk pressure, JWT missing, RPC/AuthRPC
exposure, Engine API unreachable, and consensus disconnect.

## Evaluation Output

Every evaluation now includes:

```json
{
  "stage_results": {
    "remediation_safety": {
      "score": 0.874,
      "threshold": 0.72,
      "verdict": "pass",
      "passed": true,
      "components": {},
      "hard_stops": [],
      "warnings": [],
      "evidence_refs": []
    }
  }
}
```

If the safety case fails, evaluation appends one blocker:

- `remediation safety case has hard stops`
- `remediation safety score below execution threshold`

## Design Constraint

The direction is one-way toward safety. The safety case may require more
evidence or human review; it never overrides an existing blocker and never
upgrades a decision to `execute`.
