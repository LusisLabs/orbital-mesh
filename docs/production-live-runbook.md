# Production-Like Live Runbook

This runbook describes the reproducible live Kubernetes path for Mesh Intelligence.

It is safe for local production-like validation. Do not expose the control plane directly to the public Internet. The server has no built-in authentication; put it behind TLS and an authenticated reverse proxy before external access.

Use [`docs/production-deployment-roadmap.md`](./production-deployment-roadmap.md) as the release decision record that connects this runbook to private staging, controlled production pilots, required features, and non-negotiable launch rules.

## 1. Preconditions

- Docker Desktop or Docker Engine with Compose v2.
- Host access to the Docker socket path mounted into `mesh` for the all-in-one Hermes sidecar path (`/var/run/docker.sock` by default).
- Node 22 for CI and Docker web builds.
- Python 3.12 for CI and the backend runtime image.

## 2. Verify Source

```bash
python3 -m unittest discover -s tests
cd web
npm run lint
npm test
npm run build
cd ..
```

Expected result:

- Python unit suite passes.
- TypeScript lint/typecheck passes.
- Vitest suite passes.
- `meshapp/frontend/out/index.html` points at the newly built asset names.

## 3. Start Docker-Native E2E

```bash
docker compose -f docker-compose.stack.yml up --build
```

This is the all-in-one local stack. The full topology, variables, volumes, optional LatentMAS/Deep Agents lanes, teardown, and troubleshooting are documented in [`docs/all-in-one-compose-stack.md`](./all-in-one-compose-stack.md).

This does the following:

- Starts a K3s API inside Compose.
- Writes kubeconfig into a shared Docker volume and rewrites it to the compose-reachable endpoint `https://k3s:6443`.
- Creates the `search` namespace.
- Deploys `semantic-search` as a healthy baseline Deployment.
- Starts Mesh with live Kubernetes execution enabled, allowlist context `mesh-compose`, and allowlist namespace `search`.
- Runs `mesh-smoke`, which checks readiness, seeds a CrashLoop deployment failure, launches a live run, and exits non-zero if recovery fails.

Control plane:

```text
http://127.0.0.1:8787
```

The previous host-driven `./scripts/e2e_up.sh` path remains available when you want manual `k3d` control or a host kubeconfig artifact.

## 4. Seed A Live Failure

Image pull failure:

```bash
./scripts/e2e_seed_failure.sh imagepull
```

CrashLoop failure:

```bash
./scripts/e2e_seed_failure.sh crashloop
```

Return to healthy baseline:

```bash
./scripts/e2e_seed_failure.sh healthy
```

The all-in-one stack already seeds a CrashLoop and launches a live run through `mesh-smoke`. Use the commands below when you want to rerun or change the scenario manually.

## 5. Launch Mesh Against The Live Cluster

CLI path:

```bash
./scripts/e2e_run_mesh.sh
```

Browser path:

1. Open `http://127.0.0.1:8787`.
2. In the launch panel, select `Signal: Live Kubernetes Deployment`.
3. Use deployment `semantic-search`.
4. Use namespace `search`.
5. Use kube context `mesh-compose`.
6. Use `native` evaluation and `native` orchestration.
7. Keep `MESH_AGENT_FABRIC_MODE=native` for live Kubernetes validation unless you are explicitly testing proposal lanes only.
8. Use `interruptible_auto` only in this bounded local e2e environment.

Expected terminal summary:

```json
{
  "scenario_key": "live_kubernetes:search/semantic-search",
  "stage": "completed",
  "status": "completed",
  "decision_type": "rollback_deployment",
  "execution_status": "succeeded",
  "feedback_outcome": "successful"
}
```

## 6. Inspect Evidence

Health:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

Readiness:

```bash
curl -sS http://127.0.0.1:8787/api/readiness
```

When `MESH_AGENT_FABRIC_MODE=deepagents`, the readiness payload also includes `deepagents.ready`, `deepagents.detail`, and any provider-key warnings under `deepagents.warnings`.

Research corpus:

```bash
curl -sS http://127.0.0.1:8787/api/research-corpus
```

Recent runs:

```bash
curl -sS http://127.0.0.1:8787/api/runs
```

