# Design: Sub-agent specialization for multi-domain production monitoring

## Problem

Today, the mesh control plane has two layers that look agentic but are not
actually specialized:

### The watcher is one flat thread

`WatchDaemon` ([services/watch_daemon.py](../../services/watch_daemon.py))
is a single background thread iterating a flat `list[WatchTarget]`. It only
calls `collect_kubernetes_signal()`, so it can watch K8s deployments and
nothing else. A `WatchTarget` carries `{deployment_name, namespace,
kube_context}` — no signal-type tag, no domain label, no service ownership.
One instance per control plane, hardcoded at
[services/control_plane.py:236-252](../../services/control_plane.py).

**Consequence:** we cannot watch feature-flag providers, Argo sync events,
Prometheus breaches, log-pattern spikes, or cost drift from the same control
plane. Adding a second signal source means editing the daemon.

### The agent mesh is role-specialized but domain-agnostic

`AgentMeshService`
([services/orchestrator/agent_mesh.py](../../services/orchestrator/agent_mesh.py))
fans out every run to core lanes plus native orchestration platform lanes:
`goose`, `hermes`, `codex`, `claudecode`, and `openclaw`. Each core lane has a distinct role:

| Lane | System-prompt role |
|------|-------------------|
| `goose` | operational coordination |
| `hermes` | root-cause hypothesis |
| `codex` | patch proposal |
| `claudecode` | review |
| `openclaw` | staging validation |

But:

1. **Every lane receives the same bundle** (`task/trigger/decision/
   evaluation`). A feature-flag signal still invokes `openclaw` (K8s staging
   validator). A K8s crashloop still invokes `codex` (patch proposal).
2. **No reconciliation between lanes.** `build_tasks` picks the first
   successful attempt ([agent_mesh.py:64-65](../../services/orchestrator/agent_mesh.py))
   and discards the rest. No voting, no debate, no conflict resolution.
3. **No service/domain affinity.** There is no notion of "the search
   service's dedicated sub-agent" or "the payments team's runbook-aware
   agent." All runs hit the same global fan-out.

**Consequence:** we can't give `search` a semantics-aware agent, give
`payments` an idempotency-aware agent, or give `billing` a tax-compliance-
aware agent. We can't even stop invoking the K8s staging validator on a
feature-flag regression.

## Goals

1. **Typed watchers per signal source.** Kubernetes, feature flags, ArgoCD,
   Prometheus, Loki, cost-drift — each plug in as a first-class watcher
   without editing the daemon.
2. **Per-service stateful sub-agents.** Each monitored service has a
   registered agent with its own scope, runbook, and memory slice.
3. **Signal-source routing in the agent mesh.** K8s signals go to K8s-
   specialist lanes; feature-flag signals go to flag-specialist lanes.
4. **Reconciliation between competing proposals.** When lanes disagree,
   a new arbitration step produces a single recommended action with a
   posterior-weighted confidence.
5. **Backward compatible.** The existing single-`WatchDaemon` +
   six-lane-fan-out must continue to work with zero config change. The new
   architecture lights up when operators register typed watchers and
   service agents.
6. **Observable.** Every watcher, every sub-agent, every reconciliation
   round shows up in the run event log and the agent SLO metrics.

## Non-goals

- Not replacing the decision service, the hypothesis engine, or the trust
  ladder. Those stay put.
- Not introducing a message bus. The in-process call graph is sufficient
  for now; we add a bus only if profiling shows we need one.
- Not adding a new LLM provider. Specialization is about *routing* and
  *scope*, not about picking different models per lane (though it unlocks
  that later).
- Not changing the actuator layer. Service agents still emit decisions
  that go through `DecisionService → EvaluationService → OrchestratorService
  → actuators`.

## Proposed architecture

Four composable layers, each shippable as an independent PR:

