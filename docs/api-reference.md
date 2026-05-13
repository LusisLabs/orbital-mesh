# Mesh HTTP API Reference

The control plane speaks JSON over HTTP plus Server-Sent Events for streaming. No authentication is enforced by default — Mesh is designed to run on `127.0.0.1` behind your operator's network. When exposing publicly, front it with TLS termination + auth (the OTLP receiver supports a static bearer token; see `MESH_OTEL_RECEIVER_TOKEN`).

Default base URL: `http://127.0.0.1:8787`.

All routes return `application/json` unless noted (SSE streams use `text/event-stream`). All POST bodies are JSON. Errors use HTTP status + `{"error": "...", "detail": "..."}`.

---

## Health & readiness

### `GET /api/health`

Liveness probe.

```json
{
  "status": "ok",
  "timestamp": "2026-05-13T10:30:00Z",
  "environment": "production",
  "version": "dev",
  "commit": "unknown"
}
```

### `GET /api/readiness`

Per-integration readiness (Promptfoo, Goose, Hermes, Evo, MCP servers, observer LLM, Prometheus, Loki, Jaeger, Postgres, kubectl, etc.). Use this from your own status page or sidecar.

```json
{
  "ready": true,
  "integrations": {
    "promptfoo": {"ready": true, "command": "..."},
    "goose":     {"ready": false, "reason": "command not found"},
    "kubectl":   {"ready": true, "kubeconfig": "..."}
  }
}
```

---

## Goals

### `GET /api/goals`

```json
{"goals": [{"id": "goal_default", "title": "...", "objective": "...", ...}]}
```

### `POST /api/goals` → `201`

```json
{
  "title": "Protect search latency",
  "objective": "Pause every risky remediation before execution.",
  "success_criteria": ["approval gate pauses", "vault notes written"]
}
```

Returns the created goal record.

---

## Runs

### `GET /api/runs?summary=1`

`summary=1` returns a lightweight list; omit for full run records.

### `POST /api/runs` → `201`

**With a fixture scenario:**

```json
{
  "goal_id": "goal_default",
  "scenario_key": "search_latency_regression",
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "approval_gate"
}
```

**With a raw signal payload:**

```json
{
  "goal_id": "goal_default",
  "signal_payload": { "...": "full signal" },
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "approval_gate"
}
```

Valid `steering_mode`: `approval_gate`, `interruptible_auto`.
Valid `evaluation_mode`: `native`, `promptfoo`.
Valid `orchestration_mode`: `native`, `goose`, `hermes`.

Returns the created run record (including `run_id`).

### `GET /api/runs/:id`

Full run record: stage, decision, evaluation, execution, feedback, citations, citations index.

### `POST /api/runs/:id/steer`

Send a bounded steering command. Body shape:

```json
{
  "command": "approve",
  "metadata": { "operator": "alice", "comment": "..." }
}
```

Valid `command` values:

| Command | Purpose |
|---|---|
| `approve` | Acknowledge the approval gate, allow execution to proceed. |
| `cancel` | Cancel the run; transitions to `cancelled`. |
| `pause_after_stage` | Set a pause point (`metadata.stage` = next stage). |
| `resume` | Clear a pause point. |
| `set_auto_mode` | Switch between `approval_gate` and `interruptible_auto`. |
| `override_decision` | Replace the proposed decision; run re-enters evaluation. |
| `override_execution_parameters` | Adjust execution params before actuation. |
| `attach_note` | Add a free-text note to the run record. |

Overrides always re-enter evaluation. Approval never bypasses policy or rollback constraints.

### `GET /api/runs/:id/events?after=:sequence`

Append-only event log for the run. `after` is an integer cursor; events have monotonic `sequence` numbers.

```json
{"events": [
  {"sequence": 1, "event_id": "...", "name": "trigger_ready", "payload": {...}, "timestamp": "..."},
  ...
]}
```

### `GET /api/runs/:id/scenario-analysis`

Analyzer's evidence graph for the run — failure-class hypotheses, evidence nodes, RCA confidence.

### `GET /api/runs/:id/evidence-graph`

Lower-level evidence graph the analyzer consumes (probe outputs, citations, contradictions).

### `GET /api/runs/:id/merkle`

Merkle snapshot:

```json
{
  "root": "0x…",
  "leaf_count": 27,
  "leaves": [{"event_id": "...", "hash": "0x..."}, ...]
}
```

### `GET /api/runs/:id/merkle/proof/:event_id`

Merkle inclusion proof for a single event:

```json
{
  "event_id": "...",
  "leaf_hash": "0x...",
  "root": "0x...",
  "siblings": [{"hash": "0x...", "side": "right"}, ...]
}
```

