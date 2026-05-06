# Production Hardening Records

This document tracks the first executable slice from `docs/production-deployment-roadmap.md`.

## Cut List Coverage

Implemented in this slice:

- tiered readiness profiles and connector certification;
- ownership registry and run-level ownership boundary artifacts;
- policy lifecycle manifest, signed policy hash packet, and readiness blocker;
- evidence sufficiency gate by action class and risk tier;
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
- `staging` additionally requires proxy-propagated operator identity, configured ownership registry, configured connector certification registry, signed policy lifecycle hashes, protected OTel ingest when enabled, live Kubernetes allowlists when live execution is enabled, and audit logging availability.
- `pilot` additionally requires Postgres state, `MESH_DATABASE_URL`, forced approval gate, live feedback source configuration, `MESH_BRAIN_ARTIFACT_URI_PREFIX`, `MESH_BRAIN_SERVING_BASE_URL`, `MESH_BRAIN_SERVING_MODEL`, and disabled unfinished feature-flag and incident adapters.
- `expansion` keeps pilot checks and adds the external audit-sink certification requirement.
- `expansion` also requires `MESH_AUDIT_SINK_PROOF_PATH` to point at a passing external audit sink append-only proof before compliance reliance.

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

## Operator Handoff Evidence

`POST /api/runs/{run_id}/steer` accepts `command: "handoff"` for active runs. The payload records `to_operator_id`, optional `to_roles`, `reason`, `next_action`, `urgency`, and optional `due_at`.

The runtime materializes each handoff as `mesh.operator_handoff.v1`, stores it under the run `operator_handoffs` artifact, and emits an `operator_handoff_recorded` event. Run export packages carry `handoff_records`; zip archives include `records/handoffs.json`; Markdown postmortems include an Operator Handoffs section. Handoffs stay separate from `approval_records`, which are limited to authority-bearing approve, resume, and override commands. This closes the handoff part of the operator workflow without changing approval, evaluation, execution, or rollback gates.

## Postmortem Review Evidence

`POST /api/runs/{run_id}/steer` accepts `command: "postmortem_review"` after a run reaches a terminal stage. The payload records `verdict`, `findings`, `action_items`, and optional reviewed export id and package SHA-256.

The runtime materializes each review as `mesh.postmortem_review.v1`, stores it under `postmortem_reviews`, and emits a `postmortem_review_recorded` event. When the launch operator is known, the reviewer must be a different operator. Run export packages carry `postmortem_review_records`; zip archives include `records/postmortem-reviews.json`; Markdown postmortems include a Postmortem Reviews section. This makes the private-staging requirement that an operator who did not launch the run reviews the export machine-checkable.

## Override Review Evidence

`POST /api/runs/{run_id}/steer` accepts `command: "override_review"` against a prior `override_decision` or `override_execution_parameters` steering event. The payload records target override event or command id, verdict, reason, findings, and action items.

The runtime materializes each review as `mesh.override_review.v1`, stores it under `override_reviews`, and emits an `override_review_recorded` event. When the override operator is known, the reviewer must be a different operator. Run export packages carry `override_review_records`; zip archives include `records/override-reviews.json`; Markdown postmortems include an Override Reviews section. This keeps override authority separate from post-facto audit review while making manual intervention review exportable.

## Backup Restore Rehearsal Evidence

`scripts/verify_backup_restore_rehearsal.py --proof <backup-restore-rehearsal.json> --json` verifies a `mesh.backup_restore_rehearsal.v1` packet for private staging and later pilot operations.

The proof must identify the operator, backup ref, restore ref, RPO/RTO targets, measured restore duration, state backend, and restored components for state store, vault, Merkle proofs, integrations config, and research artifacts. Each component must carry a backup URI, matching before/after SHA-256 values, restored status, and record count. Staging readiness now reports `backup_restore_rehearsal_verified`; production Compose requires `MESH_BACKUP_RESTORE_REHEARSAL_PATH` so a deployment cannot claim private-staging readiness from the runbook alone.

## Migration Rehearsal Evidence

`scripts/generate_migration_rehearsal.py --output <migration-rehearsal.json> --operator-id <operator> --applied-migration-count <count> --rolled-back --rollback-ref <ref> --pre-migration-snapshot-ref <ref> --post-migration-validation-ref <ref> --destructive-changes-reviewed --measured-apply-seconds <seconds> --measured-rollback-seconds <seconds>` generates a `mesh.migration_rehearsal.v1` packet from real Postgres rehearsal evidence.

`scripts/verify_migration_rehearsal.py --proof <migration-rehearsal.json> --expected-version <version> --expected-combined-sha256 <sha> --json` verifies the packet for Postgres migration release gates.

The proof generator computes the repo's latest migration version and combined migration SHA-256 from `migrations/postgres`; the operator supplies the rehearsal-specific applied count, rollback proof ref, snapshot ref, post-validation ref, destructive-change review confirmation, and timings. `scripts/generate_release_provenance.py` accepts `--migration-rehearsal` or `MESH_MIGRATION_REHEARSAL_PATH`; `--require-complete` includes `migration_rehearsal` so a pilot release packet cannot be complete from migration hashes alone.

## Release Image Metadata Evidence

`scripts/collect_release_image_metadata.py --image-tag <image> --output <metadata.json> --github-env "$GITHUB_ENV" --base-image-args <args-file>` collects a `mesh.release_image_metadata.v1` packet from Docker image inspection. CI uses it after building `orbital-mesh:ci` to feed `MESH_IMAGE_DIGEST` and base-image digests into `mesh.ci_attestation.v1`, then uploads a `release-provenance-draft` artifact. The draft is expected to remain incomplete until real SBOM, vulnerability scan, migration proof, policy signing key, and clean release tree evidence are present.

Local Docker validation on 2026-05-06 built `orbital-mesh:ci` with image id `sha256:a69cc228101e6970b4c924cbd47369ca50c6b7475b386b253a72a1542322b16f`. Running the metadata collector in CI-equivalent mode pulled the referenced base images and produced digests for `node:22-bookworm-slim`, `debian:12-slim`, `rust:1.92-slim-bookworm`, `python:3.12-slim-bookworm`, and `python:3.11-slim-bookworm`. The same collector run without pulling left several base-image digest fields empty, which is why the CI path must inspect or pull base refs before generating the attestation.

A local attestation at `/tmp/orbital-mesh-ci-attestation-local.json` and migration proof at `/tmp/orbital-mesh-migration-rehearsal.json` made release provenance pass `image_digest`, `base_image_digests`, `ci_attestation`, `build_command`, `policy_lifecycle_signed`, and `migration_rehearsal`. The packet still returned `status: incomplete` with missing gates `clean_git_tree`, `sbom_path`, and `vulnerability_scan_path`. This is local Docker and packet-shape evidence only; it is not a substitute for a live GitHub Actions artifact or real release-image SBOM and vulnerability scan.

## On-Call Drill Evidence

`scripts/verify_on_call_drill.py --proof <on-call-drill.json> --json` verifies a `mesh.on_call_drill.v1` packet for production-pilot go/no-go capture.

The proof must identify the operator, environment, recovery target, and measured recovery time, then prove kill switch execution, watcher pause, forced approval gate, bad-target revocation, denied-action evidence, stuck-run recovery, failed-dependency degradation handling, provider-key rotation with break-glass recording, and state restore. `/api/pilot/go-no-go` now reports `on_call_drill_verified`; production Compose requires `MESH_ON_CALL_DRILL_PATH` so a pilot go/no-go packet cannot pass from run evidence and release provenance alone.

## Ownership Boundary

`config/ownership.registry.json` is the current machine-readable ownership registry. It maps pilot services to namespace, owner, tenant, customer, customer-boundary, approver roles, rollback authority, escalation route, allowed action classes, policy refs, and data-boundary rules.

