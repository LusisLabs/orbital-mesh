# Production-Like Live Runbook

This runbook describes the reproducible live Kubernetes path for Mesh Intelligence.

It is safe for local production-like validation. Do not expose the control plane directly to the public Internet. The server has no built-in authentication; put it behind TLS and an authenticated reverse proxy before external access.

## 1. Preconditions

- Docker Desktop or Docker Engine with Compose v2.
- `k3d` for the local Kubernetes cluster.
- `kubectl` on the host.
- Node 20 or newer for the Vite build.
- Python 3.11 or newer for the backend target runtime.

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
- `web/dist/index.html` points at the newly built asset names.

## 3. Start Docker-Native E2E

```bash
./scripts/e2e_up.sh
```

This does the following:

- Creates or reuses a `k3d` cluster named `mesh-e2e`.
- Creates the `search` namespace.
- Deploys `semantic-search` as a healthy baseline Deployment.
- Writes `.mesh-runtime-state/e2e/kubeconfig`.
- Rewrites the kubeconfig server endpoint for container access.
- Points `MESH_RESEARCH_DIRECTORY` at the host workspace research corpus through `/workspace/mesh-intelligence/.mesh-runtime-state/research`.
- Starts Mesh with:
  - `docker-compose.yml`
  - `docker-compose.e2e.yml`
  - live Kubernetes execution enabled
  - context allowlist `k3d-mesh-e2e`
  - namespace allowlist `search`

Control plane:

```text
http://127.0.0.1:8787
```

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
5. Use kube context `k3d-mesh-e2e`.
6. Use `native` evaluation and `native` orchestration.
7. Use `interruptible_auto` only in this bounded local e2e environment.

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
- Persist `.mesh-runtime-state` on encrypted storage or a protected Docker volume.
- Back up `.mesh-runtime-state` if audit records must survive host replacement.

## 9. Teardown

```bash
./scripts/e2e_down.sh
```

This stops the Compose stack and deletes the `k3d` cluster.
