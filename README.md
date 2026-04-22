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

## OpenTelemetry Consumer

Mesh accepts OpenTelemetry signals as a first-class input — no external alerting pipeline required. Two paths are supported:

### Push — OTLP/HTTP receiver

Send OTLP/HTTP JSON metric payloads to `POST /v1/metrics` on the control plane. Each accepted payload creates a Mesh run with signal type `otel_metric_regression`.

```bash
# Enable the receiver
export MESH_OTEL_RECEIVER_ENABLED=1
export MESH_OTEL_RECEIVER_TOKEN=a-strong-bearer-token  # optional but recommended

# Example: forward from an OTel Collector
# (in your collector config)
exporters:
  otlphttp/mesh:
    endpoint: http://mesh:8787
    headers:
      Authorization: "Bearer a-strong-bearer-token"
      x-mesh-alert-context: '{"metric_name":"http.server.duration","service":"api-gateway","baseline_value":420,"threshold_pct":30}'
```

The optional `x-mesh-alert-context` header tells Mesh which metric tripped and supplies a baseline value. Without it, Mesh falls back to heuristics (latency/error-name matching and using the first data point as baseline).

### Pull — Prometheus queries

Point Mesh at any PromQL-compatible endpoint to pull metrics during ingest or to verify remediation outcomes during the feedback stage.

```bash
export MESH_PROMETHEUS_URL=http://prometheus:9090
export MESH_PROMETHEUS_QUERY_TIMEOUT_SECONDS=10
export MESH_FEEDBACK_PROMETHEUS_ENABLED=1
```

When `MESH_FEEDBACK_PROMETHEUS_ENABLED=1`, the feedback stage samples real post-action metrics at 10m and 30m instead of trusting stub observations on the signal payload. A monitoring outage never makes a run look like it failed — the observer silently falls back to stub observations if Prometheus is unreachable.

### Architecture

```
OTel Collector ──OTLP/HTTP──▶ POST /v1/metrics ──▶ OtlpPushIngester ──▶ IngestService ──▶ Run
Prometheus    ──PromQL────▶ PrometheusClient ──▶ PrometheusPullIngester ──▶ IngestService ──▶ Run
Prometheus    ──PromQL────▶ PrometheusFeedbackObserver ──▶ post_action_observations ──▶ FeedbackService
```

## Metric-Action Rules

The decision stage handles OTel signals through a **declarative rule registry** at `policies/metric-actions.policy.json`. When a metric Mesh wasn't hardcoded to recognize regresses, the rule engine matches it against patterns you've authored and proposes a bounded action. Unmatched signals escalate rather than silently `no_action` — the gap is always visible.

### Rule shape

```json
{
  "rules": [
    {
      "name": "scale on consumer lag",
      "match": {
        "metric_name_pattern": "(consumer_lag|queue_depth|backlog)",
        "direction": "increasing",
        "delta_pct_min": 30,
        "resource_attributes": {
          "k8s.deployment.name": "*",
          "k8s.namespace.name": "*"
        }
      },
      "propose": {
        "decision_type": "scale_deployment",
        "system": "kubernetes_service",
        "action": "scale_deployment",
        "parameters": {
          "deployment_name": "{resource_attributes.k8s.deployment.name}",
          "namespace": "{resource_attributes.k8s.namespace.name}",
          "replicas_delta": 2
        }
      },
      "bounds": {"replicas_delta_max": 3, "cooldown_seconds": 300},
      "confidence": 0.78,
      "risk_level": "low",
      "rollback_plan": "scale deployment back to the prior replica count"
    }
  ]
}
```

### Matching semantics

| Field | Behavior |
|-------|----------|
| `metric_name_pattern` | Case-insensitive regex against the signal's metric name |
| `direction` | `increasing` or `decreasing` — compares observed vs baseline |
| `delta_pct_min` / `delta_pct_max` | Inclusive bounds on the absolute percent change |
| `resource_attributes` | All key/value pairs must match. `"*"` means "key must exist" |
| `attributes` | Same semantics but on the metric data point's attributes |