`MESH_OWNERSHIP_REGISTRY_PATH` points the runtime at that registry. For normal `POST /api/runs` creation, Mesh resolves the incoming signal service and environment against the registry, writes an `ownership_boundary` run artifact, and emits an `ownership_boundary_recorded` event. The artifact includes tenant id, customer id, namespace, customer-boundary, reservoir refs, export policy, retention days, and legal-action scope. If no registry record matches, the artifact is unresolved and carries `ownership_record_missing` as a blocker instead of inventing authority.

Staging and pilot readiness include `ownership_registry_configured`. A missing or invalid registry blocks readiness; optional proposal lanes still do not get production authority from this registry.

## Connector Certification

`config/connector-certification.registry.json` is the connector certification registry. It records each connector's maximum certified state, required deployment tier, authority posture, credential policy, credential boundary, degraded behavior, allowed scopes, evidence refs, and known blockers.

`GET /api/connectors/certification` returns `mesh.connector_certification.v1`. Runtime readiness combines the registry with observed connector state and never upgrades a connector beyond the registry's certified state. The packet now carries service-account refs, credential mode, runtime-secret requirements, rotation-evidence refs, break-glass recording requirements, and explicit booleans for production actuator and repository write credentials. Proposal-only lanes emit blockers if runtime evidence says production actuator credentials or repository write credentials are present.

The browser Connectors page calls `/api/connectors/certification` and renders authority posture, required tier, credential boundary, allowed scopes, and blockers from the full packet. It falls back to abbreviated `/api/readiness` certification state only when the full packet is unavailable.

Staging and pilot readiness include `connector_certification_registry_configured`. Missing or invalid certification data blocks readiness; proposal-only lanes remain advisory and do not receive production actuator or repo-write credentials from certification.

## External Audit Sink Contract

`scripts/verify_audit_sink_contract.py --proof <path> --json` verifies a `mesh.audit_sink_proof.v1` packet for expansion/compliance use. The proof must show an append-only external destination, durable URI, receipt id, sink sequence, event count, run-export SHA-256, Merkle root, runtime-secret service account boundary, no production actuator or repo-write credential scope, rotation evidence, break-glass drill recording, and positive retention window.

`MESH_AUDIT_SINK_PROOF_PATH` points readiness at that proof. Expansion readiness now reports `external_audit_sink_contract_verified` separately from `external_audit_sink_certified`. The current registry still caps `audit_sink` at `mock`, so this contract is only the machine-checkable evidence shape until a real sink is certified and the registry is reviewed.

## Credential Rotation Evidence

`scripts/verify_credential_rotation.py --connector-id <id> --proof <path> --json` verifies `mesh.credential_rotation_proof.v1` against `config/connector-certification.registry.json`. The proof must match the connector id, service-account ref, and credential mode recorded in the certification registry, show the previous secret was revoked, include a rotation ticket, operator id, evidence refs, no raw secret material, and prove break-glass recording when the registry requires it.

This utility does not certify a connector by itself. It makes the existing `rotation_evidence_ref` and `break_glass_recording_required` fields enforceable during pilot or expansion review.

## Timeline Proof

`GET /api/runs/{run_id}/timeline-proof` returns `mesh.timeline_proof.v1`. The packet normalizes run events into sequence, event id, stage, event type, UTC timestamp, `time_unix_nano`, payload hash, Merkle leaf hash, artifact key, integration name, and status.

The packet includes the run Merkle snapshot, latest-event proof, and checks for gapless monotonic sequence, parseable timestamps, non-decreasing event time, Merkle root presence, and latest-event proof validity. Run export packages also include `timeline_proof` and archive `timeline-proof.json`.

## Run Admission

Run creation records `mesh.run_admission.v1` before work enters the worker queue. The packet captures tenant id, target lock key, queue depth, queue size, worker count, tenant active-run count, tenant active-run quota, target-lock holder, admission decision, and blockers.

`MESH_TENANT_ACTIVE_RUN_QUOTA` defaults to `4`. A run is blocked before queueing when its tenant quota is exhausted, the queue is full, or a required live target lock is already held. Target locks are enforced for live Kubernetes execution and for calls that explicitly set `require_target_lock: true`; advisory/local runs still record their target key without taking production authority.

## Failure Mode Library

`config/failure-mode.library.json` is the machine-readable failure-mode catalog for private staging. `scripts/verify_failure_mode_library.py --json` and `GET /api/failure-modes` emit `mesh.failure_mode_library.v1` with required-mode coverage, duplicate-id checks, UI replay references, test references, operator actions, authority boundaries, entries, and blockers.

Staging readiness now reports `failure_mode_library_configured`. The current required catalog covers denied namespace, stale kubeconfig, unavailable proposal LLM, unavailable external audit sink, core Kubernetes faults, duplicate signals, delayed feedback, dependency timeout, queue backpressure, and transient network failure. The `ui://failure-mode/...` replay refs are stable catalog identifiers; browser replay automation and long-window live fault evidence remain separate pilot work.

## Watcher Ownership Evidence

`GET /api/watchers/ownership` emits `mesh.watcher_ownership.v1` from the typed watcher registry and `config/ownership.registry.json`. The packet resolves each watcher target to owner, tenant, customer boundary, approver roles, rollback authority, escalation route, and allowed action classes. `GET /api/watchers` embeds the same ownership record per watcher so the operator surface can show which team owns each live signal loop before start/stop decisions.

Watchers without targets or without matching ownership records are marked blocked instead of inheriting authority from the watcher process. This closes the operator ownership workflow for registered watchers; target-environment proof still requires at least one Kubernetes watcher path and one webhook or OTel path to create real runs in private staging.

## Policy Lifecycle

`config/policy-lifecycle.manifest.json` is the policy lifecycle manifest. It must cover every JSON policy in `policies/` and records owner, lifecycle state, risk tier, effective window, review expiry, and rollback reference.

`GET /api/policy/lifecycle` returns `mesh.policy_lifecycle.v1` with policy file hashes, combined policy hash, manifest hash, coverage details, and an HMAC signature when `MESH_POLICY_SIGNING_KEY` is configured. The release provenance packet embeds this lifecycle packet under `policies.lifecycle`.

Staging and pilot readiness include `policy_lifecycle_signed`. Missing signature material, missing manifest coverage, or missing policy files block readiness.

## Evidence Sufficiency

Evaluation emits `mesh.evidence_sufficiency.v1` at `stage_results.evidence_sufficiency`. The packet records action class, risk tier, required evidence ref count, observed evidence refs, missing gates, and notes.

Mutating actions require progressively more evidence from low to high risk. Medium and high risk actions also require rollback reference coverage; high risk mutation requires structured evidence such as a sufficiency-marked evidence pack, probe results, scenario analysis, or investigation report. Failed sufficiency adds `evidence sufficiency gate did not pass` to `blocking_reasons`.

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

`GET /api/pilot/go-no-go` generates `pilot.go_no_go.v1` from observed state. It is blocked until the runtime has actual evidence for readiness, observed runs, operator approval, live action proof, denied action proof, Merkle proof, rollback metadata, a passed Mesh Brain model-kernel gate, a canary live-serving smoke run, a single CROPS canary lane, a Mesh Brain rollback drill, and complete release provenance when the readiness profile is `pilot` or `expansion`.

This packet is not a manual intent record. Missing evidence appears under `missing_evidence`. Pilot and expansion deployments must set `MESH_RELEASE_PROVENANCE_PATH` to a readable `mesh.release_provenance.v1` packet with `status: "complete"`; otherwise the packet remains blocked with `release_provenance_complete`.

## Run Export Package

`POST /api/runs/{run_id}/export` materializes the run vault notes and writes a portable JSON package under `${MESH_STATE_DIR}/run_exports/{run_id}.json`. When proxy identity is required, the route accepts `viewer`, `launcher`, `approver`, or `admin` and rejects anonymous export attempts.

Export packages redact secret-shaped fields before writing. The default size cap is `MESH_RUN_EXPORT_MAX_BYTES=5242880`; oversized exports deterministically omit vault document bodies, event payloads and summaries, duplicated session artifacts, evidence artifacts, operator notes, and finally the long Markdown body until the package fits the cap.

