# Mesh Intelligence

An agentic incident-response and bounded-remediation control plane. Mesh ingests operational signals, investigates them with read-only tools, proposes one bounded decision, gates it on policy + operator approval, and only then executes through a narrow actuator allowlist. Every step is captured as an audited artifact in a Merkle-rooted event log and mirrored into a file-backed vault.

**What Mesh is:** a remediation **orchestration and safety layer** between signals and bounded actions (Kubernetes rollouts, feature-flag rollout %, ArgoCD sync/rollback, repo patches, systemd-over-SSH, incident creation, load balancer). Runs are structured, steerable, and auditable — explicit stages, evaluation gates, steering commands, Merkle-backed history.

**What Mesh is not:** a replacement for your observability, ITSM, or general-purpose automation engine. It doesn't replace **detection**; it structures **investigation → decision → evaluation → execution → feedback** for the remediation workloads you drive through it. The investigation loop is read-only; mutating actions only fire after evaluation permits, and by default that requires operator approval.

> See [`docs/codebase-overview.md`](./docs/codebase-overview.md) for a from-source orientation, and [`architecture.md`](./architecture.md) for the deep dive.

---

## Quick start

### One-command full stack

```bash
docker compose -f docker-compose.stack.yml up --build
```

Starts the Mesh API + UI, embedded k3s, a bootstrap job that seeds a workload, and `mesh-smoke` (which seeds a CrashLoop and runs a live recovery). API at `http://127.0.0.1:8787`.

Full stack runbook: [`docs/all-in-one-compose-stack.md`](./docs/all-in-one-compose-stack.md).

### Manual local server

```bash
python3 setup_integrations.py        # detect Promptfoo / Goose / Hermes / Evo CLIs
cd web && npm install && npm run build && cd ..
python3 run_server.py                # http://127.0.0.1:8787
```

Optional install attempt for supported dependencies:

```bash
python3 setup_integrations.py --install-missing
```

`run_server.py` does not auto-start watchers. To start them after boot:

```bash
curl -X POST http://127.0.0.1:8787/api/watch/start
```

For the realtime control plane that starts watchers at boot:

```bash
PYTHONPATH=. uv run python -c "from control_plane_server import serve_forever; serve_forever()"
```

---

## Running Mesh

### Listen on a host and port

```bash
export MESH_SERVER_HOST=0.0.0.0
export MESH_SERVER_PORT=8787

curl http://127.0.0.1:8787/api/health
curl http://127.0.0.1:8787/api/readiness
```

### Watch Kubernetes deployments

The watcher polls with `kubectl`, normalizes unhealthy deployments into runs, and deduplicates per target and cooldown.

```bash
export MESH_WATCH_ENABLED=1
export MESH_WATCH_INTERVAL_SECONDS=30
export MESH_WATCH_COOLDOWN_SECONDS=300
export MESH_WATCH_TARGETS='[
  {
    "deployment_name": "frontend",
    "namespace": "search",
    "kube_context": "mesh-compose",
    "cooldown_seconds": 300
  }
]'
export MESH_KUBECTL_COMMAND=kubectl
```

Live Kubernetes mutations are off by default. To allow bounded rollout actions, enable execution and set narrow allowlists:

```bash
export MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1
export MESH_KUBERNETES_ALLOWED_CONTEXTS=mesh-compose
export MESH_KUBERNETES_ALLOWED_NAMESPACES=search
```

Leave `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=0` to propose + evaluate without mutating the cluster.

### Receive webhooks (HMAC-verified)

Register a source, then send vendor alerts. Mesh verifies an HMAC signature on the raw body via `X-Mesh-Signature` or GitHub-style `X-Hub-Signature-256`.

```bash
curl -X POST http://127.0.0.1:8787/api/webhook-sources \
  -H 'Content-Type: application/json' \
  --data-binary @fixtures/webhook_templates/prometheus.json

curl -X POST http://127.0.0.1:8787/api/webhooks/prometheus \
  -H 'Content-Type: application/json' \
  -H 'X-Mesh-Signature: sha256=<hex>' \
  -d '{ "status": "firing", "alerts": [ { "fingerprint": "frontend-high-error-rate" } ],
        "commonLabels": { "alertname": "HighErrorRate", "service": "frontend", "env": "prod" } }'
```

### Receive OTLP metrics

```bash
export MESH_OTEL_RECEIVER_ENABLED=1
export MESH_OTEL_RECEIVER_TOKEN=dev-token   # optional bearer token
```

