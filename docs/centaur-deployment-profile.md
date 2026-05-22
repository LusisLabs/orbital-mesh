# Centaur Deployment Profile

State slice: `mesh.centaur_deployment_profile.v1`

This profile extracts deployment patterns from Centaur without copying Centaur's Helm chart or creating a second control plane.

## Local Compose

- Default: disabled.
- Opt-in profile: `centaur-sandbox`.
- Adapter service: `mesh-centaur-adapter`, running `services.orchestrator.centaur_runtime_adapter`.
- Credential proxy proof service: `mesh-centaur-credential-proxy`, placeholder-only by environment contract.
- Required local proof: `docker compose --profile centaur-sandbox config --quiet` and `MESH_AGENT_FABRIC_MODE=centaur pnpm run test:focused`.
- Blocked: target-cluster sandbox execution unless `mesh.credential_egress_policy.v1` passes with runtime proxy/audit proof and a namespace/network policy proof is attached.

## Kubernetes

Mesh-owned profile: `config/centaur-sandbox-runtime.k8s.yaml`.

Environment overlays:

- `config/centaur-sandbox-runtime.local.k8s.yaml`: opt-in local execution after credential egress proof.
- `config/centaur-sandbox-runtime.preview.k8s.yaml`: disabled until preview namespace and proxy audit proof pass.
- `config/centaur-sandbox-runtime.prod.k8s.yaml`: disabled until production namespace, proxy audit, operator approval, and cleanup proof pass.

Required patterns before enabling a real sandbox runtime:

- Dedicated sandbox namespace.
- Service account scoped to sandbox lifecycle only.
- Default-deny network policy.
- Adapter egress policy that permits DNS and the credential proxy service only.
- Per-sandbox labels binding `run_id`, `task_id`, `attempt_id`, and `agent`.
- Optional warm pool.
- Separate credential proxy deployment and service; the adapter reaches credentials only through `MESH_CREDENTIAL_EGRESS_PROXY_URL`.
- Health endpoint for adapter readiness.
- Reachable credential proxy readiness and `/audit/events` endpoints; at least one redacted `mesh.credential_egress_policy.v1` audit event is required before the live proof can pass.

## Preview And Production

Preview and production stay blocked for real Centaur sandbox execution until all of these are true:

- Credential egress verification passes with proxy runtime and audit-event proof.
- Sandbox namespace policy render passes.
- Agent attempts prove no raw credential material in `AgentAttempt.output`.
- Mesh policy, approval, actuation, final run state, Merkle proof, and promotion remain authoritative.

## Validation

Use the root validation ladder first:

```bash
pnpm run lint:fast
pnpm run verify:contracts
pnpm run test:focused
pnpm run verify:full
git diff --check
```

Deployment-specific checks:

```bash
docker compose config --quiet
docker compose --profile centaur-sandbox config --quiet
pnpm run verify:centaur-k8s-live -- --credential-proxy-url http://<reachable-proxy>:15001
pnpm run verify:centaur-k8s-live -- --allow-blocked
```

No target-cluster live execution claim is valid until `pnpm run verify:centaur-k8s-live` returns `status=pass` against that cluster with a reachable credential proxy URL. `--allow-blocked` is for recording a structured blocked proof only.
