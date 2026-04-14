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
  - `evo` is read-only in Mesh. Readiness verifies the configured Evo CLI, and agent tasks record whether a bounded code-remediation run is suitable for Evo discovery or benchmark preparation. Mesh does not run `evo init`, `evo new`, `evo run`, `evo optimize`, git worktree commands, or subagents.
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
- `MESH_GITNEXUS_SIDECAR_URL`
- `MESH_GITNEXUS_SIDECAR_COMMAND`

If `setup_integrations.py` has already written a command into `.mesh-runtime-state/integrations.json`, the runtime uses that saved command unless an explicit environment variable overrides it.

`MESH_AGENT_FABRIC_MODE` is not stored in `.mesh-runtime-state/integrations.json`; it is runtime config only and defaults to `native`.

## Docker Compose defaults

The default Compose stack now starts:

- `mesh`, which bundles Promptfoo and Goose in the application image.
- `hermes`, a dedicated sidecar container built from `Dockerfile.hermes` and tagged as `${HERMES_RUNTIME_IMAGE:-autoresearch-hermes-runtime:local}`.

Inside Compose, `mesh` defaults `MESH_HERMES_COMMAND` to:

```text
docker exec -w /workspace/mesh-intelligence -e HERMES_HOME=/workspace/mesh-intelligence/.hermes-local mesh-intelligence-hermes /opt/venv/bin/hermes
```

That keeps the control plane contract stable while Hermes itself runs in its own container with a persisted `.hermes-local/` workspace state directory.

Compose provider selection uses namespaced host overrides (`MESH_COMPOSE_GOOSE_PROVIDER`, `MESH_COMPOSE_GOOSE_MODEL`, `MESH_COMPOSE_HERMES_INFERENCE_PROVIDER`, and related variables) before writing container-level `GOOSE_*` / `HERMES_*` environment variables. This prevents stray host-level `GOOSE_PROVIDER=ollama` or `HERMES_INFERENCE_PROVIDER=ollama` values from selecting Ollama automatically.

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
- GitNexus readiness reports the sidecar URL or inferred command path, depending on configuration.

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

Mesh stores Evo readiness and agent-task recommendations only. Evo workspace state (`.evo/`), benchmark instrumentation, worktrees, experiment commits, and pull requests remain outside Mesh's automatic execution path and must not be committed to `main` as a side effect of readiness or agent-task recording.

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

Use `docker-compose.prod.yml` for production-like deployments. It avoids the repository bind mount and Docker socket used by the developer stack, requires `OPENAI_API_KEY`, requires `MESH_KUBECONFIG_HOST_PATH`, and fails fast unless `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES` are set. Hermes is not configured there by default because the local sidecar path depends on `docker exec`; use Goose in-image or a separately hardened Hermes topology before enabling `MESH_HERMES_COMMAND`.

For a demo that explicitly needs Hermes via Docker exec, add `docker-compose.prod.hermes.yml`. That override starts a hardened Hermes sidecar and mounts only the Docker socket into `mesh` so `MESH_HERMES_COMMAND` can exec `/opt/venv/bin/hermes` inside the named Hermes container. The socket mount is privileged host access; do not hide it inside the baseline production compose file.
