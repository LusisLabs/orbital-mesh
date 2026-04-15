# Mesh Intelligence

Bounded closed-loop remediation control plane. Ingests infrastructure signals, decides on a remediation path, evaluates against policy gates, pauses for operator approval, executes through a constrained orchestration layer, records feedback, and persists every run into a Merkle-rooted event ledger and Obsidian-compatible vault.

## How It Works

```
Signal → Ingest → Trigger → Decision → Evaluation → Operator Gate → Execution → Feedback
```

1. **Ingest** — normalizes a raw infrastructure signal into a canonical envelope.
2. **Trigger** — decides whether the signal is actionable. If not, the run ends immediately.
3. **Decision** — picks a bounded action: `reduce_rollout`, `disable_flag`, `restart_deployment`, `rollback_deployment`, `escalate`, or `no_action`.
4. **Evaluation** — applies policy, business, and quality checks. Optionally delegates to Promptfoo.
5. **Operator gate** — pauses for human approval (default) or proceeds automatically depending on steering mode.
6. **Execution** — actuates through the native adapter, Goose bridge, or Goose CLI.
7. **Feedback** — writes outcome signals (10m/30m observations, recurrence checks, guardrail results).

Each stage emits typed events that are persisted to disk, streamed over SSE, mirrored to the vault, and included in the Merkle tree.

## Run Lifecycle

```
queued → ingesting → trigger_ready → decision_ready → evaluation_ready
       → awaiting_operator → executing → feedback_ready → completed
```

Terminal states: `completed`, `failed`, `cancelled`, `no_trigger`.

Steering commands while a run is in progress:

| Command | Effect |
|---------|--------|
| `approve` | Release the operator gate |
| `cancel` | Abort the run |
| `pause_after_stage` | Insert a pause before a future stage |
| `resume` | Continue from a pause |
| `set_auto_mode` | Toggle automatic approval |
| `override_decision` | Replace the decision (re-enters evaluation) |
| `override_execution_parameters` | Modify execution params (re-enters evaluation) |
| `attach_note` | Append an operator note to the run |

Overrides always re-enter evaluation. Approval never bypasses policy validation.

## Runtime Modes

| Mode | Layer | Description |
|------|-------|-------------|
| `native` | Evaluation + Orchestration | In-process adapters with local persistence. Works immediately, no external CLIs. |
| `promptfoo` | Evaluation | Runs a real Promptfoo eval via CLI bridge. |
| `goose` | Orchestration | Runs a Goose review step before bounded actuation. Supports OpenAI, Anthropic, and Ollama providers with fallback. |

## Repository Layout

```
mesh-intelligence/
├── control_plane_server.py          # HTTP + SSE server
├── run_server.py                    # Server entrypoint with graceful shutdown
├── run_first_slice.py               # Synchronous stdin/stdout pipeline runner
├── run_tui.py                       # Terminal UI (curses)
├── setup_integrations.py            # Bootstrap Promptfoo / Goose / GitNexus config
├── services/
│   ├── control_plane.py             # Run coordinator, steering, thread management
│   ├── runtime.py                   # Shared stage primitives
│   ├── pipeline.py                  # Synchronous pipeline wrapper
│   ├── ingest/
│   ├── trigger/
│   ├── decision/
│   ├── evaluation/
│   ├── orchestrator/
│   ├── feedback/
│   └── actuators/                   # Feature flag, incident, Kubernetes, repo-patch adapters
├── shared/mesh_runtime/
│   ├── config.py                    # RuntimeConfig with env-var binding
│   ├── state.py                     # File-backed state store
│   ├── control_plane_state.py       # Goals, runs, events persistence
│   ├── control_plane_models.py      # Dataclasses for runs, events, goals
│   ├── merkle.py                    # Merkle tree construction and proofs
│   ├── vault.py                     # Obsidian-compatible vault writer
│   └── integrations.py              # Integration discovery and readiness
├── web/                             # React + Vite browser UI
├── fixtures/                        # Signal fixtures and test codebases
├── policies/                        # Policy definitions (autonomy, rollback, protected-scope)
├── scripts/                         # Operational scripts (e2e, research)
├── tests/
├── Dockerfile                       # Multi-stage production image, non-root
├── docker-compose.yml               # Compose stack with resource limits
├── pyproject.toml                    # Ruff lint config
└── .env.example                     # Configuration template
```

## Quick Start

### 1. Bootstrap integrations

```bash
python3 setup_integrations.py
# Optional: attempt to install missing CLIs
python3 setup_integrations.py --install-missing
```

Writes integration config to `.mesh-runtime-state/integrations.json`.

### 2. Build the browser UI

```bash
cd web && npm install && npm run build && cd ..
```

### 3. Start the server

```bash
python3 run_server.py
```

Open `http://127.0.0.1:8787` in a browser.

### 4. Run from the browser

Use the left rail to select a goal, choose a scenario or paste a raw signal, pick runtime modes (`native`/`promptfoo`/`goose`), and set the steering mode (`approval_gate` or `interruptible_auto`).

### 5. Run from the command line

```bash
python3 run_first_slice.py < fixtures/signals/search_latency_regression.json
```

