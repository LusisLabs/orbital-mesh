# All-In-One Docker Compose Stack

`docker-compose.stack.yml` is the canonical local environment for launching Mesh, its local sidecars, an embedded Kubernetes control plane, and an automated live-remediation smoke run with one Compose command.

Use this stack when you need to validate the whole system contract at once:

- Mesh HTTP API and browser control plane.
- Promptfoo, Goose, and Hermes readiness.
- Dedicated Hermes sidecar.
- Dedicated GitNexus sidecar.
- Embedded k3s cluster with a seeded `semantic-search` Deployment.
- Live Kubernetes execution through the same Mesh rollout path used by production-like runs.
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

The browser control plane is published at:

```text
http://127.0.0.1:8787
```

The default stack keeps `MESH_STACK_AGENT_FABRIC_MODE=native`. That is deliberate: the smoke run should validate Mesh and Kubernetes deterministically without requiring model credentials.

## Optional Lanes

Enable the LatentMAS GPU worker sidecar:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 docker compose -f docker-compose.stack.yml up --build
```

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
| `mesh-kube-bootstrap` | One-shot kubeconfig rewrite, namespace creation, and baseline Deployment seed | none | `mesh_kubeconfig` |
| `mesh` | Mesh API, UI, readiness, run execution, vault, Merkle, and Kubernetes actuation | `${MESH_PUBLISH_PORT:-8787}` | `mesh_runtime_state`, `goose_config`, `mesh_kubeconfig` |
| `hermes` | Dedicated Hermes runtime sidecar reached by `MESH_HERMES_COMMAND` through `docker exec` | none | `hermes_home` |
| `gitnexus` | Local GitNexus HTTP sidecar | `${MESH_GITNEXUS_PUBLISH_PORT:-4747}` | container filesystem |
| `mesh-smoke` | One-shot readiness and live-remediation verifier | none | `mesh_kubeconfig` |
| `latentmas` | Optional GPU inference sidecar | `${MESH_LATENTMAS_PUBLISH_PORT:-8791}` | `latentmas_hf_cache` |

## Boot Sequence

1. Compose builds `mesh-intelligence-stack`, `mesh-intelligence-hermes`, and `mesh-intelligence-gitnexus`.
2. `k3s` starts a single-node Kubernetes API and writes kubeconfig to the shared `mesh_kubeconfig` volume.
3. `mesh-kube-bootstrap` waits for k3s health, rewrites the kubeconfig API endpoint to `https://k3s:6443`, creates context `mesh-compose`, creates namespace `search`, and applies a healthy `semantic-search` Deployment.
4. `gitnexus` and `hermes` must report healthy before `mesh` starts.
5. `mesh` starts with live Kubernetes execution enabled, `KUBECONFIG=/mesh-kubeconfig/kubeconfig`, allowed context `mesh-compose`, and allowed namespace `search`.
6. `mesh-smoke` waits for Mesh health, verifies required readiness entries, seeds a CrashLoop failure, launches a live Mesh run, and exits non-zero on failure.

## Smoke Contract

`mesh-smoke` validates the minimum whole-system contract:

- `/api/health` returns HTTP 200.
- `/api/readiness` reports Promptfoo and Hermes ready.
- Deep Agents is required only when `MESH_STACK_AGENT_FABRIC_MODE=deepagents`.
- LatentMAS is required only when `MESH_STACK_ENABLE_LATENTMAS=1`.
- Kubernetes context `mesh-compose` is usable inside the container.
- `scripts/e2e_seed_failure.sh crashloop` can mutate the local `semantic-search` Deployment.
- `scripts/e2e_run_mesh.sh` can launch a live Mesh run and receive a completed bounded recovery.

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
| Kube context | `mesh-compose` |
| Namespace | `search` |
| Deployment | `semantic-search` |
| API endpoint inside Compose | `https://k3s:6443` |
| Published host API port | `6443` |
| Mesh kubeconfig path | `/mesh-kubeconfig/kubeconfig` |

The bootstrap job rewrites the kubeconfig because a server URL like `https://127.0.0.1:6443` would point at the calling container, not the k3s container. Production deployments must use a routable Kubernetes API endpoint or in-cluster service DNS instead.

