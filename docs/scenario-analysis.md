# Scenario Analysis

Mesh scenario analysis is an advisory layer between trigger creation and final
decision creation. It does not execute actions and does not replace evaluation.
It turns the current trigger plus bounded cross-run context into audited evidence
nodes, modular subdecisions, and one synthesized recommendation.

## Runtime Contract

The control plane runs scenario analysis after `trigger_ready` and before
`decision_ready`.

The analysis emits these run events:

- `evidence_node_recorded`: one typed evidence fact from an analyzer.
- `subdecision_recorded`: one analyzer recommendation over its evidence.
- `scenario_analysis_ready`: synthesized advisory recommendation.
- `memory_compaction_recorded`: active-memory update derived from evidence.

Each event receives the normal run-event Merkle leaf. The scenario analysis
artifact stores the current Merkle root and the event ids used by the analysis.
Merkle data proves provenance; it is not treated as domain evidence.

## Analyzer Model

Analyzers implement a fixed shape:

```text
analyze(input) -> evidence nodes, subdecision
```

The v1 analyzer set is:

- `RegressionAnalyzer`: feature-flag latency, error, timeout, and rollout timing.
- `KubernetesAnalyzer`: rollout health, pod/log/event signatures, and correlation.
- `HistoricalOutcomeAnalyzer`: prior outcomes, recovery patterns, success rates.
- `RiskScopeAnalyzer`: business scope, cooldown, credentials, correlated failures.
- `MemoryRelevanceAnalyzer`: active compressed facts and recent related runs.
- `EdgeCaseAnalyzer`: unknown, conflicting, stale, or unclassified evidence.

Analyzer disagreement or fail-closed findings do not bypass policy. Review
reasons are now classified as either terminal human-review blockers or
recoverable evidence blockers. Terminal reasons still reduce confidence and can
force escalation. Recoverable reasons keep the action bounded but allow the
control plane to retry with enriched context in `interruptible_auto`.

## Active Memory

Raw run events, vault notes, learning outcomes, and Merkle records remain
durable. “Unlearning” means a fact is excluded from active decision context, not
deleted from audit history.

The file backend stores compressed active memory at:

```text
.mesh-runtime-state/memory/active_context.json
```

Facts are promoted only when they are relevant, non-empty, and confidence meets
the active-memory threshold. Suppressed facts are recorded in the compaction
artifact with a reason.

Scenario analysis no longer consumes ambiguous raw search output directly.
Instead it requests a verified `MemoryPacket` from the canonical memory
substrate. The packet contains exact-source-backed observations, claims,
procedures, contradiction flags, and citations. `memory_compaction_recorded`
now reflects a prompt-cache projection from verified canonical memory rather
than ad hoc analyzer facts.

## Public API

- `GET /api/runs/:id/scenario-analysis`
  Returns the synthesized recommendation, subdecisions, evidence refs, review
  reasons, and Merkle root.

- `GET /api/runs/:id/evidence-graph`
  Returns sanitized graph nodes and edges linking evidence to subdecisions and
  the final synthesis.

- `GET /api/memory/active?service=<service>`
  Returns compressed active memory for one service. Without `service`, returns
  the active-memory snapshot.

## Safety Rules

- Existing `DecisionService` remains authoritative for the final `Decision`.
- Existing decision types remain the only allowed decision types.
- Scenario analysis can require approval, reduce confidence, route to
  escalation, or mark a run as recoverable with additional evidence.
- Scenario analysis cannot invent actions, skip evaluation, bypass approval, or
  execute directly.
- If analysis fails, the run records the failure and falls back to the existing
  decision path.
