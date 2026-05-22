# mesh-centaur-sandbox

**Centaur Sandbox** is a proposal-only agent sandbox integration kit extracted from Orbital Mesh. It ships Mesh-owned Kubernetes manifests, credential egress verification helpers, and reference adapter code — without vendoring Centaur wholesale or creating a second control plane.

## What problem this solves

Agent investigation lanes must run untrusted work in isolation while keeping Mesh authoritative for policy, approval, actuation, Merkle proof, and promotion. This kit provides:

- Default-deny Kubernetes sandbox profiles (disabled by default)
- Separate credential egress proxy deployment pattern
- Static manifest verification
- Local fake-cluster live proof for CI
- Real-cluster live proof command for target environments

## Quick start

```bash
git clone https://github.com/LusisLabs/mesh-centaur-sandbox.git
cd mesh-centaur-sandbox
python3 -m pip install -e .
mesh-centaur-sandbox verify-e2e
```

```bash
make verify
make profile
make live
```

## Architecture

```text
┌─────────────────────┐     egress only      ┌──────────────────────────┐
│ sandbox adapter     │ ───────────────────► │ credential egress proxy  │
│ (proposal-only)     │                      │ (placeholder credentials)│
└─────────────────────┘                      └──────────────────────────┘
         │                                                │
         └────────────── AgentAttempt proposals ─────────┘
                    Mesh remains authority
```

Required patterns before enabling real execution:

- Dedicated sandbox namespace
- Default-deny NetworkPolicy
- Adapter egress limited to credential proxy (+ DNS)
- Per-sandbox labels binding run/task/attempt
- No raw credentials in adapter env, logs, or outputs

## CLI reference

| Command | Purpose |
| --- | --- |
| `list-manifests` | List bundled K8s manifest overlays |
| `verify-profile [--manifest PATH]` | Static manifest profile checks |
| `verify-live [--credential-proxy-url URL]` | Live cluster proof |
| `verify-live --fake-cluster` | Local fake kubectl + proxy proof |
| `verify-e2e` | Static profile + local fake-cluster live proof |

All commands accept `--json`. Use `--allow-blocked` with `verify-live` to record structured blocked proofs without failing CI.

### Examples

```bash
mesh-centaur-sandbox list-manifests --json
mesh-centaur-sandbox verify-profile --json
mesh-centaur-sandbox verify-live --fake-cluster --json
mesh-centaur-sandbox verify-e2e --json
```

Target cluster proof:

```bash
mesh-centaur-sandbox verify-live \
  --credential-proxy-url http://mesh-centaur-credential-egress-proxy.mesh-centaur-sandboxes:15001 \
  --json
```

## Repository layout

```text
manifests/
  centaur-sandbox-runtime.k8s.yaml          Base profile (disabled by default)
  centaur-sandbox-runtime.local.k8s.yaml    Local overlay
  centaur-sandbox-runtime.preview.k8s.yaml  Preview overlay (gated)
  centaur-sandbox-runtime.prod.k8s.yaml     Production overlay (gated)
  centaur-credential-egress.local.json      Local egress policy example
src/mesh_centaur_sandbox/
  centaur_deployment.py                     Static + live proof verifiers
  credential_egress.py                      Egress policy helpers
  adapter/                                  Reference runtime adapter + proxy
```

## Verification gates

| Gate | Command |
| --- | --- |
| Package E2E (local) | `mesh-centaur-sandbox verify-e2e` |
| Static profile | `mesh-centaur-sandbox verify-profile` |
| Fake-cluster live | `mesh-centaur-sandbox verify-live --fake-cluster` |
| Real cluster | `mesh-centaur-sandbox verify-live --credential-proxy-url URL` |

## Explicit non-claims

- Preview/prod real sandbox execution blocked until egress + audit proofs pass
- Not a second control plane
- Adapter output is `AgentAttempt` proposals only

## Orbital Mesh integration

In Orbital Mesh:

- `MESH_AGENT_FABRIC_MODE=centaur`
- Compose profile `centaur-sandbox`
- `pnpm run verify:centaur-k8s-live` against target cluster

See [HANDOVER.md](./HANDOVER.md).
