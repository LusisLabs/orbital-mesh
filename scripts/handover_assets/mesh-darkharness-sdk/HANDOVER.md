# Darkharness SDK handover

## Scope

- Perennial schemas under `src/mesh_darkharness/schemas/perennial/`
- Signing (`hmac-sha256`, optional `ed25519` via `cryptography`)
- Policy evaluation for pilot-scope boundaries
- Fixtures under `fixtures/perennial/`

## Boundaries

- **In package:** schema validation, signing proofs, offline policy checks, fixture packets.
- **Requires Mesh repo:** `--with-mesh-live` runs `scripts/verify_darkharness_live_packet.py` against a local control plane.
- **Production export:** `GET /api/runs/{id}/darkharness-packet`, `GET /api/darkharness/pilot-packet` on deployed Mesh.

## Re-sync

After upstream Mesh changes:

```bash
python3 scripts/bootstrap_handover_packages.py
```