```
┌──────────────────────────────────────────────────────────────────────┐
│                         WatcherRegistry                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────┐  │
│   │   K8s    │  │  Feature │  │  ArgoCD  │  │Prometheus│  │ Loki  │  │
│   │ Watcher  │  │  Flag W. │  │  Watcher │  │ Watcher  │  │  W.   │  │
│   └────┬─────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘  └───┬───┘  │
│        │              │             │             │           │      │
│        └──────────────┴─────────────┴─────────────┴───────────┘      │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │  typed signal
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   ServiceAgentRegistry (NEW)                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐    ┌──────────┐            │
│   │  search  │  │  payments│  │  auth    │    │  default │  (catch-  │
│   │   agent  │  │   agent  │  │  agent   │    │   agent  │   all)    │
│   │  (scope) │  │  (scope) │  │  (scope) │    │          │            │
│   └────┬─────┘  └─────┬────┘  └─────┬────┘    └─────┬────┘            │
│        │              │             │               │                 │
│        └──────────────┴─────────────┴───────────────┘                 │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │  scoped signal
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  AgentMeshService (existing, refactored)              │
│                                                                       │
│   Route by signal_source → specialist lanes only                      │
│   k8s:        goose, codex, claudecode, openclaw                      │
│   feature_flag: hermes, openclaw                                      │
│   argocd:    goose, openclaw                                          │
│                                                                       │
│   + NEW Reconciliation lane reads all proposals + hypothesis engine   │
│     posteriors, picks a winner or escalates on disagreement.          │
└───────────────────────────────────────────────────────────────────────┘
```

### Layer 1 — WatcherRegistry + typed watchers

**New file:** `services/watchers/registry.py`

```python
class Watcher(Protocol):
    name: str
    signal_source: str    # "kubernetes" | "feature_flag" | "argocd" | ...
    interval_seconds: int

    def poll(self) -> list[dict]:  # each dict is a normalized signal
        ...

    def status(self) -> dict:
        ...


class WatcherRegistry:
    def register(self, watcher: Watcher) -> None: ...
    def start_all(self) -> None: ...
    def stop_all(self) -> None: ...
    def status(self) -> dict[str, Any]: ...
```

Each registered watcher runs on its own thread. Shared infrastructure
(stop event, thread pool, per-watcher dedup state) lives in the registry.

**Initial watcher implementations** (built over multiple PRs):

| Watcher | What it polls | Shape of emitted signal |
|---------|---------------|--------------------------|
| `KubernetesWatcher` | `kubectl get` (same as today) | `kubernetes_deployment_issue` |
| `FeatureFlagWatcher` | LaunchDarkly/Split API for recent toggles | `feature_flag_change` |
| `ArgoCDWatcher` | Argo API for sync/rollout events | `argocd_sync_event` |
| `PrometheusWatcher` | Prom query API for SLO breaches | `slo_breach` |
| `LogPatternWatcher` | Loki/Elastic for error-rate spikes | `log_pattern_spike` |

All emit through `coordinator.create_run(...)` exactly like the current
daemon does, with `related_context.signal_source` tagged.

**Migration:** The existing `WatchDaemon` becomes `KubernetesWatcher` under
the hood. If `watch_targets` are configured via the old env var, a
compatibility shim registers a `KubernetesWatcher` on their behalf.

### Layer 2 — ServiceAgentRegistry

**New file:** `services/orchestrator/service_agents/registry.py`

A **service agent** is a stateful, configured agent tied to a specific
service. It owns:

- **Scope:** which deployments, namespaces, feature-flags, repos belong
  to it. Defined via a glob / label selector.
- **Runbook:** an optional markdown/YAML doc with service-specific
  remediation patterns the agent can reference.
- **Memory slice:** filtered view of `ContextStore` / `LearningStore`
  limited to this service's history.
- **Watchers:** references to the typed watchers that emit signals for
  this service.

