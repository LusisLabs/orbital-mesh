# Codebase overview (from-source analysis)

Reverse-engineered from the source on 2026-05-13, deliberately without reading `README.md`. Cross-checked against `architecture.md` (which is fresh and accurate). Use this as the reference for rewriting `README.md`.

## One-line summary

`mesh-intelligence` is an agentic incident-response and bounded-remediation control plane: it ingests operational signals, investigates them with read-only tools, proposes one bounded decision, runs it through an approval-gated policy check, and only then executes via a narrow actuator allowlist. Every step is recorded as an audited artifact.

## What it is not

- Not a general autonomous infrastructure agent. The investigation loop is read-only.
- Mutating actions are constrained to a reviewed actuator surface (Kubernetes rollouts, feature-flag rollout %, incident creation, ArgoCD sync/rollback, repo patches, systemd-over-SSH, load balancer).
- Defaults to operator approval — runs pause at `awaiting_operator` before execution unless the auto-mode policy permits.

## Pipeline

Implemented in `services/runtime.py` (`MeshRuntimeEngine.run_sync`). Every run produces a fixed chain of first-class artifacts:

```
raw signal
  └─► ingest (services/ingest/)            → normalized_event (EventEnvelope)
  └─► trigger (services/trigger/)          → trigger
  └─► signal-profile resolve               → SignalProfile
  └─► investigation_planner.plan           → investigation_plan
  └─► evidence.assemble                    → evidence_pack
  └─► investigation harness loop           → investigation_report
  └─► scenario_analysis.analyze            → scenario_analysis (+ memory_compaction)
  └─► decision.decide (HypothesisEngine)   → decision + ranked_hypotheses
  └─► profile.rca_builder.build            → rca_report
  └─► evaluation                           → evaluation result (policy/risk/rollback/cred checks)
  └─► [operator approval gate]
  └─► orchestrator → actuators             → execution_record
  └─► feedback                             → feedback_record
```

All artifacts land in run state, the event log, the file-backed vault (with Merkle roots/proofs), and the SSE stream.

## Signal profiles

Signal profiles (`shared/mesh_runtime/signal_profile.py`) bind a signal type + trigger type to the strategies that should handle it. The profile contract covers ingest, trigger, planner, evidence, RCA, decision, scenario analysis, and feedback — but **only planner, evidence, and RCA are fully profile-dispatched today**. Ingest, trigger, decision, scenario analysis, and feedback still contain monolithic per-signal branches.

| Signal | Trigger | Status |
| --- | --- | --- |
| `reth_node` | `reth_node_degraded` | Specialized planner, typed evidence probes, specialized RCA |
| `kubernetes_deployment_issue` | `kubernetes_deployment_unhealthy` | Shared harness planner, structured evidence, generic RCA |
| `otel_metric_regression` | `otel_metric_regression` | Shared harness planner, structured evidence, generic RCA |
| `webhook_alert` | `webhook_alert_firing` | Shared harness planner, structured evidence, generic RCA |
| `feature_flag` | `feature_flag_performance_regression` | Shared harness planner, structured evidence, generic RCA |
| unknown / unregistered | `generic_signal_firing` | Generic evidence, generic RCA, unconditional escalation |

Generic profile is the safety floor: unknown signals get investigated and summarized but always escalate — they cannot auto-act.

## Investigation harness

`services/investigation/harness/` implements a planner + tool-registry loop:

- **Planner**: selects read-only tool calls (Reth and CloudOps snapshots have native deterministic planners; others rely on `llm_planner.py` when configured).
- **`LoopCritic`** rejects unknown, malformed, mutating, or over-budget calls.
- **Always-on tool packs** (`services/investigation/tools/`), each auto-registered when its config/env is present:

  | Pack | Surface | Trigger |
  | --- | --- | --- |
  | `prometheus` | PromQL instant/range, labels | `MESH_PROMETHEUS_URL` |
  | `kubectl` | get/describe/logs/yaml/connectivity | kubeconfig + `kubectl` |
  | `aws` | describe/list-style calls | `MESH_AWS_TOOLS_ENABLED=1` |
  | `github` | issues, PRs, file reads | `gh auth status` |
  | `loki` | LogQL labels + log ranges | `MESH_LOKI_URL` |
  | `jaeger` | trace search + service map | `MESH_JAEGER_URL` |
  | `postgres` | SELECT-only SQL | `MESH_PG_DSN` + `psql` |
  | `mcp` | external MCP bridges | `MESH_MCP_SERVERS` |
  | `topology` | InfraGraph lineage/neighbors | always available |