Verify with any standard SHA-256 Merkle verifier — concatenate `leaf_hash` with each sibling in the order given, hash, repeat until you hit `root`.

### `GET /api/runs/:id/agent-tasks`

Deepagents / agent-task attempts recorded against the run.

### `GET /api/runs/:id/memory-crystallization`

Reasoning-bank crystallisation snapshot for this run.

### `GET /api/runs/:id/reasoning-bank`

Reasoning-bank entries the run produced or referenced.

---

## SSE streams

### `GET /api/stream/runs/:id`

Server-Sent Events stream of run events as they happen.

```
event: trigger_ready
data: {"sequence": 1, "name": "trigger_ready", ...}

event: decision_ready
data: {"sequence": 2, ...}
```

Reconnect with the `Last-Event-ID` header (browser `EventSource` does this automatically).

### `GET /api/stream/system`

System-wide event stream — every run's events interleaved, plus engine-level events (`watcher_started`, `webhook_received`, etc.).

---

## Scenarios, simulations, benchmarks

### `GET /api/scenarios`

Bundled fixture scenarios shipped under `fixtures/`. Each has a `scenario_key` you can pass to `POST /api/runs`.

### `GET /api/simulations`

Available simulation scenarios (e.g., chaos injection, AI CROPS variants).

### `POST /api/simulations/:scenario_id/run` → `201`

Launch a simulation. Body is the simulation parameter overlay.

### `GET /api/benchmarks?limit=100`

List benchmark runs (CloudOpsBench, Reth peer-starvation, etc.).

### `GET /api/benchmarks/:benchmark_id`

Full benchmark run detail.

---

## Memory + reasoning bank

### `GET /api/memory/active?service=:service`

Active memory store entries (recent crystallisations).

### `GET /api/memory/query?q=:query&service=:service&limit=10`

Free-text query over memory store.

### `GET /api/memory/claims/:claim_id`

A single memory claim with its citations.

### `GET /api/memory/graph?service=:service`

The memory graph as a node-link structure.

### `POST /api/memory/maintenance/run` → `201`

Trigger a memory-maintenance pass (consolidation, decay, deduplication).

---

## InfraGraph (topology)

The runtime maintains a typed K8s relationship graph populated per-run.

### `GET /api/graph/status`

Versions, last-updated timestamp, kind/edge counts.

### `GET /api/graph/snapshot`

Full graph snapshot (`{nodes: [...], edges: [...]}`). Kinds: `service`, `deployment`, `pod`, `node`, `event`, `statefulset`, `daemonset`, `job`, `configmap`, `secret`, `ingress`, `namespace`. Edges: `selects`, `owns`, `scheduled_on`, `routes_to`, `mounts`, `exposes`, `fired_on`.

### `GET /api/graph/neighbors/:kind/:namespace/:name`

Neighbors of a single node. Optional query: `?edge_kind=selects&direction=out&depth=1`.

### `GET /api/graph/node/:kind/:namespace/:name`

Single node lookup.

### `GET /api/graph/affected/:namespace/:deployment`

Services that route to a deployment (transitive `selects`-via-pods traversal).

### `POST /api/graph/refresh`

Re-run the populator. Body optionally narrows scope:

```json
{"namespaces": ["boutique", "default"]}
```

---

## Webhooks & alerts

### `GET /api/webhook-sources`

Registered webhook ingesters.

### `POST /api/webhook-sources` → `201`

Register a new ingester:

```json
{
  "id": "github-prod",
  "name": "Production GitHub Alerts",
  "secret": "...",
  "format": "github_webhook"
}
```

Supported `format`: `github_webhook`, `grafana_alertmanager`, `pagerduty_event`, `generic`.

### `POST /api/webhooks/:source_id` → `202`

Receive an alert. Mesh validates `X-Mesh-Signature` (or `X-Hub-Signature-256`) against the registered secret, ingests, and spawns a run if the signal trips a trigger.

### `DELETE /api/webhook-sources/:source_id`

Deregister a webhook source.

### `GET /api/alerts?source_id=:id&limit=100`

Recent alert events received.

---

## Watchers

Long-lived observers (signal_history poller, OTel listener, K8s informer) that turn ambient telemetry into Mesh triggers.

### `GET /api/watch/status` and `GET /api/watchers`

Watcher inventory + current state.

### `POST /api/watch/start` and `POST /api/watch/stop`

Master switch.

### `POST /api/watchers/:name/start` and `POST /api/watchers/:name/stop`

Toggle a single watcher.

---

## Trust ladder

Per-(action_class, service) trust levels gating live execution.

### `GET /api/trust-ladder` and `GET /api/trust-ladder/:action_class/:service`

Inspect current levels.

### `POST /api/trust-ladder/override`

