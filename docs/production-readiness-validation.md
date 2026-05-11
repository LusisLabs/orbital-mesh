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
| Python lint | `UV_CACHE_DIR=/tmp/uv-cache-ruff-fresh UV_TOOL_DIR=/tmp/uv-tools-ruff-fresh2 RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .` | PASS | Reran on 2026-05-08 with a fresh uvx cache after the reused `/tmp/uv-cache` Ruff archive returned an entrypoint error; output: `All checks passed!`. |
| Python tests | `PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uvx --with-editable . --with deepagents --with pytest pytest` | PASS | Reran on 2026-05-08 with approved network/localhost permissions after the production-autonomy proof slice; `1431 passed, 1 skipped, 7 warnings` in `279.93s`. A sandbox-only dependency-resolution attempt failed on PyPI DNS and is not a valid gate result. |
| Strict mypy | <code>TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools PYTHONPATH=. uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/&#124;latent-mesh/LatentMAS/&#124;services/skills/'</code> | PASS, SCOPED | Reran on 2026-05-08 with isolated cache/tool dirs; output: `Success: no issues found in 1 source file`. This is strict mypy under the current `pyproject.toml` scope, not whole-repo type proof. |
| Web lint/contracts | `npm run lint` | PASS | Reran on 2026-05-08; root lint invoked `npm --prefix web run lint`, contracts check and `tsc --noEmit` exited `0`. npm emitted only the existing `store-dir` config warnings. |
| Web unit tests | `npm --prefix web test` | PASS | Reran on 2026-05-04; `2` files passed, `14` tests passed. |
| Web build | `npm --prefix web run build` | PASS WITH WARNING | Reran on 2026-05-04; build exited `0`. Vite reported `dist/assets/index-DGcNkvvo.js` at `620.11 kB`, above the 500 kB warning threshold. |
| UI Labyrinth/Playwright | `npm --prefix web run test:e2e` | PASS | Reran on 2026-05-06 with approved localhost-bind permissions; `14 passed`. A sandbox-only attempt fails before browser launch with control-plane and Vite `listen EPERM`, so approved localhost bind is required in this environment. |
| Compose stack smoke | `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` | PASS | Reran on 2026-05-06; smoke container exited `0`, target probes for `rpc-gateway` and `indexer` were ready, and run `run_20260506T182325_c87c4261` completed with `decision_type=rollback_deployment`, `execution_status=succeeded`, and `feedback_outcome=successful`. |
| Production-like smoke | `./scripts/prod_smoke.sh` | PASS | Reran on 2026-05-06 against `http://127.0.0.1:8787` with approved localhost HTTP access; health returned `status=ok`, readiness returned `state_path=/app/.mesh-runtime-state`, `goose.ready=true`, and the script printed `prod smoke passed`. |
| Pilot readiness/go-no-go | `GET /api/readiness` and `GET /api/pilot/go-no-go` | BLOCKED, BOOT VERIFIED | Reran `scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 30 --expect-blocked --json` on 2026-05-11 against the live compose stack. `/api/health` returned `status=ok` with runtime commit `unknown` and `image_digest=null`; the endpoint is reachable but not release-bound. The blocked-state verifier returned `status=pass`, `mode=expect_blocked`: `/api/readiness` was `profile=pilot`, `status=blocked`, and `/api/pilot/go-no-go` was `status=blocked` with a valid `pilot.go_no_go.v1` packet. Readiness blockers are now `authenticated_ingress_deployment_verified`, `mesh_brain_artifact_uri_prefix_configured`, `mesh_brain_artifact_upload_proof_verified`, and `design_partner_packet_verified`, which are also the default expected blockers for `--expect-blocked`. Policy lifecycle signing, run-export retention review, Mesh Brain serving backend config, and backup/restore rehearsal have current local evidence; backup/restore proof `.mesh-runtime-state/backup-restore-rehearsal.json` verified with `status=pass`, `environment=pilot`, and `state_backend=postgres`. Missing go/no-go evidence remains `readiness_green`, `mesh_brain_artifact_upload_proof_verified`, `release_provenance_complete`, and `on_call_drill_verified`. The default clearance audit `scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 30 --json` still returns `status=fail` because readiness is not green, go/no-go is not `go`, release provenance is missing from `/app/.mesh-runtime-state/release-provenance.json`, and runtime commit/image digest binding is absent. Denied-action proof and Mesh Brain canary/kernel/rollback checks are currently observed by go/no-go, but they do not clear the remaining pilot blockers. |
| Release provenance / CI artifacts | CI and handoff artifacts plus `mesh.release_provenance.v1` completion and runtime-binding checks | PARTIAL, CURRENT HEAD RUNTIME BOUND | The 2026-05-10 live handoff runtime mounted a complete release packet for current `HEAD`: `git_commit=583eb3e2335cb416e1360d9f0b2cbd3420e04275`, image digest `sha256:c54e7e28b9d94cb8ecdb07b60048a9bf3cf5ce853362c37089955ff8d9303d3a`, packet SHA `db7a5d5b6cddfcf9994605672f984e10cb72ebcef8f9e3cbec86ad33855d2904`, and runtime binding matched `/api/health`. Current-head provenance generation from this checkout still returned `status=incomplete` because the local tree is dirty at `AGENTS.md` and local release inputs are missing: `image_digest`, `base_image_digests`, `policy_lifecycle_signed`, `migration_rehearsal`, `sbom_path`, `vulnerability_scan_path`, `ci_attestation`, and `build_command`. The older CI run `25525840560` and image digest `sha256:2c088dd6ae51e97f9560fbc9e65ff564d0ec173afdb33121b41219fa8684da2f` remain historical evidence for commit `803b13e51f984a27f4bf42d0014ebb8d50cdd26a` only. |
| Autonomy policy tier guard | `PYTHONPATH=. python3 -m unittest tests.test_autonomy_policy tests.test_remediation_safety -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `shared.mesh_runtime.autonomy_policy.evaluate_autonomy_policy`. The focused suite verifies `fully_autonomous`, `approval_required`, `advisory_only`, and `denied_always`; Kubernetes live rollback is allowed only when connector certification grants the `rollback` scope; live feature-flag writes fail closed because `feature_flag_adapter` is still `dry-run`/`proposal` only; local mock execution reports live blockers without promoting fixture execution to live authority; and `force_approval_gate` blocks autonomous live Kubernetes execution through `EvaluationService.stage_results.autonomy_policy`. This is contract and fixture evidence, not a live broad-production autonomy proof. |
| Watch-mode proof contract | `PYTHONPATH=. python3 -m unittest tests.test_watch_mode_proof tests.test_autonomy_policy tests.test_kubernetes_watcher tests.test_watcher_registry -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `mesh.watch_mode_proof.v1` and `scripts/verify_watch_mode_proof.py`. The verifier requires multiple ticks, at least two unique run IDs, duplicate suppression with zero repeated runs, healthy false-positive suppression, watcher kill-switch pause evidence, recovered provider failure with no run created during the failure, recorded decisions/evidence/approval state, run export refs, postmortem export refs, secret-redaction proof, and a third-party replay ref. `--require-live` fails fixture packets unless `evidence_level=live`, so fixture watch proof cannot be presented as live production proof. |
| Provider action-scope proof contract | `PYTHONPATH=. python3 -m unittest tests.test_provider_action_scope tests.test_watch_mode_proof tests.test_autonomy_policy -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `mesh.provider_action_scope_proof.v1` and `scripts/verify_provider_action_scopes.py`. The verifier checks requested incident/action scopes against `config/connector-certification.registry.json`, connector state, policy tier, evidence refs, approval behavior, rollback or compensating refs, degraded behavior, credential governance, run exports, live refs when `--require-live` is set, and secret-material absence. Fixture tests prove Kubernetes `rollback`, OTel `feedback-proof`, and audit `local-audit` can pass as registry-allowed fixture scopes, while feature-flag `write` and external audit `append-only-audit-write` fail closed because the registry does not currently certify those scopes. This does not promote incident, feature-flag, or external audit providers beyond their registry states. |
| Incident coverage proof contract | `PYTHONPATH=. python3 -m unittest tests.test_incident_coverage tests.test_provider_action_scope tests.test_watch_mode_proof tests.test_autonomy_policy -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `mesh.incident_coverage_proof.v1` and `scripts/verify_incident_coverage_proof.py`. The verifier requires coverage entries for crash loops, bad deploy/image, readiness degradation, config drift, feature-flag regression, telemetry degradation, queue/resource pressure, external provider failure, partial outage, and false-positive controls. Each class must carry signal refs, decision refs, policy refs, test refs, artifact refs, expected behavior, and explicit fixture/live separation; `--require-live` fails fixture-only packets unless every class has live run IDs and live proof refs. False-positive controls must prove `no_action` with `false_positive_run_count=0`. |
| Repeatability proof contract | `PYTHONPATH=. python3 -m unittest tests.test_repeatability_proof tests.test_incident_coverage tests.test_provider_action_scope tests.test_watch_mode_proof tests.test_autonomy_policy -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `mesh.repeatability_proof.v1` and `scripts/verify_repeatability_proof.py`. The verifier requires current-head binding, release packet commit matching, clean working tree and recreated environment when strict mode is used, no manual `.env` surgery, fresh image build, SHA-256 image digest, no stale packet reuse, command timestamps and artifact refs, at least two unique passing run IDs, and per-run artifact refs. It can be pinned with `--expected-head`; dirty-env relaxation is explicit through `--allow-dirty-env` and is not acceptable for release repeatability evidence. |
| Production-like target proof contract | `PYTHONPATH=. python3 -m unittest tests.test_review_blockers tests.test_production_target_proof tests.test_repeatability_proof tests.test_incident_coverage tests.test_provider_action_scope tests.test_watch_mode_proof tests.test_autonomy_policy tests.test_remediation_safety tests.test_provider_adapter_proof tests.test_production_cut_list.PilotGoNoGoMeshBrainGateTests.test_pilot_go_no_go_requires_mesh_brain_kernel_live_canary_and_rollback_drill tests.test_production_cut_list.PilotGoNoGoMeshBrainGateTests.test_pilot_go_no_go_keeps_retained_evidence_outside_hot_session_file -v` | PASS, FOCUSED | Reran on 2026-05-08 after adding `mesh.production_target_proof.v1`, `scripts/verify_production_target_proof.py`, and the review-blocker regression for `approval_required_before_execution`; `55` tests passed. The verifier requires a production-like environment, bounded target ref, authenticated HTTPS ingress, operator and mutation identity evidence, telemetry and feedback refs, runtime secret refs with credential rotation and no raw secret material, rehearsed rollback, audited operator approval, complete run/evaluation/execution/feedback/postmortem exports, on-call/escalation/break-glass/retention/deletion refs, Merkle/timeline/policy/evidence refs, recovery/change/decision explanation refs, and third-party replay. `--require-live` rejects fixture packets unless `evidence_level=live` and live artifact refs are present, so this is not live target clearance. A direct non-socket coordinator check also verified interruptible auto recovery now reaches `recovery_spawned` and completes the child run for recoverable review blockers; the HTTP control-plane regression still requires an approved localhost-bind test run. |
| Production-autonomy aggregate clearance | `PYTHONPATH=. python3 -m unittest tests.test_production_autonomy_clearance -v` | PASS, FOCUSED | Reran on 2026-05-08 after tightening `mesh.production_autonomy_clearance.v1`; `7` tests passed. The aggregate verifier fails unless repeatability, production-target, provider action-scope, watch-mode, incident-coverage, and on-call drill verifications all pass together. It binds the production target to watch-mode target refs, requires the production target run ID to appear in repeatability, watch-mode, and incident-coverage evidence, requires a provider action run export for that same run, requires a third-party replay ref, and requires governance drill proof for kill switch, approval-gate forcing, break-glass, credential rotation, state restore, and environment binding. CLI clearance requires live proof by default; fixture packets pass only with explicit `--allow-fixture`, which is not valid for production-autonomy claims. |
| Reth/Kurtosis historical smoke | archived only | REMOVED FROM RELEASE GATES | Reth/Kurtosis evidence remains historical research provenance under `docs/history/research/`; the old bootstrap script is no longer a controlled-production-pilot release gate. Current pilot readiness is carried by Docker Compose, Kubernetes bounded-action proof, authenticated ingress, persistence, audit, and go/no-go packets. |

Run `scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 30 --json` as the final local audit before any pilot-clearance claim. It fails unless `/api/health` is healthy, `/api/readiness` is `pilot` and ready, `/api/pilot/go-no-go` is `go` with no missing evidence, the embedded release provenance record is complete, and the runtime health metadata matches the release packet commit and image digest.

When the intended proof is that the live runtime booted and is correctly blocked on missing pilot evidence, use the explicit blocked-state audit instead of treating a blocked packet as clearance:

```bash
scripts/verify_pilot_clearance.py \
  --base-url http://127.0.0.1:8787 \
  --timeout-seconds 30 \
  --expect-blocked \
  --json
