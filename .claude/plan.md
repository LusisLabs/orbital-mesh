# Plan: Infra Graph + Action Catalog + Hypothesis Engine + Agent Self-Observability

Working branch: `claude/infra-graph-and-reasoning`
Base: master @ 1c8a81a

## Sequencing rationale

Dependency order (each builds on the previous):

1. **Infra Graph** — foundation. Models topology that everything else queries.
2. **Action Catalog** — uses graph for scope/guards (e.g. cordon_node needs node awareness).
3. **Hypothesis Engine** — uses graph for falsification (query topology + change timeline).
4. **Self-Observability** — measures all of the above.

---

## Phase 1: Infrastructure Graph

### Goal
Continuously updated, queryable, versioned model of K8s objects + service dependencies.

### Files to create
- `shared/mesh_runtime/infra_graph.py` — graph data structure + persistence
- `services/ingest/kubernetes_topology.py` — kubectl-based topology collector
- `tests/test_infra_graph.py`

### Files to modify
- `shared/mesh_runtime/__init__.py` — export `InfraGraph`
- `services/control_plane.py` — instantiate graph, wire into coordinator
- `control_plane_server.py` — add `GET /api/graph/*` endpoints

### Design
**Node types:** `service`, `deployment`, `pod`, `namespace`, `node`, `configmap`, `secret`, `ingress`, `statefulset`

**Edge types:** `routes_to` (ingress→service), `selects` (service→pod), `owns` (deployment→pod), `mounts` (pod→configmap/secret), `scheduled_on` (pod→node), `same_namespace` (pod↔pod within ns)

**Persistence:** file-locked JSON at `state_directory/graph/snapshot.json` + append-only `graph/versions/<ts>.json`. Same `fcntl.LOCK_EX` pattern as existing stores.

**Query API:**
- `get_node(kind, name, namespace) -> dict | None`
- `neighbors(kind, name, namespace, depth=1, edge_types=None) -> list[dict]`
- `affected_services(deployment_name, namespace) -> list[str]` — who depends on this
- `upstream_changes(service, window_seconds) -> list[dict]` — for hypothesis engine

**HTTP endpoints:**
- `GET /api/graph/node/{kind}/{namespace}/{name}`
- `GET /api/graph/neighbors/{kind}/{namespace}/{name}?depth=2`
- `POST /api/graph/refresh` — force topology collection

### Tests
- Build graph from mock kubectl JSON
- Query neighbors at depth 1, 2
- Version snapshots preserved
- Concurrent writes don't corrupt
- Affected services resolution

---

## Phase 2: Action Catalog Expansion

### Goal
Real K8s actions beyond rollback/restart deployment. Per-action-class trust ladder.

### Files to create
- `services/actuators/argocd.py` — ArgoCD sync/rollback
- `shared/mesh_runtime/trust_ladder.py` — per-(action_class, service) graduation
- `tests/test_kubernetes_actions.py`
- `tests/test_trust_ladder.py`

### Files to modify
- `services/actuators/service.py` — add restart_pod, scale_deployment, cordon_node, drain_node, delete_pod methods on `KubernetesAdapter`
- `services/decision/service.py` — new decision types (scale, restart_pod, cordon_node, drain_node)
- `services/orchestrator/service.py` — route new decision types to new actuator methods
- `services/evaluation/service.py` — include new actions in idempotency + allowlist
- `policies/autonomy.policy.json` — add new allowed actions

### New K8s actions
```python
class KubernetesAdapter:
    def restart_pod(params) -> kubectl delete pod <name> -n <ns>  # triggers recreation
    def scale_deployment(params) -> kubectl scale deployment/<x> --replicas=<n>
    def cordon_node(params) -> kubectl cordon <node>
    def drain_node(params) -> kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
    def delete_pod(params) -> alias for restart_pod (explicit form)
```
All with namespace/context allowlist guards. All idempotent (or documented-as-not).

### ArgoCD adapter
```python
class ArgoCDAdapter:
    def sync_application(params)  # POST /api/v1/applications/{name}/sync
    def rollback_application(params, target_revision)  # POST /api/v1/applications/{name}/rollback
    def get_application(params)  # GET
```
Config: `MESH_ARGOCD_URL`, `MESH_ARGOCD_TOKEN`. Dry-run mode when token unset.

### Trust Ladder
4 levels per `(action_class, service)` pair:
- `suggest` (0 runs): human reads hypothesis, doesn't act
- `draft` (≥3 runs, success_rate≥0.5): human approves before action
- `approve` (≥10 runs, success_rate≥0.7): action runs unless human rejects within grace window
- `auto` (≥30 runs, success_rate≥0.85): action runs, post-review only

Auto-promotion after each run. Demotion after 2 consecutive failures. Override available via steering.

Stored as `state_directory/learning/trust_ladder.json` (file-locked JSON).

### Tests
- Each new K8s action dry-run + live (mocked kubectl)
- ArgoCD sync/rollback with mocked HTTP
- Trust ladder promotion/demotion rules
- Integration: DecisionService respects trust ladder level

---

## Phase 3: Hypothesis Engine

