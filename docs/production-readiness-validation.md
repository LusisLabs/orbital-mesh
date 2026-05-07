# Production Readiness Validation

This is the release-facing validation record for the current end-to-end
wiring cleanup. Treat a gate as current only when the row says it was rerun in
the current audit. Older live evidence is kept separately so historical proofs
are not mistaken for current release clearance.

The deployment roadmap is tracked in
[`docs/production-deployment-roadmap.md`](./production-deployment-roadmap.md);
this file records validation evidence for those gates.

Latest imported hydrogen-mesh audit:

- Date: 2026-05-04.
- Branch: `master`.
- HEAD: `f91bac7`.

## Current Audit Matrix

| Gate | Command | Current audit status | Evidence |
| --- | --- | --- | --- |
| Python lint | `UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .` | PASS | Reran on 2026-05-04 after allowing uvx network access; output: `All checks passed!`. |
| Python tests | `PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --with-editable . --with deepagents --with pytest pytest` | PASS | Reran on 2026-05-06 with approved localhost/network permissions after fixing the Darkharness on-call fixture; `1317 passed, 1 skipped`. A sandbox-only rerun fails HTTP tests with `PermissionError` on localhost bind and is not a valid gate result. |
| Strict mypy | <code>TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools PYTHONPATH=. uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/&#124;latent-mesh/LatentMAS/&#124;services/skills/'</code> | PASS, SCOPED | Reran on 2026-05-06 with isolated cache/tool dirs; output: `Success: no issues found in 1 source file`. This is strict mypy under the current `pyproject.toml` scope, not whole-repo type proof. |
| Web lint/contracts | `npm --prefix web run lint` | PASS | Reran on 2026-05-04; contracts check and `tsc --noEmit` exited `0`. npm emitted only the existing `store-dir` config warnings. |
| Web unit tests | `npm --prefix web test` | PASS | Reran on 2026-05-04; `2` files passed, `14` tests passed. |
| Web build | `npm --prefix web run build` | PASS WITH WARNING | Reran on 2026-05-04; build exited `0`. Vite reported `dist/assets/index-DGcNkvvo.js` at `620.11 kB`, above the 500 kB warning threshold. |
| UI Labyrinth/Playwright | `npm --prefix web run test:e2e` | PASS | Reran on 2026-05-06 with approved localhost-bind permissions; `14 passed`. A sandbox-only attempt fails before browser launch with control-plane and Vite `listen EPERM`, so approved localhost bind is required in this environment. |
| Compose stack smoke | `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` | PASS | Reran on 2026-05-06; smoke container exited `0`, target probes for `rpc-gateway` and `indexer` were ready, and run `run_20260506T182325_c87c4261` completed with `decision_type=rollback_deployment`, `execution_status=succeeded`, and `feedback_outcome=successful`. |
| Production-like smoke | `./scripts/prod_smoke.sh` | PASS | Reran on 2026-05-06 against `http://127.0.0.1:8787` with approved localhost HTTP access; health returned `status=ok`, readiness returned `state_path=/app/.mesh-runtime-state`, `goose.ready=true`, and the script printed `prod smoke passed`. |
| Pilot readiness/go-no-go | `GET /api/readiness` and `GET /api/pilot/go-no-go` | BLOCKED | Reran on 2026-05-06 against the running compose stack. `/api/health` returned `status=ok` at `2026-05-06T23:06:13Z`, but readiness profile `pilot` remained `blocked` with blockers `authenticated_ingress_deployment_verified`, `policy_lifecycle_signed`, `agentic_operator_source_provenance_recorded`, `backup_restore_rehearsal_verified`, `mesh_brain_artifact_uri_prefix_configured`, `mesh_brain_serving_backend_configured`, `run_export_retention_reviewed`, and `design_partner_packet_verified`. `/api/pilot/go-no-go` generated at `2026-05-06T23:06:20.392779+00:00` remains `blocked`; missing evidence is `readiness_green`, Mesh Brain model/live/canary/rollback gates, `release_provenance_complete`, and `on_call_drill_verified`. |
| Release provenance / CI artifacts | CI run `25471541739` plus `mesh.release_provenance.v1` draft inspection | BLOCKED, EVIDENCE PRESERVED | Live CI reran on 2026-05-07 UTC at branch commit `7ac8a6e`; the GitHub Actions attestation was generated from PR merge SHA `a1fecfa056f4b203cc70d2bee813e45cf5080460`. It uploaded `ci-attestation` artifact `6845651971`, `release-assurance-artifacts` artifact `6845652269`, and `release-provenance-draft` artifact `6845652461`; local copies are under `/tmp/orbital-mesh-ci-25471541739/`. Python lint, web, simulation, and Python `3.11`/`3.12`/`3.13` test jobs passed. Docker built image digest `sha256:38d940295c891434ccb29734829e9c55c64f519977f7fc266de310ba7fd0ea56` and passed healthcheck, but failed the release-image assurance gate because the Grype artifact recorded `116` findings with `18` high/critical blockers. The SBOM is digest-matched and valid with `4799` components; the draft provenance packet remains incomplete with missing `policy_lifecycle_signed`, `migration_rehearsal`, `vulnerability_scan_path`, and `ci_attestation`. |
| Reth/Kurtosis historical smoke | archived only | REMOVED FROM RELEASE GATES | Reth/Kurtosis evidence remains historical research provenance under `docs/history/research/`; the old bootstrap script is no longer a controlled-production-pilot release gate. Current pilot readiness is carried by Docker Compose, Kubernetes bounded-action proof, authenticated ingress, persistence, audit, and go/no-go packets. |