Without an LLM planner and registered tools, non-Reth/non-CloudOps signals still get deterministic investigation artifacts — they just don't get a rich iterative tool-call loop.

## Decision and RCA

`services/decision/`:

- `HypothesisEngine` does deterministic RCA scoring. It is **not** replaced by the LLM.
- `llm_fallback.py` and `llm_reasoning.py` can contribute candidates but cannot bypass policy or choose production actions.
- Output: exactly one `decision`. Examples: `no_action`, `reduce_rollout`, `disable_flag`, `rollback_deployment`, `restart_deployment`, `scale_deployment`, `patch_resources`, `restart_systemd_service`, `open_incident`, `escalate`.

Hypothesis strength by domain:
- **Reth** — strongest; typed predicates over enriched evidence.
- **Kubernetes** — solid deterministic templates (crash loops, OOMs, image pulls, probes, recent deploys, config/secret changes, upstream symptoms).
- **Feature-flag / OTel / webhook / generic** — thinner deterministic coverage; lean on trigger heuristics and investigation candidates.

## Evaluation and approval

`services/evaluation/` checks policy, confidence, risk, credential readiness, rollback requirements, and integration readiness. In approval-gate mode runs pause at `awaiting_operator`.

Operator steering commands (via `POST /api/runs/:id/steer`):
`approve`, `cancel`, `pause_after_stage`, `resume`, `set_auto_mode`, `override_decision`, `override_execution_parameters`, `attach_note`. Overrides re-enter evaluation.

## Execution and actuators

`services/orchestrator/` only fires after evaluation permits. Actuator surfaces in `services/actuators/`:

- `feature_flag` (rollout %)
- `incident` / ticket creation
- `kubernetes` (rollout restart/undo) — live exec gated by `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1` plus `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES`
- `argocd` (sync, rollback)
- `repo_patch`
- `systemd_ssh` (approval-gated, for Reth/bare-metal incidents)
- `load_balancer`

External agent bridges (review-before-actuation, or read-only proposal-only): Goose, Hermes, LatentMAS, DeepAgents, Evo (external CLI), plus `agent_mesh.py` proposal registry for Codex / Claude Code / OpenClaw / DeepAgents-style workers.

## Control plane API (`control_plane_server.py` + `services/control_plane.py`)

Stdlib `ThreadingHTTPServer` (not FastAPI). 881-line server fronting a 3373-line `RunCoordinator`. Notable routes:

| Method | Path | Role |
| --- | --- | --- |
| GET | `/api/health` | Liveness, build version + commit |
| GET | `/api/readiness` | Integration readiness |
| GET | `/api/scenarios` | Fixture scenario list |
| GET | `/api/simulations`, `/api/benchmarks` | Catalogs |
| GET | `/api/service-agents` | Registered agent mesh workers |
| POST | `/api/runs` | Start a run (`signal_payload` or `scenario_key` or `otlp_payload`) |
| GET | `/api/runs/:id`, `/api/runs/:id/events` | Snapshot + paged event log |
| POST | `/api/runs/:id/steer` | Operator steering |
| GET | `/api/stream/runs/:id`, `/api/stream/system` | SSE streams |
| GET | `/api/watchers` | Watcher inventory |
| POST | `/api/watch/{start,stop}`, `/api/watchers/:name/{start,stop}` | Watcher control |
| POST | `/api/webhook-sources` | Register a webhook source |
| DELETE | `/api/webhook-sources/:id` | Remove a webhook source |
| POST | `/api/webhooks/:source_id` | Receive webhook (HMAC `X-Mesh-Signature` / `X-Hub-Signature-256`) |
| POST | `/v1/metrics` | OTLP/HTTP JSON metrics receiver (opt-in: `MESH_OTEL_RECEIVER_ENABLED`, optional `MESH_OTEL_RECEIVER_TOKEN`) |
| GET | `/api/vault/tree`, `/api/vault/document?path=...` | Audit vault browse |
| GET | `/api/trust-ladder`, POST `/api/trust-ladder/override` | Per-actuator trust levels |
| GET | `/api/rules/suggestions` | Rule-suggestion admin surface |
| GET | `/api/graph/{status,snapshot}`, POST `/api/graph/refresh` | InfraGraph |
| GET | `/api/memory/{active,query,graph}`, POST `/api/memory/maintenance/run` | Memory store |
| GET | `/api/research-sessions`, `/api/research-corpus` | Research artifacts |
| GET | `/api/alerts`, `/api/agent/slo`, `/metrics` | Ops |
| POST | `/api/simulations/:id/run` | Run a simulation scenario |
| POST | `/api/goals` | Create a goal |

