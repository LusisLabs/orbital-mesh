# mesh-hardened-arena

Offline supply-chain kit for hardened Docker images: profile registry, DHI catalog, review packet, and review-only deployment intent. No live deployment claims.

## Verify

```bash
pip install -e packages/mesh-hardened-arena
mesh-hardened-arena verify-e2e
mesh-hardened-arena verify-e2e --output-dir dist/hardened-arena/handover
```

See [HANDOVER.md](./HANDOVER.md) for integration boundaries.