Container logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml logs --tail=200 mesh
docker compose -f docker-compose.stack.yml logs --tail=200 mesh
```

## 7. Rollback Scope

`rollback_deployment` maps to:

```bash
kubectl rollout undo deployment/<name> -n <namespace>
```

It rolls the Kubernetes Deployment back to a previous ReplicaSet revision. It does not restore arbitrary application state, database state, queue contents, or external side effects.

`restart_deployment` maps to:

```bash
kubectl rollout restart deployment/<name> -n <namespace>
```

Both live actions are blocked unless:

- `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=1`
- active or requested context is allowed by `MESH_KUBERNETES_ALLOWED_CONTEXTS`
- namespace is allowed by `MESH_KUBERNETES_ALLOWED_NAMESPACES`

## 8. Public Production Gate

Before exposing beyond localhost or a private network:

- Set `MESH_SERVER_HOST=127.0.0.1` and front it with a reverse proxy on the same host, or bind to a private interface only.
- Enforce authentication and authorization at the proxy.
- Terminate TLS at the proxy.
- Keep `MESH_KUBERNETES_ALLOWED_CONTEXTS` and `MESH_KUBERNETES_ALLOWED_NAMESPACES` narrow.
- Keep `approval_gate` as the default steering mode unless the target environment is explicitly approved for interruptible auto mode.
- Keep `MESH_AGENT_FABRIC_MODE=native` as the default production posture unless Deep Agents proposal lanes are explicitly required and reviewed.
- Persist `.mesh-runtime-state` on encrypted storage or a protected Docker volume.
- Back up `.mesh-runtime-state` if audit records must survive host replacement.

## 9. First Deploy

Single VM with Compose:

```bash
export MESH_BUILD_VERSION="$(git describe --tags --always --dirty)"
export MESH_BUILD_COMMIT="$(git rev-parse HEAD)"
export MESH_KUBECONFIG_HOST_PATH=/etc/mesh/kubeconfig
export MESH_KUBERNETES_ALLOWED_CONTEXTS=prod-us-east-1
export MESH_KUBERNETES_ALLOWED_NAMESPACES=mesh-targets
export OPENAI_API_KEY=<from secret store>
docker compose -f docker-compose.prod.yml up --build -d
MESH_SMOKE_BASE_URL=http://127.0.0.1:8787 ./scripts/prod_smoke.sh
```

The smoke script defaults to `MESH_SMOKE_HTTP_TIMEOUT_SECONDS=30`. Keep that default for cold readiness probes; set a larger value on slow hosts rather than treating a readiness timeout as a successful deploy.

Terminate TLS and enforce authentication in Caddy, nginx, a cloud load balancer, or an internal private network. The app does not implement authn/authz.

Choose one deployment target and translate the same contract:

- Single VM + Compose: use `docker-compose.prod.yml`, a protected Docker volume for `mesh_runtime_state`, read-only kubeconfig mount, reverse proxy TLS/auth, and system-level backups.
- AWS ECS/Fargate: use the Docker image, task secrets for LLM keys, an EFS or equivalent persistent volume for `/app/.mesh-runtime-state`, and a read-only kubeconfig secret if acting on an external cluster.
- Kubernetes: run the image as a Deployment, mount state through a PVC, mount kubeconfig as a Secret or use in-cluster RBAC if targeting the same cluster, expose through an authenticated ingress.

Optional Deep Agents proposal lanes:

```bash
export MESH_AGENT_FABRIC_MODE=deepagents
export MESH_DEEPAGENTS_MODEL=openai:MiniMax-M2.7
export MESH_DEEPAGENTS_TIMEOUT_SECONDS=120
export MESH_DEEPAGENTS_WORKSPACE_ROOT=/app/.mesh-runtime-state/deepagents
export MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS=20000
```

This changes proposal generation only. It does not replace Mesh evaluation, approval, Kubernetes actuation, audit, or vault persistence.

## 10. Secrets And Rotation

Inject these through the platform secret store, not git:

- `OPENAI_API_KEY` for the default MiniMax OpenAI-compatible Goose route and the default Deep Agents model `openai:MiniMax-M2.7`.
- `ANTHROPIC_API_KEY` only for Anthropic-compatible MiniMax or if you explicitly choose an Anthropic Deep Agents model.
- `GOOGLE_API_KEY` and `OPENROUTER_API_KEY` only for explicitly selected providers.
- kubeconfig content referenced by `MESH_KUBECONFIG_HOST_PATH`.

Rotate by updating the platform secret, restarting the mesh container, and running `./scripts/prod_smoke.sh`. Revoke old LLM keys after the replacement container reports healthy.

## 11. Backup And Restore

Back up the Docker volume or mounted directory behind `MESH_STATE_DIRECTORY`; it contains run history, vault artifacts, Merkle proofs, integrations config, research sessions, and any Deep Agents proposal workspaces under `MESH_DEEPAGENTS_WORKSPACE_ROOT`. Restore by stopping mesh, restoring the directory or volume contents to `/app/.mesh-runtime-state`, starting mesh, and checking `/api/runs`, `/api/vault/tree`, and `/api/readiness`.

## 12. Live Kubernetes

Live Kubernetes execution requires both layers:

- Runtime identity: kubeconfig/context must exist inside the container and `MESH_KUBERNETES_ALLOWED_CONTEXTS` / `MESH_KUBERNETES_ALLOWED_NAMESPACES` must include the target.
- Network reachability: the kubeconfig server endpoint must be reachable from inside the mesh container. `https://127.0.0.1:...` usually points at the container itself, not the host or cluster API.