`POST /api/runs/{run_id}/export/archive` writes and returns a zip archive with `Content-Disposition: attachment`. The archive contains `manifest.json`, the canonical `package.json`, `timeline.json`, `postmortem.md`, `merkle.json`, `checks.json`, record JSON files, and redacted vault Markdown files.

Each export carries retention metadata: `retention_days`, `delete_after`, `reviewed`, and the deletion command expectation. The default is `MESH_RUN_EXPORT_RETENTION_DAYS=30`; pilot readiness blocks until `MESH_RUN_EXPORT_RETENTION_REVIEWED=1` and the retention window is positive.

`scripts/purge_run_exports.py --state-dir ${MESH_STATE_DIR}` audits expired generated exports without deleting by default. Add `--apply` to delete only expired `run_exports/{run_id}.json` packages and matching `run_exports/{run_id}.zip` archives whose `retention.delete_after` has passed. The utility accepts `--json` for CI evidence and `--now` for rehearsal tests.

`scripts/verify_run_export_retrieval.py --package <run_exports/run_id.json> --archive <run_exports/run_id.zip> --json` verifies audit retrieval for a saved run export. It checks the package checksum, required records, redaction, retention metadata, Merkle proof, timeline proof, archive manifest, safe archive paths, and vault Markdown inclusion when vault documents are present.

`scripts/verify_run_export_upload.py --package <run_exports/run_id.json> --archive <run_exports/run_id.zip> --proof <run-export-upload-proof.json> --json` verifies durable storage proof for the same export. The proof schema is `mesh.run_export_upload_proof.v1`; it must include durable package and archive URIs, SHA-256 values, byte counts, provider receipts, restore-test evidence, and retention metadata inherited from the export package.

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

`config/threat-model.register.json` is the machine-readable private-staging threat-model register. `scripts/verify_threat_model_register.py --json` verifies `mesh.threat_model_register.v1` findings for owner, decision, expiry, compensating control, evidence refs, duplicate ids, open findings, and expired accepted findings.

Staging readiness now reports `threat_model_register_reviewed`. The default register covers the authority boundaries below and fails closed if any finding is open, expired, or missing required review metadata.

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

## Data Classification Policy

`config/data-classification.policy.json` is the machine-readable data-classification and deletion-control policy for private staging. `scripts/verify_data_classification_policy.py --json` verifies `mesh.data_classification_policy.v1` for required data classes, owner, retention, redaction, storage locations, deletion controls, and evidence refs.

Staging readiness now reports `data_classification_policy_reviewed`. The default policy covers operational signals, operator identity, secret material, model output, audit proof, training candidates, application logs, and distributed traces. It fails closed if mutable signal/log/trace/model/training data is marked retain-only, if secret material is exportable, or if review metadata is missing.

| Data class | Examples | Handling |
| --- | --- | --- |
| Operational signal | Kubernetes pods, OTel metrics, webhook labels | retain in run artifacts; redact secrets before export |
| Operator identity | operator id, roles, proxy source | retain with run and steering audit events |
| Secret material | tokens, kubeconfig, API keys, auth headers | do not store in run artifacts; redact if received |
| Model output | observer verdicts, proposal-lane artifacts | retain as advisory artifacts with source lane |
| Audit proof | events, Merkle roots, proofs | append-only; include in go/no-go and postmortem bundles |
| Training candidates | incident corpus rows, observations, claims | exclude audit-only rows unless explicitly labeled trainable |
| Application logs | structured runtime logs, access logs, error logs | retain in the deployment log system under reviewed retention; redact before export |
| Distributed traces | Phoenix spans, request traces, workflow spans | retain only in private trace systems under reviewed retention; do not export without approval |

## Agentic Operator Source Provenance

`config/agentic-operator-source.provenance.json` is the machine-readable source-input record for `agentic-operator-core-main/`. `scripts/verify_agentic_operator_source_provenance.py --json` verifies `mesh.agentic_operator_source_provenance.v1` for Apache-2.0 license presence, source snapshot hash, required source surfaces, no active runtime posture, no wholesale-copy permission, no comparative-claim permission, authority-gate adaptation requirements, forbidden credential classes, and empty imported paths before a fork gate.

Staging readiness now reports `agentic_operator_source_provenance_recorded`. The current imported tree has no nested `.git`, so the upstream source commit is not directly inspectable in this workspace. The provenance record marks that status explicitly as `unavailable_import_snapshot` and binds the source input to `source_snapshot_sha256`; actual CRD, controller, Helm, Argo, MCP, LiteLLM, or CLI forks remain blocked until adapted contracts and focused tests exist.

## Evaluation Kit Packet

`scripts/generate_evaluation_kit_packet.py --output-dir <evaluation-kit-dir> --json` creates a `mesh.evaluation_kit_packet.v1` handoff for private-staging evaluators. The packet contains a deterministic sample run id, saved run export package, zip archive, package and archive SHA-256 values, retrieval proof, benchmark suite, golden scenario ids, harness entrypoint, formal command, and expected benchmark artifacts.

`scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json` verifies the packet schema, reruns run-export retrieval checks, validates package and archive hashes, checks the benchmark harness and golden scenarios, and requires the expected `benchmark.json`, `scorecard.json`, `scenario-results.jsonl`, and `report.md` outputs in the benchmark packet.

`scripts/verify_benchmark_run_artifacts.py --run-dir <benchmark-run-dir> --json` verifies a completed benchmark directory after the packet's benchmark command runs. It checks required artifact presence, artifact hashes, benchmark/scorecard consistency, suite, expected scenario ids, scenario counts, pass-rate floor, unsafe-action ceiling, weighted-score floor, non-empty report, and absence of scenario errors.

This closes the local sample-export, benchmark-handoff, and benchmark-output-verification parts of the enterprise and developer evaluation kits. Target-environment sample exports, durable upload proof, and durable benchmark publication remain deployment-specific evidence.

## Benchmark Run Artifact Verification

`mesh.benchmark_run_artifacts_verification.v1` is the machine-readable verification packet emitted by `scripts/verify_benchmark_run_artifacts.py`.

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
- CI attestation path and hash;
- build command and builder identity;
- readiness profile and environment.

`scripts/generate_release_provenance.py` now emits `mesh.release_provenance.v1` packets. Local developer output is allowed to be `status: incomplete`; pilot release jobs must run with `--require-complete`.

Current local generation returns `status: incomplete` because this worktree is dirty and CI-only artifacts are absent:

- `clean_git_tree`;
- `image_digest`;
- `base_image_digests`;
- `sbom_path`;
- `vulnerability_scan_path`;
- `ci_attestation`;
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

- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_production_cut_list` passed with `22` tests after adding the ownership registry contract, staging readiness blocker, and run-level `ownership_boundary` artifact/event path;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_production_cut_list.ReadinessProfileTests` passed with `25` tests after extending the existing `ownership_boundary` contract with namespace, customer boundary, reservoir refs, export policy, retention, and legal-action scope. Evidence level: focused contract/API proof; remaining gap: customer-specific registry onboarding and live tenant-boundary rehearsal in Kubernetes;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_release_provenance tests.test_production_cut_list` passed with `27` tests after adding the policy lifecycle manifest, signed policy hash packet, `/api/policy/lifecycle`, release-provenance embedding, and readiness blocker;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_pipeline` passed with `19` tests after adding `stage_results.evidence_sufficiency` and the mutating-action insufficient-evidence blocker;
- `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list` passed with `14` tests after the evidence sufficiency gate was wired into evaluation;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_integrations tests.test_release_provenance tests.test_production_cut_list.ReadinessProfileTests` passed with `44` tests after adding the connector certification registry, `/api/connectors/certification`, readiness blocker, release-provenance embedding, and dirty-tree path parser fix;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_production_cut_list.ReadinessProfileTests tests.test_release_provenance` passed with `29` tests after adding structured connector credential boundaries and proposal-lane credential-bleed blockers. Evidence level: focused contract/API/release-packet proof; remaining gap: live Kubernetes service-account rotation evidence and break-glass recording rehearsal;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_production_cut_list.ReadinessProfileTests tests.test_release_provenance` passed with `26` tests after adding `mesh.timeline_proof.v1`, `/api/runs/{run_id}/timeline-proof`, run-export `timeline_proof`, and archive `timeline-proof.json`;
- `PYTHONPATH=. python3 -m unittest tests.test_contracts tests.test_production_cut_list.ReadinessProfileTests tests.test_control_plane_resource_lifecycle` passed with `35` tests after adding `mesh.run_admission.v1`, tenant active-run quota config, run admission events/artifacts, and live target-lock admission blockers;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `3` tests after making `scripts/generate_release_provenance.py --json` runnable without `PYTHONPATH`;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `3` tests after adding CI attestation path/hash/provider metadata to `mesh.release_provenance.v1`. Evidence level: focused release-packet contract proof; remaining gap: CI must provide the real attestation artifact together with image digest, base-image digests, SBOM, vulnerability scan, clean tree, and build command;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `4` tests after adding `scripts/generate_ci_attestation.py` and wiring `.github/workflows/ci.yml` to upload `dist/ci-attestation.json` from the `docker-build` job. Evidence level: focused script/workflow contract proof; remaining gap: live GitHub Actions run artifact is still required;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `5` tests after allowing `mesh.release_provenance.v1` to consume `image.digest` and `build.command` from `mesh.ci_attestation.v1` when explicit release CLI args are absent. Evidence level: focused release-packet contract proof; remaining gap: CI must supply real digest-bearing attestation plus SBOM and vulnerability scan artifacts;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `5` tests after extending `mesh.ci_attestation.v1` with `build.base_images[]` and allowing `mesh.release_provenance.v1` to consume attested base-image digests when explicit release CLI args are absent. Evidence level: focused release-packet contract proof; remaining gap: CI must supply real digest-bearing attestation plus SBOM and vulnerability scan artifacts;
- `PYTHONPATH=. python3 -m unittest tests.test_release_provenance` passed with `6` tests after tightening `mesh.release_provenance.v1` so SBOM artifacts must be CycloneDX JSON and vulnerability scan artifacts must include scanner identity with no high or critical findings. Evidence level: focused release-packet contract proof; remaining gap: CI must supply real SBOM and vulnerability scan artifacts generated from the release image;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `9` tests after adding `scripts/normalize_release_assurance_artifacts.py` to convert raw CycloneDX, OSV, npm audit, Grype, or already-normalized scan output into release-provenance-compatible SBOM and vulnerability scan artifacts. Evidence level: focused artifact-normalization proof; remaining gap: CI must run real release-image scanners and feed their raw output into the normalizer;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `11` tests after adding `scripts/generate_release_assurance_rehearsal_inputs.py` and wiring CI to upload `release-assurance-contract-rehearsal`. Evidence level: CI handoff contract rehearsal; remaining gap: this artifact is synthetic and must not be used as pilot SBOM or vulnerability scan evidence;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `12` tests after making release provenance reject `release-assurance-rehearsal` SBOM and vulnerability scan artifacts for pilot completeness. Evidence level: focused release-packet guard proof; remaining gap: CI must supply real release-image scanner output;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `13` tests after making `ci_attestation` require `mesh.ci_attestation.v1`, a matching `attestation_sha256`, and passed `python-test`, `web`, and `docker-build` checks before release provenance trusts attested image digest, build command, or base-image digests. Evidence level: focused release-packet guard proof; remaining gap: live GitHub Actions must publish the real attestation artifact for the release image;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `14` tests after making `ci_attestation` require `provider: "github-actions"` plus non-empty `workflow`, `job`, `run_id`, and `sha` metadata before release provenance trusts attested image digest, build command, or base-image digests. Evidence level: focused release-packet guard proof; remaining gap: live GitHub Actions must publish the real attestation artifact for the release image;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `15` tests after adding `--require-github-actions` to `scripts/generate_ci_attestation.py` and the CI docker-build job. Evidence level: focused generator/workflow contract proof; remaining gap: live GitHub Actions must publish the real digest-bearing attestation artifact for the release image;
- `PYTHONPATH=. python3 -m unittest tests.test_perennial_materialization tests.test_production_cut_list tests.test_darkharness_live_verifier tests.test_darkharness_export_path` passed with `37` tests after making pilot/expansion go/no-go require a complete `MESH_RELEASE_PROVENANCE_PATH` packet and fixing Perennial action materialization so structured ownership-boundary payloads cannot replace the `data_boundary` enum. Evidence level: focused API/proof-chain contract proof; remaining gap: a real CI release job must generate and mount the complete release packet for pilot capture;
- `PYTHONPATH=. python3 -m unittest tests.test_release_assurance_artifacts tests.test_release_provenance` passed with `16` tests after making normalized SBOM and vulnerability scan artifacts carry `MESH_IMAGE_DIGEST` and making release provenance reject artifacts whose recorded digest does not match the release image digest. Evidence level: focused release-artifact binding proof; remaining gap: CI must run real release-image scanners and pass the real image digest into the normalizer;
- `PYTHONPATH=. python3 -m unittest tests.test_audit_sink_contract tests.test_contracts tests.test_production_cut_list.ReadinessProfileTests` passed with `30` tests after adding `mesh.audit_sink_proof.v1`, `scripts/verify_audit_sink_contract.py`, `MESH_AUDIT_SINK_PROOF_PATH`, expansion readiness blocker `external_audit_sink_contract_verified`, and compose/doc/cut-list markers for the external audit sink contract. Files changed: `shared/mesh_runtime/audit_sink.py`, `shared/mesh_runtime/schemas/audit-sink-proof.schema.json`, `scripts/verify_audit_sink_contract.py`, `shared/mesh_runtime/config.py`, `shared/mesh_runtime/integrations.py`, compose files, docs, and focused tests. Evidence level: focused contract/readiness proof; remaining gap: real external sink deployment must emit a reviewed proof packet, and `config/connector-certification.registry.json` still caps `audit_sink` at `mock` until certification is approved;
- `PYTHONPATH=. python3 -m unittest tests.test_credential_rotation tests.test_audit_sink_contract tests.test_contracts` passed with `27` tests after adding `mesh.credential_rotation_proof.v1` and `scripts/verify_credential_rotation.py` to verify service-account rotation evidence against `config/connector-certification.registry.json`. Files changed: `shared/mesh_runtime/credential_rotation.py`, `shared/mesh_runtime/schemas/credential-rotation-proof.schema.json`, `scripts/verify_credential_rotation.py`, `shared/mesh_runtime/__init__.py`, docs, cut-list guard, and focused tests. Evidence level: focused credential-boundary proof; remaining gap: real pilot connectors must produce proof packets from deployed secret stores, and this verifier does not rotate credentials by itself;
- `PYTHONPATH=. python3 -m unittest tests.test_run_export_retrieval tests.test_run_export_retention tests.test_production_cut_list.RunExportPackageTests` passed with `8` tests after adding `mesh.run_export_retrieval.v1`, `scripts/verify_run_export_retrieval.py`, cut-list markers, and fixing archive generation so redacted vault Markdown files are actually included instead of being skipped by unreachable code. Files changed: `shared/mesh_runtime/run_export_retrieval.py`, `shared/mesh_runtime/schemas/run-export-retrieval.schema.json`, `scripts/verify_run_export_retrieval.py`, `services/control_plane.py`, `shared/mesh_runtime/__init__.py`, docs, and focused tests. Evidence level: focused audit-retrieval proof; remaining gap: run export archives still need durable external storage upload and restore rehearsal in the target pilot environment;
- `PYTHONPATH=. python3 -m unittest tests.test_run_export_upload tests.test_run_export_retrieval tests.test_run_export_retention` passed with `10` tests after adding `mesh.run_export_upload_proof.v1` and `scripts/verify_run_export_upload.py` to verify durable package/archive upload receipts against local export hashes and retrieval proof. Files changed: `shared/mesh_runtime/run_export_upload.py`, `shared/mesh_runtime/schemas/run-export-upload-proof.schema.json`, `scripts/verify_run_export_upload.py`, `shared/mesh_runtime/__init__.py`, `scripts/verify_release_cut_list.py`, docs, and focused tests. Evidence level: focused durable-export upload proof; remaining gap: target pilot storage must produce real upload proof manifests and execute a restore test from the uploaded blobs;
- `PYTHONPATH=. python3 -m unittest tests.test_pilot_signoff tests.test_production_cut_list.PilotGoNoGoMeshBrainGateTests` passed with `7` tests after adding `mesh.pilot_signoff.v1` and `scripts/verify_pilot_signoff.py` to build and verify signed operator approval over the captured `pilot.go_no_go.v1` packet and complete release-provenance hash. Files changed: `shared/mesh_runtime/pilot_signoff.py`, `shared/mesh_runtime/schemas/pilot-signoff.schema.json`, `scripts/verify_pilot_signoff.py`, `shared/mesh_runtime/__init__.py`, `scripts/verify_release_cut_list.py`, docs, and focused tests. Evidence level: focused signoff-contract proof; remaining gap: target pilot operations must run the build and verify commands with a secret-store-backed HMAC key after capturing the live go/no-go packet;
- `PYTHONPATH=. python3 -m unittest tests.test_operator_handoff tests.test_production_cut_list.OperatorRoleApiTests` passed with `4` tests after adding `mesh.operator_handoff.v1`, `command: "handoff"` on the existing steering API, `operator_handoff_recorded` events, and run-export/archive handoff records. Files changed: `shared/mesh_runtime/operator_handoff.py`, `shared/mesh_runtime/schemas/operator-handoff.schema.json`, `shared/mesh_runtime/run_events.py`, `shared/mesh_runtime/__init__.py`, `services/control_plane.py`, docs, cut-list guard, and focused tests. Evidence level: focused API/export contract proof; remaining gap: target pilot operators still need to execute real handoff drills across named shifts and review exported handoffs during postmortem review;
- `PYTHONPATH=. python3 -m unittest tests.test_postmortem_review tests.test_production_cut_list.RunExportPackageTests` passed with `5` tests after adding `mesh.postmortem_review.v1`, terminal-stage `command: "postmortem_review"`, independent-reviewer enforcement when launch identity is known, `postmortem_review_recorded` events, and run-export/archive review records. Files changed: `shared/mesh_runtime/postmortem_review.py`, `shared/mesh_runtime/schemas/postmortem-review.schema.json`, `shared/mesh_runtime/run_events.py`, `shared/mesh_runtime/__init__.py`, `control_plane_server.py`, `services/control_plane.py`, docs, cut-list guard, and focused tests. Evidence level: focused postmortem-review contract proof; remaining gap: target pilot operators still need to run a real independent postmortem review drill over a live exported run package;
- `PYTHONPATH=. python3 -m unittest tests.test_override_review tests.test_production_cut_list.RunExportPackageTests` passed with `6` tests after adding `mesh.override_review.v1`, terminal-stage `command: "override_review"`, independent-reviewer enforcement when override operator identity is known, `override_review_recorded` events, and run-export/archive override review records. Files changed: `shared/mesh_runtime/override_review.py`, `shared/mesh_runtime/schemas/override-review.schema.json`, `shared/mesh_runtime/run_events.py`, `shared/mesh_runtime/__init__.py`, `control_plane_server.py`, `services/control_plane.py`, docs, cut-list guard, and focused tests. Evidence level: focused override-review contract proof; remaining gap: target pilot operators still need to run a real override intervention and independent override review drill over the exported run package;
- `PYTHONPATH=. python3 -m unittest tests.test_backup_restore_rehearsal tests.test_production_cut_list.ReadinessProfileTests tests.test_production_cut_list.ProductionComposeContractTests` passed with `13` tests after adding `mesh.backup_restore_rehearsal.v1`, `scripts/verify_backup_restore_rehearsal.py`, staging readiness blocker `backup_restore_rehearsal_verified`, and compose/cut-list markers for restore proof. Files changed: `shared/mesh_runtime/backup_restore.py`, `shared/mesh_runtime/schemas/backup-restore-rehearsal.schema.json`, `scripts/verify_backup_restore_rehearsal.py`, `shared/mesh_runtime/config.py`, `shared/mesh_runtime/integrations.py`, compose files, docs, cut-list guard, and focused tests. Evidence level: focused backup/restore contract proof; remaining gap: target private-staging operators still need to produce a proof packet from a real restore rehearsal over deployed state, vault, Merkle, integrations, and research artifacts;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/backup_restore.py shared/mesh_runtime/config.py shared/mesh_runtime/integrations.py shared/mesh_runtime/__init__.py scripts/verify_backup_restore_rehearsal.py scripts/verify_release_cut_list.py tests/test_backup_restore_rehearsal.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the backup/restore rehearsal slice;
- `PYTHONPATH=. python3 -m unittest tests.test_migration_rehearsal tests.test_release_provenance tests.test_production_cut_list.ProductionComposeContractTests` passed with `15` tests after adding `mesh.migration_rehearsal.v1`, `scripts/verify_migration_rehearsal.py`, release-provenance `migration_rehearsal` completeness gating, and compose/cut-list markers. Files changed: `shared/mesh_runtime/migration_rehearsal.py`, `shared/mesh_runtime/schemas/migration-rehearsal.schema.json`, `scripts/verify_migration_rehearsal.py`, `scripts/generate_release_provenance.py`, compose files, docs, cut-list guard, and focused tests. Evidence level: focused migration-rehearsal release-gate proof; remaining gap: target CI/pilot operators still need to run a real Postgres migration rehearsal and pass the proof path into the signed release packet;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/migration_rehearsal.py shared/mesh_runtime/__init__.py scripts/verify_migration_rehearsal.py scripts/generate_release_provenance.py scripts/verify_release_cut_list.py tests/test_migration_rehearsal.py tests/test_release_provenance.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the migration-rehearsal release-gate slice;
- `PYTHONPATH=. python3 -m unittest tests.test_on_call_drill tests.test_production_cut_list.PilotGoNoGoMeshBrainGateTests tests.test_production_cut_list.ProductionComposeContractTests tests.test_mesh_runtime_config` passed with `21` tests after adding `mesh.on_call_drill.v1`, `scripts/verify_on_call_drill.py`, pilot go/no-go `on_call_drill_verified`, config path resolution, and compose/cut-list markers. Files changed: `shared/mesh_runtime/on_call_drill.py`, `shared/mesh_runtime/schemas/on-call-drill.schema.json`, `scripts/verify_on_call_drill.py`, `services/control_plane.py`, `shared/mesh_runtime/config.py`, `shared/mesh_runtime/__init__.py`, compose files, docs, cut-list guard, and focused tests. Evidence level: focused on-call drill proof contract; remaining gap: target pilot operators still need to execute the real kill-switch, watcher-pause, bad-target revocation, provider-key rotation, failed-dependency, stuck-run, and restore drill and mount the proof at `MESH_ON_CALL_DRILL_PATH`;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/on_call_drill.py shared/mesh_runtime/config.py shared/mesh_runtime/__init__.py services/control_plane.py scripts/verify_on_call_drill.py scripts/verify_release_cut_list.py tests/test_on_call_drill.py tests/test_production_cut_list.py tests/test_mesh_runtime_config.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the on-call drill go/no-go slice;
- `PYTHONPATH=. python3 -m unittest tests.test_failure_mode_library tests.test_production_cut_list.ReadinessProfileTests tests.test_production_cut_list.ProductionComposeContractTests tests.test_mesh_runtime_config` passed with `29` tests after adding `mesh.failure_mode_library.v1`, `scripts/verify_failure_mode_library.py`, staging readiness `failure_mode_library_configured`, config path resolution, and compose/cut-list markers. Files changed: `config/failure-mode.library.json`, `shared/mesh_runtime/failure_modes.py`, `shared/mesh_runtime/schemas/failure-mode-library.schema.json`, `shared/mesh_runtime/schemas/failure-mode-library-packet.schema.json`, `scripts/verify_failure_mode_library.py`, `shared/mesh_runtime/config.py`, `shared/mesh_runtime/integrations.py`, `shared/mesh_runtime/__init__.py`, compose files, docs, cut-list guard, and focused tests. Evidence level: focused failure-mode catalog contract; remaining gap: browser replay automation and target-environment live fault evidence are still required before calling replay coverage production-validated;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/failure_modes.py shared/mesh_runtime/config.py shared/mesh_runtime/integrations.py shared/mesh_runtime/__init__.py scripts/verify_failure_mode_library.py scripts/verify_release_cut_list.py tests/test_failure_mode_library.py tests/test_production_cut_list.py tests/test_mesh_runtime_config.py` passed after the failure-mode library readiness slice;
- `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the failure-mode library readiness slice;
- `PYTHONPATH=. python3 -m unittest tests.test_failure_mode_library tests.test_production_cut_list.OperatorRoleApiTests` passed with `6` tests after adding read-only `GET /api/failure-modes` exposure for the verified failure-mode catalog entries. Files changed: `control_plane_server.py`, `services/control_plane.py`, `shared/mesh_runtime/failure_modes.py`, `shared/mesh_runtime/schemas/failure-mode-library-packet.schema.json`, docs, cut-list guard, and focused tests. Evidence level: focused read-only API contract; remaining gap: browser replay automation and target-environment live fault evidence are still required;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/failure_modes.py services/control_plane.py control_plane_server.py scripts/verify_release_cut_list.py tests/test_failure_mode_library.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the failure-mode catalog API slice;
- `PYTHONPATH=. python3 -m unittest tests.test_watcher_ownership tests.test_watcher_registry` passed with `13` tests and `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list.OperatorRoleApiTests` passed with `1` localhost-bound API test after adding `mesh.watcher_ownership.v1`, `GET /api/watchers/ownership`, embedded watcher ownership on `/api/watchers`, and Fleet watcher owner/escalation rendering. Files changed: `shared/mesh_runtime/watcher_ownership.py`, `shared/mesh_runtime/schemas/watcher-ownership.schema.json`, `control_plane_server.py`, `services/control_plane.py`, `shared/mesh_runtime/__init__.py`, `web/src/App.tsx`, `web/src/types.ts`, docs, cut-list guard, and focused tests. Evidence level: focused watcher ownership API/UI contract; remaining gap: target private-staging runs must still prove at least one Kubernetes watcher path and one webhook or OTel path create real runs;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/watcher_ownership.py shared/mesh_runtime/__init__.py services/control_plane.py control_plane_server.py scripts/verify_release_cut_list.py tests/test_watcher_ownership.py tests/test_production_cut_list.py`, `npm --prefix web run lint`, `npm --prefix web run build`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the watcher ownership slice;
- `PYTHONPATH=. python3 -m unittest tests.test_mesh_runtime_config tests.test_prod_hardening` passed with `21` tests after adding the config field and readiness cache key;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/connector_certification.py shared/mesh_runtime/integrations.py shared/mesh_runtime/config.py shared/mesh_runtime/__init__.py services/control_plane.py control_plane_server.py scripts/generate_release_provenance.py scripts/verify_release_cut_list.py tests/test_contracts.py tests/test_integrations.py tests/test_release_provenance.py tests/test_production_cut_list.py` passed;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/timeline_proof.py shared/mesh_runtime/connector_certification.py shared/mesh_runtime/integrations.py shared/mesh_runtime/config.py shared/mesh_runtime/__init__.py services/control_plane.py control_plane_server.py scripts/verify_release_cut_list.py tests/test_contracts.py tests/test_production_cut_list.py tests/test_release_provenance.py` passed;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/connector_certification.py tests/test_contracts.py scripts/verify_release_cut_list.py` passed after adding connector credential-boundary enforcement;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/run_admission.py shared/mesh_runtime/config.py shared/mesh_runtime/__init__.py shared/mesh_runtime/run_events.py services/control_plane.py scripts/verify_release_cut_list.py tests/test_contracts.py tests/test_production_cut_list.py` passed;
- `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/ownership.py services/control_plane.py scripts/verify_release_cut_list.py tests/test_contracts.py tests/test_production_cut_list.py` passed after the tenant-boundary contract tightening;
- `npm run lint` passed after the ownership, connector certification, policy lifecycle, and evidence sufficiency schema/API contract changes;
- `npm run lint` passed after the tenant-boundary and connector credential-boundary tightening;
- `npm --prefix web run build` passed after the accumulated web/API contract changes; Vite reported the existing large chunk warning for `index-*.js`;
- `docker compose -f docker-compose.stack.yml config --quiet` passed;
- `env MESH_DATABASE_URL=postgresql://mesh:mesh@postgres:5432/mesh MESH_PROMETHEUS_URL=http://prometheus.local MESH_BRAIN_ARTIFACT_URI_PREFIX=s3://mesh-prod-artifacts/mesh-brain MESH_BRAIN_SERVING_BASE_URL=http://mesh-brain-serving.private:8000 MESH_BRAIN_SERVING_MODEL=nvidia/nemotron-3-nano-4b MESH_KUBERNETES_ALLOWED_CONTEXTS=mesh-compose MESH_KUBERNETES_ALLOWED_NAMESPACES=search MESH_KUBECONFIG_HOST_PATH=/tmp/kubeconfig MESH_POLICY_SIGNING_KEY=test-policy-signing-key OPENAI_API_KEY=dummy docker compose -f docker-compose.prod.yml config --quiet` passed;
- `python3 scripts/generate_release_provenance.py --json` returned `status: incomplete` with `connector_certification_registry: true` and missing CI/release gates for clean tree, image digest, base-image digests, signed policy lifecycle, SBOM, vulnerability scan, and build command;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json` returned `status: incomplete` with `policy_lifecycle_signed: true` and remaining missing gates for clean tree, image digest, base-image digests, SBOM, vulnerability scan, CI attestation, and build command;
- `python3 scripts/generate_ci_attestation.py --output /tmp/orbital-mesh-ci-attestation.json --check python-test --check web --check docker-build --image-tag orbital-mesh:ci --image-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --build-command "docker build -t orbital-mesh:ci ."` emitted `mesh.ci_attestation.v1` with a 64-character `attestation_sha256`;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --ci-attestation /tmp/orbital-mesh-ci-attestation.json` returned `status: incomplete` with `ci_attestation: true`; remaining missing gates were clean tree, image digest, base-image digests, SBOM, vulnerability scan, and build command;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --ci-attestation /tmp/orbital-mesh-ci-attestation.json` returned `status: incomplete` with `ci_attestation`, `image_digest`, and `build_command` true from the attestation; remaining missing gates were clean tree, base-image digests, SBOM, and vulnerability scan;
- `python3 scripts/generate_ci_attestation.py --output /tmp/orbital-mesh-ci-attestation.json --check python-test --check web --check docker-build --image-tag orbital-mesh:ci --image-digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --base-image-digest node:22-bookworm-slim=sha256:0000000000000000000000000000000000000000000000000000000000000001 --base-image-digest debian:12-slim=sha256:0000000000000000000000000000000000000000000000000000000000000002 --base-image-digest rust:1.92-slim-bookworm=sha256:0000000000000000000000000000000000000000000000000000000000000003 --base-image-digest python:3.12-slim-bookworm=sha256:0000000000000000000000000000000000000000000000000000000000000004 --base-image-digest python:3.11-slim-bookworm=sha256:0000000000000000000000000000000000000000000000000000000000000005 --build-command "docker build -t orbital-mesh:ci ."` emitted `mesh.ci_attestation.v1` with attested `image.digest`, `build.command`, and five base-image digests;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --ci-attestation /tmp/orbital-mesh-ci-attestation.json` returned `status: incomplete` with `ci_attestation`, `image_digest`, `build_command`, `base_image_digests`, and `policy_lifecycle_signed` true from local inputs; remaining missing gates were clean tree, SBOM, and vulnerability scan;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --require-complete --allow-dirty --ci-attestation /tmp/orbital-mesh-ci-attestation.json --sbom /tmp/orbital-mesh-sbom.json --vulnerability-scan /tmp/orbital-mesh-vulnerability-scan.json` returned `status: complete` with synthetic CycloneDX SBOM and normalized vulnerability scan fixtures. Evidence level: local release-packet rehearsal only; `--allow-dirty` and synthetic artifacts are not valid for pilot signing;
- `python3 scripts/normalize_release_assurance_artifacts.py --sbom-input /tmp/orbital-mesh-sbom.json --scan-input /tmp/orbital-mesh-vulnerability-scan.json --scanner normalized-test --output-dir /tmp/orbital-mesh-release-assurance --require-scan --fail-on-blocking` returned `mesh.release_assurance_artifact_normalization.v1` with `status: complete`, `finding_count: 0`, and `blocking_finding_count: 0`;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --require-complete --allow-dirty --ci-attestation /tmp/orbital-mesh-ci-attestation.json --sbom /tmp/orbital-mesh-release-assurance/sbom.cdx.json --vulnerability-scan /tmp/orbital-mesh-release-assurance/vulnerability-scan.json` returned `status: complete` against the normalized local fixtures. Evidence level: local release-packet rehearsal only; `--allow-dirty` and synthetic scanner inputs are not valid for pilot signing;
- `python3 scripts/generate_release_assurance_rehearsal_inputs.py --output-dir /tmp/orbital-mesh-release-assurance-rehearsal-raw --component-version local-test` returned `mesh.release_assurance_rehearsal_inputs.v1` with raw CycloneDX and empty vulnerability-scan fixtures;
- `python3 scripts/normalize_release_assurance_artifacts.py --sbom-input /tmp/orbital-mesh-release-assurance-rehearsal-raw/raw-sbom.cdx.json --scan-input /tmp/orbital-mesh-release-assurance-rehearsal-raw/raw-vulnerability-scan.json --scanner release-assurance-rehearsal --output-dir /tmp/orbital-mesh-release-assurance-rehearsal --require-scan --fail-on-blocking` returned `mesh.release_assurance_artifact_normalization.v1` with `status: complete`, `finding_count: 0`, and `blocking_finding_count: 0`;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --allow-dirty --ci-attestation /tmp/orbital-mesh-ci-attestation.json --sbom /tmp/orbital-mesh-release-assurance-rehearsal/sbom.cdx.json --vulnerability-scan /tmp/orbital-mesh-release-assurance-rehearsal/vulnerability-scan.json` returned `status: incomplete`; `sbom_path` and `vulnerability_scan_path` were false with missing reasons `real_release_image_sbom` and `real_release_image_vulnerability_scan`;
- `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --require-complete --allow-dirty --ci-attestation /tmp/orbital-mesh-ci-attestation.json --sbom /tmp/orbital-mesh-release-assurance/sbom.cdx.json --vulnerability-scan /tmp/orbital-mesh-release-assurance/vulnerability-scan.json` returned `status: complete` against local fixtures with `ci_attestation: true`, `hash_valid: true`, and passed checks `docker-build`, `python-test`, and `web`. Evidence level: local release-packet rehearsal only; `--allow-dirty` and synthetic scanner inputs are not valid for pilot signing;
- `python3 scripts/verify_release_cut_list.py --json` returned `status: pass`;
- `git diff --check` passed;
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
- `python3 scripts/verify_threat_model_register.py --json` returned `status: pass` with 9 accepted findings, 0 open findings, 0 expired findings, and no missing review metadata after adding `mesh.threat_model_register.v1`, `config/threat-model.register.json`, `shared/mesh_runtime/threat_model.py`, `shared/mesh_runtime/schemas/threat-model-register.schema.json`, `scripts/verify_threat_model_register.py`, `MESH_THREAT_MODEL_REGISTER_PATH`, and staging readiness gate `threat_model_register_reviewed`. Files changed: threat-model register/config/schema/verifier, runtime config, readiness integrations, compose files, docs, cut-list guard, and focused tests. Evidence level: focused threat-model register/readiness contract; remaining gap: target staging operators must still perform deployment-specific abuse-case review and update, accept, or fix findings with real environment evidence before external exposure;
- `PYTHONPATH=. python3 -m unittest tests.test_threat_model_register tests.test_mesh_runtime_config tests.test_production_cut_list.ReadinessProfileTests` passed with `28` tests, `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/threat_model.py shared/mesh_runtime/config.py shared/mesh_runtime/integrations.py shared/mesh_runtime/__init__.py scripts/verify_threat_model_register.py scripts/verify_release_cut_list.py tests/test_threat_model_register.py tests/test_mesh_runtime_config.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the threat-model register slice;
- `python3 scripts/verify_data_classification_policy.py --json` returned `status: pass` with 8 covered classes, 0 missing classes, 0 duplicate ids, no secret export, and no missing deletion controls after adding `mesh.data_classification_policy.v1`, `config/data-classification.policy.json`, `shared/mesh_runtime/data_classification.py`, `shared/mesh_runtime/schemas/data-classification-policy.schema.json`, `scripts/verify_data_classification_policy.py`, `MESH_DATA_CLASSIFICATION_POLICY_PATH`, and staging readiness gate `data_classification_policy_reviewed`. Files changed: data-classification policy/schema/verifier, runtime config, readiness integrations, compose files, docs, cut-list guard, and focused tests. Evidence level: focused data-classification/readiness contract; remaining gap: target staging operators must still prove deletion execution for deployment log and trace systems and reviewed storage backends before external exposure;
- `PYTHONPATH=. python3 -m unittest tests.test_data_classification tests.test_mesh_runtime_config tests.test_production_cut_list.ReadinessProfileTests` passed with `31` tests, `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/data_classification.py shared/mesh_runtime/config.py shared/mesh_runtime/integrations.py shared/mesh_runtime/__init__.py scripts/verify_data_classification_policy.py scripts/verify_release_cut_list.py tests/test_data_classification.py tests/test_mesh_runtime_config.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the data-classification policy slice;
- `python3 scripts/verify_agentic_operator_source_provenance.py --json` returned `status: pass` with 13 source paths, Apache-2.0 license verified, source snapshot hash matched, no copied paths, no missing authority gates, and no missing forbidden credential classes after adding `mesh.agentic_operator_source_provenance.v1`, `config/agentic-operator-source.provenance.json`, `shared/mesh_runtime/agentic_operator_provenance.py`, `shared/mesh_runtime/schemas/agentic-operator-source-provenance.schema.json`, `scripts/verify_agentic_operator_source_provenance.py`, `MESH_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH`, and staging readiness gate `agentic_operator_source_provenance_recorded`. Files changed: source-provenance manifest/schema/verifier, runtime config, readiness integrations, compose files, docs, cut-list guard, and focused tests. Evidence level: focused source-input provenance/readiness contract; remaining gap: the imported source tree has no nested git metadata, so upstream source commit remains unavailable in this workspace and actual CRD/controller/Helm/Argo/MCP/LiteLLM/CLI forks remain blocked until adapted contracts and focused tests exist;
- `PYTHONPATH=. python3 -m unittest tests.test_agentic_operator_provenance tests.test_mesh_runtime_config tests.test_production_cut_list.ReadinessProfileTests` passed with `32` tests, `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/agentic_operator_provenance.py shared/mesh_runtime/config.py shared/mesh_runtime/integrations.py shared/mesh_runtime/__init__.py scripts/verify_agentic_operator_source_provenance.py scripts/verify_release_cut_list.py tests/test_agentic_operator_provenance.py tests/test_mesh_runtime_config.py tests/test_production_cut_list.py`, `./scripts/verify_release_cut_list.py --json`, `docker compose -f docker-compose.stack.yml config`, and `git diff --check` passed after the agentic-operator source provenance slice;
- `python3 scripts/generate_evaluation_kit_packet.py --output-dir /tmp/orbital-mesh-evaluation-kit --json` returned `status: complete` and embedded `mesh.evaluation_kit_packet_verification.v1` with `status: pass` for sample run `run_20260506T004050_3580ffdf`. The packet includes a generated run export package, zip archive, retrieval proof, package/archive SHA-256 checks, golden benchmark scenario ids, formal `python3 -m services.benchmark run --suite golden ...` command, harness entrypoint, and expected benchmark artifact list. Files changed: `shared/mesh_runtime/evaluation_kit.py`, `shared/mesh_runtime/schemas/evaluation-kit-packet.schema.json`, `shared/mesh_runtime/__init__.py`, `scripts/generate_evaluation_kit_packet.py`, `scripts/verify_evaluation_kit_packet.py`, `tests/test_evaluation_kit_packet.py`, release cut-list guard, and evaluation-kit docs. Evidence level: focused evaluation-kit packet and sample-export contract; remaining gap: target-environment sample exports, durable upload proof, and actual benchmark output artifacts remain deployment-specific evidence;
- `PYTHONPATH=. python3 -m unittest tests.test_evaluation_kit_packet` passed with `2` tests, `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/evaluation_kit.py shared/mesh_runtime/__init__.py scripts/generate_evaluation_kit_packet.py scripts/verify_evaluation_kit_packet.py scripts/verify_release_cut_list.py tests/test_evaluation_kit_packet.py`, and `./scripts/verify_release_cut_list.py --json` passed after the evaluation-kit packet slice;
- `python3 -m services.benchmark run --suite golden --scenario-id feature_flag_latency_disable --scenario-id kubernetes_crashloop_patch --runtime-state-mode none --output /tmp/orbital-mesh-evaluation-kit/benchmark-runs` passed after replacing Python 3.11-only `datetime.UTC` usage in the benchmark harness with `timezone.utc`. It produced benchmark run `bench_20260506T004243847690Z`, score `93.75`, `pass_rate: 1.0`, and `unsafe_action_rate: 0.0`;
- `python3 scripts/verify_benchmark_run_artifacts.py --run-dir /tmp/orbital-mesh-evaluation-kit/benchmark-runs/bench_20260506T004243847690Z --expected-suite golden --expected-scenario-id feature_flag_latency_disable --expected-scenario-id kubernetes_crashloop_patch --min-pass-rate 1 --max-unsafe-action-rate 0 --json` returned `mesh.benchmark_run_artifacts_verification.v1` with `status: pass`, all artifact hashes, and no blockers. Files changed: `shared/mesh_runtime/benchmark_artifacts.py`, `shared/mesh_runtime/schemas/benchmark-run-artifacts-verification.schema.json`, `scripts/verify_benchmark_run_artifacts.py`, `services/benchmark/runner.py`, `services/benchmark/loghub.py`, `shared/mesh_runtime/__init__.py`, `tests/test_benchmark_run_artifacts.py`, docs, and cut-list guard. Evidence level: focused benchmark-output artifact proof; remaining gap: target environments still need durable benchmark publication and any customer-specific benchmark corpus evidence;
- `PYTHONPATH=. python3 -m unittest tests.test_benchmark_run_artifacts tests.test_benchmark_harness.BenchmarkHarnessTest.test_runtime_state_mode_can_skip_persisted_state_artifacts tests.test_benchmark_harness.BenchmarkHarnessTest.test_benchmark_run_writes_scorecard_and_report` passed with `4` tests, `RUFF_CACHE_DIR=/tmp/ruff-cache ruff check shared/mesh_runtime/benchmark_artifacts.py shared/mesh_runtime/__init__.py services/benchmark/runner.py services/benchmark/loghub.py scripts/verify_benchmark_run_artifacts.py scripts/verify_release_cut_list.py tests/test_benchmark_run_artifacts.py tests/test_benchmark_harness.py`, `./scripts/verify_release_cut_list.py --json`, and `git diff --check` passed after the benchmark-output artifact verification slice;
- `npm --prefix web run lint`, `npm --prefix web run build`, and `./scripts/e2e_ui_operator.sh` passed after wiring the browser Connectors page to `/api/connectors/certification` and asserting Kubernetes authority posture, runtime-secret credential mode, service-account boundary, and allowed scopes in the operator UI. Evidence level: focused browser/API integration proof; remaining gap: target private-staging operators still need live connector credential rotation and break-glass rehearsal evidence;
- `python3 scripts/generate_migration_rehearsal.py --output /tmp/orbital-mesh-migration-rehearsal.json --operator-id local-rehearsal --environment staging --applied-migration-count 5 --rolled-back --rollback-ref restore://postgres/migration-rehearsal/local --pre-migration-snapshot-ref snapshot://postgres/pre-migration/local --post-migration-validation-ref validation://postgres/post-migration/local --destructive-changes-reviewed --measured-apply-seconds 12.5 --measured-rollback-seconds 18.25 --json` generated `mesh.migration_rehearsal.v1` bound to migration version `004_incident_corpus` and the current combined migration hash. `python3 scripts/verify_migration_rehearsal.py --proof /tmp/orbital-mesh-migration-rehearsal.json --expected-version 004_incident_corpus --expected-combined-sha256 998d0a00b6dc1c7317d895f47b3ce45a0ae2fe38ec741314826483180fc4d9ee --json` passed, and `python3 scripts/generate_release_provenance.py --json --migration-rehearsal /tmp/orbital-mesh-migration-rehearsal.json` set `migration_rehearsal: true` while leaving the hard CI/image/SBOM/signature/clean-tree gates incomplete. Files changed: migration rehearsal runtime helper, generator script, cut-list guard, docs, and focused tests. Evidence level: focused proof-generation and release-packet wiring proof; remaining gap: target CI/pilot operators must replace the local refs with proof refs from a real Postgres rehearsal before signing a pilot release packet;
- `.github/workflows/ci.yml` now runs `scripts/collect_release_image_metadata.py` after building `orbital-mesh:ci`, feeds `MESH_IMAGE_DIGEST` and base-image digest args into `scripts/generate_ci_attestation.py`, generates `dist/release-provenance-draft.json`, and uploads `release-provenance-draft` alongside `ci-attestation`. Files changed: CI workflow, release image metadata collector, cut-list guard, docs, and focused tests. Evidence level: static CI handoff and local unit proof; remaining gap: a live GitHub Actions run must publish the real artifacts, and the release provenance draft remains incomplete until real release-image SBOM/vulnerability scan, target migration proof, signed policy key, and clean release tree are present;
- `docker build --build-arg MESH_BUILD_VERSION=ci-local --build-arg MESH_BUILD_COMMIT=0056fd18c052c07fe98ac65395a60733e698d621 -t orbital-mesh:ci .` passed and produced local image id `sha256:a69cc228101e6970b4c924cbd47369ca50c6b7475b386b253a72a1542322b16f`. `scripts/collect_release_image_metadata.py --image-tag orbital-mesh:ci --output /tmp/orbital-mesh-release-image-metadata.json --base-image-args /tmp/orbital-mesh-base-image-digest.args` then produced base-image digests for all referenced Dockerfile bases. `MESH_POLICY_SIGNING_KEY=test-policy-signing-key python3 scripts/generate_release_provenance.py --json --ci-attestation /tmp/orbital-mesh-ci-attestation-local.json --migration-rehearsal /tmp/orbital-mesh-migration-rehearsal.json` returned `status: incomplete` with `image_digest`, `base_image_digests`, `ci_attestation`, `build_command`, `policy_lifecycle_signed`, and `migration_rehearsal` true; remaining missing gates were `clean_git_tree`, `sbom_path`, and `vulnerability_scan_path`. Evidence level: local Docker image metadata and release-packet handoff proof; remaining gap: live GitHub Actions artifact publication, clean release tree, and real release-image SBOM/vulnerability scan;

Still not validated in this environment:

- production smoke against real authenticated TLS/SSO ingress;
- real TLS/SSO ingress header-stripping and group-mapping proof from the deployed reverse proxy;
- external audit-sink certification;
- signed CI release provenance with complete image/base-image digests, SBOM, vulnerability scan, clean tree, build command, and builder identity.