```json
{
  "action_class": "rollback_deployment",
  "service": "frontend",
  "level": "trusted_with_approval",
  "reason": "operator_override"
}
```

### `GET /api/agent/slo`

Per-service-agent SLO posture.

---

## OTLP metrics receiver

### `POST /api/otlp/v1/metrics`

Accepts OTLP/HTTP JSON metrics. When `MESH_OTEL_RECEIVER_ENABLED=1`, an inbound payload becomes a Mesh run via the OTLP ingester. Optional bearer auth via `MESH_OTEL_RECEIVER_TOKEN`. Optional `x-mesh-alert-context` header (JSON) names the offending metric + baseline value.

---

## Vault

### `GET /api/vault/tree`

Vault filesystem tree mirror.

### `GET /api/vault/document?path=:vault_path`

Single document content.

---

## Research sessions

### `GET /api/research-sessions`

Filesystem autoresearch sessions under `MESH_RESEARCH_DIRECTORY`. Independent of run lifecycle.

### `GET /api/research-sessions/:session_id`

Manifest + final report when present.

### `GET /api/research-corpus`

Aggregate grounding and drift assessment across sessions.

---

## Reconciliation

### `GET /api/reconciliation/:run_id`

Reconciliation snapshot for a completed run — what changed, what reverted, what diverged.

### `GET /api/service-agents`

Registered service-agent inventory.

---

## Rules & rule learning

### `GET /api/rules/suggestions`

Decision rule suggestions inferred from operator overrides. Returns `[]` when rule learning is disabled or insufficient evidence has accumulated. **Suggestions never auto-apply** — paste approved ones into the policy file manually.

---

## Python client snippets

### Start a run and stream its events

```python
import httpx

with httpx.Client(base_url="http://127.0.0.1:8787") as client:
    run = client.post("/api/runs", json={
        "goal_id": "goal_default",
        "scenario_key": "search_latency_regression",
        "evaluation_mode": "native",
        "orchestration_mode": "native",
        "steering_mode": "approval_gate",
    }).json()

    with client.stream("GET", f"/api/stream/runs/{run['run_id']}") as stream:
        for line in stream.iter_lines():
            if line.startswith("data:"):
                print(line[5:].strip())
```

### Approve a run

```python
httpx.post(
    f"http://127.0.0.1:8787/api/runs/{run_id}/steer",
    json={"command": "approve", "metadata": {"operator": "alice"}},
)
```

### Send a webhook alert

```python
import httpx, json, hmac, hashlib

body = json.dumps({"alert": "HighErrorRate", "service": "frontend"}).encode()
sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
httpx.post(
    f"http://127.0.0.1:8787/api/webhooks/{source_id}",
    content=body,
    headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
)
```

### Query the topology graph

```python
neighbors = httpx.get(
    "http://127.0.0.1:8787/api/graph/neighbors/service/boutique/frontend",
    params={"edge_kind": "selects", "direction": "out"},
).json()
```

---

## Error model

| Status | Meaning |
|---|---|
| 400 | Bad request (malformed body, invalid steering command, unknown scenario) |
| 401 | Unauthorized (OTLP / webhook signature mismatch) |
| 403 | Forbidden (live execution disabled, allowlist violation) |
| 404 | Not found (run, goal, webhook source, etc.) |
| 409 | Conflict (steering command incompatible with current stage) |
| 422 | Validation error (policy violation, schema mismatch) |
| 500 | Internal error — see server log |
| 503 | Dependency unavailable (OTLP disabled, integration down) |

Errors include a JSON body:

```json
{"error": "run not found", "detail": "..." }
```

---

## CORS

CORS is permissive on `/api/*` and `/api/stream/*` (preflight responses include `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET,POST,DELETE,OPTIONS`, `Access-Control-Allow-Headers: Content-Type,Authorization,X-Mesh-Signature,X-Hub-Signature-256,X-Mesh-Alert-Context`). Lock this down with a reverse proxy in production.

---

## Internal Python API

Programmatic embedding (without the HTTP server) is supported through the runtime engine. Minimal example:

```python
from shared.mesh_runtime import RuntimeConfig
from services.runtime import MeshRuntimeEngine

config = RuntimeConfig(state_directory=".mesh-state", evaluation_mode="native", orchestration_mode="native")
engine = MeshRuntimeEngine(config=config)

run = engine.run_sync(
    raw_signal={"trigger_type": "metric_regression", "service": "frontend", ...},
    trigger_metadata={"source": "embedded"},
)
print(run.stage, run.decision, run.feedback)
```

See [`docs/extending-mesh.md`](./extending-mesh.md) for how to register custom diagnostic tools, probe selectors, and orchestration adapters.
