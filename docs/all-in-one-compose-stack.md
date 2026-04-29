# All-In-One Docker Compose Stack

`docker-compose.stack.yml` is the canonical local environment for launching Mesh, its required local sidecars, an embedded Kubernetes control plane, and an automated live-remediation smoke run with one Compose command.

Use this stack when you need to validate the whole system contract at once:

- Mesh HTTP API and native `MeshControl` OS companion.
- Promptfoo, Goose, and Hermes readiness.
- Dedicated Hermes sidecar.
- Embedded k3s cluster with a seeded `semantic-search` Deployment.
- Additional compose-local k3s clusters labeled as VM and bare-metal substrates for multi-context runs.
- Compose-local RPC gateway and indexer HTTP targets for live coverage probes.
- Live Kubernetes execution through the same Mesh rollout path used by production-like runs.
- Scheduled reversible chaos injection across all compose-local Kubernetes contexts.
- Optional LatentMAS GPU inference sidecar.
- Optional Deep Agents proposal fabric.

Use the lighter `docker-compose.yml` when you only need the Mesh server and bundled CLI integrations for manual development.

## Start

Default deterministic stack:

```bash
docker compose -f docker-compose.stack.yml up --build
```

Detached mode:

```bash
docker compose -f docker-compose.stack.yml up --build -d
docker compose -f docker-compose.stack.yml ps
docker compose -f docker-compose.stack.yml logs -f mesh-smoke
```

The Mesh API is published at:

```text
http://127.0.0.1:8787
```

The internal OS companion is published through `mesh-ui` at:

```text
http://127.0.0.1:3000/?app=MeshControl
```

The default stack keeps `MESH_STACK_AGENT_FABRIC_MODE=native`. That is deliberate: the smoke run should validate Mesh and Kubernetes deterministically without requiring model credentials.

## Optional Lanes

Enable the LatentMAS GPU worker sidecar:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 docker compose -f docker-compose.stack.yml up --build
```

**Apple Silicon / Docker Desktop:** Linux containers do not see Metal. Use the CPU image and device (no NVIDIA `deploy` block in the stack file):

```bash
MESH_LATENTMAS_DOCKERFILE=Dockerfile.latentmas.cpu MESH_LATENTMAS_DEVICE=cpu \
  COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 \
  docker compose -f docker-compose.stack.yml up --build
```

**Metal (MPS) on macOS:** run LatentMAS on the host (`MESH_LATENTMAS_DEVICE=mps`, `python -m services.orchestrator.latentmas_server`) and set `MESH_STACK_LATENTMAS_URL=http://host.docker.internal:8791` for Mesh. **Linux + NVIDIA + CUDA:** keep `Dockerfile.latentmas`, set `MESH_LATENTMAS_DEVICE=cuda`, and add `-f docker-compose.latentmas-nvidia.yml` so Compose requests the GPU.

Enable Deep Agents proposal lanes:

```bash
MESH_STACK_AGENT_FABRIC_MODE=deepagents OPENAI_API_KEY=... docker compose -f docker-compose.stack.yml up --build
```

