# Mesh Intelligence

`mesh-intelligence` is a **local, policy-guided operator control plane** for **bounded** closed-loop remediation. It ingests infrastructure signals, decides on a remediation path, evaluates the decision against policy and quality gates, pauses for **operator steering** before actuation by default, executes through a bounded orchestration layer, records feedback, persists run memory into an Obsidian-compatible vault, and exposes continuous Merkle roots and proofs for the run log.

## Positioning and scope

**What Mesh is:** a remediation **orchestration and safety layer** between **signals** (fixtures, custom JSON, live Kubernetes harvest) and **bounded actions** (feature flags, incidents, Kubernetes rollouts). It makes runs **structured, steerable, and auditable**: explicit stages, evaluation gates, steering commands, and (for supported paths) Merkle-backed event history.

**What Mesh is not:** a replacement for observability/monitoring, ITSM, or your general-purpose automation engine (Ansible, Terraform, etc.) taken as a whole. It does not replace **detection**; it structures **decision → evaluation → execution → feedback** for remediation-shaped workloads you drive through this control plane.

**External messaging:** Prefer **policy-guided**, **bounded**, and **intent-driven** remediation. Avoid hype terms such as **“self-healing”** or generic **“AI-powered”**; Mesh runs are **operator-steerable** and **evaluation-gated** unless you explicitly choose interruptible auto mode.

## Kubernetes rollback scope (live execution)

When `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED` is set and allowlists permit the target, **`rollback_deployment`** maps to **`kubectl rollout undo`** for the Deployment (previous revision). That **only** moves the Deployment’s rollout back; it does **not** by itself restore full arbitrary application state beyond what the workload’s images and ReplicaSet history imply. **`restart_deployment`** maps to **`kubectl rollout restart`**. Both are additionally constrained by **`MESH_KUBERNETES_ALLOWED_CONTEXTS`** and **`MESH_KUBERNETES_ALLOWED_NAMESPACES`**.

## Rubric (repository-aligned, publicly defensible)

These are the dimensions this codebase is built to support; they match a disciplined launch narrative without unverifiable “#1” claims:

| Dimension | Mesh behavior |
|-----------|----------------|
| Execution safety | Approval gate by default; optional interruptible auto; Kubernetes live execution off by default; allowlists when live |
| Policy / evaluation | Dedicated evaluation stage; native or Promptfoo evaluation; overrides re-enter evaluation before execution |
| Operator control | Steering surface (approve, cancel, override decision/parameters, pause, notes) |
| Auditability | Merkle roots and per-event proofs; vault mirroring of run memory |

---

## Tldr
Ingress: client starts run via POST /api/runs using signal_payload or scenario_key.
Ingest stage: IngestService.normalize_signal(...) creates normalized event envelope.
Trigger stage: TriggerService.detect(...) decides if signal is actionable.
no trigger -> run ends no_trigger/completed
Decision stage: DecisionService.decide(...) picks bounded action (no_action, reduce_rollout, disable_flag, escalate, etc.).
Evaluation stage: EvaluationService.evaluate(...) applies policy/business/quality checks (Promptfoo when enabled).
Operator gate: enters awaiting_operator if required by steering mode/pause points.
Execution stage: OrchestratorService.execute(...) calls native path or Goose bridge/adapter.
Feedback stage: FeedbackService.record(...) writes outcome signals (10m/30m observations, recurrence/guardrails).
Persistence/streaming: each stage emits typed events, persisted + streamed over SSE, mirrored to vault, Merkle updated.
---

The system now ships with two operator surfaces:

- Browser-first control plane served by `run_server.py`
- Curses TUI served by `run_tui.py` for terminal-native inspection

The browser UI is the primary interface.

## What It Does

- Runs the existing feature-flag remediation loop end to end
- Streams stage-by-stage run updates through HTTP + SSE
- Pauses at the approval gate before execution by default
- Supports bounded steering commands while a run is in progress
- Persists goals, runs, notes, and artifact state in structured runtime storage
- Mirrors that memory into a fixed Obsidian-compatible vault layout
- Computes Merkle roots for canonical run events and returns proofs per event
- Integrates with a managed local GitNexus sidecar for code/process context
- Supports three runtime modes:
  - `native`
  - `promptfoo`
  - `goose`

## Runtime Model

Each run advances through explicit stages:

