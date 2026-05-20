# SignalProfile — agnostic pipeline contract

## Why this exists

Today Mesh's pipeline is signal-type-aware in 29 places (19 silent
early-returns, 7 control-flow branches, 3 data-shape reads). Adding a
new signal type means editing 8 directories and risking silent skips
in stages that don't have a per-type branch yet.

For example, a Kubernetes incident run today silently no-ops 3 of 8
diagnostic stages:

```
ingest      → ✅ normalized
trigger     → ✅ detected
plan        → ❌ None (services/investigation/reth_planner.py:32)
evidence    → ⚠️ pass-through (services/evidence/service.py:430)
investigation → ✅ runs (generic harness path)
scenario_analysis → ✅ runs
decision    → ⚠️ runs but has signal-type branches
rca_report  → ❌ None (services/investigation/rca.py:16)
evaluation  → ✅
orchestrator → ✅
feedback    → ✅
```

Three of those silent skips would never alert an operator that
something is wrong — the run succeeds with empty diagnostic output.

`SignalProfile` is the canonical fix: one registration per signal
type, dispatching through typed strategy protocols, with an explicit
**generic agentic fallback** for unknown types that escalates by
default rather than silently no-op'ing.

## Goals

1. **One file per signal type.** Adding a new source = registering
   one `SignalProfile`. No edits to `runtime.py`, `decision.py`,
   `evidence/service.py`, `observer/`, or `orchestrator/`.
2. **No silent skips.** Every stage runs for every signal type. If a
   strategy returns no useful output, the absence is logged and
   audited, never silently dropped.
3. **Unknown types escalate.** The `GenericSignalProfile`'s decision
   strategy returns `escalate` regardless of harness output — unknown
   sources cannot auto-act.
4. **Existing invariants preserved.** One-way safety promotion,
   deterministic posterior, single-tenant by design — all carry over
   verbatim, just enforced at the strategy level instead of via
   per-type if/else blocks.
5. **Migration is incremental.** Strategies wrap current code during
   transition. Old paths deleted only after every stage migrates.

## The `SignalProfile` contract

```python
@dataclass(frozen=True)
class SignalProfile:
    """Per-signal-type pipeline configuration.

    Adding a new signal type means registering one of these against
    the SignalProfileRegistry. The registry then drives dispatch for
    every stage of the pipeline.
    """
    # Identity
    signal_type: str           # "reth_node" | "kubernetes_deployment_issue" | "otel_metric_regression" | ...
    trigger_type: str          # "reth_node_degraded" | "kubernetes_deployment_unhealthy" | ...
    schema_name: str           # JSON schema filename under shared/mesh_runtime/schemas/

    # Stage strategies (Protocol-typed; see signal_profile_protocols.py)
    ingest_normalizer: IngestNormalizer
    trigger_detector: TriggerDetector
    investigation_planner: InvestigationPlanner
    evidence_strategy: EvidenceStrategy
    rca_builder: RcaBuilder
    decision_strategy: DecisionStrategy
    scenario_analyzer: ScenarioAnalyzer
    feedback_strategy: FeedbackStrategy

    # Routing metadata (replaces .startswith() chains in runtime.py / orchestrator)
    signal_source: str         # "blockchain_node" | "kubernetes" | "metrics" | "feature_flag" | "webhook" | "generic"
    default_severity: str      # "low" | "medium" | "high" | "critical"
    requires_namespace: bool
```

## Strategy protocols

Each strategy is a `typing.Protocol`. Concrete implementations live
under `shared/mesh_runtime/signal_profiles/<signal_type>.py`.

| Protocol | Method signature | Notes |
|---|---|---|
| `IngestNormalizer` | `normalize(raw: dict) -> EventEnvelope` | Validates payload against `profile.schema_name`. |
| `TriggerDetector` | `detect(envelope: EventEnvelope) -> Trigger \| None` | Returns `None` if thresholds not met — this is the ONE legitimate silent skip in the pipeline (a non-incident). |
| `InvestigationPlanner` | `plan(trigger: Trigger, raw_signal: dict) -> InvestigationPlan` | Always returns a plan. Never `None`. Generic profile builds a probe list against the always-on tool packs. |
| `EvidenceStrategy` | `assemble(trigger, signal_payload, plan) -> EvidencePack` | Always returns a pack. Pre-fast-path scans, probe runner, sufficiency check. |
| `RcaBuilder` | `build(trigger, decision, evidence_pack) -> RcaReport` | Always returns a report. Generic profile synthesizes from `investigation_report.root_cause_candidates`. |
| `DecisionStrategy` | `decide(trigger, scenario_analysis, evidence_pack, investigation_report) -> Decision` | Bounded action surface per profile. Generic profile returns `escalate`. |
| `ScenarioAnalyzer` | `analyze(trigger, ...) -> ScenarioAnalysis` | Cross-run context. Generic profile returns a minimal pass-through analysis. |
| `FeedbackStrategy` | `record(trigger, decision, execution, envelope) -> FeedbackRecord` | T+10m / T+30m outcome checks per type. Generic profile records a stub. |