For the one-command local stack, use `docker-compose.stack.yml`; it rewrites kubeconfig to the compose-reachable endpoint automatically. For the legacy host-driven path, `./scripts/e2e_up.sh` still rewrites the kubeconfig endpoint for container access. For production, use a real routable API endpoint or in-cluster service DNS when running mesh inside Kubernetes.

## 13. Hermes And Goose Break Glass

Goose is bundled in the mesh image. If `/api/readiness` reports Goose unavailable, verify provider env, key presence, `OPENAI_BASE_URL`, and `MESH_GOOSE_RUN_TIMEOUT_SECONDS`.

If `/api/readiness` reports Deep Agents warnings, verify `MESH_AGENT_FABRIC_MODE`, the selected `MESH_DEEPAGENTS_MODEL`, the provider API key for that model family, and that `/app/.mesh-runtime-state/deepagents` is writable by the container user.

Hermes runs as a dedicated sidecar in the all-in-one stack and is reached through `MESH_HERMES_COMMAND=${MESH_STACK_HERMES_EXEC_COMMAND:-/usr/local/bin/compose_hermes_exec.sh}`. If readiness still reports Hermes unavailable, verify the Docker socket mount, the Hermes service health for the active Compose project, and the configured stack-scoped Hermes command.

Deep Agents is still proposal-only in this topology. Do not widen it into direct Kubernetes access, direct repo writes, or Mesh actuation.

## 14. Teardown

```bash
docker compose -f docker-compose.stack.yml down -v
```

This stops the all-in-one Compose stack and removes its named volumes. Use `./scripts/e2e_down.sh` only for the legacy host-driven `k3d` path.

## 15. HelixDB Memory Projection Troubleshooting

When `MESH_MEMORY_GRAPH_BACKEND=helix` is enabled, the runtime projects memory records to a HelixDB backend. The projection uses an outbox pattern to ensure atomic writes.

Outbox location:

- File backend: `<state_directory>/helix_memory_projection_outbox.json`
- Postgres backend: table `helix_memory_projection_outbox`

Diagnosing failed outbox events:

```bash
# Check file-based outbox
cat <state_directory>/helix_memory_projection_outbox.json | jq '.[] | select(.status == "failed")'

# Check Postgres outbox (requires database access)
psql -d mesh -c "SELECT event_id, operation, status, attempts, last_error FROM helix_memory_projection_outbox WHERE status = 'failed';"
```

Replaying failed events:

```bash
python3 scripts/verify_helix_memory_projection.py --json --replay-pending
```

The `--replay-pending` flag replays any events with `status = 'failed'` before running the verification probe. This is useful after fixing network connectivity to HelixDB or after schema migrations.
