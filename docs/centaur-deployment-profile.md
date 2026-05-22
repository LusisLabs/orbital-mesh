# Centaur Deployment Profile

State slice: `mesh.centaur_deployment_profile.v1`

This profile extracts deployment patterns from Centaur without copying Centaur's Helm chart or creating a second control plane.

## Local Compose

- Default: disabled.
- Allowed: fake Centaur adapter for local contract tests.
- Blocked: live sandbox execution unless `mesh.credential_egress_policy.v1` passes and a namespace/network policy proof is attached.

## Kubernetes

Mesh-owned profile: `config/centaur-sandbox-runtime.k8s.yaml`.

Required patterns before enabling a real sandbox runtime:

- Dedicated sandbox namespace.
- Service account scoped to sandbox lifecycle only.
- Default-deny network policy.
- Per-sandbox labels binding `run_id`, `task_id`, `attempt_id`, and `agent`.
- Optional warm pool.
- Credential proxy sidecar pattern, disabled with the rest of the profile until credential proof passes.
- Health endpoint for adapter readiness.

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
```

No target-cluster live execution claim is valid until Kubernetes manifests are rendered for that environment and the credential-egress proof passes there.
