# Integrations

`mesh-intelligence` resolves external tooling through a small integration contract rather than calling vendor CLIs directly from the control plane. `python3 setup_integrations.py` writes the resolved commands to `.mesh-runtime-state/integrations.json`, and the runtime/API report readiness for each integration independently.

## Modes

- Evaluation modes:
  - `native` keeps evaluation in-process.
  - `promptfoo` runs `services/evaluation/promptfoo_bridge.py`, which invokes the configured Promptfoo CLI and returns the Mesh evaluation contract.
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
- `MESH_AGENT_FABRIC_MODE`
- `MESH_DEEPAGENTS_MODEL`
- `MESH_DEEPAGENTS_TIMEOUT_SECONDS`
- `MESH_DEEPAGENTS_WORKSPACE_ROOT`
- `MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS`

If `setup_integrations.py` has already written a command into `.mesh-runtime-state/integrations.json`, the runtime uses that saved command unless an explicit environment variable overrides it.

`MESH_AGENT_FABRIC_MODE` is not stored in `.mesh-runtime-state/integrations.json`; it is runtime config only and defaults to `native`.

## Docker Compose defaults

The one-command all-in-one stack is `docker-compose.stack.yml`:

```bash
docker compose -f docker-compose.stack.yml up --build
```

This is the preferred local whole-system validation path. It is documented in detail in [`docs/all-in-one-compose-stack.md`](./all-in-one-compose-stack.md).

It starts:

- `k3s`, a local Kubernetes API inside the compose graph.
- `mesh-kube-bootstrap`, a one-shot job that rewrites kubeconfig for the compose network and seeds the baseline `semantic-search` Deployment.
- `mesh`, which bundles Promptfoo and Goose in the application image, enables live Kubernetes execution against the shared kubeconfig, and defaults `MESH_AGENT_FABRIC_MODE=native` in this topology for deterministic smoke runs.
- `hermes`, a dedicated sidecar container built from `Dockerfile.stack.hermes`.
- `gitnexus`, a local GitNexus HTTP sidecar built from `Dockerfile.stack.gitnexus`.
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

Inside the lighter Compose stack, `mesh` defaults `MESH_HERMES_COMMAND` to `hermes` and persists Hermes state in `/workspace/mesh-intelligence/.hermes-local`.

Compose provider selection uses namespaced host overrides (`MESH_COMPOSE_GOOSE_PROVIDER`, `MESH_COMPOSE_GOOSE_MODEL`, `MESH_COMPOSE_HERMES_INFERENCE_PROVIDER`, and related variables) before writing container-level `GOOSE_*` / `HERMES_*` environment variables. This prevents stray host-level `GOOSE_PROVIDER=ollama` or `HERMES_INFERENCE_PROVIDER=ollama` values from selecting Ollama automatically.

Stack-only integration variables:

- `MESH_STACK_HERMES_COMMAND` overrides the Mesh-to-Hermes sidecar command. The default uses `docker exec` against `mesh-intelligence-hermes-stack`.
- `MESH_STACK_GITNEXUS_URL` overrides the Mesh-to-GitNexus sidecar URL. The default is `http://gitnexus:4747`.
- `MESH_DOCKER_SOCKET_HOST_PATH` controls the host Docker socket mounted into the Mesh container for sidecar command execution.
- `MESH_STACK_AGENT_FABRIC_MODE` selects `native` or `deepagents` for proposal lanes in the full stack.
- `MESH_STACK_ENABLE_LATENTMAS` controls whether Mesh expects the optional LatentMAS profile to be ready.
- `HERMES_AGENT_REF`, `UV_VERSION`, `GOOSE_VERSION`, and `GITNEXUS_VERSION` are pinned by default and should be changed only as an explicit dependency upgrade.

## Readiness behavior

- Promptfoo readiness checks the resolved Promptfoo command.
- Goose readiness checks the resolved Goose bridge target and reports provider/profile warnings when configuration is incomplete.
- Hermes readiness checks the resolved Hermes bridge target and reports the resolved command description.
- Evo readiness runs the resolved command with `--version` and only reports ready when the output identifies `evo-hq-cli`. The unrelated PyPI `evo` package is reported as an unexpected package.
- Deep Agents readiness reports:
  - disabled when `MESH_AGENT_FABRIC_MODE` is not `deepagents`
  - unavailable when the vendored `deepagents` package cannot be imported
  - ready when Deep Agents is enabled and importable, with `detail` showing the configured model and workspace root
  - provider-key warnings in `deepagents.warnings` when the selected model family is missing credentials
Goose no longer probes installed Ollama models during integration resolution. If `OPENAI_BASE_URL` or `OPENAI_HOST` is configured and no explicit Goose provider is set, the resolver infers the OpenAI-compatible route and defaults the model to `MiniMax-M2.5`. Ollama is used only when `GOOSE_PROVIDER=ollama` or an equivalent explicit provider setting is present.

## Evo proposal lane

Use a globally installed `evo-hq-cli`:

```bash
MESH_EVO_COMMAND=evo
```

Or point Mesh at the vendored source checkout when `uv` is available in the runtime:

```bash
MESH_EVO_COMMAND="uv run --project /workspace/mesh-intelligence/evo/plugins/evo evo"
```

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

Operational restriction:

- Do not give Deep Agents direct access to production kubeconfig or Mesh actuators.
- Do not point the adapter at the real repo checkout for writes.
- Do not treat Deep Agents readiness as approval to bypass evaluation or operator gates.

## Production compose

Use `docker-compose.prod.yml` for production-like deployments. It avoids the repository bind mount and Docker socket used by the all-in-one stack, requires `OPENAI_API_KEY`, requires `MESH_KUBECONFIG_HOST_PATH`, and fails fast unless `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES` are set. Promptfoo, Goose, and Hermes are bundled in the mesh image; override `MESH_HERMES_COMMAND` only when using an explicitly reviewed external Hermes topology.