```text
POST /v1/metrics                            # OTLP/HTTP JSON
Authorization: Bearer dev-token             # when MESH_OTEL_RECEIVER_TOKEN is set
x-mesh-alert-context: {"metric":"…","service":"…","baseline":…}   # optional, JSON-encoded
```

### Enable read-only investigation tools

Optional. When configured, Mesh exposes them to the read-only investigation harness:

```bash
export MESH_PROMETHEUS_URL=http://localhost:9090
export MESH_LOKI_URL=http://localhost:3100
export MESH_JAEGER_URL=http://localhost:16686
export MESH_PG_DSN=postgresql://user:pass@localhost:5432/app
export MESH_AWS_TOOLS_ENABLED=1
export MESH_MCP_SERVERS=name=stdio://path/to/server
# GitHub pack auto-enables when `gh auth status` succeeds.
# kubectl pack auto-enables when kubectl + kubeconfig are reachable.
# topology pack is always available.
```

---

## Pipeline & stages

Each run produces a fixed chain of first-class artifacts:

```
raw signal
  └─► ingest                              → normalized_event
  └─► trigger                             → trigger
  └─► signal-profile resolve              → SignalProfile
  └─► investigation planner               → investigation_plan
  └─► evidence assembly                   → evidence_pack
  └─► investigation harness (read-only)   → investigation_report
  └─► scenario analysis                   → scenario_analysis (+ memory_compaction)
  └─► hypothesis engine + decision        → decision + ranked_hypotheses
  └─► profile RCA builder                 → rca_report
  └─► evaluation (policy/risk/rollback)   → evaluation
  └─► [operator approval gate]
  └─► orchestrator → actuators            → execution_record
  └─► feedback observer                   → feedback_record
```

Run stages (from `services/runtime.py` and `services/control_plane.py`):

```
queued → ingesting → trigger_ready → evidence_pack_ready → investigation_ready
       → scenario_analysis_ready → decision_ready → evaluation_ready
       → awaiting_operator → executing → feedback_ready
       → completed | failed | cancelled | no_trigger | recovery_spawned
```

Operator steering commands are bounded: `approve`, `cancel`, `pause_after_stage`, `resume`, `set_auto_mode`, `override_decision`, `override_execution_parameters`, `attach_note`. Overrides always re-enter evaluation. Approval never bypasses policy or rollback constraints.

---

## Signal profiles

Mesh is signal-agnostic: one harness, one safety model, many signal types. A `SignalProfile` binds a signal + trigger type to strategy implementations (planner, evidence, RCA — and progressively ingest/trigger/decision/feedback as those migrate from monolithic per-signal branches).

| Signal | Trigger | Status |
| --- | --- | --- |
| `reth_node` | `reth_node_degraded` | Specialized planner, typed evidence probes, specialized RCA |
| `kubernetes_deployment_issue` | `kubernetes_deployment_unhealthy` | Harness planner, structured evidence, generic RCA |
| `otel_metric_regression` | `otel_metric_regression` | Harness planner, structured evidence, generic RCA |
| `webhook_alert` | `webhook_alert_firing` | Harness planner, structured evidence, generic RCA |
| `feature_flag` | `feature_flag_performance_regression` | Harness planner, structured evidence, generic RCA |
| unknown / unregistered | `generic_signal_firing` | Generic evidence + RCA, **unconditional escalation** |

Generic is the safety floor: unknown signals are investigated and summarized but cannot auto-act.

---

## Investigation harness

`services/investigation/harness/` runs a planner + tool-registry loop. The `LoopCritic` rejects unknown, malformed, mutating, or over-budget calls. Always-on tool packs auto-register when their backing config/env is present:

| Pack | Surface | Backing config |
| --- | --- | --- |
| `prometheus` | PromQL instant/range, label values | `MESH_PROMETHEUS_URL` |
| `kubectl` | get / describe / logs (read-only) | kubectl on PATH + kubeconfig |
| `aws` | describe / list (read-only) | `MESH_AWS_TOOLS_ENABLED=1` |
| `github` | issues, PRs, file reads | `gh auth status` succeeds |
| `loki` | LogQL labels + log ranges | `MESH_LOKI_URL` |
| `jaeger` | trace search, service map | `MESH_JAEGER_URL` |
| `postgres` | SELECT-only SQL | `MESH_PG_DSN` + `psql` |
| `mcp` | bridged MCP tool servers | `MESH_MCP_SERVERS` |
| `topology` | InfraGraph lineage / neighbors | always-on |
| `cloudops` | snapshot analyzers (admission events, service routing, node dataplane) | per-run snapshot |
| `reth` | peer-starvation + node probes | per-trigger Reth payload |