## HTTP API

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/readiness` | Integration readiness |
| `GET` | `/api/scenarios` | List available fixture scenarios |
| `GET` | `/api/goals` | List goals |
| `POST` | `/api/goals` | Create a goal |
| `GET` | `/api/runs` | List runs |
| `POST` | `/api/runs` | Create a run |
| `GET` | `/api/runs/:id` | Get run details |
| `POST` | `/api/runs/:id/steer` | Send a steering command |
| `GET` | `/api/runs/:id/events` | List run events |
| `GET` | `/api/runs/:id/merkle` | Merkle snapshot |
| `GET` | `/api/runs/:id/merkle/proof/:event_id` | Merkle proof for a single event |
| `GET` | `/api/stream/runs/:id` | SSE stream for a run |
| `GET` | `/api/stream/system` | SSE stream for system-wide events |
| `GET` | `/api/vault/tree` | Vault file listing |
| `GET` | `/api/vault/document` | Read a vault document |

### Create a run

```json
{
  "goal_id": "goal_default",
  "scenario_key": "search_latency_regression",
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "approval_gate"
}
```

Or with a raw signal payload:

```json
{
  "goal_id": "goal_default",
  "signal_payload": { "..." : "full signal" },
  "evaluation_mode": "native",
  "orchestration_mode": "native",
  "steering_mode": "interruptible_auto",
  "pause_points": []
}
```

### Steering command

```json
{
  "command": "override_execution_parameters",
  "parameters": { "rollout_pct": 5 }
}
```

## Vault

Run and goal memory are mirrored to `.mesh-runtime-state/vault/` in an Obsidian-compatible layout:

```
vault/
├── Goals/
├── Runs/
├── Decisions/
├── Evaluations/
├── Executions/
├── Feedback/
├── Merkle/
└── Notes/
```

Each run produces a run note, JSON artifact notes (decision, evaluation, execution, feedback), operator notes, and a Merkle note with the current root and event list.

## Merkle Event Ledger

Every run event is hashed as a leaf. The root is recomputed on each append. The API exposes the current root, full event list, and per-event inclusion proofs. This is for run inspection and auditability, not blockchain settlement.

## Production Deployment

The server has no built-in authentication. Place it behind a reverse proxy, terminate TLS at the edge, and enforce auth before exposing it publicly.

### Container (recommended)

```bash
docker compose up --build -d
```

The image:
- Bundles Promptfoo and Goose
- Runs as a non-root `mesh` user
- Writes `integrations.json` during boot
- Resource limits: 2G memory, 2 CPUs (configurable in `docker-compose.yml`)

Volumes:
- `mesh_runtime_state` → `/app/.mesh-runtime-state`
- `goose_config` → `/root/.config/goose`
- Bind mount `./` → `/workspace/mesh-intelligence`

Override the published port:

```bash
MESH_PUBLISH_PORT=18080 docker compose up --build -d
```

Configure Goose with an API provider:

```bash
export GOOSE_PROVIDER=openai
export GOOSE_MODEL=gpt-4o-mini
export OPENAI_API_KEY=...
docker compose up --build -d
```

Or point at a local Ollama:

```bash
export OLLAMA_HOST=http://host.docker.internal:11434
docker compose up --build -d
```

Optional GitNexus sidecar:

```bash
# On the host
npx -y gitnexus@latest serve
# Set in .env
MESH_GITNEXUS_SIDECAR_URL=http://host.docker.internal:4747
```

### Bare metal

1. Build the UI: `cd web && npm ci && npm run build`
2. Set `MESH_WEB_ASSET_PATH` if `web/dist` is not adjacent to the Python tree.
3. Keep `MESH_SERVER_HOST=127.0.0.1` unless on a trusted network.
4. Enable access logs: `MESH_ACCESS_LOG=1`

## Security

The production-hardened server includes:

- Safe URL path segment parsing (no raw index access)
- Path traversal protection on the vault document endpoint
- Request body size limits (`MESH_MAX_JSON_BODY_BYTES`, default 1MB)
- `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` headers
- CORS preflight handling
- SSE stream timeout (`MESH_SSE_MAX_CONNECTION_SECONDS`, default 30min)
- Graceful shutdown on SIGTERM/SIGINT
- Thread-safe run coordination with lock-protected state
- Corrupt state file recovery with automatic backup

## Environment Variables

See [`.env.example`](./.env.example) for the full list with comments. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MESH_SERVER_HOST` | `127.0.0.1` | Bind address |
| `MESH_SERVER_PORT` | `8787` | Bind port |
| `MESH_ENVIRONMENT` | `local` | Environment tag |
| `MESH_EVALUATION_MODE` | `native` | `native` or `promptfoo` |
| `MESH_ORCHESTRATION_MODE` | `native` | `native` or `goose` |
| `MESH_DEFAULT_STEERING_MODE` | `approval_gate` | `approval_gate` or `interruptible_auto` |
| `MESH_STATE_DIRECTORY` | `.mesh-runtime-state` | Persistence root |
| `MESH_MAX_JSON_BODY_BYTES` | `1048576` | Max POST body size |
| `MESH_SECURITY_HEADERS` | `true` | Send security response headers |
| `MESH_ACCESS_LOG` | `false` | Enable request logging |
| `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED` | `false` | Enable live kubectl actuation |
| `MESH_KUBERNETES_ALLOWED_CONTEXTS` | (none) | Comma-separated allowed kube contexts |
| `MESH_KUBERNETES_ALLOWED_NAMESPACES` | (none) | Comma-separated allowed namespaces |

## Development

### Tests

```bash
python3 -m unittest discover -s tests -v
```

### Lint

```bash
pip install ruff
ruff check .
```

### Web

```bash
cd web
npm test
npm run build
npx tsc --noEmit   # type check
```

## Docs

- [architecture.md](./architecture.md)
- [first-closed-loop-contract.md](./first-closed-loop-contract.md)
- [docs/CODEX_RUN_SUMMARY.md](./docs/CODEX_RUN_SUMMARY.md)

