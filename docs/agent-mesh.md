# Agent Mesh

Mesh Intelligence exposes a supervised worker contract so external agents can participate in incident response without owning production side effects.

## Boundary

Mesh owns:

- run state and audit events
- policy and evaluation gates
- test and smoke requirements
- Kubernetes actuation
- vault and Merkle evidence
- production promotion decisions

Agents own:

- investigation summaries
- root-cause hypotheses
- patch proposals
- review findings
- staging validation suggestions

Workers do not write production, mutate the real repo checkout, mutate `main`, or bypass Kubernetes allowlists. Code-writing adapters must stay inside isolated workspaces and return diffs, changed-file lists, summaries, and test results for Mesh evaluation.

## Worker Contract

Each run that reaches evaluation records an `agent_tasks` artifact.

- `MESH_AGENT_FABRIC_MODE=native` keeps the default `native_contract` attempts for Goose, Hermes, Codex, Claude Code, OpenClaw, and Evo. Those attempts are read-only proposals, not real CLI invocations.
- `MESH_AGENT_FABRIC_MODE=deepagents` routes those lanes through `services/orchestrator/deepagents_adapter.py`. Mesh creates a per-run sandbox workspace under `MESH_DEEPAGENTS_WORKSPACE_ROOT`, copies only allowed files into that workspace for patch-shaped tasks, and records Deep Agents output as proposal artifacts. Mesh still owns policy, tests, audit, Kubernetes actuation, and production promotion.

LatentMAS can be enabled as a first-class full-inference worker lane. It runs through a separate PyTorch/Hugging Face sidecar and records an additional `latentmas_http` attempt ahead of the native lanes. LatentMAS output is advisory only: Mesh still owns policy, tests, audit, Kubernetes actuation, and production promotion.

API:

```text
GET /api/runs/:run_id/agent-tasks
```

Artifact shape:

```json
{
  "task_id": "task_run_..._rollback_plan_...",
  "run_id": "run_...",
  "kind": "root_cause|patch|review|rollback_plan",
  "status": "completed",
  "allowed_paths": [],
  "test_commands": [],
  "kubernetes_scope": {
    "context": "k3d-mesh-e2e",
    "namespace": "search",
    "deployment_name": "semantic-search"
  },
  "attempts": [
    {
      "agent": "goose",
      "adapter": "native_contract",
      "status": "completed",
      "summary": "Operational plan...",
      "risk_flags": [],
      "recommended_action": "execute"
    }
  ],
  "selected_attempt_id": "attempt_..."
}
```

With LatentMAS enabled, the first attempt may look like:

```json
{
  "agent": "latentmas",
  "adapter": "latentmas_http",
  "status": "completed",
  "summary": "LatentMAS recommends the gated execution path.",
  "risk_flags": [],
  "recommended_action": "execute",
  "output": {
    "confidence": 0.91,
    "raw_prediction": "{\"summary\":\"...\"}",
    "agent_traces": [],
    "metrics": {
      "model_name": "Qwen/Qwen3-4B",
      "elapsed_time_sec": 12.4,
      "latent_steps": 10,
      "prompt_mode": "sequential",
      "backend": "transformers"
    }
  }
}
```

If the sidecar is unavailable, Mesh records a failed LatentMAS attempt with `latentmas_unavailable` and continues with the remaining worker lanes for the active agent fabric mode.
LatentMAS health is preflight-aware: the sidecar now reports readiness detail from `/health`, and Mesh skips the inference call when the sidecar reports `ready: false`. This prevents a false-green readiness check followed by an immediate `500` on `/infer`.

With Deep Agents enabled, a lane attempt looks like:

```json
{
  "agent": "codex",
  "adapter": "deepagents",
  "status": "completed",
  "summary": "Bounded patch proposal prepared in sandbox workspace.",
  "risk_flags": [],
  "recommended_action": "human_review",
  "changed_files": ["fixtures/codebases/search_service/app/search.py"],
  "test_results": [
    {
      "name": "pytest",
      "passed": true,
      "detail": "2 checks passed"
    }
  ],
  "output": {
    "workspace_path": "/app/.mesh-runtime-state/deepagents/run_.../task_.../codex",
    "diff": "--- a/...\n+++ b/...\n@@ ...",
    "deepagents_final_message": "{...}"
  }
}
```

If Deep Agents is enabled but the dependency or provider credentials are unavailable, Mesh records a failed or degraded attempt with non-blocking risk flags such as `deepagents_dependency_missing` or `deepagents_model_credentials_missing`.
Agent-task collection is best-effort and bounded by `MESH_AGENT_TASK_TIMEOUT_SECONDS` so proposal lanes cannot block control-plane execution. Slow lanes degrade into recorded failed attempts with `agent_mesh_timeout`.
For `openai:MiniMax-*` Deep Agents models, Mesh resolves credentials from `OPENAI_API_KEY` and falls back to `MINIMAX_API_KEY` for the OpenAI-compatible MiniMax route.

## Evo Proposal Lane

Evo is integrated as a bounded proposal lane. Mesh checks whether `evo-hq-cli` is configured and records whether the current task has enough code-remediation boundaries for Evo discovery:

- explicit repo path
- allowed paths
- test commands or benchmark gates
- code-remediation task kind

The Evo attempt remains `adapter="native_contract"`. It returns `evo_discover_candidate` for bounded patch tasks with allowed paths and tests, `prepare_benchmark` when benchmark/test gates are missing, and `human_review` when Evo is unavailable or the task is not code-remediation-shaped.