```python
@dataclass
class ServiceAgentConfig:
    service: str
    scope: ServiceScope   # {deployments: [...], namespaces: [...], flags: [...], repos: [...]}
    runbook_path: str | None
    preferred_lanes: list[str] = field(default_factory=list)  # optional bias
    autonomy_overrides: dict[str, str] | None = None  # {action_class: max_tier}
    llm_profile: str | None = None  # future: model choice


class ServiceAgent:
    def __init__(self, config: ServiceAgentConfig, context_store, learning_store,
                 infra_graph, trust_ladder): ...

    def scoped_context(self) -> dict[str, Any]:
        """Memory slice for this service only."""

    def evaluate_signal(self, signal: dict) -> bool:
        """Does this signal belong to me?"""

    def augment_trigger(self, trigger: Trigger) -> Trigger:
        """Add runbook hints, scope-specific context, etc."""


class ServiceAgentRegistry:
    def register(self, agent: ServiceAgent) -> None: ...
    def route(self, signal: dict) -> ServiceAgent:
        """Find the matching agent for a signal, or fall back to default."""
    def list_agents(self) -> list[dict[str, Any]]: ...
```

**Config example** (`MESH_SERVICE_AGENTS_CONFIG` as JSON file path):

```yaml
agents:
  - service: search
    scope:
      deployments: [search-api, search-ingest]
      namespaces: [search, search-staging]
      repos: [hyperstrategy/search]
    runbook_path: runbooks/search.md
    preferred_lanes: [goose, codex]
    autonomy_overrides:
      rollback_deployment: approve    # cap at approve even if ladder says auto
  - service: payments
    scope:
      deployments: [payments-*]
      namespaces: [payments]
    runbook_path: runbooks/payments.md
    autonomy_overrides:
      disable_flag: suggest    # payments can never auto-disable flags
```

The **default agent** handles anything with no match — it mirrors today's
global behavior.

### Layer 3 — Signal-source routing in AgentMeshService

The current `_agents()` returns a static list. Replace with a routing table
keyed on `(signal_source, decision_type)`:

```python
_LANE_ROUTING: dict[str, list[str]] = {
    "kubernetes": ["goose", "codex", "claudecode", "openclaw"],
    "feature_flag": ["hermes", "openclaw"],
    "argocd": ["goose", "openclaw"],
    "slo_breach": ["hermes", "goose"],
    "log_pattern": ["hermes", "codex"],
}

def _agents(signal_source: str, service_agent: ServiceAgent | None) -> list[str]:
    lanes = _LANE_ROUTING.get(signal_source, _DEFAULT_LANES)
    if service_agent and service_agent.config.preferred_lanes:
        lanes = [l for l in lanes if l in service_agent.config.preferred_lanes] or lanes
    return lanes
```

