# mesh-darkharness-sdk

Standalone Perennial Darkharness SDK extracted from Orbital Mesh. Ships packet schemas, HMAC/Ed25519 signing helpers, policy evaluation, and fixtures for allowed/denied pilot actions.

## Verify

```bash
pip install -e packages/mesh-darkharness-sdk
mesh-darkharness verify-e2e
mesh-darkharness verify-packet fixtures/perennial/allowed_action.json
```

Optional Mesh control-plane live proof (requires repo checkout):

```bash
mesh-darkharness verify-e2e --with-mesh-live
```

See [HANDOVER.md](./HANDOVER.md) for integration boundaries.