## Runtime modes

- **Evaluation**: `native` (in-process trajectory + verifier checks) or `promptfoo` (compat mode).
- **Orchestration**: `native` (in-process actuators) or `goose` / `hermes` (review bridge before actuation).
- **State backend**: file-backed under `MESH_STATE_DIRECTORY` (default) or Postgres via `MESH_STATE_BACKEND=postgres` + `MESH_DATABASE_URL` (psycopg-pool–backed).

## Repository layout

```
control_plane_server.py     # stdlib HTTP/SSE server (881 lines)
services/
  control_plane.py          # RunCoordinator (3373 lines): runs, approvals, watchers, vault, webhook ingest
  runtime.py                # MeshRuntimeEngine: the core pipeline
  pipeline.py               # FirstSlicePipeline thin wrapper
  ingest/                   # raw payload → EventEnvelope (k8s, OTel, webhook, bare-metal)
  trigger/                  # envelope → Trigger
  evidence/                 # EvidencePack assembly + Reth probe registry
  investigation/
    harness/                # planner + critic + registry + loop
    tools/                  # always-on read-only tool packs
    cloudops_*, reth_planner, llm_planner, rca, topology_builder
  scenario_analysis/
  decision/                 # HypothesisEngine + LLM fallback/reasoning
  evaluation/               # policy gates, promptfoo bridge, SRE judge
  orchestrator/             # bounded execution, external agent bridges
    service_agents/         # agent mesh registry
  actuators/                # k8s/argocd/systemd-ssh/repo_patch/load_balancer/feature_flag/incident
  feedback/                 # Prometheus + k8s post-action observers
  observer/                 # LLM observer (Anthropic/OpenAI) with redaction
  watchers/                 # k8s/base watcher daemons
  benchmark/                # CloudOpsBench/LogHub/SREGym harness + gates + scoring
  signal_correlator.py, signal_history/, signal_profiles/, simulation/, skills/, trigger/
shared/mesh_runtime/        # contracts, JSON schemas, state store, vault, infra graph,
                            # reasoning bank, learning store, trust ladder, policies,
                            # alert store, webhook templates, postgres state, OTel
  schemas/                  # JSON Schema source of truth
policies/                   # autonomy, metric-actions, protected-scope, reth-node, rollback
fixtures/                   # signals, decisions, monitoring corpus, webhook templates, codebases
benchmarks/                 # benchmark scenarios + corpora + gate config
simulation/                 # synthetic Reth fault-injection harness (python -m simulation)
plugins/mesh-intelligence/  # skills bundle
latent-mesh/LatentMAS/      # vendored Rust multi-agent subsystem
deepagents/                 # vendored DeepAgents package (editable install)
web/                        # React 18 + Vite + TS UI (SSE/REST client)
tui.py                      # textual TUI alternative (49k lines)
migrations/                 # state-store migrations
scripts/                    # 39 ops/CI/contract-gen scripts
tests/                      # pytest suite
docs/                       # architecture and runbook docs
docker-compose.stack.yml    # full local topology (Mesh + embedded k3s + UI + smoke)
docker-compose.yml          # base compose
docker-compose.reth-demo.yml
Dockerfile*                 # main + latentmas-cpu + hermes
```

## Stack

| Area | Stack |
| --- | --- |
| Core services + runtime | Python 3.11+, `uv` |
| HTTP API | stdlib `http.server` (ThreadingHTTPServer) — not FastAPI |
| Web UI | React 19, Vite/Next, TypeScript, `pnpm` |
| TUI | textual (`tui.py`) |
| Schemas / contracts | JSON Schema (source of truth) + Python dataclasses |
| State | File-backed (default) or Postgres (psycopg3 + pool) |
| Audit | Append-only vault with Merkle roots + proofs |
| LatentMAS | Rust (`cargo`) under `latent-mesh/LatentMAS/` |
| Simulation observer | Anthropic / OpenAI (`MESH_OBSERVER_MODEL`, default `claude-sonnet-4-6`) |
| Eval (optional extra) | `deepeval` via `uv sync --extra eval` |

