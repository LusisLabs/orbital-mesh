# Production Hardening Records

This document tracks the first executable slice from `docs/production-deployment-roadmap.md`.

## Cut List Coverage

Implemented in this slice:

- tiered readiness profiles and connector certification;
- operator identity and role checks around run creation, steering, kill switch, watcher mutation, trust-ladder override, and policy simulation;
- evidence graph as the default run-inspection surface in the UI;
- mutation-free policy simulator for fixtures, captured runs, and inline signals;
- executable authority-boundary tests for role gates, policy simulation, kill switch behavior, readiness profiles, and pilot live-feedback requirements;
- threat model, data classification, and supply-chain provenance records;
- pilot go/no-go packet generator;
- pilot live-feedback requirement;
- explicit disabling requirement for unfinished feature-flag and incident adapters;
- consolidated kill-switch API and UI panel;
- trust-ladder API rationale and browser UI visibility for autonomy ceilings, blockers, and next promotion requirements;
- run export package API and UI action for timeline JSON, Markdown postmortem, evidence artifacts, decision/evaluation/execution/feedback records, approvals, vault notes, and Merkle proof;
- enterprise and startup evaluation kit packaging from active repository paths;
- community governance and contribution boundary documentation;
- design-partner pilot packet;
- reference architecture packet tied to active compose, API, ingress, Postgres, Kubernetes, GPU, regulated-enterprise, and offline-adjacent paths;
- pilot SLO and error-budget contract with hard stops, measurement sources, latency targets, and review cadence;
- Postgres restart-proof harness for environments with `MESH_DATABASE_URL`;
- production-like compose defaults for Postgres state, named operator identity, approval-gated smoke, and disabled unfinished feature-flag and incident adapters;
- release provenance generator with an explicit `--require-complete` pilot gate;
- authenticated ingress rehearsal harness and proxy trust-boundary documentation;
- Mesh Brain durable artifact URI contract for model-kernel, live-smoke, rollback, and backend-matrix evidence refs;
- release-cut guard for active image names, API markers, docs, compose pilot defaults, provenance markers, authenticated ingress markers, and smoke paths.
- OpenSSF-oriented security audit baseline: private vulnerability reporting policy, CODEOWNERS for critical paths, Dependabot coverage, pinned GitHub Actions, weekly security audit workflow, dependency review, secret scanning, lockfile vulnerability scanning, npm audit, CodeQL where supported, OpenSSF Scorecard where supported, and `scripts/verify_security_audit_readiness.py`.

Deferred from the immediate list:

- broad historical-doc naming cleanup outside active release paths;
- production smoke against real authenticated TLS/SSO ingress;
- Helm, Terraform, marketplace, and ingress-controller-specific reference packages;
- deployment-specific ingress, Prometheus, audit-sink, signed-release, and load/concurrency SLO evidence;
- external audit-sink certification, SBOM generation, release-packet vulnerability scan artifact capture, image digest capture, and signed CI release packet production.

## Readiness Profiles

`MESH_READINESS_PROFILE` accepts `local`, `staging`, `pilot`, and `expansion`.

- `local` checks that local state, vault paths, and security headers are present. Promptfoo, Hermes, Goose, Evo, LatentMAS, and Deep Agents are optional lanes.
- `staging` additionally requires proxy-propagated operator identity, protected OTel ingest when enabled, live Kubernetes allowlists when live execution is enabled, and audit logging availability.
- `pilot` additionally requires Postgres state, `MESH_DATABASE_URL`, forced approval gate, live feedback source configuration, `MESH_BRAIN_ARTIFACT_URI_PREFIX`, `MESH_BRAIN_SERVING_BASE_URL`, `MESH_BRAIN_SERVING_MODEL`, and disabled unfinished feature-flag and incident adapters.
- `expansion` keeps pilot checks and adds the external audit-sink certification requirement.

`GET /api/readiness` returns `profile`, `status`, `required_checks`, `optional_checks`, `blockers`, and `connector_certification`.

## Operator Identity And Roles

When `MESH_OPERATOR_IDENTITY_REQUIRED=1`, mutating run APIs require proxy headers:

- identity header: `X-Mesh-Operator` by default, overridable with `MESH_OPERATOR_HEADER`;
- roles header: `X-Mesh-Roles` by default, overridable with `MESH_OPERATOR_ROLES_HEADER`.

Roles:

- `launcher` can create runs and non-approval steering commands;
- `approver` can approve and override decisions or execution parameters;
- `admin` can use all mutating controls, watcher controls, trust-ladder overrides, and the kill switch;
- `viewer` can call the mutation-free policy simulator.

Run creation records the operator under the run `operator` artifact. Steering commands and approval records include the operator identity and roles.

`docs/authenticated-ingress.md` documents the deployment boundary: Mesh trusts proxy-stamped identity headers, so production ingress must terminate TLS, enforce SSO/OIDC/SAML or equivalent identity, strip client-supplied Mesh identity headers, and only then set `X-Mesh-Operator` and `X-Mesh-Roles`.

`scripts/verify_authenticated_ingress.py` starts an ephemeral local control plane with `operator_identity_required=True` and proves app-level role behavior across anonymous denial, viewer simulation, launcher run creation, approver approval, and admin kill-switch access.

## Policy Simulator

`POST /api/policy/simulate` evaluates a fixture, captured run signal, or inline signal without creating a run session or recording evaluation state.

Accepted inputs:

- `{"scenario_key": "search_latency_regression"}`;
- `{"captured_run_id": "run_..."}`;
- `{"signal_payload": {...}}`.

The response includes `trigger`, `evidence_pack`, `scenario_analysis`, `decision`, `evaluation`, `blockers`, `allowed_action`, `denied_action`, `rollback_path`, and `mutates: false`.

## Kill Switch

`GET /api/kill-switch` returns watcher state, live-execution state, forced approval-gate state, and Kubernetes allowlists.

`POST /api/kill-switch` accepts:

- `stop_watchers: true`;
- `disable_live_execution: true`;
- `force_approval_gate: true`;
- `clear_namespace_allowlist: true`.

The kill switch records a `kill_switch` artifact and forces active run controls out of `interruptible_auto` by adding the `evaluation_ready` pause point.

## Trust Ladder Rationale

`GET /api/trust-ladder` and `GET /api/trust-ladder/{action_class}/{service}` return the persisted per-service/action evidence plus computed rationale fields:

- `next_level`;
- `promotion_requirements`;
- `promotion_blockers`;
- `autonomy_ceiling_reason`.

The computed fields are not persisted into `learning/trust_ladder.json`; they are derived from current thresholds so API clients and exported evidence do not need to reimplement threshold math. Manual override reason is surfaced as a blocker so operators can distinguish earned autonomy from forced autonomy.

The browser trust ladder renders current level, next threshold, recent blockers, run count, success rate, consecutive failures, overrides, and the current ceiling reason for each service/action entry.

## Pilot Go/No-Go Packet

`GET /api/pilot/go-no-go` generates `pilot.go_no_go.v1` from observed state. It is blocked until the runtime has actual evidence for readiness, observed runs, operator approval, live action proof, denied action proof, Merkle proof, rollback metadata, a passed Mesh Brain model-kernel gate, a canary live-serving smoke run, a single CROPS canary lane, and a Mesh Brain rollback drill.

This packet is not a manual intent record. Missing evidence appears under `missing_evidence`.

## Run Export Package

`POST /api/runs/{run_id}/export` materializes the run vault notes and writes a portable JSON package under `${MESH_STATE_DIR}/run_exports/{run_id}.json`. When proxy identity is required, the route accepts `viewer`, `launcher`, `approver`, or `admin` and rejects anonymous export attempts.

Export packages redact secret-shaped fields before writing. The default size cap is `MESH_RUN_EXPORT_MAX_BYTES=5242880`; oversized exports deterministically omit vault document bodies, event payloads and summaries, duplicated session artifacts, evidence artifacts, operator notes, and finally the long Markdown body until the package fits the cap.

`POST /api/runs/{run_id}/export/archive` writes and returns a zip archive with `Content-Disposition: attachment`. The archive contains `manifest.json`, the canonical `package.json`, `timeline.json`, `postmortem.md`, `merkle.json`, `checks.json`, record JSON files, and redacted vault Markdown files.

Each export carries retention metadata: `retention_days`, `delete_after`, `reviewed`, and the deletion command expectation. The default is `MESH_RUN_EXPORT_RETENTION_DAYS=30`; pilot readiness blocks until `MESH_RUN_EXPORT_RETENTION_REVIEWED=1` and the retention window is positive.

`scripts/purge_run_exports.py --state-dir ${MESH_STATE_DIR}` audits expired generated exports without deleting by default. Add `--apply` to delete only expired `run_exports/{run_id}.json` packages and matching `run_exports/{run_id}.zip` archives whose `retention.delete_after` has passed. The utility accepts `--json` for CI evidence and `--now` for rehearsal tests.