1. `queued`
2. `ingesting`
3. `trigger_ready` or `no_trigger`
4. `decision_ready`
5. `evaluation_ready`
6. `awaiting_operator`
7. `executing`
8. `feedback_ready`
9. `completed`, `failed`, or `cancelled`

Steering is bounded. Supported commands are:

- `approve`
- `cancel`
- `pause_after_stage`
- `resume`
- `set_auto_mode`
- `override_decision`
- `override_execution_parameters`
- `attach_note`

Overrides always re-enter evaluation before execution. Approval never bypasses policy validation or rollback constraints.

## Runtime Modes

### `native`

Default local mode. Uses in-process adapters with real local persistence and audit semantics. This is the mode that works immediately without external CLIs.

### `promptfoo`

CLI-backed evaluation mode. `setup_integrations.py` resolves this to a bridge command that runs a real Promptfoo eval and returns the mesh evaluation contract. Readiness is reported explicitly through the API and UI.

### `goose`

CLI-backed orchestration mode. `setup_integrations.py` resolves this to a bridge command that runs a real Goose review step before bounded local actuation. When Ollama is installed, the bootstrap path prefers the first working local model, starting with `qwen2.5:0.5b`. Readiness is reported explicitly through the API and UI.

## Repository Layout

```text
mesh-intelligence/
├── Dockerfile                       # production image (Vite UI + Python server)
├── docker-compose.yml               # persisted state volume + health checks
├── .env.example                     # configuration template
├── control_plane_server.py          # local HTTP + SSE server
├── run_server.py                    # browser control-plane entrypoint
├── run_first_slice.py               # synchronous stdin/stdout loop runner
├── run_tui.py                       # terminal UI entrypoint
├── setup_integrations.py            # bootstrap Promptfoo / Goose / GitNexus config
├── swarmclaw/                       # optional Next.js operator stack (separate surface)
├── services/
│   ├── control_plane.py             # long-lived coordinator and steering logic
│   ├── runtime.py                   # shared stage primitives used by pipeline + coordinator
│   ├── pipeline.py                  # synchronous convenience wrapper
│   ├── evaluation/
│   ├── orchestrator/
│   ├── feedback/
│   ├── decision/
│   ├── trigger/
│   └── ingest/
├── shared/mesh_runtime/
│   ├── config.py
│   ├── control_plane_models.py
│   ├── control_plane_state.py
│   ├── integrations.py
│   ├── merkle.py
│   ├── vault.py
│   └── state.py
├── web/                             # React/Vite browser control plane
├── fixtures/
├── policies/
└── tests/
```

## Quick Start

### 1. Install and verify integrations

```bash
python3 setup_integrations.py
```

Optional install attempt for supported dependencies:

```bash
python3 setup_integrations.py --install-missing
```

This writes integration configuration to:

```text
.mesh-runtime-state/integrations.json
```

The saved commands point at bridge entrypoints inside `mesh-intelligence`, not raw vendor binaries. That keeps the control plane contract stable while still exercising the real Promptfoo and Goose CLIs.

### 2. Install the browser UI dependencies

```bash
cd web
npm install
npm run build
cd ..
```

### 3. Start the local control plane

```bash
python3 run_server.py
```

Default server address:

```text
http://127.0.0.1:8787
```

### 4. Open the browser

Point the browser at:

```text
http://127.0.0.1:8787
```

### 5. Launch a run

Use the left rail to:

- select or create a goal
- choose a fixture scenario or paste a raw signal JSON payload
- select `native`, `promptfoo`, or `goose`
- choose `approval_gate` or `interruptible_auto`

## Web Control Plane

The browser UI is a React/Vite application under [`web/`](./web) using:

- a dense operator shell and graph-driven center stage inspired by `mesh-llm`
- server connection, status, and side-panel patterns inspired by `GitNexus`

The layout is:

- Left rail
  - goals
  - scenarios
  - integration readiness
  - launch run
  - run queue (Mesh pipeline runs)
  - research sessions (MiniMax / Goose autoresearch artifacts under `.mesh-runtime-state/research/`; not pipeline runs)
- Center
  - active goal
  - live run graph
  - steering console
  - timeline
- Right inspector
  - overview
  - evidence
  - policy
  - execution
  - feedback
  - vault preview
  - Merkle proof
  - GitNexus-backed code/process context

