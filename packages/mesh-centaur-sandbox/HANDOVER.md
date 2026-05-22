# Centaur sandbox handover

## Scope

- Kubernetes manifests under `manifests/centaur-sandbox-runtime*.k8s.yaml`
- Static profile verification (disabled-by-default deployments, network policy, proxy separation)
- Live proof with credential egress proxy health and redacted audit events

## Boundaries

- Deployments default to `replicas: 0`; preview/prod overlays remain gated until credential egress proof.
- Credential proxy is a separate deployment, not a sidecar.
- Adapter egress is proxy-only; raw secret material must not appear in audit events.

## Re-sync

```bash
python3 scripts/bootstrap_handover_packages.py
```

## Mesh integration

- `MESH_AGENT_FABRIC_MODE=centaur`
- Compose profile `centaur-sandbox`
- `pnpm run verify:centaur-k8s-live`
