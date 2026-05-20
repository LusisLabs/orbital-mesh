5. Route a patch/review task to the correct bounded agent with exact failing
   evidence.
6. Warn when a service is accumulating delivery risk across repeated flaky
   checks, rollbacks, or missing provenance.
7. Demote trust for agents or services whose outputs repeatedly require
   rollback or human correction.

## Reactive actions improved

Pipeline-native Mesh should improve post-incident work:

1. Identify the likely offending PR, commit range, or artifact digest.
2. Choose rollback target from verified release history.
3. Separate bad release from infrastructure failure.
4. Explain why a rollout was allowed despite weak evidence.
5. Produce an audit packet for incident review.
6. Feed outcome back into service, agent, and policy trust state.

## Acceptance criteria

### Phase 1: Graph contract and GitHub read model

- Versioned schemas exist for all required graph nodes and edges.
- GitHub read-only ingestion supports PR, commit, check suite, workflow run, and
  deployment status events.
- Existing GitHub investigation tools remain read-only.
- Contract tests prove invalid graph packets fail closed.
- No mutation of repositories, PRs, or CI state.

### Phase 2: Release and deployment binding

- Release provenance packets attach to `BuildArtifact` nodes.
- Kubernetes deployment signals attach to `DeploymentEvent` nodes when artifact
  or release identifiers are present.
- Missing artifact/digest/provenance links appear as explicit evidence gaps.
- Reactive runs include a delivery context summary artifact.

### Phase 3: Proactive gate evaluator

- Policy gates evaluate delivery context before promotion events.
- Gate decisions produce auditable `PolicyDecision` nodes.
- Required outcomes include `allow`, `require_approval`,
  `require_canary`, and `block_promotion`.
- Approval cannot override missing hard evidence without an explicit policy
  exception record.

### Phase 4: Agent packet routing

- Agent tasks include scoped delivery packets.
- Patch/review/staging/remediation lanes receive different evidence slices.
- Agent outputs remain proposals.
- Mesh records which evidence packet each agent saw.

### Phase 5: Operator console

- Delivery timeline renders PR, CI, build, deploy, runtime, policy, and feedback
  state for a service.
- Missing evidence is visible without reading logs.
- Operators can inspect why Mesh held, allowed, or escalated a promotion.

### Phase 6: Zaxy durable memory sidecar

- Selected Mesh run and delivery events mirror into Zaxy after Mesh persistence.
- Zaxy mirror packets carry Mesh event id, sequence, Merkle root, citation refs,
  and redaction status.
- Readiness reports Eventloom integrity, latest mirrored sequence, projection
  lag, and graph availability.
- Mesh runs continue when Zaxy is unavailable.
- Zaxy projections are explicitly rebuildable and non-authoritative.

### Phase 7: LangGraph proposal workflow adapter

- The existing DeepAgents path can invoke a LangGraph workflow for proposal
  lanes.
- LangGraph uses scoped thread ids and returns an `AgentAttempt`.
- Zaxy checkout is available as a first workflow node when configured.
- No LangGraph node performs production actuation, approval, merge, or shared
  memory promotion.
- Mesh records the workflow id and evidence packet seen by the agent.

## Metrics

- Percentage of production runtime signals linked to a deployment event.
- Percentage of deployment events linked to build artifact digest.
- Percentage of build artifacts linked to CI and release provenance.
- Mean time from runtime alert to candidate offending change.
- Promotion holds caused by missing evidence.
- Prevented incidents: canary or staging gate caught regression before prod.
- Rollback target confidence.
- Agent proposal acceptance rate after delivery packet routing.
- Reduction in ambiguous RCA outcomes.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Vendor-specific CI assumptions | Start with GitHub, keep normalized generic envelope stable. |
| Overblocking delivery | Ship gates in observe-only mode first, then require explicit policy opt-in. |
| Noisy or incomplete webhooks | Persist evidence gaps and support periodic read-model reconciliation. |
| Agent authority creep | Keep all codegen and review lanes proposal-only. |
| Sensitive logs/artifacts | Store refs and redacted summaries by default; require explicit allowlist for raw artifacts. |
| False causality | Label deploy correlation as hypothesis until runtime evidence and feedback support it. |
| Zaxy availability becomes a hidden dependency | Make Zaxy enrichment optional and visible in readiness. |
| LangGraph workflow state drifts from Mesh run state | Treat LangGraph checkpoints as debug/resume state only, never canonical state. |

## Implementation sequence

1. Add schema-only graph contracts and tests.
2. Add read-only GitHub delivery event adapter.
3. Bind release provenance to build artifact nodes.
4. Bind deployment events to Kubernetes/runtime signals.
5. Add delivery context artifact to Mesh runs.
6. Add observe-only proactive gate evaluator.
7. Add agent delivery packet routing.
8. Add Zaxy Eventloom mirror for selected run and delivery events.
9. Add Zaxy memory checkout into Mesh `MemoryPacket` and delivery packet
   enrichment.
10. Add LangGraph proposal workflow adapter inside the DeepAgents path.
11. Add operator console Delivery view.
12. Turn selected gates from observe-only to enforcing policy.

## Validation plan

Use the existing root gate split:

```bash
pnpm run lint:fast
pnpm run test:focused
pnpm run verify:contracts
pnpm run verify:security
pnpm run verify:full
pnpm run lint
```

For each implementation phase:

- Measure twice, cut once: write the graph contract before wiring runtime paths.
- Add focused contract tests before integration behavior.
- Use fixture events for GitHub/CI/deploy cases.
- Preserve current remediation behavior until delivery context is present and
  tests prove the new path.
- Keep the codebase clean: no generated tmp files, no dead docs, no unused
  adapters, no committed sandbox worktrees.

## Implemented integration choices

1. `DeliveryContextGraph` persists as a Mesh run artifact in the existing state
   backend, so file and Postgres backends stay authoritative without adding a
   separate delivery store.
2. Promotion gates are observe-only by default. The contract supports enforcing
   `block_promotion`, but enforcement requires an explicit policy-mode switch.
3. Repository and service ownership remain evidence fields on the delivery graph
   until CODEOWNERS/runtime-topology conflict resolution is formalized.
4. CI and release artifacts are stored as refs, hashes, and redacted summaries by
   default; raw external artifacts stay outside Mesh unless an allowlist is added.
5. The first enforceable pilot outcomes are `require_approval`,
   `require_canary`, and `block_promotion`; `allow` cannot override hard missing
   evidence without a policy exception record.
6. Zaxy mirrors selected persisted run events after Mesh persistence succeeds and
   remains non-authoritative/rebuildable.
7. Zaxy can use a local outbox or configured authenticated endpoint; Mesh runs do
   not depend on Zaxy availability.
8. LangGraph starts as a proposal workflow adapter for patch, review, staging,
   and remediation lanes through scoped delivery packets and `AgentAttempt`
   records.