## Registry semantics

```python
class SignalProfileRegistry:
    def register(self, profile: SignalProfile) -> None:
        """Add a profile. Raises if signal_type already registered."""

    def get(self, signal_type: str) -> SignalProfile | None:
        """Strict lookup. Returns None for unknown types."""

    def get_for_trigger(self, trigger_type: str) -> SignalProfile | None:
        """Lookup by trigger_type."""

    def get_or_generic(self, signal_type: str) -> SignalProfile:
        """Lookup by signal_type, falling back to the generic profile.

        This is what runtime.py calls. Never returns None — unknown
        signal types always resolve to GenericSignalProfile, which
        runs the full agentic pipeline and escalates rather than
        auto-acting.
        """
```

**Registry build is fail-loud:**
- Duplicate `signal_type` registration raises `ProfileAlreadyRegistered`.
- Profile missing any of the 8 strategies raises `IncompleteProfile`.
- The `GenericSignalProfile` is always registered last and cannot be
  overridden.

## The 6 shipping profiles

| Profile | `signal_type` | `trigger_type` | Source of truth (today) |
|---|---|---|---|
| **Reth** | `reth_node` | `reth_node_degraded` | `services/evidence/service.py` (assembly), `services/investigation/reth_planner.py` (planner), `services/investigation/rca.py` (RCA builder) |
| **Kubernetes** | `kubernetes_deployment_issue` | `kubernetes_deployment_unhealthy` | `services/decision/service.py:835` (decision), `services/investigation/service.py:516` (RCA fragments) |
| **OTel** | `otel_metric_regression` | `otel_metric_regression` | `services/decision/service.py:909` (decision) |
| **Feature flag** | `webhook_alert` (FF subset) | `feature_flag_performance_regression` | `services/scenario_analysis/service.py:265` (analysis) |
| **Webhook (generic)** | `webhook_alert` | `webhook_alert_firing` | `services/control_plane.py:606+` (extraction) |
| **Generic** | `*` (fallback) | `*` (fallback) | NEW — built fresh against the always-on harness |

## Generic profile — the agentic fallback

`GenericSignalProfile` is what runs when an inbound signal carries a
`signal_type` not in the registry. Each strategy is designed to
produce useful output from any signal shape without crashing.

| Stage | Generic behavior |
|---|---|
| `ingest_normalizer` | Validates against a minimal "any event" schema. Stamps `signal_source="generic"`. |
| `trigger_detector` | Threshold-based on `severity` field if present, otherwise emit a trigger for any signal at `severity in {high, critical}`. |
| `investigation_planner` | Build a probe list spanning every always-on tool pack (kubectl/prometheus/loki/jaeger/postgres/aws/github/mcp/topology). LLM-driven via `LlmProbeSelector`. |
| `evidence_strategy` | Pass-through pack. Structural-completeness check (count populated fields). Sufficient if and only if `severity` is set + at least one identifier (host/service/target). |
| `rca_builder` | Synthesizes from `investigation_report.root_cause_candidates`. No type-specific fallback fields. |
| `decision_strategy` | **Returns `escalate` unconditionally.** Records the harness findings in `decision.reasoning.observer_notes`. |
| `scenario_analyzer` | Minimal pass-through (no cross-run lookup). |
| `feedback_strategy` | Records stub outcome at T+10m: `not_applicable: generic_profile_does_not_auto_act`. |

**Invariant:** the generic profile never produces an auto-action.
This is the safety floor for unknown signal types.

## Invariants

