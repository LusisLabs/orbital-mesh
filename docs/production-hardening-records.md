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
- enterprise and startup evaluation kit packaging from active repository paths;
- community governance and contribution boundary documentation;
- design-partner pilot packet;
- Postgres restart-proof harness for environments with `MESH_DATABASE_URL`;
- production-like compose defaults for Postgres state, named operator identity, approval-gated smoke, and disabled unfinished feature-flag and incident adapters;
- release-cut guard for active image names, API markers, docs, compose pilot defaults, and smoke paths.

Deferred from the immediate list:

- broad historical-doc naming cleanup outside active release paths;
- production smoke against authenticated TLS ingress;
- external audit-sink certification, SBOM generation, vulnerability scan, and signed release provenance.

## Readiness Profiles

`MESH_READINESS_PROFILE` accepts `local`, `staging`, `pilot`, and `expansion`.

- `local` checks that local state, vault paths, and security headers are present. Promptfoo, Hermes, Goose, Evo, LatentMAS, and Deep Agents are optional lanes.
- `staging` additionally requires proxy-propagated operator identity, protected OTel ingest when enabled, live Kubernetes allowlists when live execution is enabled, and audit logging availability.
- `pilot` additionally requires Postgres state, `MESH_DATABASE_URL`, forced approval gate, live feedback source configuration, and disabled unfinished feature-flag and incident adapters.
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

## Pilot Go/No-Go Packet

`GET /api/pilot/go-no-go` generates `pilot.go_no_go.v1` from observed state. It is blocked until the runtime has actual evidence for readiness, observed runs, operator approval, live action proof, denied action proof, Merkle proof, and rollback metadata.

This packet is not a manual intent record. Missing evidence appears under `missing_evidence`.

Observed local-stack packet on 2026-05-04:

- status: `go`;
- readiness: `pilot` profile, `status: ready`, no blockers;
- approved and live-action proof run: `run_20260504T204223_791d4770`;
- denied-action proof run: `run_20260504T204409_5229c69a`, blocked with `approval required before execution`;
- Merkle proof observed for six runs, including the live action, denied action, and Postgres restart-proof runs;
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
| Run exports | vault and Merkle artifacts | redaction rules and export-size limits |

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

Until those fields are generated from CI artifacts, pilot readiness remains blocked at the release-packet layer.

## Release Cut Guard

Run:

```bash
scripts/verify_release_cut_list.py --json
```

The guard checks active Docker image defaults, required production docs, smoke scripts, API markers, and release-packet references. It is a static guard; it does not replace live compose smoke, production smoke, browser e2e, or Postgres restart proof.

## Current Validation Evidence

Validated in this slice:

- `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list tests.test_production_faults_and_packaging` passed with `13` tests;
- `scripts/verify_release_cut_list.py --json` returned `status: pass`;
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

- production smoke against authenticated TLS ingress;
- external audit-sink certification and signed release provenance from CI artifacts.