The active run is preserved in URL state with `?run=<run_id>`.

## HTTP API

Implemented routes:

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/scenarios`
- `GET /api/goals`
- `POST /api/goals`
- `GET /api/runs`
- `POST /api/runs`
- `GET /api/runs/:id`
- `POST /api/runs/:id/steer`
- `GET /api/runs/:id/events`
- `GET /api/runs/:id/merkle`
- `GET /api/runs/:id/merkle/proof/:event_id`
- `GET /api/stream/runs/:id`
- `GET /api/stream/system`
- `GET /api/vault/tree`
- `GET /api/vault/document`
- `GET /api/research-sessions` (filesystem autoresearch sessions; same `state_directory` as the server)
- `GET /api/research-sessions/:session_id` (manifest + `synthesis/final-report.md` when present)
- `GET /api/research-corpus` (aggregate grounding and drift assessment across research sessions)

### Create Goal

```json
{
  "title": "Protect search latency",
  "objective": "Pause every risky remediation before execution.",
  "success_criteria": ["approval gate pauses", "vault notes written"]
}
```

### Create Run

```json
{
  "goal_id": "goal_default",
  "scenario_key": "search_latency_regression",
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "approval_gate"
}
```

Raw signal payloads are also supported:

```json
{
  "goal_id": "goal_default",
  "signal_payload": {
    "...": "full signal payload"
  },
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "interruptible_auto",
  "pause_points": []
}
```

Live Kubernetes deployment harvesting is also supported:

```json
{
  "goal_id": "goal_default",
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "interruptible_auto",
  "live_signal": {
    "source": "kubernetes",
    "deployment_name": "semantic-search",
    "namespace": "search",
    "kube_context": "k3d-mesh-e2e",
    "environment": "local"
  }
}
```

### Steering Command

```json
{
  "command": "override_execution_parameters",
  "parameters": {
    "rollout_pct": 5
  }
}
```

## Vault Layout

Run and goal memory are mirrored to:

```text
.mesh-runtime-state/vault/
```

Fixed directories:

- `Goals/`
- `Runs/`
- `Decisions/`
- `Evaluations/`
- `Executions/`
- `Feedback/`
- `Merkle/`
- `Notes/`

Each run writes:

- a run note linking the goal and stage artifacts
- JSON-backed artifact notes for decision, evaluation, execution, and feedback
- operator notes
- a Merkle note containing the current root and event IDs

## Merkle Event Ledger

Every canonical run event is hashed as a leaf. The server recomputes the root whenever a new event is appended. The API exposes:

- current root and event list
- per-event proofs for decision, evaluation, execution, and feedback events

This is intended for run inspection and auditability, not blockchain settlement.

## TUI

The TUI remains available as a local terminal companion:

```bash
python3 run_tui.py
```

Mode toggles now use:

- `native` / `promptfoo`
- `native` / `goose`

The TUI is no longer the primary operator interface.

## Environment Variables

Supported configuration variables:

- `MESH_ENVIRONMENT`
- `MESH_EVALUATION_MODE`
- `MESH_ORCHESTRATION_MODE`
- `MESH_STATE_DIRECTORY`
- `MESH_RESEARCH_DIRECTORY` — autoresearch import root for `/api/research-sessions` and `/api/research-corpus`; defaults to `<state>/research`.
- `MESH_SERVER_HOST`
- `MESH_SERVER_PORT`
- `MESH_WEB_ASSET_PATH`
- `MESH_VAULT_PATH`
- `MESH_INTEGRATIONS_CONFIG_PATH`
- `MESH_DEFAULT_STEERING_MODE`
- `MESH_DEFAULT_OPERATOR_PAUSE_POINT`
- `MESH_PROMPTFOO_COMMAND`
- `MESH_GOOSE_COMMAND`
- `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED` — when `1`/`true`, `kubernetes_service` actions use live `kubectl` execution instead of the default mock adapter.
- `MESH_KUBECTL_COMMAND` — override the `kubectl` command used for live Kubernetes execution.
- `MESH_KUBERNETES_ROLLOUT_TIMEOUT_SECONDS` — timeout for `kubectl rollout status` after restart/rollback actions.
- `MESH_KUBERNETES_ALLOWED_CONTEXTS` — comma-separated allowlist of kube contexts permitted for live execution.
- `MESH_KUBERNETES_ALLOWED_NAMESPACES` — comma-separated allowlist of namespaces permitted for live execution.
- `MESH_GITNEXUS_SIDECAR_URL`
- `MESH_GITNEXUS_SIDECAR_COMMAND`
- `MESH_GITNEXUS_DISABLE_AUTOSTART` — when `1`/`true`, never infer a local GitNexus CLI command from the filesystem (recommended in containers unless you mount a GitNexus tree).
- `MESH_MAX_JSON_BODY_BYTES` — max `Content-Length` for JSON `POST` bodies (default `1048576`; use `0` to disable the limit).
- `MESH_SECURITY_HEADERS` — when `true` (default), sends `X-Content-Type-Options` and `Referrer-Policy` on HTTP responses.
- `MESH_ACCESS_LOG` — when `1`/`true`, enables access logging via Python’s logging module (configure handlers as needed for your environment).

See [`.env.example`](./.env.example) for a ready-to-copy template.

### Live Kubernetes E2E

To drive a real local cluster instead of the mock Kubernetes adapter:

```bash
export MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1
export MESH_KUBECTL_COMMAND=kubectl
export MESH_KUBERNETES_ALLOWED_CONTEXTS=k3d-mesh-e2e
export MESH_KUBERNETES_ALLOWED_NAMESPACES=search
```

Harvest a live deployment into the mesh signal contract:

```bash
python3 scripts/collect_kubernetes_signal.py --deployment semantic-search --namespace search > /tmp/semantic-search-signal.json
```

Then run the first slice against that signal:

```bash
python3 run_first_slice.py < /tmp/semantic-search-signal.json
```

The browser UI can also launch a run directly from a live deployment now. In the launch form, change the signal source to `Live Kubernetes Deployment`, enter the deployment and namespace, and launch the run. The backend will harvest the deployment signal first, then execute the normal Mesh pipeline.

### Docker-Native Local E2E

For a polished local loop, use `k3d` for the cluster and Docker Compose for Mesh:

1. Bring up the healthy baseline cluster and Mesh stack:

```bash
./scripts/e2e_up.sh
```

2. Seed a failure:

```bash
./scripts/e2e_seed_failure.sh imagepull
# or
./scripts/e2e_seed_failure.sh crashloop
```

3. Launch Mesh against the live cluster:

From the browser:

```text
http://127.0.0.1:8787
```

Choose `Signal: Live Kubernetes Deployment` and launch `search/semantic-search`.

Or from the CLI:

```bash
./scripts/e2e_run_mesh.sh
```

4. Tear everything down:

```bash
./scripts/e2e_down.sh
```

`e2e_up.sh` generates a container-safe kubeconfig under `.mesh-runtime-state/e2e/kubeconfig` and starts Compose with `docker-compose.e2e.yml`, which enables live Kubernetes execution inside the mesh container while keeping the allowed context and namespace bounded.
For local `k3d` use, that generated kubeconfig intentionally enables insecure TLS verification after rewriting the API server host for container access. Treat it as a disposable local-development artifact, not a production kubeconfig.

### Empirical showcase (multi-scenario pipeline digest)

Run the **same engine** the product uses (`FirstSlicePipeline`: ingest → trigger → decision → evaluation → orchestration → feedback) across **feature-flag**, **Kubernetes**, and **no-trigger** scenarios with isolated state per run. Produces structured metrics and a narrative insights file—useful for demos, investor drafts, or feeding MiniMax research.

```bash
python3 scripts/mesh_showcase_research.py
# Optional: chain MiniMax multi-wave synthesis (requires API keys; see goose-autoresearch skill)
python3 scripts/mesh_showcase_research.py --minimax
```

Output directory (default: `.mesh-runtime-state/research/<timestamp>-mesh-showcase/`):

- `data/run_summaries.json` — machine-readable metrics and stage chains
- `synthesis/showcase-insights.md` — grounded “why this architecture matters” bullets
- `manifest.json` — appears under **Research (MiniMax)** in the control plane UI when the server shares that `state_directory`

The control plane now computes a research-intelligence summary for every session. It scores whether a report is repo-grounded or off-domain, flags unsupported-superlative risk and evidence-scope limits, strips `<think>...</think>` reasoning blocks before UI/API display, and exposes a corpus-level summary at `/api/research-corpus`. See `docs/research-intelligence.md`.

For the full live Kubernetes production-like procedure, see `docs/production-live-runbook.md`.

## Production deployment

The mesh control plane is an **HTTP server without built-in authentication**. Put it behind a reverse proxy or private network, terminate TLS at the edge, and enforce auth at that layer before exposing it publicly.

### Container (recommended)

Build and run with Compose. The default stack starts only:

1. **`mesh`** — browser control plane and Python backend on **8787**. The image bundles **Promptfoo** and **Goose**, writes `integrations.json` during container boot, emits structured runtime logs when enabled, and bind-mounts this repository at `/workspace/mesh-intelligence` so repo-patch style remediation can operate against the live checkout.
2. **GitNexus is optional** — Compose no longer builds a `gitnexus` container. If you already have a GitNexus instance running on the host or elsewhere, point `MESH_GITNEXUS_SIDECAR_URL` at it. Otherwise the control plane still starts cleanly and GitNexus readiness simply reports unavailable.

```bash
docker compose up --build -d
```

Persistence:

- **Mesh** state: volume `mesh_runtime_state` → `/app/.mesh-runtime-state`
- **Goose** profile/config: volume `goose_config` → `/root/.config/goose`
- **Workspace mirror**: bind mount `./` → `/workspace/mesh-intelligence`

Override ports if needed:

```bash
MESH_PUBLISH_PORT=18080 docker compose up --build -d
```

Real-time logs:

```bash
docker compose logs -f mesh
```

Inspect readiness from the running backend:

```bash
curl http://127.0.0.1:8787/api/readiness
```

By default, Promptfoo becomes ready automatically in the container. Goose is also installed in the image, but it only reports ready after you provide a working provider configuration such as:

```bash
export GOOSE_PROVIDER=openai
export GOOSE_MODEL=gpt-4o-mini
export OPENAI_API_KEY=...
docker compose up --build -d
```

If you prefer a local model, point Goose at Ollama running on the host:

```bash
export OLLAMA_HOST=http://host.docker.internal:11434
docker compose up --build -d
```

For repo-patch and Kubernetes/code-remediation style flows, use repo paths from inside the container namespace, for example:

```text
/workspace/mesh-intelligence/fixtures/codebases/search_service
```

Optional GitNexus on the host:

```bash
npx -y gitnexus@latest serve
```

Then keep:

```bash
MESH_GITNEXUS_SIDECAR_URL=http://host.docker.internal:4747
```

Or blank the variable out if you do not want the sidecar integration at all.

Health: `GET /api/health` on mesh; GitNexus exposes `GET /api/info` for quick probes (Docker Compose uses this). `GET /api/heartbeat` is Server-Sent Events and is not suitable for typical HTTP health checks.

**Native GitNexus beside native Python:** in one terminal `npx -y gitnexus@latest serve` (or `gitnexus serve` if installed globally), in another set `MESH_GITNEXUS_SIDECAR_URL=http://127.0.0.1:4747` and run `python3 run_server.py`.

