# Integrations

`orbital-mesh` resolves external tooling through a small integration contract rather than calling vendor CLIs directly from the control plane. `python3 setup_integrations.py` writes the resolved commands to `.mesh-runtime-state/integrations.json`, and the runtime/API report readiness for each integration independently.

## Modes

- Evaluation modes:
  - `native` runs the `services.evaluation.mesh_eval` package: deterministic contract checks, Mesh trajectory scoring, verifier output, and LatentMAS tokenizer metadata in-process.
  - `promptfoo` is legacy-compatible input only. It no longer controls pass/fail; Mesh still evaluates `task -> trace -> verifier -> scorer -> memory`.
- Orchestration modes:
  - `native` keeps orchestration in-process through the bounded local actuators.
  - `goose` runs `services/orchestrator/goose_bridge.py`, which invokes the configured Goose command and returns structured review metadata before actuation.
  - `hermes` runs `services/orchestrator/hermes_bridge.py`, which invokes the configured Hermes command and returns structured review metadata before actuation.
- Proposal lanes:
  - `evo` is bounded in Mesh. Readiness verifies the configured Evo CLI, agent tasks record whether a bounded code-remediation run is suitable for Evo discovery or benchmark preparation, and operator steering can explicitly launch a scoped Evo bootstrap or status check for eligible runs.
- Agent fabric modes:
  - `native` keeps agent-task lanes as deterministic `native_contract` artifacts.
  - `deepagents` routes Goose/Hermes/Codex/Claude Code/OpenClaw/Evo proposal lanes through `services/orchestrator/deepagents_adapter.py`. The adapter runs inside a per-run sandbox workspace and returns proposal artifacts only. It does not execute Mesh actuation, live Kubernetes commands, or real repo writes.

## Environment variables

- `MESH_PROMPTFOO_COMMAND`
- `MESH_GOOSE_COMMAND`
- `MESH_GOOSE_COMMAND_TIMEOUT_SECONDS`
- `MESH_GOOSE_RUN_TIMEOUT_SECONDS`
- `MESH_HERMES_COMMAND`
- `MESH_HERMES_COMMAND_TIMEOUT_SECONDS`
- `MESH_HERMES_RUN_TIMEOUT_SECONDS`
- `MESH_EVO_COMMAND`
- `MESH_EVO_COMMAND_TIMEOUT_SECONDS`

Promptfoo readiness may still appear for older stacks, but the active evaluation
artifacts are `task_trace`, `trajectory_score`, `verifier_output`, and
`phoenix_spans`. DeepEval is used for code-defined CI evals when installed in
the CI environment. Phoenix/OpenTelemetry span export is best-effort trace
inspection and never blocks execution.
- `MESH_EVAL_CONTEXT_TOKEN_BUDGET`
- `MESH_EVAL_TOKENIZER_JSON`
- `MESH_EVAL_SENTENCEPIECE_MODEL`
- `MESH_EVAL_LATENTMAS_CRATE`
- `MESH_EVAL_LATENTMAS_COMMAND`
- `MESH_EVAL_LATENTMAS_TIMEOUT_SECONDS`
- `MESH_READINESS_PROBE_TIMEOUT_SECONDS`
- `MESH_AGENT_FABRIC_MODE`
- `MESH_DEEPAGENTS_MODEL`
- `MESH_DEEPAGENTS_TIMEOUT_SECONDS`
- `MESH_DEEPAGENTS_WORKSPACE_ROOT`
- `MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS`

If `setup_integrations.py` has already written a command into `.mesh-runtime-state/integrations.json`, the runtime uses that saved command unless an explicit environment variable overrides it.

`MESH_AGENT_FABRIC_MODE` is not stored in `.mesh-runtime-state/integrations.json`; it is runtime config only and defaults to `native`.

## Native Mesh Eval

`mesh_eval` is the package boundary for the Promptfoo replacement. It packages
the native trajectory evaluator with the LatentMAS tokenizer boundary so every
task trace records the context-budget basis used for evaluation.

