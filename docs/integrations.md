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

## Environment variables

- `MESH_PROMPTFOO_COMMAND`
- `MESH_GOOSE_COMMAND`
- `MESH_GOOSE_COMMAND_TIMEOUT_SECONDS`
- `MESH_HERMES_COMMAND`
- `MESH_HERMES_COMMAND_TIMEOUT_SECONDS`
- `MESH_GITNEXUS_SIDECAR_URL`
- `MESH_GITNEXUS_SIDECAR_COMMAND`

If `setup_integrations.py` has already written a command into `.mesh-runtime-state/integrations.json`, the runtime uses that saved command unless an explicit environment variable overrides it.

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
- GitNexus readiness reports the sidecar URL or inferred command path, depending on configuration.

Goose no longer probes installed Ollama models during integration resolution. If `OPENAI_BASE_URL` or `OPENAI_HOST` is configured and no explicit Goose provider is set, the resolver infers the OpenAI-compatible route and defaults the model to `MiniMax-M2.5`. Ollama is used only when `GOOSE_PROVIDER=ollama` or an equivalent explicit provider setting is present.