## Validation gates

From `AGENTS.md`:

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest

RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict \
  --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'

pnpm install --frozen-lockfile
pnpm --dir web run build
pnpm --dir meshapp/frontend run build

(cd latent-mesh/LatentMAS && cargo test && cargo clippy)   # only when touching Rust
```

Note: `mypy --strict` is currently scoped (per `pyproject.toml`) to `services/decision/hypothesis_engine.py` — the rest of the runtime is being typed incrementally.

## Entrypoints

```bash
# Full simulated stack (Mesh + embedded k3s + seed workloads + UI + smoke verifier)
docker compose -f docker-compose.stack.yml up --build

# Realtime control plane with watchers started at boot
PYTHONPATH=. uv run python -c "from control_plane_server import serve_forever; serve_forever()"

# Local API/UI dev path (watchers started later via API)
python3 run_server.py
curl -X POST http://127.0.0.1:8787/api/watch/start

# TUI
python3 run_tui.py

# Fault-injection simulation (drives the full pipeline against a Reth fault catalog)
export ANTHROPIC_API_KEY=sk-ant-...
python -m simulation
```

## Persistence model

Default durable store is file-backed under `MESH_STATE_DIRECTORY`. Persisted artifacts: run sessions and goals, per-run event logs, run snapshots, evidence packs, investigation + RCA reports, evaluation + execution artifacts, agent task artifacts, deferred rechecks, vault documents, Merkle roots/proofs. Postgres backend behind `MESH_STATE_BACKEND=postgres` + `MESH_DATABASE_URL` (process-wide connection pool).

## Robustness boundary (as of this read)

**Robust today:**
- Unknown signals reach a safe generic fallback.
- Generic signals escalate unconditionally — LLM/planner output cannot demote.
- Reth/K8s/OTel/webhook/feature-flag/generic profiles all emit the full artifact chain.
- Reth evidence + hypothesis ranking are typed and evidence-backed.
- K8s has meaningful deterministic hypotheses and scenario analysis.
- Investigation harness enforces read-only tool calls.

**Known gaps** (also flagged in `architecture.md`):
- Ingest, trigger, decision, scenario analysis, and feedback are not yet fully profile-dispatched.
- AI/tool loop isn't guaranteed for every signal unless an LLM planner and tools are configured. Reth and CloudOps have stronger native loop support.
- Feature-flag / OTel / webhook / generic deterministic hypothesis coverage is thinner than Reth/K8s.
- `services/control_plane.py` duplicates parts of runtime orchestration (future drift risk).
- Legacy `EvidenceService()` callers without a profile registry can still bypass the safer profile evidence path.

## Likely README drift points

When rewriting `README.md`, check it against the items below — these are the most likely places it's gone stale:

1. **Reth-centric framing.** Repo is now signal-agnostic via profiles; Reth is one profile of six.
2. **Actuator list.** ArgoCD, repo-patch, systemd-SSH, and load-balancer actuators exist in code and may not be documented.
3. **OTLP metrics receiver.** `POST /v1/metrics` with `MESH_OTEL_RECEIVER_ENABLED` + optional bearer token (`MESH_OTEL_RECEIVER_TOKEN`) and `x-mesh-alert-context` header.
4. **Webhook source HMAC.** `/api/webhook-sources` registration + `X-Mesh-Signature` / `X-Hub-Signature-256` verification.
5. **Postgres state backend** (`MESH_STATE_BACKEND=postgres` + `MESH_DATABASE_URL`).
6. **Admin surfaces:** trust ladder (`/api/trust-ladder`, `/api/trust-ladder/override`), rule suggestions (`/api/rules/suggestions`), InfraGraph (`/api/graph/*`), memory (`/api/memory/*`), research (`/api/research-*`).
7. **External agent bridges:** Goose / Hermes / LatentMAS / DeepAgents / Evo, plus the agent-mesh proposal registry.
8. **Validation gates** (commands in `AGENTS.md`) — README's quickstart/CI section should match.
9. **mypy is scoped, not whole-repo** — don't claim repo-wide strict typing.
10. **HTTP server is stdlib, not FastAPI** — surprising for readers expecting a typical Python service.