## Historical Live Evidence

These entries are preserved as prior evidence only. They do not clear the
current audit by themselves.

| Gate | Historical result | Notes |
| --- | --- | --- |
| Compose stack smoke | PASS | Prior smoke run `run_20260427T025924_056a8fdf` reached `awaiting_operator` with decision `rollback_deployment`; this was accepted by the stack smoke gate at that time. |
| Reth/Kurtosis smoke | PASS | Prior note recorded an existing enclave `mesh-reth` and service `el-1-reth-lighthouse`. The bootstrap helper is retained for historical research loops, not as a current release gate. |
| Reth/Kurtosis full loop | PASS | Prior session `.mesh-runtime-state/reth-kurtosis-loop/session_20260427T030606Z` recorded `2` cycles, `1` restart decision, `1` successful execution, and `0` failed cycles. The artifact is not present in the current local state. |

## Reth/Kurtosis Historical Post-Action Observation

The prior full-loop run wrote post-action observations for
`run_20260427T030624_bb07b35f`:

| Field | Value |
| --- | --- |
| `rpc_reachable` | `true` |
| `peer_count` | `0` |
| `min_peer_count` | `0` |
| `block_lag` | `0` |
| `max_block_lag` | `32` |
| `syncing` | `true` |
| `new_error_signatures` | `[]` |
| `feedback_outcome` | `successful` |

The execution used `kurtosis_cli_fallback=docker_label_restart` because the
spawned local control-plane process could not reach the Kurtosis engine through
`/var/run/docker.sock`; the bounded Docker-label fallback found exactly one
service container and succeeded.

## Current Local Runtime Artifacts

- `.mesh-runtime-state/reth-kurtosis-loop/` is absent, so the current checkout
  has no inspectable local Reth/Kurtosis run artifacts.
- `.mesh-runtime-state/compose-chaos/summary-20260504T223149Z.json` reports
  `ready: false`, `status: below_threshold`, `capability_axis_pass_rate:
  0.2174`, and `5` passed axes out of `23` known axes. This is useful risk
  evidence, but it is not the compose stack smoke gate.
- `.mesh-runtime-state/release-provenance.json` is an ignored historical packet
  generated at `2026-05-06T00:32:43Z` for commit
  `0056fd18c052c07fe98ac65395a60733e698d621`. It is incomplete and has no
  SBOM, vulnerability scan, CI attestation, or migration rehearsal artifact
  path, so it does not clear the current release provenance gate.
- `.mesh-runtime-state/`, `.venv/`, `web/dist/`, and `web/test-results/` are
  ignored local artifacts and must not be treated as committed release proof.

## Source Hygiene

- `.DS_Store`, local zip bundles, `.mesh-runtime-state/`, `.hermes-local/`,
  and `kurtosis/` are ignored runtime or generated artifacts.
- Commit fixtures under `fixtures/` only when deterministic and required by
  tests or docs.
- Commit generated web contracts only when backend schema changes require
  them, and run `npm --prefix web run contracts:check` through the web lint or
  build gate before PR.

## Release Blockers To Track

- Full strict mypy remains partial until the `files` scope is expanded beyond
  `services/decision/hypothesis_engine.py`.
- Release provenance remains incomplete until the release image has zero
  blocking vulnerability findings and a real GitHub Actions attestation with
  workflow, job, run id, commit SHA, and passed `python-test`, `web`, and
  `docker-build` checks. The latest pull-test scan is still blocked by Python
  `3.13.13`, glibc `2.41-12+deb13u2`, ncurses `6.5+20250216-2`, and libcap2
  `1:2.75-10+b8` findings from the runtime base image. Direct Grype scans of
  `python:3.13-slim-bookworm`, `python:3.12-slim-bookworm`, and
  `python:3.13-slim-bullseye` reported `30`, `31`, and `56` blockers
  respectively, so a simple Debian tag swap does not close the image gate.
- Pilot readiness remains blocked until the target environment supplies
  authenticated ingress, backup/restore, signed policy, Mesh Brain, retention,
  design-partner, and related deployment-specific evidence packets.
- Compose and UI gates depend on local Docker/browser availability and must be
  recorded with exact command output before merge. Reth/Kurtosis remains
  historical research provenance, not a controlled-production-pilot release
  gate.
- Compose stack smoke now rejects container-local Kubernetes loopback endpoints
  and requires the Compose-local RPC gateway and indexer targets to answer HTTP
  probes before the run launches.
- Unfinished production adapters are classified in
  [`docs/integrations.md`](./integrations.md); release notes must not describe
  them as production-complete integrations.
