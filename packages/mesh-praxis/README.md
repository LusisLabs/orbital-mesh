# mesh-praxis

Praxis pipeline: source ingest → MCP contract → Akto advisory evidence → Mesh certification → bounded dry-run runtime with revocation.

## Verify

```bash
pip install -e packages/mesh-praxis
mesh-praxis verify-e2e
mesh-praxis build-proof-packet
```

See [HANDOVER.md](./HANDOVER.md) for authority boundaries.