Enable both:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 MESH_STACK_AGENT_FABRIC_MODE=deepagents OPENAI_API_KEY=... docker compose -f docker-compose.stack.yml up --build
```

Deep Agents remains proposal-only. It does not receive direct Kubernetes credentials, does not edit the real checkout, and does not execute Mesh actuation. LatentMAS is advisory. Mesh policy, evaluation, approval behavior, audit, and Kubernetes allowlists remain authoritative.

## Topology

| Service | Role | Published port | Persistence |
| --- | --- | --- | --- |
| `k3s` | Embedded Kubernetes API used for local live execution | `${MESH_K3S_API_PUBLISH_PORT:-6443}` | `k3s_server_data`, `mesh_kubeconfig` |
| `k3s-vm` | Second embedded Kubernetes API representing a VM-backed node pool | none | `k3s_vm_server_data`, `mesh_kubeconfig_vm` |
| `k3s-baremetal` | Third embedded Kubernetes API representing a bare-metal node pool | none | `k3s_baremetal_server_data`, `mesh_kubeconfig_baremetal` |
| `postgres` | Local Postgres for production-style persistence testing | `${MESH_POSTGRES_PUBLISH_PORT:-5432}` | `mesh_postgres_data` |
| `rpc-gateway` | Compose-local HTTP RPC gateway target used by the smoke probe | none | none |
| `indexer` | Compose-local HTTP indexer target used by the smoke probe | none | none |
| `mesh-kube-bootstrap` | One-shot kubeconfig rewrite, namespace creation, and baseline Deployment seed | none | `mesh_kubeconfig` |
| `mesh-kube-bootstrap-vm` | One-shot bootstrap for the VM-labeled k3s cluster | none | `mesh_kubeconfig_vm` |
| `mesh-kube-bootstrap-baremetal` | One-shot bootstrap for the bare-metal-labeled k3s cluster | none | `mesh_kubeconfig_baremetal` |
| `mesh` | Mesh API, readiness, run execution, vault, Merkle, and Kubernetes actuation | `${MESH_PUBLISH_PORT:-8787}` | `mesh_runtime_state`, `goose_config`, all `mesh_kubeconfig*` volumes |
| `mesh-ui` | Lusis OS shell with native `MeshControl` | `${MESH_UI_PUBLISH_PORT:-3000}` | none |
| `hermes` | Dedicated Hermes runtime sidecar reached by `MESH_HERMES_COMMAND` through `docker exec` | none | `hermes_home` |
| `mesh-smoke` | One-shot readiness and live-remediation verifier | none | `mesh_kubeconfig` |
| `mesh-chaos` | Long-running random chaos injector and Mesh run launcher | none | `.mesh-runtime-state/compose-chaos` |
| `latentmas` | Optional GPU inference sidecar | `${MESH_LATENTMAS_PUBLISH_PORT:-8791}` | `latentmas_hf_cache` |

## Boot Sequence

1. Compose builds `mesh-intelligence-stack` and `mesh-intelligence-hermes`.
2. `k3s`, `k3s-vm`, and `k3s-baremetal` start single-node Kubernetes APIs and write kubeconfigs to separate volumes.
3. `postgres` starts for production-style persistence testing. Mesh still defaults to `MESH_STATE_BACKEND=file`; set `MESH_STATE_BACKEND=postgres` to use it.
4. The bootstrap jobs wait for k3s health, rewrite kubeconfig API endpoints to Compose-reachable service names, assign unique context/cluster/user names, create namespace `search`, and apply healthy `semantic-search` Deployments.
5. `hermes` must report healthy before `mesh` starts.
6. `mesh` starts with live Kubernetes execution enabled, a colon-merged `KUBECONFIG`, allowed contexts `mesh-compose,mesh-compose-vm,mesh-compose-baremetal`, and allowed namespace `search`.
7. `mesh-ui` waits for Mesh health and serves the internal OS companion.
8. `mesh-smoke` waits for Mesh health, verifies required readiness entries, seeds a CrashLoop failure, launches a live Mesh run, and exits non-zero on failure.
9. `mesh-chaos` waits for the smoke run, then schedules reversible chaos across all three contexts and launches Mesh runs against the affected target after each injection.

## Smoke Contract

`mesh-smoke` validates the minimum whole-system contract:

- `/api/health` returns HTTP 200.
- `/api/readiness` reports Promptfoo and Hermes ready.
- Deep Agents is required only when `MESH_STACK_AGENT_FABRIC_MODE=deepagents`.
- LatentMAS is required only when `MESH_STACK_ENABLE_LATENTMAS=1`.
- Kubernetes context `mesh-compose` is usable inside the container.
- The kubeconfig API server is not a loopback URL from inside the smoke container.
- `rpc-gateway` and `indexer` answer real HTTP health probes and emit Mesh-shaped OTel coverage signals through `scripts/compose_target_probe.py`.
- `scripts/e2e_seed_failure.sh crashloop` can mutate the local `semantic-search` Deployment.
- `scripts/e2e_run_mesh.sh` can launch a live Mesh run and reach either completed bounded recovery or an explicit operator gate when policy blocks actuation. The default terminal wait is 600 seconds because native agent fanout, evaluation, and reconciliation can take several minutes before the run lands at the operator gate.

Inspect the result:

```bash
docker compose -f docker-compose.stack.yml logs --tail=200 mesh-smoke
docker compose -f docker-compose.stack.yml logs --tail=200 mesh
```

Manual rerun after the stack is up:

```bash
docker compose -f docker-compose.stack.yml run --rm mesh-smoke
```

Use that `run --rm mesh-smoke` command when you need a process exit code for CI or local verification. `docker compose up --wait` is not the assertion command for this topology because `mesh-smoke` is intentionally one-shot; some Compose versions return non-zero after a completed one-shot service even when it exits `0`.

## Kubernetes Details

The stack uses a Compose-internal k3s API instead of host `k3d`.

Defaults:

| Setting | Default |
| --- | --- |
| Kube contexts | `mesh-compose`, `mesh-compose-vm`, `mesh-compose-baremetal` |
| Namespace | `search` |
| Deployment | `semantic-search` |
| API endpoints inside Compose | `https://k3s:6443`, `https://k3s-vm:6443`, `https://k3s-baremetal:6443` |
| Published host API port | `6443` |
| Mesh kubeconfig path | `/mesh-kubeconfig/kubeconfig:/mesh-kubeconfig-vm/kubeconfig:/mesh-kubeconfig-baremetal/kubeconfig` |

