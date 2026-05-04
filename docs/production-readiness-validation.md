# Production Readiness Validation

This matrix is the release-facing validation record for the current
end-to-end wiring cleanup. It separates proven gates from partial gates and
local environment blockers.

The deployment roadmap is tracked in
[`docs/production-deployment-roadmap.md`](./production-deployment-roadmap.md);
this file records validation evidence for those gates.

## Validation Matrix

| Gate | Command | Current status | Notes |
| --- | --- | --- | --- |
| Python lint | `UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx ruff check .` | PASS | `All checks passed!` |
| Focused Python tests | `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_hypothesis_engine_reth.py tests/test_kurtosis_reth_actuation.py tests/test_monitoring_corpus.py tests/test_incident_corpus.py` | PASS | `39 passed`; covers Reth hypothesis, Kurtosis actuation, monitoring catalog, and incident corpus export. |
| Strict mypy | `TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict ...` | PARTIAL PASS | `Success: no issues found in 1 source file`; `pyproject.toml` currently scopes mypy to `services/decision/hypothesis_engine.py`, so this is not whole-repo proof. |
| Web lint/contracts | `npm --prefix web run lint` | PASS | Includes generated contract drift check and `tsc --noEmit`. |
| Web unit tests | `npm --prefix web test` | PASS | `2` files, `12` tests. |
| Web build | `npm --prefix web run build` | PASS WITH WARNING | Built successfully; Vite still reports `dist/assets/index-*.js` at `571.09 kB`, above the 500 kB warning threshold. |
| UI Labyrinth/Playwright | `npm --prefix web run test:e2e` | PASS | `6 passed`; required elevated localhost bind permission for the temporary API/Vite servers. |
| Compose stack smoke | `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` | PASS | Smoke run `run_20260427T025924_056a8fdf` reached `awaiting_operator` with decision `rollback_deployment`; this is accepted by the stack smoke gate. |
| Reth/Kurtosis smoke | `MESH_KURTOSIS_HOME=.../kurtosis scripts/run_reth_kurtosis_smoke.sh` | PASS | Existing enclave `mesh-reth` and service `el-1-reth-lighthouse` were running. |
| Reth/Kurtosis full loop | `MESH_SERVER_PORT=19999 python3 scripts/run_reth_kurtosis_full_loop.py --base-url http://127.0.0.1:19999 --interval-seconds 1 --duration-seconds 12 --autonomous-remediation` | PASS | Session `.mesh-runtime-state/reth-kurtosis-loop/session_20260427T030606Z`; `2` cycles, `1` restart decision, `1` successful execution, `0` failed cycles. |

## Reth/Kurtosis Post-Action Observation

The full-loop run wrote post-action observations for
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
- Compose, UI, and Reth/Kurtosis gates depend on local Docker/Kurtosis/browser
  availability and must be recorded with exact command output before merge.
- Compose stack smoke now rejects container-local Kubernetes loopback endpoints
  and requires the Compose-local RPC gateway and indexer targets to answer HTTP
  probes before the run launches.
- Unfinished production adapters are classified in
  [`docs/integrations.md`](./integrations.md); release notes must not describe
  them as production-complete integrations.
