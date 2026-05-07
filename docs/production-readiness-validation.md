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
| Pilot readiness/go-no-go | `GET /api/readiness` and `GET /api/pilot/go-no-go` | BLOCKED, RELEASE PROVENANCE ONLY | Reran on 2026-05-07 against the running compose stack. `/api/health` returned `status=ok` at `2026-05-07T21:01:49Z` with `commit: "unknown"` and `image_digest: null`. `/api/readiness` returned `profile=pilot`, `status=ready`, `blockers=[]` at `2026-05-07T21:01:49Z`. `/api/pilot/go-no-go` generated at `2026-05-07T21:02:07.280983+00:00` remains `blocked`; the only missing evidence is `release_provenance_complete`. The mounted packet points at commit `af409496617d770d57e375fc73c7fa753e97d266` and image digest `sha256:e195d6da1f435af4f5bd7a261fe7ead956b967564f7e47d34442c54b421da0fb`, but runtime binding is missing `runtime_build_commit` and `runtime_image_digest`. |
| Release provenance / CI artifacts | CI run `25520749001` plus `mesh.release_provenance.v1` completion and runtime-binding checks | PACKET COMPLETE, DEPLOYMENT BINDING BLOCKED | Live CI passed on 2026-05-07 UTC at branch commit `e91aff66b6abbf0cfc159f629cead3df7354bd06`. Docker health smoke asserted the same commit and image digest `sha256:24ab96dd5a08d7b9b32dbdd3ed5b823b8884da6eab62cc2b4c430dcd4b30f2fc`. Downloaded artifacts are under `/tmp/orbital-mesh-ci-25520749001-e91aff6/`. Combining the CI attestation, SBOM, vulnerability scan, signed policy lifecycle, and local migration proof produced `/tmp/orbital-mesh-ci-25520749001-e91aff6/release-provenance-complete.json` with `status=complete`, `missing=[]`, and packet SHA `ff945e1405ac25246b340dcc214c83457fc5f31061e9df28e8d8b52bac9e47aa`. Runtime verification against `--health-url http://127.0.0.1:8787/api/health` failed because the running control plane reports no runtime commit or image digest. Verification against `--image-ref orbital-mesh-stack:dev` failed because the local image ID is `sha256:00c155b9d73bee677ead21086124f91826cd397c5aa060f5e385f3e22dd5f487`, not the CI packet digest. A local rebuild with the CI build args produced `orbital-mesh:ci-e91aff6` at `sha256:c4af94f0a80344426298ea52e855b905526ff37f557d839fbb70f62d0a1c8494`, so independent rebuild is not a valid activation path for the current packet. |
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
- `.mesh-runtime-state/release-provenance.json` is an ignored local packet
  still mounted by the running stack at the 2026-05-07T21:02:07Z go/no-go
  check. It was generated for commit
  `af409496617d770d57e375fc73c7fa753e97d266` and image digest
  `sha256:e195d6da1f435af4f5bd7a261fe7ead956b967564f7e47d34442c54b421da0fb`.
  The packet itself is complete with packet SHA
  `cf12b3d7fe813fe42874bb800d3f08cebc659970a47791445908cc2229c81319`,
  but it does not clear the live go/no-go gate because the running control
  plane reports no runtime commit or image digest.
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
- Release provenance packet generation is complete for CI run `25520749001`,
  but live deployment binding remains blocked. The running stack must use the
  exact release packet and report matching `MESH_BUILD_COMMIT` and
  `MESH_BUILD_IMAGE_DIGEST` from the deployed image. Independent local rebuild
  is not a valid substitute for the current packet because the rebuilt image
  did not match the CI digest. The current workflow does not publish a pullable
  release image; enabling registry publication or uploading a runnable image
  artifact would export a built private-repo image to GitHub storage and needs
  explicit operator approval before it becomes an active release path.
- Pilot readiness is currently green in the running compose stack. Pilot
  go/no-go remains blocked only by `release_provenance_complete`, caused by
  missing runtime commit and image-digest binding.
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