The bootstrap job rewrites the kubeconfig because a server URL like `https://127.0.0.1:6443` would point at the calling container, not the k3s container. Production deployments must use a routable Kubernetes API endpoint or in-cluster service DNS instead.

Live actions are still bounded by:

```text
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1
MESH_KUBERNETES_ALLOWED_CONTEXTS=mesh-compose,mesh-compose-vm,mesh-compose-baremetal
MESH_KUBERNETES_ALLOWED_NAMESPACES=search
```

`rollback_deployment` maps to `kubectl rollout undo deployment/<name> -n <namespace>`. `restart_deployment` maps to `kubectl rollout restart deployment/<name> -n <namespace>`.

## Configuration Matrix

| Variable | Default | Purpose |
| --- | --- | --- |
| `MESH_PUBLISH_PORT` | `8787` | Host port for Mesh HTTP/UI |
| `MESH_K3S_API_PUBLISH_PORT` | `6443` | Host port for the local k3s API |
| `MESH_POSTGRES_PUBLISH_PORT` | `5432` | Host port for local Postgres |
| `MESH_STATE_BACKEND` | `file` | `file` or `postgres` runtime state backend |
| `MESH_DATABASE_URL` | `postgresql://mesh:mesh@postgres:5432/mesh` | Postgres/Supabase connection URL |
| `MESH_LATENTMAS_PUBLISH_PORT` | `8791` | Host port for optional LatentMAS |
| `MESH_STACK_KUBE_CONTEXT` | `mesh-compose` | Normalized kube context in the shared kubeconfig |
| `MESH_STACK_NAMESPACE` | `search` | Seeded namespace and Mesh allowlist |
| `MESH_STACK_DEPLOYMENT` | `semantic-search` | Seeded Deployment and smoke target |
| `MESH_STACK_MULTI_ALLOWED_CONTEXTS` | `mesh-compose,mesh-compose-vm,mesh-compose-baremetal` | Runtime context allowlist for the multi-cluster stack |
| `MESH_STACK_ALLOWED_NAMESPACES` | `search` | Runtime namespace allowlist |
| `MESH_STACK_CHAOS_TARGETS` | `mesh-compose:search:semantic-search:container,mesh-compose-vm:search:semantic-search:vm,mesh-compose-baremetal:search:semantic-search:baremetal` | Chaos target list as `context:namespace:deployment:substrate` entries |
| `MESH_STACK_CHAOS_DURATION_SECONDS` | `259200` | Long-running chaos duration; default is 3 days |
| `MESH_STACK_CHAOS_MIN_SLEEP_SECONDS` | `45` | Minimum delay between chaos cycles |
| `MESH_STACK_CHAOS_MAX_SLEEP_SECONDS` | `180` | Maximum delay between chaos cycles |
| `MESH_STACK_CHAOS_HOLD_SECONDS` | `30` | Fault dwell time before launching the Mesh run and reverting |
| `MESH_STACK_CHAOS_SEED` | `20260428` | Deterministic replay seed for chaos selection |
| `MESH_STACK_CHAOS_RUN_WAIT_SECONDS` | `600` | Base timeout for a post-injection Mesh run to reach a terminal stage |
| `MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS` | `120` | Extra wait granted after each observed run stage or status transition |
| `MESH_STACK_CHAOS_RUN_STAGE_GRACE_SECONDS` | `600` | Extra wait granted after `scenario_analysis_ready` or `evaluation_ready`, where native analysis and evaluation can stay busy longer |
| `MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS` | `1800` | Hard cap for one post-injection Mesh run wait, even when progress is observed |
| `MESH_STACK_CHAOS_REQUEST_TIMEOUT_SECONDS` | `90` | Per-request timeout for Mesh run launch and polling calls |
| `MESH_STACK_AGENT_FABRIC_MODE` | `native` | `native` or `deepagents` proposal fabric |
| `MESH_REASONING_BANK_ENABLED` | `1` | Enables pre-decision retrieval and post-run distillation of strategy memory |
| `MESH_REASONING_BANK_MAX_STRATEGIES` | `8` | Maximum advisory strategy memories attached to a run |
| `MESH_REASONING_BANK_SCALING_MODE` | `sequential` | ReasoningBank retrieval/scaling mode |
| `MESH_CORPUS_MEMORY_ENABLED` | `1` | Projects the incident corpus database into canonical runtime memory at Mesh startup |
| `MESH_CORPUS_DATABASE_PATH` | `/workspace/mesh-intel/.mesh-runtime-state/corpus/incident_corpus.sqlite` | SQLite incident corpus imported into live memory |
| `MESH_CORPUS_MEMORY_PROJECTION_LIMIT` | `5000` | Maximum corpus rows projected on startup |
| `MESH_VAULT_MATERIALIZE_MIN_INTERVAL_SECONDS` | `30` | Minimum interval between non-terminal vault bundle rewrites for the same run |
| `MESH_READINESS_PROBE_TIMEOUT_SECONDS` | `15` | Per-integration CLI readiness timeout used by the Mesh API in the compose stack |
| `MESH_EVAL_CONTEXT_TOKEN_BUDGET` | `2048` | Context token budget recorded and probed by native `mesh_eval` |
| `MESH_EVAL_TOKENIZER_JSON` | empty | Optional Hugging Face `tokenizer.json` for the Rust tokenizer probe |
| `MESH_EVAL_SENTENCEPIECE_MODEL` | empty | Optional SentencePiece `.model` for the Rust tokenizer probe |
| `MESH_EVAL_LATENTMAS_COMMAND` | `latentmas` | Rust LatentMAS CLI used by native `mesh_eval` inside the Mesh image |
| `MESH_EVAL_LATENTMAS_TIMEOUT_SECONDS` | `30` | Timeout for the best-effort tokenizer probe |
| `MESH_EXPECT_MESH_EVAL_TOKENIZER_PROBE` | `1` | Makes smoke fail unless `task_trace.mesh_eval.latent_mesh.tokenizer_probe.status == ok` |
| `MESH_STACK_ENABLE_LATENTMAS` | `0` | Enables Mesh readiness expectation for LatentMAS |
| `MESH_STACK_LATENTMAS_URL` | `http://latentmas:8791` | Mesh-to-sidecar LatentMAS URL |
| `MESH_STACK_HERMES_EXEC_COMMAND` | `docker exec -w /workspace/mesh-intel ... mesh-intel-hermes-stack /opt/venv/bin/hermes` | Mesh-to-sidecar Hermes command |
| `MESH_STACK_GITNEXUS_URL` | empty | Optional external GitNexus sidecar URL |
| `MESH_STACK_SMOKE_EVALUATION_MODE` | `native` | Smoke run evaluation mode |
| `MESH_STACK_SMOKE_ORCHESTRATION_MODE` | `native` | Smoke run orchestration mode |
| `MESH_STACK_SMOKE_STEERING_MODE` | `interruptible_auto` | Smoke run steering mode |
| `MESH_STACK_RPC_GATEWAY_URL` | `http://rpc-gateway:8080/health` | Smoke probe URL for the Compose-local RPC gateway target |
| `MESH_STACK_INDEXER_URL` | `http://indexer:8080/health` | Smoke probe URL for the Compose-local indexer target |
| `E2E_RUN_REQUEST_TIMEOUT_SECONDS` | `90` | Per-request timeout for smoke run launch and polling calls |
| `E2E_RUN_TERMINAL_WAIT_SECONDS` | `600` | Smoke run wait for `completed`, `failed`, `cancelled`, `no_trigger`, or accepted `awaiting_operator` |
| `E2E_RUN_PROGRESS_GRACE_SECONDS` | `120` | Extra smoke wait granted after each observed run stage or status transition |
| `E2E_RUN_STAGE_GRACE_SECONDS` | `600` | Extra smoke wait granted after `scenario_analysis_ready` or `evaluation_ready` |
| `E2E_RUN_MAX_WAIT_SECONDS` | `1800` | Hard cap for one smoke run wait, even when progress is observed |
| `E2E_ACCEPT_AWAITING_OPERATOR` | `1` in stack smoke | Treat an explicit operator gate as a valid smoke outcome |
| `MESH_DOCKER_SOCKET_HOST_PATH` | `/var/run/docker.sock` | Docker socket mount used for Hermes sidecar invocation |
| `HERMES_AGENT_REF` | `1525624904159e7c2d6ac3feef951e27ad0d23bb` | Pinned Hermes Agent git ref used by mesh and Hermes images |
| `UV_VERSION` | `0.11.6` | Pinned uv installer version used by mesh and Hermes images |
| `GOOSE_VERSION` | `v1.30.0` | Pinned Goose release used by the mesh image |

