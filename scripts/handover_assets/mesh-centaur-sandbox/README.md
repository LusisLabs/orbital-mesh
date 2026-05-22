# mesh-centaur-sandbox

Centaur-style sandbox Kubernetes manifests with separate credential egress proxy deployment, default-deny network policy, and live proof helpers.

## Verify

```bash
pip install -e packages/mesh-centaur-sandbox
mesh-centaur-sandbox verify-e2e
```

See [HANDOVER.md](./HANDOVER.md) for deployment gating.