```

`--expect-blocked` still fails on endpoint errors, the wrong readiness profile, missing blocked status, malformed go/no-go packets, missing expected blocker names, unexpected extra blocker names, missing blocker-detail mappings, or regression of expected observed go/no-go proofs such as denied-action and Mesh Brain kernel/canary/rollback evidence. The JSON output includes `prompt_to_artifact_checklist`, readiness blocker details, go/no-go missing-evidence details, and observed-proof details so each live gap maps back to its state slice, env vars, evidence path, remediation, and source endpoint. It does not clear pilot readiness or release clearance.

## Pilot Evidence Handoff

Use this checklist only for moving a booted-but-blocked pilot runtime to a
clearance audit. Do not replace target-environment proof with local fixtures,
historical packets, or unchecked paths.

The remaining pilot evidence/config inputs are:

- `MESH_AUTHENTICATED_INGRESS_PROOF_PATH` for deployed HTTPS/identity proxy proof.
- `MESH_POLICY_SIGNING_KEY` or `MESH_POLICY_SIGNING_KEY_PATH` for signed policy lifecycle proof.
- `MESH_BACKUP_RESTORE_REHEARSAL_PATH` for target backup/restore rehearsal proof.
- `MESH_BRAIN_ARTIFACT_URI_PREFIX`, `MESH_BRAIN_ARTIFACT_REGISTRY_PATH`, and `MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH` for durable Mesh Brain artifact storage and upload proof.
- `MESH_BRAIN_SERVING_BASE_URL` and `MESH_BRAIN_SERVING_MODEL` for the live Mesh Brain serving backend.
- `MESH_RUN_EXPORT_RETENTION_REVIEWED=1` after target retention review is complete.
- `MESH_DESIGN_PARTNER_PACKET_PATH` for the partner packet bound to the captured go/no-go and release-provenance hashes.
- `MESH_RELEASE_PROVENANCE_PATH`, with `MESH_BUILD_COMMIT` and `MESH_BUILD_IMAGE_DIGEST` matching `/api/health`.
- `MESH_ON_CALL_DRILL_PATH` for the staffed pilot drill proof.

After setting those inputs in the deployed runtime, capture the evidence in
this order:

```bash
scripts/generate_release_provenance.py --require-complete --json
scripts/verify_pilot_clearance.py --base-url https://<mesh-host> --timeout-seconds 30 --json
```

If the final command still fails, rerun the blocked-state audit with
`--expect-blocked --json` and inspect `prompt_to_artifact_checklist` before
changing readiness code. The checklist is the source of truth for which state
slice, env var, evidence path, remediation, and endpoint still blocks pilot.

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
- The earlier `.mesh-runtime-state/release-provenance.json` packet for commit
  `803b13e51f984a27f4bf42d0014ebb8d50cdd26a` is historical. The current live
  handoff runtime mounted a complete current-head release packet at
  `/release-provenance.json` for commit
  `583eb3e2335cb416e1360d9f0b2cbd3420e04275` and image digest
  `sha256:c54e7e28b9d94cb8ecdb07b60048a9bf3cf5ce853362c37089955ff8d9303d3a`,
  with packet SHA
  `db7a5d5b6cddfcf9994605672f984e10cb72ebcef8f9e3cbec86ad33855d2904`. This
  proves runtime binding only; readiness and go/no-go remain blocked.
- `.mesh-runtime-state/`, `.venv/`, `meshapp/frontend/out/`, `web/dist/`, and `web/test-results/` are
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
- Current-head release provenance has split evidence. The live handoff runtime
  reports matching current-head commit and image digest, but local provenance
  generation from this checkout remains incomplete until the dirty tree and
  local release inputs listed above are resolved. The older CI run
  `25525840560` remains historical evidence for commit
  `803b13e51f984a27f4bf42d0014ebb8d50cdd26a`, not for current `HEAD`.
- Pilot readiness and go/no-go must be treated as runtime-bound, not
  repository-wide. The current handoff runtime is commit/image bound to
  `583eb3e2335cb416e1360d9f0b2cbd3420e04275`, but the pilot-clearance verifier
  still returns `status=fail` because readiness and go/no-go evidence are
  blocked. Historical green rows do not clear the current runtime.
- Current readiness blockers map to explicit runtime inputs, not optional
  advisory checks: `MESH_OPERATOR_IDENTITY_REQUIRED=1`,
  `MESH_AUTHENTICATED_INGRESS_PROOF_PATH`, a signed policy lifecycle key,
  `MESH_BACKUP_RESTORE_REHEARSAL_PATH`, `MESH_STATE_BACKEND=postgres`,
  `MESH_DATABASE_URL`, either Prometheus feedback config or enabled Kubernetes
  live execution, durable `MESH_BRAIN_ARTIFACT_URI_PREFIX`,
  `MESH_BRAIN_ARTIFACT_REGISTRY_PATH`,
  `MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH`,
  `MESH_BRAIN_SERVING_BASE_URL`, `MESH_BRAIN_SERVING_MODEL`,
  `MESH_RUN_EXPORT_RETENTION_REVIEWED=1`, `MESH_DESIGN_PARTNER_PACKET_PATH`,
  and either disabled unfinished adapter credentials or valid provider proof
  packets for the feature-flag and incident adapters.
- `MESH_MEMORY_GRAPH_BACKEND=helix` is an optional verified-memory projection.
  It does not clear `MESH_STATE_BACKEND=postgres`, `MESH_DATABASE_URL`,
  backup/restore, migration, load, release-provenance, or pilot go/no-go
  blockers until a separate HelixDB canonical state backend and equivalent
  target-environment proof gates exist.
- Broad production-autonomy claims remain blocked. The current autonomy policy
  guard is a deterministic contract in
  `shared.mesh_runtime.autonomy_policy.evaluate_autonomy_policy` and is wired
  into `EvaluationService.stage_results.autonomy_policy`, but live proof is
  still required for each target actuator, connector scope, operator-approval
  path, kill-switch state, and release-bound runtime image before any claim
  beyond bounded pilot or design-partner scope.
- Watch mode has a focused proof contract and verifier, but no current live
  watch-mode packet is mounted in this audit. A live claim must provide a
  `mesh.watch_mode_proof.v1` packet from the target environment and pass
  `scripts/verify_watch_mode_proof.py --proof <path> --require-live --json`
  with run IDs, artifact refs, timestamps, provider-failure evidence,
  kill-switch evidence, and exported postmortems from that same session.
- Provider action scopes have a focused verifier, but the current registry
  still blocks broad provider-write claims. Feature-flag production writes,
  incident-provider writes, and external audit append-only writes require
  connector registry state changes backed by real provider proof packets,
  credential rotation and break-glass evidence, approval behavior, rollback or
  compensating action refs, run exports, and live proof refs. Until those
  artifacts exist, `scripts/verify_provider_action_scopes.py --require-live`
  must fail for those scopes.
- Incident coverage has a focused verifier, but no current live incident
  coverage packet is mounted in this audit. A broad autonomy claim must provide
  `mesh.incident_coverage_proof.v1` from the target environment and pass
  `scripts/verify_incident_coverage_proof.py --proof <path> --require-live
  --json`, covering crash loop, bad deploy/image, readiness degradation,
  config drift, feature-flag regression, telemetry degradation, queue/resource
  pressure, external provider failure, partial outage, and false-positive
  controls with live run IDs and artifact refs from the same proof window.
- Repeatability has a focused proof contract, but no current live repeatability
  packet is mounted in this audit. A release or broad-autonomy claim must pass
  `scripts/verify_repeatability_proof.py --proof <path> --expected-head
  <current-head> --json` without `--allow-dirty-env`, proving a fresh image,
  current-head release packet, no stale packet reuse, no manual `.env` surgery,
  at least two unique passing run IDs, command timestamps, and artifact paths.
- Production-like target proof has a focused verifier, but no current live
  target packet is mounted in this audit. A broad production-autonomy claim must
  provide `mesh.production_target_proof.v1` from the target environment and
  pass `scripts/verify_production_target_proof.py --proof <path>
  --expected-environment <target-env> --require-live --json`, proving the same
  bounded path has authenticated ingress, identity, telemetry, protected
  secrets, rollback, operator approval, postmortem export, governance refs, and
  replayable audit evidence. Missing credentials, ingress proof, or runtime live
  artifacts keep this gate blocked.
- Aggregate production-autonomy clearance has a focused verifier, but no
  current live proof bundle is mounted in this audit. A broad autonomy claim
  must pass `scripts/verify_production_autonomy_clearance.py` without
  `--allow-fixture` or `--allow-dirty-env`, using current-head repeatability,
  live production-target, live provider action-scope, live watch-mode, live
  incident-coverage, and on-call drill proof packets from the same bounded
  environment. The production target run must be bound through repeatability,
  watch-mode, provider action export, incident coverage, target refs, and
  third-party replay evidence in the aggregate verifier output. The on-call
  drill must prove kill-switch live-execution stop, watcher pause,
  approval-gate forcing, break-glass recording, credential rotation, state
  restore, and environment binding.
- Compose and UI gates depend on local Docker/browser availability and must be
  recorded with exact command output before merge. Reth/Kurtosis remains
  historical research provenance, not a controlled-production-pilot release
  gate.
- Full Python pytest is current for this proof-contract slice:
  `1431 passed, 1 skipped, 7 warnings` on 2026-05-08 with approved
  network/localhost permissions. The prior `1419 passed, 1 skipped, 3 failed`
  broad run is superseded by this result; the two `test_production_cut_list.py`
  failures and the control-plane recovery regression now pass in the full
  suite.
- Compose stack smoke now rejects container-local Kubernetes loopback endpoints
  and requires the Compose-local RPC gateway and indexer targets to answer HTTP
  probes before the run launches.
- Unfinished production adapters are classified in
  [`docs/integrations.md`](./integrations.md); release notes must not describe
  them as production-complete integrations.