Provider variables such as `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MESH_COMPOSE_GOOSE_PROVIDER`, `MESH_COMPOSE_GOOSE_MODEL`, `MESH_COMPOSE_HERMES_INFERENCE_PROVIDER`, and `MESH_COMPOSE_HERMES_MODEL` are passed through to the relevant containers. The default smoke path does not require model credentials because it runs native evaluation and native orchestration.

## Volumes

| Volume | Contents |
| --- | --- |
| `mesh_runtime_state` | Runs, goals, vault, Merkle proofs, readiness snapshots, research sessions, Deep Agents sandboxes |
| `mesh_kubeconfig` | k3s-generated kubeconfig rewritten for the Compose network |
| `mesh_kubeconfig_vm` | VM-labeled k3s kubeconfig rewritten for the Compose network |
| `mesh_kubeconfig_baremetal` | Bare-metal-labeled k3s kubeconfig rewritten for the Compose network |
| `k3s_server_data` | k3s server state |
| `k3s_vm_server_data` | VM-labeled k3s server state |
| `k3s_baremetal_server_data` | Bare-metal-labeled k3s server state |
| `mesh_postgres_data` | Local Postgres data for `MESH_STATE_BACKEND=postgres` tests |
| `goose_config` | Goose config inside the Mesh container |
| `hermes_home` | Hermes sidecar config, sessions, logs, memories, and skills |
| `latentmas_hf_cache` | Hugging Face model cache for the optional LatentMAS sidecar |

