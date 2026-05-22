# mesh-hardened-arena

**Hardened Arena** is an offline supply-chain review kit for selecting Docker Hardened Images posture, generating proof packets, and emitting human-reviewable deployment *intent* artifacts. It does not deploy infrastructure or claim target validation.

## What problem this solves

Teams adopting hardened base images need a structured, fail-closed way to:

1. Declare intended deployment posture (`solo`, `startup staging`, `enterprise rehearsal`)
2. Reference a catalog of hardened image/chart candidates
3. Generate a review packet with proof gates, probe plans, and blockers
4. Emit review-only K8s/Compose intent bundles with **no live deploy commands** and **no secret values**

## Quick start

```bash
git clone https://github.com/LusisLabs/mesh-hardened-arena.git
cd mesh-hardened-arena
python3 -m pip install -e .
mesh-hardened-arena verify-e2e
```

```bash
make verify
mesh-hardened-arena list-profiles
```

## Pipeline

```text
profiles.json  →  catalog.json  →  review packet  →  intent bundle
     │                 │                 │                  │
 verify-profiles   verify-catalog   verify-packet    verify-intent
```

Bundled profiles (all `recipe` posture, no production claims):

| Profile ID | Intended use |
| --- | --- |
| `solo_project_default` | One-person lab / compact production-like arena |
| `startup_saas_staging` | Startup SaaS staging rehearsal |
| `enterprise_onprem_rehearsal` | Enterprise on-prem rehearsal |

## CLI reference

| Command | Purpose |
| --- | --- |
| `list-profiles` | List bundled profile ids |
| `show-profile PROFILE` | Print one profile registry entry |
| `verify-profiles [--profiles PATH]` | Verify profile registry |
| `verify-catalog [--catalog PATH]` | Verify DHI catalog snapshot |
| `generate-packet PROFILE --output PATH` | Generate review packet JSON |
| `verify-packet PATH` | Verify generated packet |
| `generate-intent PROFILE --output-dir DIR` | Generate review-only intent bundle |
| `verify-intent PATH` | Verify intent bundle directory |
| `verify-e2e [--output-dir DIR]` | Run full pipeline |

All commands accept `--json`.

### Examples

```bash
mesh-hardened-arena verify-profiles --json
mesh-hardened-arena generate-packet solo_project_default --output dist/packet.json
mesh-hardened-arena verify-packet dist/packet.json
mesh-hardened-arena generate-intent solo_project_default --output-dir dist/intent
mesh-hardened-arena verify-intent dist/intent
```

Generated intent bundles set:

- `review_only: true`
- `live_deployment_allowed: false`
- `secret_values_present: false`

## Repository layout

```text
config/
  hardened-arena.profiles.json
  hardened-arena.catalog.json
src/mesh_hardened_arena/
  schemas/                   JSON Schema contracts
  hardened_arena*.py         Profile, catalog, packet, intent, proof
```

## Verification gates

| Gate | Command |
| --- | --- |
| Full pipeline | `mesh-hardened-arena verify-e2e` |
| Profiles only | `mesh-hardened-arena verify-profiles` |
| Catalog only | `mesh-hardened-arena verify-catalog` |

## Explicit non-claims

- `production_readiness_claim: false` on all seed profiles
- `target_validated` remains false until separate target smoke proof
- DHI catalog is `catalog_data_only`, not whole-system compliance
- Intent artifacts require human review before any cluster apply

## Orbital Mesh integration

Not yet exposed on Mesh HTTP APIs. Use this repo as the handoff surface until `/api/hardened-arena/*` endpoints land in Orbital Mesh.

See [HANDOVER.md](./HANDOVER.md).