The package includes:

- timeline JSON for all run events;
- Markdown postmortem summary;
- evidence artifacts, including signal, trigger, evidence graph, investigation, scenario analysis, agent tasks, readiness, and memory crystallization when present;
- decision, evaluation, execution, feedback, approval, and operator-note records;
- Merkle snapshot and latest-event proof;
- vault Markdown documents for the run and linked artifacts;
- package checksum and persisted path.

The browser audit surface exposes `Build export` and `Archive` actions and shows event count, vault document count, package checksum, compaction state, and retention state.

Observed local-stack packet on 2026-05-04:

- status: `go`;
- readiness: `pilot` profile, `status: ready`, no blockers;
- approved and live-action proof run: `run_20260504T204223_791d4770`;
- denied-action proof run: `run_20260504T204409_5229c69a`, blocked with `approval required before execution`;
- Merkle proof observed for six runs, including the live action, denied action, and Postgres restart-proof runs;
- missing evidence: none.

Observed local-stack packet on 2026-05-05 after the live compose smoke:

- status: `blocked`;
- readiness: `pilot` profile, `status: blocked`;
- readiness blockers: `mesh_brain_artifact_uri_prefix_configured`, `mesh_brain_serving_backend_configured`, `run_export_retention_reviewed`;
- live-action and approved proof run: `run_20260505T054747_9a8c2386`;
- run outcome: `completed`, decision `rollback_deployment`, execution `succeeded`, feedback `successful`;
- Merkle root for the live run: `5b962a4e378546c7373271148fc9f420303ea20b11183a0d94eab32a647e5f06`, with `58` leaves;
- pilot packet observed `8` runs, live-action proof, denied-action proof, operator approval, rollback plan, and Merkle proof;
- missing pilot evidence: `readiness_green`, Mesh Brain model-kernel gate, Mesh Brain live canary smoke, single CROPS canary lane, and Mesh Brain rollback drill.

Observed local-stack packet on 2026-05-05 after Mesh Brain pilot env wiring:

- status: `go`;
- readiness: `pilot` profile, `status: ready`, no blockers;
- readiness inputs were `MESH_BRAIN_ARTIFACT_URI_PREFIX=s3://mesh-prod-artifacts/mesh-brain`, `MESH_BRAIN_SERVING_BASE_URL=http://host.docker.internal:1234`, `MESH_BRAIN_SERVING_MODEL=nvidia/nemotron-3-nano-4b`, and `MESH_RUN_EXPORT_RETENTION_REVIEWED=1`;
- the serving backend was a local OpenAI-compatible smoke backend, not a production model-serving backend;
- model-kernel proof run: `run_20260505T055908_8be1e9e5`, `final_release_decision: pass`, Merkle root `9f9fec65f443517bfa930c5b10adf4bf77d5838fb82ebab961951f9777096049`;
- live canary smoke run: `run_20260505T055908_51637047`, `final_release_decision: canary`, single lane `tenant_a/crops`, Merkle root `61fa5d84e0ba2ed2b763166155e06e0b82dd2ea027b6e0d213c2f4c86bad75dc`;
- rollback drill run: `run_20260505T055908_d53f14ca`, `final_release_decision: pass`, restored previous artifact, Merkle root `72f227d7b8dc755c93293c0bb4125f6f3ed9f5c02db9b86e33a881274e9b4dfa`;
- pilot packet observed `11` runs, live-action proof, denied-action proof, operator approval, rollback plan, Merkle proof, model-kernel gate, live canary smoke, single CROPS canary lane, and rollback drill;
- missing evidence: none.

## Connector Certification States

Certification states currently used:

- `mock`;
- `read-only`;
- `staging-ready`;
- `pilot-ready`;
- `production-ready`;
- `proposal-only`;
- `unfinished`;
- `disabled`.

Feature-flag and incident adapters remain `unfinished` unless disabled. Deep Agents and Evo remain `proposal-only`. Kubernetes becomes `pilot-ready` only when live execution is enabled with context and namespace allowlists.

## Threat Model Register

Initial authority boundaries:

| Boundary | Current control | Required before external operators |
| --- | --- | --- |
| HTTP API | proxy identity headers plus app-level role checks | authenticated TLS reverse proxy |
| SSE streams | read-only stream, security headers | authenticated reverse proxy and viewer role |
| Webhooks | registered source with HMAC verification | vendor-specific template validation |
| OTel ingest | optional bearer token | bearer token or private ingress |
| Kubeconfig | live execution disabled by default | least-privilege context and namespace allowlists |
| Proposal lanes | advisory artifacts only | no kubeconfig, repo write, or actuator credentials |
| State store | file or Postgres backend | encrypted persistent storage and restore rehearsal |
| Run exports | vault and Merkle artifacts | redaction rules, export-size limits, archive format, and pilot retention review gate |
| Mesh Brain artifacts | state-store refs with SHA-256 and optional durable URI prefix | object-storage upload proof for every production URI |

Open findings must be tracked with owner, decision, expiry, and compensating control before staging exposure.

## Data Classification

| Data class | Examples | Handling |
| --- | --- | --- |
| Operational signal | Kubernetes pods, OTel metrics, webhook labels | retain in run artifacts; redact secrets before export |
| Operator identity | operator id, roles, proxy source | retain with run and steering audit events |
| Secret material | tokens, kubeconfig, API keys, auth headers | do not store in run artifacts; redact if received |
| Model output | observer verdicts, proposal-lane artifacts | retain as advisory artifacts with source lane |
| Audit proof | events, Merkle roots, proofs | append-only; include in go/no-go and postmortem bundles |
| Training candidates | incident corpus rows, observations, claims | exclude audit-only rows unless explicitly labeled trainable |

## Supply-Chain Provenance Record

Pilot release packets must include:

- git commit;
- image tag and digest;
- base-image digest;
- dependency lockfiles;
- policy file hashes;
- migration version;
- SBOM path;
- vulnerability scan path;
- build command and builder identity;
- readiness profile and environment.

`scripts/generate_release_provenance.py` now emits `mesh.release_provenance.v1` packets. Local developer output is allowed to be `status: incomplete`; pilot release jobs must run with `--require-complete`.

Current local generation returns `status: incomplete` because this worktree is dirty and CI-only artifacts are absent:

- `clean_git_tree`;
- `image_digest`;
- `base_image_digests`;
- `sbom_path`;
- `vulnerability_scan_path`;
- `build_command`.

Until those fields are supplied by CI and `--require-complete` exits successfully, pilot readiness remains blocked at the release-packet layer even if `/api/pilot/go-no-go` is `go`.

## Release Cut Guard

Run:

```bash
scripts/verify_release_cut_list.py --json
```

The guard checks active Docker image defaults, required production docs, smoke scripts, run-export purge utility, API markers, compose pilot defaults, release-provenance markers, authenticated ingress markers, and release-packet references. It is a static guard; it does not replace live compose smoke, production smoke, browser e2e, authenticated ingress rehearsal, Postgres restart proof, or signed CI provenance.

The guard also checks that `docs/post-training/runtime.md`, `mesh_brain/artifact_registry.py`, and the control-plane artifact recorder retain the Mesh Brain durable artifact contract. Production deployments must set `MESH_BRAIN_ARTIFACT_URI_PREFIX` to a durable object-storage prefix and must upload each recorded blob to the corresponding URI. Local paths in the state store are audit/debug refs only.

## Current Validation Evidence

Validated in this slice:

