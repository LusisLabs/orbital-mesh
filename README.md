# Mesh Intelligence

A **local, policy-guided operator control plane** for **bounded** closed-loop remediation, with an **agentic SRE investigation harness** wired into every trigger.

Mesh ingests infrastructure signals → investigates with read-only tools (Prometheus, kubectl, AWS, GitHub, Loki, Jaeger, Postgres, MCP, topology graph) → proposes a decision → evaluates it against policy and quality gates → pauses for **operator approval** by default → executes through a bounded actuator → records feedback. Every step is captured in a Merkle-rooted event log and mirrored into an Obsidian-compatible vault for audit.

**What Mesh is:** a remediation **orchestration and safety layer** between signals and bounded actions (feature flags, incident routing, Kubernetes rollouts). Runs are **structured, steerable, and auditable** — explicit stages, evaluation gates, steering commands, Merkle-backed event history.

**What Mesh is not:** a replacement for your observability, ITSM, or general-purpose automation engine. It doesn't replace **detection**; it structures **decision → evaluation → execution → feedback** for the remediation workloads you drive through it.

---

## Quick start

### One-command full stack

```bash
docker compose -f docker-compose.stack.yml up --build
```

This starts Mesh, embedded k3s, a bootstrap job that seeds a search/semantic-search workload, `mesh-ui`, and `mesh-smoke` (which seeds a CrashLoop and launches a live Mesh recovery run). The API is at `http://127.0.0.1:8787`.

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

---

## Architecture

```
signal ─┬─→ trigger ─→ investigation ─→ decision ─→ evaluation ─┬─→ approval ─→ execution ─→ feedback
        │                  │                                    │       gate          │
        │                  ↓                                    │                     ↓
        │       agentic tool loop                               │            Kubernetes / flags /
        │       (read-only, LLM-driven)                         │            incidents (bounded)
        │                                                       │
        └─────────────→ Merkle event log + Obsidian vault ←─────┘
```

Every run advances through explicit stages:

```
queued → ingesting → trigger_ready → decision_ready → evaluation_ready
       → awaiting_operator → executing → feedback_ready
       → completed | failed | cancelled | recovery_spawned
```

Operator steering commands are bounded: `approve`, `cancel`, `pause_after_stage`, `resume`, `set_auto_mode`, `override_decision`, `override_execution_parameters`, `attach_note`. Overrides always re-enter evaluation. Approval never bypasses policy or rollback constraints.

Deeper architecture: [`architecture.md`](./architecture.md) · [`docs/architecture/api-and-runtime-map.md`](./docs/architecture/api-and-runtime-map.md).

---

## Agentic SRE harness

On **every trigger** (not just benchmark scenarios), Mesh wires an investigation harness with cross-domain read-only tools the LLM can call:

| Pack | Tools | Backing config |
|---|---|---|
| `prometheus` | range/instant query, label values | `RuntimeConfig.prometheus_url` |
| `kubectl` | get/describe/logs (read-only) | `kubectl` on PATH + kubeconfig |
| `aws` | describe/list (read-only) | `MESH_AWS_TOOLS_ENABLED=1` |
| `github` | issues, PRs, file reads | `gh auth status` succeeds |
| `loki` | log range queries | `MESH_LOKI_URL` |
| `jaeger` | trace search, service map | `MESH_JAEGER_URL` |
| `postgres` | SELECT-only queries | `MESH_PG_DSN` + `psql` |
| `mcp` | bridged MCP tool servers | `MESH_MCP_SERVERS` |
| `topology` | graph lineage, service→pods, neighbors | always-on |
| `cloudops` | snapshot analyzers (admission events, service routing, node dataplane) | per-run snapshot |
| `reth` | peer-starvation probes | per-trigger Reth payload |

The harness enforces read-only via a `LoopCritic`. Mutating actions are policy-gated and never reachable from the investigation loop — they ship through the actuator layer after evaluation passes.

Full harness reference: [`docs/investigation-harness.md`](./docs/investigation-harness.md). Extending: [`docs/extending-mesh.md`](./docs/extending-mesh.md).