**Backward compat:** if `signal_source` is absent or `"unknown"`, fall
back to the full six-lane fan-out (today's behavior).

### Layer 4 — Reconciliation lane

**New file:** `services/orchestrator/reconciliation.py`

Instead of "first successful attempt wins," a reconciliation step:

1. Collects all `AgentAttempt` proposals from the fan-out.
2. Joins each attempt with the hypothesis-engine posterior for its
   `recommended_action`.
3. Applies weighted voting:
   - Each lane gets a base weight (service-agent preference > unspecialized).
   - Multiplied by the trust-ladder level for that action class on this service.
   - Multiplied by the hypothesis posterior for the recommended action.
4. Picks the action with the highest weighted vote *if it clears a
   disagreement threshold* (default 1.5× the runner-up).
5. If the top two actions are within the threshold, emit a
   `RECONCILIATION_DISAGREEMENT` event and force `approval_required`.

Output:

```python
@dataclass
class ReconciliationResult:
    selected_action: str
    winning_lane: str
    weight: float
    runner_up_action: str | None
    runner_up_weight: float
    disagreement: bool
    disagreement_ratio: float
    attempt_weights: dict[str, float]   # per lane
```

Recorded as a run event so the audit trail shows *why* this action won.

## Data model changes

New / modified types in `shared/mesh_runtime/`:

```python
# NEW: shared/mesh_runtime/service_scope.py
@dataclass
class ServiceScope:
    deployments: list[str] = field(default_factory=list)  # glob-match
    namespaces: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # label-match

    def matches(self, signal: dict) -> bool:
        """Return True if the signal falls inside this scope."""

# Additions to shared/mesh_runtime/contracts.py::Trigger
# (all optional, all None-defaulted for backward compat)
@dataclass
class Trigger:
    # ... existing fields ...
    signal_source: str | None = None       # "kubernetes" | "feature_flag" | ...
    service_agent: str | None = None       # which service agent owns this
    watcher_id: str | None = None          # which watcher produced the signal
```

New run event types (added to `shared/mesh_runtime/run_events.py`):

```
WATCHER_TRIGGERED          # emitted by a watcher when it enqueues a run
SERVICE_AGENT_ROUTED       # which agent picked up the signal
RECONCILIATION_DECIDED     # reconciliation verdict
RECONCILIATION_DISAGREEMENT # when voting is close
```

## Configuration

New environment variables:

```
MESH_WATCHER_CONFIG_PATH           # path to watchers.json (see below)
MESH_SERVICE_AGENTS_CONFIG_PATH    # path to service-agents.yaml
MESH_RECONCILIATION_ENABLED        # default false; opt-in
MESH_RECONCILIATION_THRESHOLD      # min runner-up ratio, default 1.5
```

`watchers.json` shape:

```json
{
  "watchers": [
    {
      "kind": "kubernetes",
      "name": "prod-cluster-k8s",
      "interval_seconds": 60,
      "kube_context": "prod",
      "targets": [{"deployment_name": "search-api", "namespace": "search"}]
    },
    {
      "kind": "launchdarkly",
      "name": "prod-flags",
      "interval_seconds": 300,
      "project": "production",
      "environments": ["prod"]
    },
    {
      "kind": "prometheus",
      "name": "slo-watcher",
      "interval_seconds": 120,
      "prom_url": "http://prometheus:9090",
      "queries": [
        {"service": "search", "expr": "histogram_quantile(0.95, sum(rate(latency[5m])) by (le))", "threshold": 250}
      ]
    }
  ]
}
```

`service-agents.yaml` shape: shown in the Layer-2 example above.

## Phasing

Each phase is an independent, mergeable PR. Every phase keeps existing
behavior intact if the new config is not provided.

### Phase 1 — WatcherRegistry + KubernetesWatcher

- Create `services/watchers/{registry,base,kubernetes}.py`.
- Refactor `WatchDaemon` to delegate to `KubernetesWatcher`. Keep the
  class as a thin wrapper so import paths don't break.
- Compat shim: if `MESH_WATCH_TARGETS` is set but `MESH_WATCHER_CONFIG_PATH`
  is not, synthesize a single `KubernetesWatcher` entry.
- New HTTP: `GET /api/watchers`, `POST /api/watchers/{name}/start|stop`.
- Tests: registry registration, start/stop, status, shim.

**Delivers:** no behavior change, but adds the seams for new watchers.

### Phase 2 — FeatureFlagWatcher + PrometheusWatcher

- LaunchDarkly-first (most common) with pluggable provider interface.
- PrometheusWatcher does pull-based SLO checks.
- Both emit signals with `signal_source` tagged.
- Tests against mocked APIs.

**Delivers:** real multi-source ingestion.

### Phase 3 — ServiceAgentRegistry + routing in AgentMeshService

- Add `ServiceScope`, `ServiceAgent`, `ServiceAgentRegistry`.
- Plumb `signal_source` through ingest → trigger → decision → agent mesh.
- Add `_LANE_ROUTING` table.
- `service_agent.augment_trigger(...)` runs before decision.
- Runbook rendering: load markdown, strip headers, fold into
  `trigger.related_context.runbook_hints`.
- Tests: scope matching, routing by source, default-agent fallback.

**Delivers:** agents are now specialized by service.

### Phase 4 — Reconciliation lane

- Collect attempts post-fan-out.
- Weight by lane preference × trust ladder × hypothesis posterior.
- Emit `RECONCILIATION_DECIDED` / `DISAGREEMENT` events.
- Web UI panel showing the weighted vote breakdown.
- Tests: unanimous vote, close vote → disagreement, missing posterior
  gracefully degrades to uniform weighting.

**Delivers:** first-wins is replaced by posterior-weighted arbitration.

### Phase 5 — Observability upgrades

- New agent SLOs: `watcher_signals_per_minute{watcher}`,
  `service_agent_runs{service}`, `reconciliation_disagreement_rate`.
- Web UI: per-watcher health panel, per-service-agent dashboard.

## Migration & rollout

**Default state:** everything off. Existing single `WatchDaemon` behavior
is preserved by the Phase-1 compat shim. No config change required to
continue operating as today.

**Opt-in path:**

1. Operator provides `MESH_WATCHER_CONFIG_PATH` → new watchers light up.
2. Operator provides `MESH_SERVICE_AGENTS_CONFIG_PATH` → service routing
   activates. Signals matching a scope go to their specialist agent;
   everything else still hits the default agent (today's behavior).
3. Operator sets `MESH_RECONCILIATION_ENABLED=1` → reconciliation replaces
   first-wins. Can disable anytime; runs fall back to first-wins.

**Rollback:** every phase is gated by a flag or the absence of a config
file. Reverting to today's behavior is one env var flip.

## Risks & open questions

1. **Thundering herd from parallel watchers.** Ten watchers on
   one-minute cadence → spikes of kubectl/API calls. Mitigation: jittered
   intervals (+/- 20%) per watcher on startup; per-watcher concurrency cap.
2. **ServiceAgent scope ambiguity.** What if two agents claim the same
   deployment? Mitigation: deterministic precedence — most-specific scope
   wins (namespace > glob > label). Log ambiguous matches as events.
3. **Runbook format divergence.** Markdown vs YAML vs per-org format.
   Mitigation: start with markdown-only, keep parser pluggable.
4. **Per-service memory cost.** `ContextStore` already caps at 200 per
   service. Service agents hold references, not copies — no extra memory.
5. **Reconciliation when no hypotheses available.** If the hypothesis
   engine hasn't produced posteriors, fall back to trust-ladder-only
   weighting, with `hypothesis_available=False` recorded in the event.
6. **Does a "default agent" trigger specialization decay?** If most
   traffic falls through to default, we won't learn service-specific
   patterns. Mitigation: dashboard metric `unspecialized_runs_share` flags
   drift above a threshold.
7. **Cost of per-service LLM profiles.** Out of scope here, but the
   `llm_profile` field lets a future phase route different services to
   cheaper/faster models. Keeping the hook in the data model now is cheap.
8. **Watcher failure modes.** Each watcher can fail independently
   (e.g. Prom down). Mitigation: per-watcher health status surfaced via
   `/api/watchers`; dead-watcher alerts as an own signal source
   (metawatcher). Don't block other watchers.

## Testing strategy

### Unit tests

- `WatcherRegistry`: register/start/stop, status aggregation, shim.
- Each watcher: signal shape, error recovery, dedup.
- `ServiceScope`: glob matching, label matching, overlap detection.
- `ServiceAgentRegistry.route`: exact match, default fallback, ambiguity.
- Reconciliation: unanimous, close, missing posteriors.

### Integration tests

- End-to-end: register two watchers + two service agents → each watcher's
  signal reaches the right agent → right lanes invoked.
- Backward-compat: only `MESH_WATCH_TARGETS` set → single
  `KubernetesWatcher` runs, same behavior as today's `WatchDaemon`.
- Disagreement path: seed two lanes with conflicting recommendations →
  reconciliation flags disagreement → autonomy tier forced to
  `approval_required`.

### Failure-mode tests

- Kill one watcher thread mid-poll → registry reports dead status; other
  watchers unaffected.
- ServiceAgent config references a missing runbook → start succeeds,
  logs warning, augment returns trigger unchanged.
- Reconciliation with one lane returning error → graceful degrade to
  voting among remaining lanes.

## Appendix A — Compat shim sketch

```python
# services/watchers/compat.py
def register_legacy_watchers(config: RuntimeConfig, registry: WatcherRegistry) -> None:
    """Bridge MESH_WATCH_TARGETS → single KubernetesWatcher entry."""
    if not config.watch_enabled or not config.watch_targets:
        return
    if os.getenv("MESH_WATCHER_CONFIG_PATH"):
        return  # operator has migrated; do nothing
    registry.register(KubernetesWatcher(
        name="legacy-k8s",
        interval_seconds=config.watch_interval_seconds,
        targets=[WatchTarget(**t) for t in config.watch_targets],
        kubectl_command=config.kubectl_command,
    ))
```

## Appendix B — Scope matching sketch

```python
# shared/mesh_runtime/service_scope.py
import fnmatch

@dataclass
class ServiceScope:
    deployments: list[str] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def matches(self, signal: dict) -> bool:
        ctx = signal.get("related_context", {}) or {}
        if self.deployments and not any(
            fnmatch.fnmatch(ctx.get("deployment_name", ""), pat)
            for pat in self.deployments
        ):
            return False
        if self.namespaces and ctx.get("namespace") not in self.namespaces:
            return False
        if self.flags and signal.get("feature_flag", {}).get("flag_key") not in self.flags:
            return False
        for k, v in self.labels.items():
            if ctx.get("labels", {}).get(k) != v:
                return False
        return True

    def specificity(self) -> int:
        """More specific scopes outrank less specific ones for the same signal."""
        return (
            len(self.deployments) * 3
            + len(self.namespaces) * 2
            + len(self.flags) * 2
            + len(self.repos) * 2
            + len(self.labels)
        )
```

## Appendix C — Reconciliation math

Given N lane attempts, let `action_i` be lane `i`'s recommended action
and:

```
W_i = w_lane(i) × w_trust(action_i, service) × w_posterior(action_i)
```

where:
- `w_lane(i)` = 1.0 default, or 1.5 if the lane is in the service agent's
  `preferred_lanes`.
- `w_trust(a, s)` = 0.4 (suggest), 0.7 (draft), 1.0 (approve), 1.3 (auto).
- `w_posterior(a)` = the hypothesis engine's posterior confidence for `a`,
  clamped to [0.1, 1.0]; 0.5 if no posterior available.

Aggregate by action:

```
score(a) = sum(W_i for i where action_i == a)
```

Pick `argmax(score)`. Disagreement if
`score(winner) / score(runner_up) < threshold` (default 1.5). On
disagreement: force `approval_required` and record the full weight
breakdown in the run event.

## Summary table

| Layer | New file(s) | Modifies | Backward-compat? | Ships in |
|-------|-------------|----------|------------------|----------|
| 1 — WatcherRegistry | `services/watchers/*` | `watch_daemon.py`, `control_plane.py` | Yes (compat shim) | Phase 1 |
| 2 — More watchers | `services/watchers/{feature_flag,prometheus}.py` | — | Yes (opt-in) | Phase 2 |
| 3 — ServiceAgent routing | `services/orchestrator/service_agents/*`, `shared/mesh_runtime/service_scope.py` | `agent_mesh.py`, `contracts.py`, `ingest/service.py` | Yes (default agent) | Phase 3 |
| 4 — Reconciliation | `services/orchestrator/reconciliation.py` | `agent_mesh.py` | Yes (env flag) | Phase 4 |
| 5 — Observability | — | `agent_slo.py`, web UI | Yes | Phase 5 |