## Teardown

Stop containers but keep volumes:

```bash
docker compose -f docker-compose.stack.yml down
```

Stop containers and remove stack state:

```bash
docker compose -f docker-compose.stack.yml down -v
```

Use `down -v` when you want a clean k3s cluster, kubeconfig, Mesh state directory, and smoke baseline.

## Troubleshooting

Inspect service state:

```bash
docker compose -f docker-compose.stack.yml ps
```

Inspect k3s startup:

```bash
docker compose -f docker-compose.stack.yml logs --tail=200 k3s
```

Inspect bootstrap:

```bash
docker compose -f docker-compose.stack.yml logs --tail=200 mesh-kube-bootstrap
```

Inspect readiness and live run:

```bash
docker compose -f docker-compose.stack.yml logs --tail=200 mesh
docker compose -f docker-compose.stack.yml logs --tail=200 mesh-smoke
```

Common failure modes:

- `k3s` never becomes healthy: Docker must support privileged containers. Docker Desktop must have enough CPU and memory for k3s plus the Mesh image.
- Bootstrap cannot reach Kubernetes: the kubeconfig volume may contain stale data. Run `docker compose -f docker-compose.stack.yml down -v` and start again.
- Smoke reports a loopback Kubernetes server URL: the shared kubeconfig was not rewritten to `https://k3s:6443`. Inspect `mesh-kube-bootstrap` logs and recreate the stack volume.
- Smoke reports `rpc_gateway` or `indexer` unavailable: inspect `rpc-gateway` and `indexer` logs; the smoke run will not count those as covered until their HTTP probes succeed.
- `hermes` is unavailable: verify the `hermes` service is healthy for the active Compose project and the Mesh container can access the mounted Docker socket.
- GitNexus is unavailable: the stack does not start GitNexus by default. Start it externally and set `MESH_STACK_GITNEXUS_URL` if repository-context inspection is required.
- Deep Agents readiness fails: provide the provider API key for the selected `MESH_DEEPAGENTS_MODEL`, or run the default native fabric.
- `mesh_eval` tokenizer probe fails: verify the Mesh image contains `/usr/local/bin/latentmas`, leave both tokenizer model env vars empty for the heuristic fallback, or provide a valid `MESH_EVAL_TOKENIZER_JSON` / `MESH_EVAL_SENTENCEPIECE_MODEL`.
- LatentMAS readiness fails: use the `latentmas` profile, provide GPU-capable Docker runtime if `MESH_LATENTMAS_DEVICE=cuda`, or keep `MESH_STACK_ENABLE_LATENTMAS=0`.

## Relationship To Other Compose Files

| File | Use |
| --- | --- |
| `docker-compose.stack.yml` | Full local stack: Mesh, sidecars, k3s, bootstrap, smoke |
| `docker-compose.yml` | Lighter developer stack for manual Mesh API/UI work |
| `docker-compose.e2e.yml` | Legacy host-driven k3d live Kubernetes overlay |
| `docker-compose.latentmas.yml` | Optional LatentMAS overlay for the lighter developer stack |
| `docker-compose.prod.yml` | Production-like container deployment without repository bind mount or Docker socket |

Do not use `docker-compose.stack.yml` as the production deployment template. It intentionally mounts the repository and Docker socket, publishes a local Kubernetes API, and runs privileged k3s for complete local validation.