Mutating actions are policy-gated and never reachable from the investigation loop — they ship through actuators after evaluation passes.

Harness reference: [`docs/investigation-harness.md`](./docs/investigation-harness.md) · Extending: [`docs/extending-mesh.md`](./docs/extending-mesh.md).

---

## Decision, evaluation, actuators

- **Decision** (`services/decision/`). `HypothesisEngine` does deterministic RCA scoring. LLM proposers (`llm_fallback.py`, `llm_reasoning.py`) can contribute candidates but cannot bypass policy or pick production actions. Output: exactly one decision (`no_action`, `reduce_rollout`, `disable_flag`, `rollback_deployment`, `restart_deployment`, `scale_deployment`, `patch_resources`, `restart_systemd_service`, `open_incident`, `escalate`, …).
- **Evaluation** (`services/evaluation/`). Policy / confidence / risk / credential / rollback / integration-readiness checks. In approval-gate mode runs pause at `awaiting_operator` before execution.
- **Actuators** (`services/actuators/`). Bounded surfaces: `feature_flag` (rollout %), `incident`, `kubernetes` (rollout restart/undo, gated), `argocd` (sync, rollback), `repo_patch`, `systemd_ssh` (approval-gated), `load_balancer`.

External agent bridges (review-before-actuation, or read-only proposals): Goose, Hermes, LatentMAS (vendored Rust), DeepAgents, Evo (external CLI), plus an `agent_mesh.py` proposal registry.

---

## HTTP API

The server is a stdlib `http.server.ThreadingHTTPServer` exposing JSON + SSE. Selected routes (full reference: [`docs/api-reference.md`](./docs/api-reference.md)):

```
GET    /api/health                              liveness + build info
GET    /api/readiness                           integration readiness
GET    /api/scenarios                           bundled fixture scenarios
GET    /api/simulations | /api/benchmarks       catalogs

POST   /api/goals                               create a goal
GET    /api/goals                               list goals

POST   /api/runs                                start a run (signal_payload | scenario_key | otlp_payload)
GET    /api/runs                                list runs
GET    /api/runs/:id                            run snapshot
GET    /api/runs/:id/events                     paged event log
POST   /api/runs/:id/steer                      operator steering
GET    /api/runs/:id/scenario-analysis          analyzer evidence graph
GET    /api/runs/:id/evidence-graph             evidence DAG
GET    /api/runs/:id/agent-tasks                agent-task artifacts
GET    /api/runs/:id/reasoning-bank             reasoning-bank entries
GET    /api/runs/:id/memory-crystallization     memory crystallization artifacts
GET    /api/runs/:id/merkle                     Merkle root + tree
GET    /api/runs/:id/merkle/proof/:event_id     inclusion proof

GET    /api/stream/runs/:id                     SSE stream of run events
GET    /api/stream/system                       SSE stream of system events

GET    /api/watchers · POST /api/watch/{start,stop} · POST /api/watchers/:name/{start,stop}
POST   /api/webhook-sources · DELETE /api/webhook-sources/:id
POST   /api/webhooks/:source_id                 HMAC-verified ingest
POST   /v1/metrics                              OTLP/HTTP JSON (opt-in)

GET    /api/graph/{status,snapshot} · POST /api/graph/refresh
GET    /api/graph/neighbors/:kind/:ns/:name · /api/graph/node/* · /api/graph/affected/*

GET    /api/trust-ladder · POST /api/trust-ladder/override
GET    /api/rules/suggestions                   admin (manual policy-paste workflow)
GET    /api/memory/{active,query,graph} · POST /api/memory/maintenance/run
GET    /api/research-sessions · /api/research-corpus
GET    /api/service-agents · /api/agent/slo · /api/alerts · /metrics
GET    /api/vault/tree · /api/vault/document
```

**Minimal Python client:**

```python
import httpx

resp = httpx.post("http://127.0.0.1:8787/api/runs", json={
    "goal_id": "goal_default",
    "scenario_key": "search_latency_regression",
    "evaluation_mode": "native",
    "orchestration_mode": "native",
    "steering_mode": "approval_gate",
})
run_id = resp.json()["run_id"]

with httpx.stream("GET", f"http://127.0.0.1:8787/api/stream/runs/{run_id}") as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            print(line)
```

