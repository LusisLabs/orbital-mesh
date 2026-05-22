# Hardened Arena handover

## Scope

- Profile registry: `config/hardened-arena.profiles.json`
- DHI catalog snapshot: `config/hardened-arena.catalog.json`
- Packet and intent generators with schema validation
- Review-only outputs; no kubeconfig or secret material

## Boundaries

- **In package:** offline profile/catalog verification, packet generation, intent bundle generation.
- **Not wired:** control-plane HTTP export (supply-chain kit only).
- **No deployment claims:** packets block `target_validated` and `production_ready` overclaims.

## Re-sync

```bash
python3 scripts/bootstrap_handover_packages.py
```