Rules are evaluated top-to-bottom; **the first match wins**. Put specific rules before generic ones.

### Parameter rendering

Parameters use `{dotted.path}` placeholders resolved against the signal:
- `{resource_attributes.k8s.deployment.name}` → the deployment name from OTel
- `{attributes.http.route}` → a metric data point attribute
- `{service}` → a top-level signal field

OTel attribute keys commonly contain dots (`k8s.deployment.name`). The resolver greedy-matches longest keys first, so this works correctly.

### Bounds enforcement

Numeric bounds are enforced at match time:
- `replicas_delta_max: 3` clamps any replica delta the rule produces to `[-3, +3]`
- A rule author writing `replicas_delta: 50` with `replicas_delta_max: 3` still emits `3` — typos don't become runaway actuations

### Starter rules

The shipped policy covers four common patterns:

| Rule | Metrics it catches | Action |
|------|-------------------|--------|
| `scale on consumer lag` | Kafka, RabbitMQ, Celery, SQS queue metrics | +2 replicas (max +3) |
| `scale on cpu saturation` | OTel + Prometheus CPU utilization variants | +2 replicas (max +4) |
| `raise memory limit on saturation` | Memory utilization / usage bytes | Patch to 2Gi limit |
| `scale on request rate spike` | HTTP request count, active connections | +1 replica (max +2) |

### Adding rules

1. Edit `policies/metric-actions.policy.json`
2. Rules load on service startup with LRU caching — restart the server to reload
3. `python3 -m unittest tests.test_metric_action_rules` verifies your rule parses and matches

### Available actions

| `decision_type` | `system` | `action` | Used for |
|-----------------|----------|----------|----------|
| `scale_deployment` | `kubernetes_service` | `scale_deployment` | Adjust replica count by delta or absolute |
| `patch_resources` | `kubernetes_service` | `patch_resources` | Adjust CPU/memory limits or requests |
| `rollback_deployment` | `kubernetes_service` | `rollback_deployment` | Revert to previous revision |
| `restart_deployment` | `kubernetes_service` | `restart_deployment` | Rolling restart |
| `disable_flag` / `reduce_rollout` | `feature_flag_service` | `set_rollout` | Feature flag control |
| `escalate` | `incident_service` | `open_incident` | Hand off to human |
| `no_action` | `audit_log_sink` | `record_no_action` | Record the signal, do nothing |

Add actuator methods in `services/actuators/service.py` and wire the action in `services/orchestrator/goose_adapter.py` + `goose_bridge.py` before adding a new action to the schema enum.

## Decision Layers

The decision stage has four layers, each covering more of the long tail than the last. All are composable — disable what you don't need, enable what you want.

```
OTel signal
    │
    ▼
┌─── Layer 1: Hardcoded action catalog (scale_deployment, rollback, disable_flag, ...)
│
▼
Layer 2: Declarative rule matcher — policies/metric-actions.policy.json
│
▼ (no rule matched)
Layer 3: LLM fallback — Goose proposes a bounded action from the allowlist
│
▼ (LLM unavailable or rejected)
Layer 4: escalate → learning store captures operator override → candidate rule
```

| Layer | Coverage | Determinism | Cost | Enable |
|-------|----------|-------------|------|--------|
| 1. Curated catalog | 8 actions | Full | Code | Always on |
| 2. Rule matcher | ~70% of signals | Full | YAML | Always on |
| 3. LLM fallback | +15% (long tail) | Non-deterministic | 5-30s LLM call | `MESH_LLM_DECISION_FALLBACK_ENABLED=1` |
| 4. Rule learning | Grows over time | Requires human approval | File I/O | `MESH_RULE_LEARNING_ENABLED=1` |

### Layer 3 — LLM fallback