---

## Runtime modes

Each run picks one evaluation mode and one orchestration mode.

**Evaluation**
- `native` — in-process trajectory + verifier checks, behavioral scorers, reasoning-bank memory.
- `promptfoo` — compatibility mode for Promptfoo-backed eval artifacts. Same Mesh trajectory evaluation underneath; kept so older stacks don't break.

**Orchestration**
- `native` — in-process bounded actuators, full audit + persistence.
- `goose` — CLI-bridged Goose review step before bounded local actuation.
- `hermes` — CLI-bridged Hermes review step before bounded local actuation. Default image bundles the CLI.

**Proposal lane (not an orchestration mode)**
- `evo` — Mesh probes the configured `evo-hq-cli` and records an agent-task recommendation for bounded code-remediation runs. Launched via a separate steering command, not normal run progression.

CLI bridge details: [`docs/integrations.md`](./docs/integrations.md).

---

## Configuration

All runtime configuration lives in env vars (full template: `.env.example`). Highlights:

```bash
# Server + state
MESH_SERVER_HOST=0.0.0.0
MESH_SERVER_PORT=8787
MESH_STATE_DIRECTORY=.mesh-runtime-state
MESH_VAULT_PATH=.mesh-runtime-state/vault
MESH_STATE_BACKEND=file                 # or "postgres"
MESH_DATABASE_URL=postgresql://...      # required when MESH_STATE_BACKEND=postgres

# Modes
MESH_DEFAULT_STEERING_MODE=approval_gate
MESH_EVALUATION_MODE=native
MESH_ORCHESTRATION_MODE=native
MESH_AGENT_FABRIC_MODE=native           # or "deepagents"

# Diagnostic tool packs (auto-enable when set)
MESH_PROMETHEUS_URL=http://prom:9090
MESH_LOKI_URL=http://loki:3100
MESH_JAEGER_URL=http://jaeger:16686
MESH_PG_DSN=postgresql://...
MESH_AWS_TOOLS_ENABLED=1
MESH_MCP_SERVERS=name=stdio://path/to/server

# Ingest surfaces
MESH_OTEL_RECEIVER_ENABLED=0            # POST /v1/metrics OTLP receiver
MESH_OTEL_RECEIVER_TOKEN=               # optional bearer token

# Live Kubernetes execution (off by default)
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=0
MESH_KUBERNETES_ALLOWED_CONTEXTS=k3d-mesh
MESH_KUBERNETES_ALLOWED_NAMESPACES=default,boutique
```

When `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1` and the allowlist permits, `rollback_deployment` maps to `kubectl rollout undo` and `restart_deployment` to `kubectl rollout restart`. Both stay constrained by `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES`.

Postgres backend: see [`docs/postgres-persistence.md`](./docs/postgres-persistence.md).

---

## Repository layout