### Goal
Generate multiple candidate causes, falsify against telemetry + graph + change timeline, feed into DecisionService.

### Files to create
- `services/decision/hypothesis_engine.py` — generator + falsifier
- `services/decision/hypothesis_templates.py` — built-in hypothesis patterns
- `tests/test_hypothesis_engine.py`

### Files to modify
- `services/decision/service.py` — invoke hypothesis engine before rule tree
- `services/orchestrator/agent_mesh.py` — replace static native lane bodies with real LLM reasoning
- `shared/mesh_runtime/contracts.py` — add `Hypothesis` dataclass

### Design

**Hypothesis shape:**
```python
@dataclass
class Hypothesis:
    hypothesis_id: str
    description: str
    candidate_causes: list[str]           # ["recent_deploy", "config_change", "upstream_outage"]
    falsification_predicates: list[dict]  # queryable claims, e.g. {"type": "recent_deploy", "within": "10m"}
    prior_confidence: float               # before falsification
    posterior_confidence: float           # after evidence
    supporting_evidence: list[str]
    disconfirming_evidence: list[str]
```

**Generation strategy (two-track):**
1. **Template-based** — pre-built hypothesis patterns for known error signatures (crash_loop→recent_deploy|oom|config_change; image_pull_failure→registry_auth|tag_missing|network)
2. **LLM-based** — Goose call with `(signal, service_context, change_timeline, graph_neighbors)` → returns 3-5 candidates

**Falsification:**
For each hypothesis, each predicate gets tested:
- `recent_deploy`: query change timeline (AlertStore) within window
- `upstream_dependency_down`: query infra graph neighbors + their health
- `config_change`: query change timeline for ConfigMap/Secret updates
- `resource_exhaustion`: check pod metrics (memory, cpu) if available
- `external_outage`: correlate with blast_wave signal

Each predicate returns `(supported: bool, evidence_ref: str)`. Posterior confidence updated via simple Bayesian-ish: `posterior = prior * (1 + 0.2 * support_count - 0.3 * disconfirm_count)`.

**Integration:**
- Ranked hypotheses go into `Decision.reasoning.hypotheses` (new field)
- Top hypothesis's recommended action type biases rule engine
- If top hypothesis is high-confidence + mapped to concrete action → skip escalate

**Multi-agent upgrade:**
In `agent_mesh.py`, replace static `_codex_attempt`/`_claudecode_attempt`/`_openclaw_attempt` with real LLM calls using the hypothesis as context. Add a **reconciliation lane** that reads all attempts + hypotheses and picks the best-supported action (or flags disagreement).

### Tests
- Template hypothesis generation from error signatures
- Falsification against mock change timeline
- Posterior update math
- Integration: HypothesisEngine feeds DecisionService

---

## Phase 4: Agent Self-Observability

### Goal
Measure the agent's own performance: MTTR, false-positive rate, rollback rate. Expose as Prometheus metrics + UI dashboard.

### Files to create
- `shared/mesh_runtime/agent_slo.py` — SLO computation
- `services/metrics/service.py` — Prometheus exposition
- `tests/test_agent_slo.py`

### Files to modify
- `control_plane_server.py` — `GET /metrics` endpoint + `GET /api/agent/slo`
- `web/src/App.tsx` — add KPI dashboard page (basic version)
- `shared/mesh_runtime/control_plane_state.py` — helper queries for SLO windows

### SLO metrics
```python
# Per service, per 24h/7d/30d rolling window
- mttr_seconds_p50, p95  # trigger→successful feedback
- false_positive_rate    # escalate → no_action after human review
- rollback_rate          # executions that got reverted (orchestrator retry exhausted OR steering cancel)
- auto_execution_rate    # runs that completed without human approval
- mean_time_to_detect    # signal arrival → trigger_ready
- mean_time_to_decide    # trigger_ready → decision_ready
- evaluation_gate_rejection_rate  # how often policy blocks a decision

# Global
- runs_per_hour
- active_runs_gauge
- watch_daemon_signals_per_hour (if watch enabled)
```

### Prometheus format
Plain text exposition. Labels: `service`, `environment`, `decision_type`.

### HTTP
- `GET /metrics` — Prometheus scrape endpoint
- `GET /api/agent/slo?window=24h` — JSON for UI

### UI
Simple KPI dashboard route `/agent` showing:
- MTTR chart (last 24h / 7d)
- Success/failure/escalation counts
- Top 5 problematic services
- Trust-ladder progression chart

### Tests
- SLO computation from mock run sessions
- Prometheus format correctness
- Rolling window edge cases (empty, single run, exactly at boundary)

---

## Testing strategy

Each phase has unit tests + one integration test that exercises the full pipeline with the new feature.

Final verification:
1. `ruff check .` passes
2. `python3 -m unittest discover -s tests` — all tests pass, no regressions
3. Full startup smoke test: `run_server.py` starts, `/api/health` + new endpoints respond

## Deliverable

Single PR with the 4 phases, each as a separate commit so reviewers can follow the chain. Tracker file in `.claude/plan.md` updated with completion markers as we go.