- `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list` passed with `13` tests after adding the run export package API/UI path, secret redaction, size-cap compaction, zip archive endpoint, and retention readiness gate;
- `PYTHONPATH=. python3 -m unittest tests.test_run_export_retention tests.test_trust_ladder` passed with `13` tests after adding the dry-run-first purge utility and computed trust-ladder autonomy rationale;
- `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` passed on 2026-05-05 and produced live run `run_20260505T054747_9a8c2386` with `rollback_deployment`, execution `succeeded`, and feedback `successful`;
- `./scripts/prod_smoke.sh` passed against `http://127.0.0.1:8787` after the stack remained healthy;
- `docker compose -f docker-compose.stack.yml up -d --build --force-recreate mesh mesh-agent-operator` passed after wiring Mesh Brain pilot env passthroughs into the stack compose file;
- `POST /api/mesh-brain/model-kernel-probe` passed and produced `run_20260505T055908_8be1e9e5`;
- `POST /api/mesh-brain/live-serving-smoke` passed against the local OpenAI-compatible smoke backend and produced `run_20260505T055908_51637047`;
- `POST /api/mesh-brain/rollback-drill` passed and produced `run_20260505T055908_d53f14ca`;
- `GET /api/pilot/go-no-go` returned `status: go` with no missing evidence after the rollback-drill predicate was corrected to accept the drill contract's `final_release_decision: pass`;
- `PYTHONPATH=. python3 -m unittest tests.test_authenticated_ingress tests.test_release_provenance tests.test_production_faults_and_packaging tests.test_run_export_retention tests.test_trust_ladder` passed with `26` tests when localhost binding was allowed for the authenticated-ingress rehearsal;
- `python3 scripts/verify_postgres_restart_proof.py --skip-if-missing --json` returned `status: skipped` because `MESH_DATABASE_URL` was not set in the local shell;
- `scripts/generate_release_provenance.py --json` returned `status: incomplete` because the worktree is dirty and CI release artifacts are absent;
- `npm --prefix web run lint` passed after adding the run export API client, archive blob client, audit UI controls, compaction metadata, and retention state;
- `npm --prefix web run build` passed after adding the run export UI controls, archive blob client, compaction metadata, and retention state, with the existing Vite chunk-size warning;
- `npm --prefix web run test:e2e` passed with `12` Playwright tests after adding the run export audit controls, archive action, compaction metadata, retention state, and trust-ladder rationale rendering;
- `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list tests.test_production_faults_and_packaging` passed with `15` tests;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance tests.test_production_faults_and_packaging` passed with `11` tests;
- `python3 -m unittest tests.test_authenticated_ingress` passed with `2` tests and asserted that `scripts/verify_authenticated_ingress.py --json` returned `status: passed`;
- `python3 -m unittest tests.test_authenticated_ingress tests.test_release_provenance tests.test_production_faults_and_packaging` passed with `13` tests after adding the reference architecture and pilot SLO packets;
- `scripts/verify_release_cut_list.py --json` returned `status: pass`;
- `scripts/generate_release_provenance.py --json` returned `status: incomplete` with missing CI release gates listed above;
- `scripts/verify_postgres_restart_proof.py --skip-if-missing --json` returned `status: skipped`;
- `npm --prefix web run test:e2e` passed with `12` Playwright tests after fixing the portable UI seed path and mobile drawer layering;
- `npm --prefix web run lint` passed;
- `npm --prefix web run build` passed with the existing Vite chunk-size warning;
- focused `ruff check` over changed scripts and production tests passed;
- `scripts/prod_smoke.sh` passed against a temporary local control-plane server at `http://127.0.0.1:18789`;
- `docker compose -f docker-compose.stack.yml run --rm mesh-smoke` passed against the running all-in-one stack; live run `run_20260504T203226_314011a8` completed `rollback_deployment` with `execution_status: succeeded` and `feedback_outcome: successful`;
- `/usr/local/bin/python3 /workspace/orbital-mesh/scripts/verify_postgres_restart_proof.py --database-url postgresql://mesh:mesh@postgres:5432/mesh --json` passed inside the mesh container; proof run `run_20260504T203344_be2f641d` restored run state, events, memory, Merkle root, and event proof.
- after switching `docker-compose.stack.yml` to Postgres and named operator defaults, `GET /api/readiness` returned `status: ready` for the `pilot` profile with no blockers;
- `docker compose -f docker-compose.stack.yml run --rm mesh-smoke` passed again with approval-gated live run `run_20260504T204223_791d4770`;
- a denied-action evidence run `run_20260504T204409_5229c69a` stopped at `awaiting_operator` with `final_recommendation: human_review` and `blocking_reasons: ["approval required before execution"]`;
- `scripts/prod_smoke.sh` passed against the active compose control plane at `http://127.0.0.1:8787`;
- `/usr/local/bin/python3 /workspace/orbital-mesh/scripts/verify_postgres_restart_proof.py --database-url postgresql://mesh:mesh@postgres:5432/mesh --json` passed again inside the mesh container; proof run `run_20260504T205340_e1afbbdd` restored run state, events, memory, Merkle root, and event proof;
- `GET /api/pilot/go-no-go` returned `status: go`, all checks true, `run_count: 6`, and `missing_evidence: []`.

Still not validated in this environment:

- production smoke against real authenticated TLS/SSO ingress;
- real TLS/SSO ingress header-stripping and group-mapping proof from the deployed reverse proxy;
- external audit-sink certification;
- signed CI release provenance with complete image/base-image digests, SBOM, vulnerability scan, clean tree, build command, and builder identity.