| # | Invariant | Enforced by |
|---|---|---|
| 1 | No silent skips — every stage produces an artifact (even if "no-op" is the artifact). | `runtime.py` calls strategies unconditionally; the artifact is recorded with `status` reflecting whether the strategy had useful output. |
| 2 | Unknown types cannot auto-act. | `GenericSignalProfile.decision_strategy.decide()` returns `escalate`. |
| 3 | Profile registration is fail-loud — duplicate or incomplete profiles raise at registry build time. | `SignalProfileRegistry.__init__` validates the full set before returning. |
| 4 | Schema validation per profile. | `IngestNormalizer.normalize` validates against `profile.schema_name`. |
| 5 | One-way safety promotion preserved. | `DecisionService` wraps `profile.decision_strategy.decide()` and rejects any verdict that demotes upstream-set escalation. |
| 6 | Deterministic posterior preserved. | `HypothesisEngine` still reads only `kind="fact"` evidence (unchanged). Strategies are indexed on `symptom_class`, not `signal_type`. |
| 7 | Every profile × every stage covered by tests. | CI matrix: `tests/test_signal_profile_matrix.py` iterates the registry. |

## Migration mapping — the 29 type-dispatch sites

This is the inventory the strategies replace. After Phase 4 each
listed location should contain no `signal_type` or `trigger_type`
comparison.

| File:line | Today | Moves into |
|---|---|---|
| `services/trigger/service.py:70-79` | 5-way `if/elif` on `signal_type` | `profile.trigger_detector.detect` |
| `services/evidence/service.py:430` | `if signal_type != "reth_node": return ...` | `profile.evidence_strategy.assemble` |
| `services/investigation/reth_planner.py:32` | `if trigger.trigger_type != "reth_node_degraded": return None` | `profile.investigation_planner.plan` |
| `services/investigation/rca.py:16` | `if trigger.trigger_type != "reth_node_degraded": return None` | `profile.rca_builder.build` |
| `services/investigation/service.py:516,527` | K8s-only RCA fragments | `K8sSignalProfile.rca_builder` (extracted) |
| `services/decision/service.py:94-141` | 4-way dispatch on `trigger_type` | `profile.decision_strategy.decide` |
| `services/scenario_analysis/service.py:265,315,374,634,647` | per-type analysis branches | `profile.scenario_analyzer.analyze` |
| `services/runtime.py:176` | Reth-specific harness wiring | Already handled by `_auto_wire_investigation_harness` 3-path; harness keeps its split |
| `services/control_plane.py:606-638` | Per-type signal-summary extraction | `profile.signal_source` + a small shared summarizer |
| `services/control_plane.py:2761` | OTel-only logic gate | Lifted into `OtelSignalProfile` |
| `services/control_plane.py:3259-3265` | `.startswith("kubernetes_")` chain | `profile.signal_source` |
| `services/orchestrator/agent_mesh.py:602-610` | `.startswith()` chain | `profile.signal_source` |
| `services/feedback/service.py:93,100` | per-type feedback branches | `profile.feedback_strategy.record` |

## Phased rollout

| PR | Phases | Scope |
|---|---|---|
| **PR 1** | 0 + 1 + 2A | Spec doc, registry, all 6 profiles registered, investigation planner + RCA builder dispatching through profile |
| **PR 2** | 2B + 2C | Evidence strategy + decision strategy migration |
| **PR 3** | 2D + 2E + 3 | Scenario analyzer + feedback + trigger detection + orchestrator routing + generic profile hardening |
| **PR 4** | 4 + 5 | Cleanup old dispatch code + register AWS CloudWatch as proof-of-pattern |

Each PR is independently shippable. Behavior change per PR is bounded
by a feature flag (`MESH_PROFILE_DISPATCH_<STAGE>=1`) during migration;
flag flips to default-on in PR 4.

## Out of scope

Deliberately:

- **Multi-profile per signal type.** Each `signal_type` resolves to
  exactly one profile. Multi-customer specialization would happen at
  the runtime config layer (a deployment selects which profile set
  to load), not here.
- **Profile inheritance.** Profiles share strategy *classes* via the
  protocol, not via inheritance trees. No `RethSignalProfile(BaseProfile)`
  abstract class — just composition.
- **Hot reload.** Profile registry is built once at engine start.
  Adding a new profile requires a deploy.
- **Per-tenant profile overrides.** Single-tenant invariant (3) stays
  intact — no tenant predicate on the registry.

## References

- Current type-dispatch audit: this doc's "Migration mapping" section.
- Architecture reference: [`../../architecture.md`](../../architecture.md)
- Investigation harness: [`../investigation-harness.md`](../investigation-harness.md)