---

## HTTP API

The server exposes a JSON+SSE control surface. Selected routes:

```
GET    /api/health                              liveness
GET    /api/readiness                           integration readiness
GET    /api/scenarios                           bundled fixture scenarios
GET    /api/goals                               list goals
POST   /api/goals                               create goal
GET    /api/runs                                list runs
POST   /api/runs                                start a run
GET    /api/runs/:id                            run detail
POST   /api/runs/:id/steer                      send a steering command
GET    /api/runs/:id/events                     event log
GET    /api/runs/:id/scenario-analysis          analyzer evidence graph
GET    /api/runs/:id/merkle                     Merkle root + tree
GET    /api/runs/:id/merkle/proof/:event_id     Merkle inclusion proof
GET    /api/stream/runs/:id                     SSE stream of run events
GET    /api/stream/system                       SSE stream of system events
GET    /api/graph/snapshot                      InfraGraph snapshot
GET    /api/graph/neighbors/:kind/:ns/:name     graph traversal
GET    /api/vault/tree | /document              vault read API
GET    /api/research-sessions                   filesystem autoresearch
POST   /api/webhook-sources                     register a webhook ingester
```

Full reference (every route, request/response shapes, SSE format, error codes): [`docs/api-reference.md`](./docs/api-reference.md).

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

## Modes

Each run chooses one evaluation mode and one orchestration mode.

**Evaluation:**
- `native` — deterministic trajectory checks, task traces, behavioral scorers, verifier output, reasoning-bank memory.
- `promptfoo` — legacy-compatible mode name; pass/fail is still the same Mesh trajectory evaluation. Kept so older stacks don't break.

**Orchestration:**
- `native` — in-process bounded actuators with full audit and persistence.
- `goose` — CLI-bridged Goose review step before bounded local actuation.
- `hermes` — CLI-bridged Hermes review step before bounded local actuation. Default image bundles the CLI.

**Proposal lane (not an orchestration mode):**
- `evo` — Mesh probes the configured `evo-hq-cli`, records an agent-task recommendation for bounded code-remediation runs. Launched via a separate operator steering command, not by normal run progression.

CLI bridge details: [`docs/integrations.md`](./docs/integrations.md).

---

## Configuration

All runtime configuration lives in env vars (full template in `.env.example`). Key knobs:

```bash
MESH_SERVER_HOST=0.0.0.0
MESH_SERVER_PORT=8787
MESH_STATE_DIRECTORY=.mesh-runtime-state
MESH_VAULT_PATH=.mesh-runtime-state/vault
MESH_STATE_BACKEND=file                 # or "postgres"
MESH_DATABASE_URL=postgresql://...      # when MESH_STATE_BACKEND=postgres

MESH_DEFAULT_STEERING_MODE=approval_gate
MESH_EVALUATION_MODE=native
MESH_ORCHESTRATION_MODE=native
MESH_AGENT_FABRIC_MODE=native           # or "deepagents"

# Diagnostic tool packs (always-on when set)
MESH_PROMETHEUS_URL=http://prom:9090
MESH_LOKI_URL=http://loki:3100
MESH_JAEGER_URL=http://jaeger:16686
MESH_PG_DSN=postgresql://...
MESH_AWS_TOOLS_ENABLED=1
MESH_MCP_SERVERS=name=stdio://path/to/server

# Live Kubernetes execution (off by default)
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=0
MESH_KUBERNETES_ALLOWED_CONTEXTS=k3d-mesh
MESH_KUBERNETES_ALLOWED_NAMESPACES=default,boutique
```

When `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1` and the allowlist permits, `rollback_deployment` maps to `kubectl rollout undo` and `restart_deployment` to `kubectl rollout restart`. Both stay constrained by `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES`.

---

## Repository layout