```
mesh-intelligence/
├── control_plane_server.py        # stdlib HTTP + SSE server
├── run_server.py                  # local dev API entrypoint
├── run_tui.py                     # curses terminal UI
├── setup_integrations.py          # detect / install CLI integrations
├── services/
│   ├── runtime.py                 # MeshRuntimeEngine — pipeline orchestration
│   ├── control_plane.py           # RunCoordinator — runs, approvals, watchers, vault, webhooks
│   ├── pipeline.py                # FirstSlicePipeline thin wrapper
│   ├── ingest/                    # raw payload → EventEnvelope
│   ├── trigger/                   # envelope → Trigger
│   ├── evidence/                  # EvidencePack assembly + Reth probe registry
│   ├── investigation/
│   │   ├── harness/               # planner + critic + tool registry + loop
│   │   ├── tools/                 # always-on read-only tool packs
│   │   ├── cloudops_*, reth_planner, llm_planner, rca, topology_builder
│   ├── scenario_analysis/
│   ├── decision/                  # HypothesisEngine + LLM proposers
│   ├── evaluation/                # policy gates, promptfoo bridge, SRE judge
│   ├── orchestrator/              # native + goose/hermes/latentmas/deepagents/evo bridges
│   │   └── service_agents/        # agent mesh registry
│   ├── actuators/                 # k8s, argocd, systemd-ssh, repo_patch, load_balancer
│   ├── feedback/                  # Prometheus + k8s post-action observers
│   ├── observer/                  # LLM observer (redacted) for simulation
│   ├── watchers/                  # k8s + base watcher daemons
│   ├── benchmark/                 # CloudOpsBench / LogHub / SREGym + gates + scoring
│   ├── signal_correlator.py · signal_history/ · signal_profiles/
│   └── simulation/ · skills/
├── shared/mesh_runtime/
│   ├── schemas/                   # JSON Schema source of truth
│   ├── contracts.py · config.py
│   ├── infra_graph.py             # typed topology graph
│   ├── merkle.py · vault.py       # audit
│   ├── postgres_state.py · state.py · state_store_factory.py
│   ├── reasoning_bank.py · learning.py · trust_ladder.py
│   └── alert_store.py · webhook_templates.py · …
├── web/                           # React 18 + Vite + TS browser UI
├── tui.py                         # textual TUI implementation
├── simulation/                    # synthetic Reth fault-injection harness
├── benchmarks/                    # scenarios, corpora, gate config
├── fixtures/                      # signals, decisions, webhook templates, monitoring corpus, codebases
├── policies/                      # autonomy, metric-actions, protected-scope, reth-node, rollback
├── plugins/mesh-intelligence/     # skills bundle
├── latent-mesh/LatentMAS/         # vendored Rust multi-agent subsystem (cargo)
├── deepagents/                    # vendored DeepAgents package (editable install)
├── migrations/                    # state-store migrations
├── scripts/                       # ops / CI / contract-gen
├── tests/                         # pytest-compatible (unittest-based)
└── docs/
```

---

## Verification

Canonical validation gates (also in [`AGENTS.md`](./AGENTS.md)):

```bash
# Python tests
PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest

# Lint + typecheck (cache in /tmp if default cache dirs aren't writable)
RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict \
  --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'

# Web build
npm --prefix web ci
npm --prefix web run build

# Rust (only when touching latent-mesh/LatentMAS/)
(cd latent-mesh/LatentMAS && cargo test && cargo clippy)
```

Note: `mypy --strict` is currently scoped (per `pyproject.toml`) to `services/decision/hypothesis_engine.py`. The rest of the runtime is being typed incrementally — this is a partial gate by design, not whole-repo proof.

Targeted subsets are easy to run:

```bash
uv run python -m unittest tests.test_investigation_harness
uv run python -m unittest tests.test_cloudops_analyzers

# Live Kubernetes E2E (requires k3d/k3s + kubeconfig)
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1 \
  uv run python -m unittest tests.test_kubernetes_live_e2e
```

---

## Documentation index

| Topic | File |
| --- | --- |
| From-source codebase overview | [`docs/codebase-overview.md`](./docs/codebase-overview.md) |
| Architecture deep-dive | [`architecture.md`](./architecture.md) |
| API + runtime map | [`docs/architecture/api-and-runtime-map.md`](./docs/architecture/api-and-runtime-map.md) |
| HTTP API reference | [`docs/api-reference.md`](./docs/api-reference.md) |
| Investigation harness | [`docs/investigation-harness.md`](./docs/investigation-harness.md) |
| Extending Mesh | [`docs/extending-mesh.md`](./docs/extending-mesh.md) |
| All-in-one compose stack | [`docs/all-in-one-compose-stack.md`](./docs/all-in-one-compose-stack.md) |
| CLI integrations (Goose / Hermes / Promptfoo / Evo) | [`docs/integrations.md`](./docs/integrations.md) |
| Postgres persistence | [`docs/postgres-persistence.md`](./docs/postgres-persistence.md) |
| Production runbook | [`docs/production-live-runbook.md`](./docs/production-live-runbook.md) |
| Memory + reasoning bank | [`docs/memory-architecture.md`](./docs/memory-architecture.md) · [`docs/reasoning-bank.md`](./docs/reasoning-bank.md) |
| Remediation safety loop | [`docs/remediation-safety-loop.md`](./docs/remediation-safety-loop.md) |
| Scenario analysis | [`docs/scenario-analysis.md`](./docs/scenario-analysis.md) |

---

## License & contributing

Contributor expectations: [`AGENTS.md`](./AGENTS.md).

**External messaging:** prefer **policy-guided**, **bounded**, and **intent-driven** remediation. Avoid "self-healing" or generic "AI-powered" framing — Mesh runs are operator-steerable and evaluation-gated unless explicit interruptible auto mode is enabled.