Set either `MESH_EVAL_TOKENIZER_JSON` or `MESH_EVAL_SENTENCEPIECE_MODEL`, not
both. If neither is set, `mesh_eval` records the explicit heuristic fallback.
Set `MESH_EVAL_LATENTMAS_COMMAND` to a Rust LatentMAS command, for example:

```bash
MESH_EVAL_LATENTMAS_COMMAND="cargo run --quiet --manifest-path latent-mesh/LatentMAS/Cargo.toml --"
```

When configured, Mesh runs a best-effort Rust tokenizer probe for the evaluated
task and embeds the result under `task_trace.mesh_eval.latent_mesh.tokenizer_probe`.
Probe failure records an error artifact and never replaces deterministic
contract, verifier, or trajectory gates.

## Docker Compose defaults

The one-command all-in-one stack is `docker-compose.stack.yml`:

```bash
docker compose -f docker-compose.stack.yml up --build
```

This is the preferred local whole-system validation path. It is documented in detail in [`docs/all-in-one-compose-stack.md`](./all-in-one-compose-stack.md).

It starts:

- `k3s`, a local Kubernetes API inside the compose graph.
- `postgres`, a local Postgres database for production-style persistence testing.
- `mesh-kube-bootstrap`, a one-shot job that rewrites kubeconfig for the compose network and seeds the baseline `semantic-search` Deployment.
- `mesh`, which bundles Promptfoo and Goose in the application image, enables live Kubernetes execution against the shared kubeconfig, and defaults `MESH_AGENT_FABRIC_MODE=native` in this topology for deterministic smoke runs.
- `hermes`, a dedicated sidecar container built from `Dockerfile.stack.hermes`.
- `mesh-smoke`, a one-shot validation container that checks readiness, seeds a failure, and launches a live Mesh run.

