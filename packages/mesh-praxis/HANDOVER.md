# Praxis handover

## Scope

- P1 contract fixtures under `fixtures/praxis/p1_contracts.json`
- P8 e2e proof packet fixture
- Source bundle ingest with secret scanning
- Managed dry-run runtime chain through connector revocation

## Authority boundaries

- Mesh owns certification and revocation; Akto/ACP are advisory only.
- Mutating tools default to denied until Mesh certifies.
- Managed runtime is dry-run only; no production deployment claims.

## Re-sync

```bash
python3 scripts/bootstrap_handover_packages.py
```
