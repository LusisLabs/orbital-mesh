# Mesh CTO Handover Packages

Four standalone packages extracted from Orbital Mesh for CTO handoff and integration. Each package is pip-installable, ships its own schemas/config/fixtures, and exposes a single end-to-end verifier.

| Package | Purpose | Verify |
| --- | --- | --- |
| [mesh-darkharness-sdk](./mesh-darkharness-sdk/) | Perennial Darkharness packet schemas, signing, policy | `mesh-darkharness verify-e2e` |
| [mesh-hardened-arena](./mesh-hardened-arena/) | Hardened-image profile → packet → review-only intent | `mesh-hardened-arena verify-e2e` |
| [mesh-praxis](./mesh-praxis/) | Source → MCP contract → Akto evidence → certification → bounded dry-run runtime | `mesh-praxis verify-e2e` |
| [mesh-centaur-sandbox](./mesh-centaur-sandbox/) | Centaur-style sandbox K8s manifests + credential egress live proof | `mesh-centaur-sandbox verify-e2e` |

## Verify all packages

From repo root:

```bash
python3 scripts/bootstrap_handover_packages.py
python3 scripts/verify_handover_packages.py
```

Optional Mesh control-plane live proof for Darkharness:

```bash
python3 scripts/verify_handover_packages.py --with-darkharness-mesh-live
```

## Integration with Orbital Mesh

These packages are **slices** of `shared/mesh_runtime/` and related config. Re-sync after upstream changes:

```bash
python3 scripts/bootstrap_handover_packages.py
```

Mesh integration anchors:

- Darkharness HTTP export: `GET /api/runs/{id}/darkharness-packet`, `GET /api/darkharness/pilot-packet`
- Hardened Arena: offline supply-chain kit; not yet wired to control-plane HTTP
- Praxis: `shared/mesh_runtime/praxis.py` authority boundary; Mesh certifies, Akto/ACP never promote alone
- Centaur: `MESH_AGENT_FABRIC_MODE=centaur`, compose profile `centaur-sandbox`, `pnpm run verify:centaur-k8s-live`

## Handover checklist

1. Run `python3 scripts/verify_handover_packages.py` — all four must pass.
2. Copy the target `packages/<name>/` directory to the destination repo or artifact store.
3. Read the package `HANDOVER.md` for integration boundaries and env requirements.
4. For Darkharness production export, deploy Mesh control plane and run `scripts/verify_darkharness_live_packet.py`.