Optional GPU worker lane:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 docker compose -f docker-compose.stack.yml up --build
```

Optional Deep Agents proposal fabric:

```bash
MESH_STACK_AGENT_FABRIC_MODE=deepagents OPENAI_API_KEY=... docker compose -f docker-compose.stack.yml up --build
```

The lighter developer stack remains `docker-compose.yml`. It starts `mesh`, which bundles Promptfoo, Goose, and Hermes in the application image.

Inside the lighter Compose stack, `mesh` defaults `MESH_HERMES_COMMAND` to `hermes` and persists Hermes state in `/workspace/orbital-mesh/.hermes-local`.

Compose provider selection uses namespaced host overrides (`MESH_COMPOSE_GOOSE_PROVIDER`, `MESH_COMPOSE_GOOSE_MODEL`, `MESH_COMPOSE_HERMES_INFERENCE_PROVIDER`, and related variables) before writing container-level `GOOSE_*` / `HERMES_*` environment variables. This prevents stray host-level `GOOSE_PROVIDER=ollama` or `HERMES_INFERENCE_PROVIDER=ollama` values from selecting Ollama automatically.

Stack-only integration variables:

- `MESH_STACK_HERMES_EXEC_COMMAND` overrides the Mesh-to-Hermes sidecar command. The default uses `/usr/local/bin/compose_hermes_exec.sh`, which finds the project-local Hermes sidecar through Docker Compose labels.
- `MESH_STACK_GITNEXUS_URL` points Mesh at an external GitNexus sidecar. The stack does not start GitNexus by default.
- `MESH_DOCKER_SOCKET_HOST_PATH` controls the host Docker socket mounted into the Mesh container for sidecar command execution.
- `MESH_STACK_AGENT_FABRIC_MODE` selects `native` or `deepagents` for proposal lanes in the full stack.
- `MESH_STACK_ENABLE_LATENTMAS` controls whether Mesh expects the optional LatentMAS profile to be ready.
- `MESH_AGENT_TASK_TIMEOUT_SECONDS` bounds proposal-lane collection during run execution. Slow agent-task lanes degrade into recorded failed attempts instead of blocking execution.
- `HERMES_AGENT_REF`, `UV_VERSION`, and `GOOSE_VERSION` are pinned by default and should be changed only as an explicit dependency upgrade.

Legacy host-driven e2e overlay variables:

- `MESH_E2E_KUBERNETES_ALLOWED_CONTEXTS` defaults the `docker-compose.e2e.yml` allowlist to `k3d-mesh-e2e`.
- `MESH_E2E_KUBERNETES_ALLOWED_NAMESPACES` defaults the `docker-compose.e2e.yml` allowlist to `search`.
- `MESH_E2E_KUBERNETES_LIVE_EXECUTION_ENABLED` defaults live execution to enabled for the e2e overlay.

## Readiness behavior

- Promptfoo readiness checks the resolved Promptfoo command.
- Goose readiness checks the resolved Goose bridge target and reports provider/profile warnings when configuration is incomplete.
- Hermes readiness checks the resolved Hermes bridge target and reports the resolved command description.
- Evo readiness runs the resolved command with `--version` and only reports ready when the output identifies `evo-hq-cli`. The unrelated PyPI `evo` package is reported as an unexpected package.
- Readiness probes run concurrently, use `MESH_READINESS_PROBE_TIMEOUT_SECONDS` for each generic CLI probe, and are cached briefly by the control plane so one slow optional integration does not serialize every `/api/readiness` or system stream response.
- Deep Agents readiness reports:
  - disabled when `MESH_AGENT_FABRIC_MODE` is not `deepagents`
  - unavailable when the vendored `deepagents` package cannot be imported
  - ready when Deep Agents is enabled and importable, with `detail` showing the configured model and workspace root
  - provider-key warnings in `deepagents.warnings` when the selected model family is missing credentials
- For `MESH_DEEPAGENTS_MODEL=openai:MiniMax-*`, Mesh now resolves the OpenAI-compatible key from `OPENAI_API_KEY` first and falls back to `MINIMAX_API_KEY` when present.
- LatentMAS readiness now reads the sidecar `/health` payload instead of treating any HTTP 200 as ready. If the configured device is unavailable, readiness surfaces the sidecar detail string rather than reporting a false green state.
Goose no longer probes installed Ollama models during integration resolution. If `OPENAI_BASE_URL` is configured and no explicit Goose provider is set, the resolver infers the OpenAI-compatible route and defaults the model to `MiniMax-M2.5`. Ollama is used only when `GOOSE_PROVIDER=ollama` or an equivalent explicit provider setting is present.

## Mock, Fallback, And Stub Classification

| Path | Classification | Production posture |
| --- | --- | --- |
| `KubernetesAdapter` mock mode | Intentional safety default | No cluster mutation unless `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1` and context/namespace allowlists pass. |
| `SystemdSshAdapter` mock mode | Intentional safety default | No SSH mutation unless `MESH_SSH_EXECUTION_ENABLED=1` and host/service allowlists pass. |
| `KurtosisAdapter` mock mode | Intentional safety default | No Kurtosis mutation unless `MESH_KURTOSIS_EXECUTION_ENABLED=1`, enclave/service allowlists pass, and autonomous Reth restart is separately enabled when required. |
| Kurtosis Docker-label restart fallback | Bounded operational fallback | Used only when the Kurtosis engine is unreachable. It restarts exactly one Docker container selected by Kurtosis labels and fails closed when the target is ambiguous. |
| `FeatureFlagAdapter` | Unfinished production adapter | Local deterministic seam only; replace with the real flag provider before production flag rollout. |
| `IncidentAdapter` | Unfinished production adapter | Local deterministic seam only; replace with PagerDuty/Opsgenie/Jira/Linear integration before production incident creation. |
| `AuditLogAdapter` | Unfinished production adapter | Local deterministic seam only; replace or mirror into durable audit storage before compliance reliance. |
| Feedback stub observations | Intentional replay/development fallback | Live Prometheus observations override stub fields when configured. Stub values remain allowed for fixtures and replay, and monitoring query failure does not mark remediation failed by itself. |
| Observer fallback approve | Intentional non-blocking observer default | Observer outages stamp an errored approval so deterministic policy still controls. The observer can promote escalation only when it returns a valid escalation verdict. |
| Goose fallback provider/model | Operational redundancy | Secondary LLM route after primary Goose provider failure; outputs still pass schema validation and bounded action allowlists. |
| Native evaluation/orchestration modes | Intentional deterministic local modes | Used for CI and local smoke paths; live action still depends on the relevant actuator allowlists and execution flags. |

Paths classified as unfinished production adapters must not be presented as
production integrations in release notes or readiness output. Paths classified
as intentional safety defaults are acceptable only when their operational docs
state the enablement flags, allowlists, and failure behavior.

## Evo proposal lane

Use a globally installed `evo-hq-cli`:

```bash
MESH_EVO_COMMAND=evo
```

Or point Mesh at the vendored source checkout when `uv` is available in the runtime:

```bash
MESH_EVO_COMMAND="uv run --project /workspace/orbital-mesh/evo/plugins/evo evo"
```

The stack image now installs `uv` into `/usr/local/bin`, so this command remains valid after the container drops from `root` to the non-root `mesh` user.

Mesh stores Evo readiness and agent-task recommendations by default. Evo execution is not part of normal run progression; it requires an explicit `launch_evo` steering command on an eligible run.

`launch_evo` rules:

- accepted only when a run is paused at `evaluation_ready` or after completion
- requires `evo.ready == true`
- requires a `repo_patch_service` decision plus `repo_path`, `allowed_paths`, and `test_commands`
- requires `target_path` to stay inside the run's `allowed_paths`
- requires `benchmark_command` when `.evo/meta.json` is not already present

`launch_evo` records run-scoped artifacts under `evo_launches`, writes an `Evo/<run_id>.md` vault note, and emits `integration_name="evo"` events as the launch moves through queued, running, and completed or failed states.

Operational boundary:

- Mesh may run `evo status` for an existing workspace or `evo init`, `evo new`, and `evo run` for an explicitly steered bounded bootstrap.
- Mesh does not run `evo optimize`, create pull requests, merge branches, or bypass evaluation and operator gates.
- Evo workspace state (`.evo/`), benchmark instrumentation, worktrees, and experiment commits must not be committed to `main` as a side effect of readiness or agent-task recording.

## Deep Agents agent fabric

Enable the optional Deep Agents fabric:

```bash
MESH_AGENT_FABRIC_MODE=deepagents
MESH_DEEPAGENTS_MODEL=openai:MiniMax-M2.7
MESH_DEEPAGENTS_TIMEOUT_SECONDS=120
MESH_DEEPAGENTS_WORKSPACE_ROOT=.mesh-runtime-state/deepagents
MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS=20000
```

Behavior:

- Mesh creates one sandbox workspace per run/task/lane under `MESH_DEEPAGENTS_WORKSPACE_ROOT`.
- For patch-shaped tasks, Mesh copies only `allowed_paths` files into that workspace before invoking Deep Agents.
- The adapter records `adapter="deepagents"` plus `workspace_path`, `diff`, `deepagents_final_message`, `changed_files`, and `test_results` in the attempt output when available.
- Missing provider keys should not crash the control plane. The attempt carries non-blocking risk flags and readiness warnings instead.
- Deep Agents uses the OpenAI-compatible MiniMax route with explicit `base_url` and API key wiring when the configured model is `openai:MiniMax-*`. This avoids proposal-lane 401s caused by relying on implicit env discovery.

Operational restriction:

- Do not give Deep Agents direct access to production kubeconfig or Mesh actuators.
- Do not point the adapter at the real repo checkout for writes.
- Do not treat Deep Agents readiness as approval to bypass evaluation or operator gates.

## Production compose

Use `docker-compose.prod.yml` for production-like deployments. It avoids the repository bind mount and Docker socket used by the all-in-one stack, requires `OPENAI_API_KEY`, requires `MESH_KUBECONFIG_HOST_PATH`, and fails fast unless `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES` are set. Promptfoo, Goose, and Hermes are bundled in the mesh image; override `MESH_HERMES_COMMAND` only when using an explicitly reviewed external Hermes topology.