Live actions are still bounded by:

```text
MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1
MESH_KUBERNETES_ALLOWED_CONTEXTS=mesh-compose
MESH_KUBERNETES_ALLOWED_NAMESPACES=search
```

`rollback_deployment` maps to `kubectl rollout undo deployment/<name> -n <namespace>`. `restart_deployment` maps to `kubectl rollout restart deployment/<name> -n <namespace>`.

## Configuration Matrix

| Variable | Default | Purpose |
| --- | --- | --- |
| `MESH_PUBLISH_PORT` | `8787` | Host port for Mesh HTTP/UI |
| `MESH_K3S_API_PUBLISH_PORT` | `6443` | Host port for the local k3s API |
| `MESH_GITNEXUS_PUBLISH_PORT` | `4747` | Host port for GitNexus |
| `MESH_LATENTMAS_PUBLISH_PORT` | `8791` | Host port for optional LatentMAS |
| `MESH_STACK_KUBE_CONTEXT` | `mesh-compose` | Normalized kube context in the shared kubeconfig |
| `MESH_STACK_NAMESPACE` | `search` | Seeded namespace and Mesh allowlist |
| `MESH_STACK_DEPLOYMENT` | `semantic-search` | Seeded Deployment and smoke target |
| `MESH_STACK_ALLOWED_CONTEXTS` | `mesh-compose` | Runtime context allowlist |
| `MESH_STACK_ALLOWED_NAMESPACES` | `search` | Runtime namespace allowlist |
| `MESH_STACK_AGENT_FABRIC_MODE` | `native` | `native` or `deepagents` proposal fabric |
| `MESH_STACK_ENABLE_LATENTMAS` | `0` | Enables Mesh readiness expectation for LatentMAS |
| `MESH_STACK_LATENTMAS_URL` | `http://latentmas:8791` | Mesh-to-sidecar LatentMAS URL |
| `MESH_STACK_HERMES_COMMAND` | `docker exec ... mesh-intelligence-hermes-stack /opt/venv/bin/hermes` | Mesh-to-sidecar Hermes command |
| `MESH_STACK_SMOKE_EVALUATION_MODE` | `native` | Smoke run evaluation mode |
| `MESH_STACK_SMOKE_ORCHESTRATION_MODE` | `native` | Smoke run orchestration mode |
| `MESH_STACK_SMOKE_STEERING_MODE` | `interruptible_auto` | Smoke run steering mode |
| `MESH_DOCKER_SOCKET_HOST_PATH` | `/var/run/docker.sock` | Docker socket mount used for Hermes sidecar invocation |
| `HERMES_AGENT_REF` | `1525624904159e7c2d6ac3feef951e27ad0d23bb` | Pinned Hermes Agent git ref used by mesh and Hermes images |
| `UV_VERSION` | `0.11.6` | Pinned uv installer version used by mesh and Hermes images |
| `GOOSE_VERSION` | `v1.30.0` | Pinned Goose release used by the mesh image |
| `GITNEXUS_VERSION` | `1.6.1` | Pinned GitNexus npm version used by the sidecar image |

Provider variables such as `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MESH_COMPOSE_GOOSE_PROVIDER`, `MESH_COMPOSE_GOOSE_MODEL`, `MESH_COMPOSE_HERMES_INFERENCE_PROVIDER`, and `MESH_COMPOSE_HERMES_MODEL` are passed through to the relevant containers. The default smoke path does not require model credentials because it runs native evaluation and native orchestration.

## Volumes

| Volume | Contents |
| --- | --- |
| `mesh_runtime_state` | Runs, goals, vault, Merkle proofs, readiness snapshots, research sessions, Deep Agents sandboxes |
| `mesh_kubeconfig` | k3s-generated kubeconfig rewritten for the Compose network |
| `k3s_server_data` | k3s server state |
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
- `hermes` is unavailable: verify `mesh-intelligence-hermes-stack` is healthy and the Mesh container can access the mounted Docker socket.
- `gitnexus` is unavailable: verify port `4747` is free or override `MESH_GITNEXUS_PUBLISH_PORT`.
- Deep Agents readiness fails: provide the provider API key for the selected `MESH_DEEPAGENTS_MODEL`, or run the default native fabric.
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