```
mesh-intelligence/
├── control_plane_server.py        # HTTP + SSE server (stdlib http.server)
├── run_server.py                  # browser control-plane entrypoint
├── run_tui.py                     # curses terminal UI
├── run_first_slice.py             # synchronous stdin/stdout runner
├── setup_integrations.py          # detect / install CLI integrations
├── services/
│   ├── runtime.py                 # MeshRuntimeEngine — stage orchestration
│   ├── ingest/                    # signal → audited trigger
│   ├── trigger/                   # trigger gating
│   ├── investigation/             # agentic SRE harness
│   │   ├── harness/               # ToolRegistry, LoopCritic, planner
│   │   ├── tools/                 # 11 domain packs
│   │   ├── cloudops_analyzers.py  # K8sGPT-style analyzers
│   │   └── topology_builder.py    # InfraGraph populator
│   ├── decision/                  # rule + LLM fallback proposers
│   ├── evaluation/                # trajectory + scorer gates
│   ├── orchestrator/              # native / goose / hermes / deepagents
│   ├── actuators/                 # Kubernetes / flags / incidents
│   ├── feedback/                  # post-execution observers
│   └── benchmark/                 # CloudOpsBench / Reth scenarios
├── shared/mesh_runtime/
│   ├── config.py                  # RuntimeConfig
│   ├── infra_graph.py             # typed K8s topology graph
│   ├── merkle.py                  # event-log Merkle tree
│   ├── vault.py                   # Obsidian-compatible vault mirror
│   └── state.py                   # run state store
├── web/                           # React/Vite browser control plane
├── fixtures/                      # scenario JSON
├── policies/                      # remediation policy JSON
├── tests/
└── docs/
```

---

## Verification

```bash
# Python tests (fast)
uv run python -m unittest discover tests -v

# Targeted subsets
uv run python -m unittest tests.test_investigation_harness
uv run python -m unittest tests.test_cloudops_analyzers
uv run python -m unittest tests.test_topology

# Browser UI
cd web && npm test && cd ..

# Live Kubernetes E2E (requires k3d/k3s + kubeconfig)
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1 \
  uv run python -m unittest tests.test_kubernetes_live_e2e
```

CI runs the Python test suite on every PR. See [`AGENTS.md`](./AGENTS.md) for contributor expectations.

---

## Documentation index

| Topic | File |
|---|---|
| Architecture deep-dive | [`architecture.md`](./architecture.md) |
| API + runtime map | [`docs/architecture/api-and-runtime-map.md`](./docs/architecture/api-and-runtime-map.md) |
| HTTP API reference | [`docs/api-reference.md`](./docs/api-reference.md) |
| Extending Mesh (plug-ins) | [`docs/extending-mesh.md`](./docs/extending-mesh.md) |
| Investigation harness | [`docs/investigation-harness.md`](./docs/investigation-harness.md) |
| All-in-one compose stack | [`docs/all-in-one-compose-stack.md`](./docs/all-in-one-compose-stack.md) |
| CLI integrations (Goose/Hermes/Promptfoo/Evo) | [`docs/integrations.md`](./docs/integrations.md) |
| Postgres persistence | [`docs/postgres-persistence.md`](./docs/postgres-persistence.md) |
| Production runbook | [`docs/production-live-runbook.md`](./docs/production-live-runbook.md) |
| Memory + reasoning bank | [`docs/memory-architecture.md`](./docs/memory-architecture.md) · [`docs/reasoning-bank.md`](./docs/reasoning-bank.md) |
| Safety loop | [`docs/remediation-safety-loop.md`](./docs/remediation-safety-loop.md) |
| Scenario analysis | [`docs/scenario-analysis.md`](./docs/scenario-analysis.md) |
| Research sessions | [`docs/research-intelligence.md`](./docs/research-intelligence.md) |
| First closed-loop contract | [`first-closed-loop-contract.md`](./first-closed-loop-contract.md) |

---

## License & contributing

Contributor guide: [`AGENTS.md`](./AGENTS.md). Demo walkthrough: [`demo.md`](./demo.md). Plan + roadmap: [`plan.md`](./plan.md).

**External messaging:** prefer **policy-guided**, **bounded**, and **intent-driven** remediation. Avoid **"self-healing"** or generic **"AI-powered"** framing — Mesh runs are **operator-steerable** and **evaluation-gated** unless explicit interruptible auto mode is enabled.