When a signal doesn't match any rule, Mesh asks the LLM to propose a bounded action from an allowlist. Hard constraints:

- The LLM can only propose `(system, action)` pairs from a hardcoded allowlist in `services/decision/llm_fallback.py`
- Required parameters are validated against a schema
- Numeric parameters (`replicas_delta`, `replicas`) are clamped to bounds
- Confidence capped at 0.85 — the LLM can't claim certainty
- Unknown keys dropped silently
- Any failure mode (timeout, invalid JSON, bad action) falls through to `escalate` with a specific risk flag in the reasoning

Enable:

```bash
export MESH_LLM_DECISION_FALLBACK_ENABLED=1
export MESH_LLM_DECISION_FALLBACK_TIMEOUT_SECONDS=30
export MESH_GOOSE_COMMAND=goose  # goose bridge must already be configured
```

### Layer 4 — Rule learning from operator overrides

Every time an operator uses `override_decision` or `override_execution_parameters` on an OTel-shaped signal, Mesh records the override. When ≥5 overrides for similar signals agree on the same action and the resulting runs succeeded, Mesh synthesizes a candidate rule and surfaces it at `/api/rules/suggestions`.

Enable:

```bash
export MESH_RULE_LEARNING_ENABLED=1
export MESH_RULE_LEARNING_MIN_OBSERVATIONS=5
export MESH_RULE_LEARNING_MAX_AGE_DAYS=30
```

Review suggestions:

```bash
curl http://127.0.0.1:8787/api/rules/suggestions
```

Each suggestion returns a ready-to-paste rule alongside supporting evidence:

```json
{
  "suggestions": [
    {
      "fingerprint": "lag:payments:default:up",
      "rule": { "name": "...", "match": {...}, "propose": {...}, "bounds": {...} },
      "observation_count": 7,
      "success_rate": 0.86,
      "supporting_evidence": {
        "action_votes": {"scale_deployment": 6, "restart_deployment": 1},
        "sample_run_ids": ["run_20260401...", "..."]
      }
    }
  ]
}
```

**Suggestions never auto-apply.** Operators review, edit if needed, paste into `policies/metric-actions.policy.json`, and restart the server. A typo in a learned rule reaches the same actuators as a hand-written one — the friction is intentional.

**Fingerprinting.** Signals are grouped by `(normalized_metric_name, service, namespace, direction)`. Normalization collapses naming variants: `kafka.consumer.lag`, `kafka_consumer_lag_total`, and `ConsumerLag` all fingerprint identically so overrides cluster correctly across exporter versions.

**Parameter synthesis.** Numeric values use the median across observations (outlier-resistant); strings use the mode. Integer observations stay integers.

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
| `MESH_OTEL_RECEIVER_ENABLED` | `false` | Enable the `POST /v1/metrics` OTLP receiver |
| `MESH_OTEL_RECEIVER_TOKEN` | (none) | Bearer token required on OTLP requests when set |
| `MESH_PROMETHEUS_URL` | (none) | Prometheus/PromQL endpoint for pull ingest + feedback |
| `MESH_PROMETHEUS_QUERY_TIMEOUT_SECONDS` | `10` | Per-query timeout |
| `MESH_FEEDBACK_PROMETHEUS_ENABLED` | `false` | Sample real post-action metrics during feedback |
| `MESH_LLM_DECISION_FALLBACK_ENABLED` | `false` | Layer 3: consult the LLM when no rule matches |
| `MESH_LLM_DECISION_FALLBACK_TIMEOUT_SECONDS` | `30` | Per-call LLM timeout |
| `MESH_RULE_LEARNING_ENABLED` | `false` | Layer 4: capture overrides and synthesize rule suggestions |
| `MESH_RULE_LEARNING_MIN_OBSERVATIONS` | `5` | Minimum overrides before a rule is suggested |
| `MESH_RULE_LEARNING_MAX_AGE_DAYS` | `30` | Only consider overrides from the last N days |

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