Evo readiness is configured with:

```bash
MESH_EVO_COMMAND=evo
# or
MESH_EVO_COMMAND="uv run --project /workspace/mesh-intelligence/evo/plugins/evo evo"
```

Normal run processing does not invoke Evo. Evo commands are only reachable through an explicit steering command.

## Evo Launch Steering

Mesh exposes a bounded operator-triggered launch path:

```json
{
  "command": "launch_evo",
  "target_path": "app/search.py",
  "benchmark_command": "python3 benchmark.py --target {target}",
  "instrumentation_mode": "inline",
  "metric": "max",
  "gate_command": "python3 -m unittest discover -s tests"
}
```

Execution rules:

- accepted only when a run is paused at `evaluation_ready` or after the run has already completed
- requires `evo.ready == true`
- requires a `repo_patch_service` decision with `repo_path`, `allowed_paths`, and `test_commands`
- requires `target_path` to be one of the run's `allowed_paths`
- requires `benchmark_command` when the repo does not already contain `.evo/meta.json`

Artifact shape:

- run artifact key: `evo_launches`
- vault note: `Evo/<run_id>.md`
- event stream: `integration_name="evo"` with queued, running, and completed or failed records

Boundaries:

- Mesh may run `evo status` for an existing workspace or `evo init`, `evo new`, and `evo run` for an operator-approved bounded bootstrap.
- Mesh does not run `evo optimize`, create PRs, merge changes, or promote anything to production.
- Mesh requires a clean git worktree before Evo bootstrap.

## LatentMAS Sidecar

LatentMAS is disabled unless all of these are set:

```bash
MESH_LATENTMAS_ENABLED=1
MESH_LATENTMAS_URL=http://127.0.0.1:8791
```

Optional controls:

```bash
MESH_LATENTMAS_TIMEOUT_SECONDS=600
MESH_LATENTMAS_MODEL_NAME=Qwen/Qwen3-4B
MESH_LATENTMAS_DEVICE=cuda
MESH_LATENTMAS_PROMPT_MODE=sequential
MESH_LATENTMAS_LATENT_STEPS=10
MESH_LATENTMAS_MAX_NEW_TOKENS=1024
MESH_LATENTMAS_USE_VLLM=0
MESH_LATENTMAS_MAX_ARTIFACT_CHARS=20000
```

Run the opt-in Docker profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.latentmas.yml --profile latentmas up --build
```

In the all-in-one stack, use the stack profile and set Mesh to expect LatentMAS readiness:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 docker compose -f docker-compose.stack.yml up --build
```

The sidecar exposes:

```text
GET /health
POST /infer
```

`GET /api/readiness` includes `latentmas.ready`, `latentmas.detail`, and `latentmas.url`.

## Deep Agents Fabric

Deep Agents is disabled unless:

```bash
MESH_AGENT_FABRIC_MODE=deepagents
```

In the all-in-one stack, enable it through the stack-scoped variable so the smoke verifier also expects Deep Agents readiness:

```bash
MESH_STACK_AGENT_FABRIC_MODE=deepagents OPENAI_API_KEY=... docker compose -f docker-compose.stack.yml up --build
```

Optional controls:

```bash
MESH_DEEPAGENTS_MODEL=openai:MiniMax-M2.7
MESH_DEEPAGENTS_TIMEOUT_SECONDS=120
MESH_DEEPAGENTS_WORKSPACE_ROOT=.mesh-runtime-state/deepagents
MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS=20000
```

Readiness behavior:

- If `MESH_AGENT_FABRIC_MODE` is not `deepagents`, `/api/readiness` reports Deep Agents as disabled.
- If the vendored `deepagents` package is unavailable on `PYTHONPATH`, readiness reports Deep Agents unavailable.
- If Deep Agents is enabled and importable, readiness reports the configured model and workspace path.
- Provider-key warnings are surfaced through `deepagents.warnings`; missing keys do not block the Mesh control plane from running.

Operational boundary:

- Deep Agents never executes Mesh actuation.
- Deep Agents never runs live `kubectl`.
- Deep Agents never edits the real repository checkout.
- Patch-shaped lanes only see copied `allowed_paths` files inside the sandbox workspace.
- Any sandbox-created file outside the allowlist is flagged and withheld as a safe proposal artifact.

## Frontend

Open the `Agents` tab on any run. The panel shows:

- task kind and scope
- participating worker lanes
- selected attempt
- adapter
- recommended action
- risk flags
- allowed paths and test counts
- changed files
- test results
- workspace path
- diff artifact when present

## Codex Plugin

The repo includes a local Codex plugin at `plugins/mesh-intelligence` and a repo marketplace entry at `.agents/plugins/marketplace.json`.

The plugin contributes the `mesh-intelligence` skill. Codex workers using that skill should call the bundled read-only helper:

```bash
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py health
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py summary --run-id run_...
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py agent-tasks --run-id run_...
```

The helper defaults to `http://127.0.0.1:8787` and honors `MESH_BASE_URL`. It does not mutate Mesh state. If it reports `stale_agent_tasks_route: true`, the running Mesh server predates the agent-task route and must be restarted from the current tree before Codex can read first-class `agent_tasks` payloads.

## Production Rule

Treat LatentMAS, Deep Agents, Goose, Hermes, Codex, Claude Code, OpenClaw, and Evo as bounded workers. They can propose. Mesh decides. Production execution remains behind Mesh policy, smoke checks, and approval gates.
