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
| Focused Python tests | `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_hypothesis_engine_reth.py tests/test_kurtosis_reth_actuation.py tests/test_monitoring_corpus.py tests/test_incident_corpus.py` | BLOCKED | The documented command is stale: `tests/test_kurtosis_reth_actuation.py` is absent in the current checkout. A direct local attempt collected no tests for that command and exited with code `4`. No current pass is recorded. |
| Strict mypy | <code>TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/&#124;latent-mesh/LatentMAS/&#124;services/skills/'</code> | NOT REVALIDATED | `pyproject.toml` still scopes mypy to `services/decision/hypothesis_engine.py`, so the gate is not whole-repo proof. The current uvx revalidation did not produce a usable final result: the first attempt hit a shared-cache build error and the isolated-cache retry did not return output before it was stopped. |
| Web lint/contracts | `npm --prefix web run lint` | PASS | Reran on 2026-05-04; contracts check and `tsc --noEmit` exited `0`. npm emitted only the existing `store-dir` config warnings. |
| Web unit tests | `npm --prefix web test` | PASS | Reran on 2026-05-04; `2` files passed, `14` tests passed. |
| Web build | `npm --prefix web run build` | PASS WITH WARNING | Reran on 2026-05-04; build exited `0`. Vite reported `dist/assets/index-DGcNkvvo.js` at `620.11 kB`, above the 500 kB warning threshold. |
| UI Labyrinth/Playwright | `npm --prefix web run test:e2e` | FAIL | Reran on 2026-05-04. The seed step failed before browser launch because the default fixture `.mesh-runtime-state/reth-kurtosis-loop/session_20260426T193540Z/000005_disk_pressure_escalate/run_final.json` is not present. |
| Compose stack smoke | `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` | NOT RERUN | No current 2026-05-04 compose stack smoke result is recorded in this audit. The most recent local compose-chaos summary found during this audit is not a substitute for this gate and reports `status: below_threshold`. |
| Reth/Kurtosis smoke | `MESH_KURTOSIS_HOME=.../kurtosis scripts/run_reth_kurtosis_smoke.sh` | BLOCKED | `scripts/run_reth_kurtosis_smoke.sh` is absent in the current checkout. |
| Reth/Kurtosis full loop | `MESH_SERVER_PORT=19999 python3 scripts/run_reth_kurtosis_full_loop.py --base-url http://127.0.0.1:19999 --interval-seconds 1 --duration-seconds 12 --autonomous-remediation` | NOT RERUN | The full-loop helper still references the missing smoke bootstrap script when the default enclave/service are unavailable. `.mesh-runtime-state/reth-kurtosis-loop/` is absent locally, so no current full-loop artifact was available to inspect. |

## Historical Live Evidence

These entries are preserved as prior evidence only. They do not clear the
current audit by themselves.

| Gate | Historical result | Notes |
| --- | --- | --- |
| Compose stack smoke | PASS | Prior smoke run `run_20260427T025924_056a8fdf` reached `awaiting_operator` with decision `rollback_deployment`; this was accepted by the stack smoke gate at that time. |
| Reth/Kurtosis smoke | PASS | Prior note recorded an existing enclave `mesh-reth` and service `el-1-reth-lighthouse`. The bootstrap script named by that note is not present now. |
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

- Replace or remove the stale focused Python test gate that references
  `tests/test_kurtosis_reth_actuation.py`.
- Make the Python 3.11 validation path reproducible without relying on a
  long-running or unstable ad hoc uvx environment setup.
- Fix `npm --prefix web run test:e2e` so it uses a committed deterministic
  fixture or generates one instead of depending on an ignored
  `.mesh-runtime-state/reth-kurtosis-loop/.../run_final.json` file.
- Restore, replace, or remove `scripts/run_reth_kurtosis_smoke.sh`; both the
  readiness document and `scripts/run_reth_kurtosis_full_loop.py` currently
  assume it exists.
- Full strict mypy remains partial until the `files` scope is expanded beyond
  `services/decision/hypothesis_engine.py`.
- Compose, UI, and Reth/Kurtosis gates depend on local Docker/Kurtosis/browser
  availability and must be recorded with exact command output before merge.
- Compose stack smoke now rejects container-local Kubernetes loopback endpoints
  and requires the Compose-local RPC gateway and indexer targets to answer HTTP
  probes before the run launches.
- Unfinished production adapters are classified in
  [`docs/integrations.md`](./integrations.md); release notes must not describe
  them as production-complete integrations.