### Bare metal

1. Build the browser bundle: `cd web && npm ci && npm run build`.
2. Set `MESH_WEB_ASSET_PATH` to the absolute path of `web/dist` if it is not adjacent to the Python tree.
3. Bind `MESH_SERVER_HOST` to `0.0.0.0` only on trusted networks; otherwise keep the default loopback binding and front with a reverse proxy on the same host.
4. Enable access logs in production if desired: `MESH_ACCESS_LOG=1` (Python logging; ensure your process supervisor captures stdout/stderr).

## Development Commands

### Python

```bash
python3 -m unittest discover -s tests
python3 run_first_slice.py < fixtures/signals/search_latency_regression.json
```

### Web

```bash
cd web
npm test
npm run build
```

## Verification Status

The current implementation is verified by:

- Python unit and integration coverage across pipeline behavior and HTTP control-plane flows
- frontend unit tests for run graph generation
- production frontend build

The stable local path is:

1. `native` evaluation + `native` orchestration
2. browser operator approval gate
3. vault and Merkle inspection
4. optional Promptfoo / Goose CLI enablement through `setup_integrations.py`

## Supporting Docs

- [architecture.md](./architecture.md)
- [first-closed-loop-contract.md](./first-closed-loop-contract.md)
- [docs/CODEX_RUN_SUMMARY.md](./docs/CODEX_RUN_SUMMARY.md)
