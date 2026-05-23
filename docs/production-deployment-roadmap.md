# Production Deployment Roadmap

This is the deployment decision record for moving the fragmented Mesh pieces into one production-ready orbital-mesh release.

## Objective

Ship a bounded operator control plane that real users can test against real environments without giving an agent unrestricted production authority.

The first production test must prove:

- authenticated operators can launch, inspect, steer, approve, and audit runs;
- live signals can enter through manual replay, Kubernetes watchers, vendor webhooks, and OTel metrics;
- every proposed action is constrained by policy, evidence, evaluation, allowlists, and rollback metadata;
- production integrations are classified honestly as ready, proposal-only, safety-default, or unfinished adapter;
- deployment compatibility is classified honestly as validated, supported, recipe, or not planned;
- forked Kubernetes operator work from the provenance-recorded `agentic-operator-core-main/` source input is imported through contract, provenance, and validation gates, not copied wholesale;
- operators can assemble a hardened production-arena environment from a declared target profile without confusing image-level hardening with whole-system production readiness;
- state, events, artifacts, Merkle proofs, and feedback survive restart and can be reviewed after the fact.

## Current Integrated Surface

| Surface | Current repo anchor | Production posture |
| --- | --- | --- |
| Control plane API and SSE | `control_plane_server.py`, `services/control_plane.py` | Core runtime. Must be placed behind authenticated TLS before external access. |
| Operator UI | `meshapp/`, served by `run_server.py` from `meshapp/frontend/out` and available through the zero-native shell | Primary human operator surface for local, CI-visible, and production-pilot review. `web/` remains the Vite reference surface during migration. |
| Archived GPUI operator console | `docs/history/gpui/mesh-gpui/` | Archived experiment. Not an active build, packaging, or parity target. |
| TUI | `run_tui.py` | Local companion only. |
| Manual and fixture runs | `POST /api/runs`, `fixtures/signals/` | Safe replay and demo path. |
| Kubernetes live signals | `services/ingest/kubernetes_live_signal.py`, `services/watchers/kubernetes.py` | Production candidate when kubeconfig, network reachability, context allowlist, and namespace allowlist are all set. |
| Vendor alert webhooks | `services/ingest/webhook_service.py` | Production candidate after HMAC source registration and alert templates are validated per vendor. |
| OTel metric ingest | `/v1/metrics`, `services/ingest/otel_signal.py` | Production candidate only with bearer token or private ingress. |
| Decision and policy | `services/decision/`, `policies/` | Core differentiator. Deterministic policy is authoritative. |
| Evidence and investigation | `services/evidence/`, `services/investigation/` | Production candidate for inbound evidence; live probe actions remain phase-gated. |
| Evaluation | `services/evaluation/`, `services/evaluation/mesh_eval/` | Core gate. `promptfoo` is a compatibility mode name; Mesh-native pass/fail is authoritative. |
| Orchestration and actuation | `services/orchestrator/`, `services/actuators/` | Bounded actions only. Kubernetes and SSH remain off unless explicit live flags and allowlists pass. |
| Goose and Hermes | `services/orchestrator/*_bridge.py`, `docs/integrations.md` | Review/proposal lanes. They do not own production actuation. |
| Deep Agents fabric | `services/orchestrator/deepagents_adapter.py` | Proposal-only sandbox lane. No direct kubeconfig, repo writes, or actuation. |
| Mesh Brain | `mesh_brain/`, `docs/post-training/` | Model-lifecycle plane. Runtime hooks are ready for controlled MVP proof, not broad model-serving production. |
| Readiness and SLO surfaces | `/api/readiness`, `/api/agent/slo`, `/metrics` | Existing observability base. Needs tier-specific readiness profiles before pilot. |
| Persistence | `.mesh-runtime-state`, Postgres-backed stores, optional HelixDB memory projection | JSON state is replay-friendly; Postgres persistence is required before multi-operator production reliance. HelixDB is a graph-vector projection for verified memory, not canonical run-state proof. |
| Audit and proofs | vault mirror, run events, Merkle proofs | Core launch requirement. External compliance sink remains an integration gap. |
| Deployment compatibility | `docker-compose.stack.yml`, `docker-compose.prod.yml`, `docs/deployment-compatibility.md`, `docs/reference-architectures.md` | Open by contract. Docker Compose and Kubernetes are validated paths; other container and orchestrator targets are supported, recipes, backlog, or not planned according to evidence. |
| Hardened production arena | `docs/reference-architectures.md`, `docs/deployment-compatibility.md`, future deployment-profile registry | Roadmap capability for spinning up a user-shaped production-like system that Mesh can probe, evaluate, and learn from. Hardened images, Helm charts, SBOMs, and attestations are supply-chain inputs; target smoke, readiness, feedback, audit, rollback, and release packets still decide readiness. |
| Agentic operator fork source | `config/agentic-operator-source.provenance.json`, `docs/agentic-operator-core-import-plan.md` | Provenance-recorded source input for future CRD, tenant isolation, Argo scheduling, Helm packaging, MCP, LiteLLM routing, metering, and network-policy patterns. The source tree may be absent from a checkout and must be adapted to Orbital Mesh authority gates before runtime use. |

## Release Phases

### Phase 0: Source Consolidation

Goal: orbital-mesh is the only active runtime target.

Exit gates:

- repository name, docs, Docker image tags, and public copy use orbital-mesh consistently;
- legacy `mesh-intelligence` references are either compatibility import paths or documented migration notes;
- staged Mesh Brain additions remain covered by package exports, tests, and runtime docs;
- no production doc claims an unfinished adapter is complete.

Validation:

- `PYTHONPATH=. python3 -m unittest discover -s tests`
- `pnpm run lint:fast`
- `pnpm --dir web run lint`
- `pnpm --dir web run build`
- `pnpm --dir meshapp/frontend run lint`
- `pnpm --dir meshapp/frontend run build`

### Phase 1: Local Production-Like E2E

Goal: prove a full loop in a disposable but live Kubernetes environment.

Exit gates:

- `docker-compose.stack.yml` starts Mesh, k3s, Hermes, Postgres, bootstrap, and smoke verification;
- smoke seeds a real workload failure and reaches a defensible terminal state;
- `/api/readiness`, `/api/health`, `/metrics`, run events, vault notes, and Merkle proofs are inspectable;
- the UI can launch a live Kubernetes run and show stage-by-stage state;
- the evidence graph is the primary run-inspection surface: signal, trigger, evidence, hypothesis, decision, evaluation, approval, execution, and feedback;
- a policy simulator can replay fixture and live-captured signals without mutation and show the decision, blockers, allowed action, denied action, and rollback path;
- the failure-mode library covers denied namespace, stale kubeconfig, LLM unavailable, audit sink unavailable, and at least the core Kubernetes failure modes;
- executable invariant tests prove that approval, allowlist, policy, evaluation, payload-size, and proposal-lane isolation gates cannot be bypassed;
- local fault tests cover duplicate signals, delayed feedback, dependency timeout, queue backpressure, and transient network failure;
- every live actuator call is blocked unless the execution flag and allowlists pass.

Validation:

- `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke`
- `pnpm --dir web run test:e2e`
- `./scripts/prod_smoke.sh` against the running service

### Phase 2: Private Staging With Real Operators

Goal: let internal users test Mesh against non-customer-impacting real infrastructure.

Required features:

- authenticated reverse proxy with TLS;
- operator identity propagated into run creation, steering commands, notes, approvals, and audit events;
- app-level role enforcement for viewer, launcher, approver, and admin once proxy identity is present;
- tiered readiness profiles for `local`, `staging`, `pilot`, and `expansion`, with required and optional integrations separated;
- threat model and abuse-case review for every authority boundary: HTTP API, SSE, webhooks, OTel ingest, kubeconfig, LLM keys, proposal lanes, state store, and exported run bundles;
- data classification, retention, redaction, and deletion rules for signals, logs, traces, prompts, model outputs, vault notes, and exported postmortem bundles;
- supply-chain record for the built image: pinned dependencies, SBOM, vulnerability scan, base-image digest, and build provenance;
- deployment compatibility matrix that separates validated targets from supported contracts, recipes, backlog, and not-planned platforms;
- import plan for the agentic-operator source provenance that maps AgentWorkload, Tenant, Argo, MCP, LiteLLM, Helm, cost, and network-isolation pieces into Orbital Mesh contracts;
- least-privilege kubeconfig or in-cluster RBAC limited to staging namespaces;
- webhook source registration per vendor with HMAC verification;
- OTel ingest protected by bearer token or private ingress;
- connector certification states for each integration: mock, read-only, staging-ready, pilot-ready, production-ready;
- persistent state on encrypted storage;
- backup and restore rehearsal for state, vault, Merkle proof data, integrations config, and research artifacts;
- structured logs shipped to the staging log system;
- Prometheus scrape of `/metrics`;
- run export packages for postmortem review, including JSON timeline, Markdown summary, evidence artifacts, Merkle proof, and decision/evaluation/execution records;
- visible trust-ladder state per service and action class, including why autonomy is not higher yet;
- kill-switch controls for watchers, live execution, namespaces, action classes, and forced approval gate;
- enterprise evaluation kit: one-command stack, sample run export, architecture brief, security boundary brief, benchmark methodology, and 30-day pilot success rubric;
- reference architectures for private cloud, Kubernetes platform teams, GPU/AI infrastructure, regulated enterprise, and air-gapped or VPC-only deployments;
- hardened production-arena blueprint that chooses ingress, identity, secrets, policy, storage, observability, backup, and optional AI lanes from the user's target profile, then emits a Mesh probe plan and proof requirements;
- startup and developer evaluation path: five-minute local demo, thirty-minute staging path, free sample fixtures, small-team runbook, and no-procurement trial artifact;
- documented rollback for the Mesh service itself.

Exit gates:

- at least three operators complete launch, inspect, approve, override, cancel, and postmortem review paths;
- at least one Kubernetes watcher path and one webhook or OTel path create real runs;
- readiness profiles correctly fail when a required staging integration is disabled and stay green when only optional lanes are unavailable;
- run export and policy simulator outputs are reviewed by an operator who did not launch the run;
- threat-model findings are either fixed or explicitly accepted with owner, expiry, and compensating control;
- backup restore meets the stated recovery point and recovery time targets in a rehearsal, not only by documentation;
- all autonomous production-impacting modes remain disabled in staging until trust-ladder evidence supports elevation;
- every failed readiness check is visible in the UI and API.

### Phase 3: Controlled Production Pilot

Goal: test with real users and real production environments under narrow blast radius.

Scope constraints:

- one production environment;
- one or two low-blast-radius services;
- one namespace allowlist;
- approval gate as default;
- no autonomous feature-flag or incident-provider writes until real provider adapters replace local seams;
- Deep Agents, Goose, Hermes, and Mesh Brain remain proposal/review planes unless separately approved.

Required features:

- production ingress with SSO or equivalent identity enforcement;
- audit events include operator identity, source IP or proxy identity, run id, target, decision, evaluation result, approval command, and execution record;
- read-only run viewer role and separate approver role;
- production kubeconfig stored as a platform secret or in-cluster service account with least-privilege RBAC;
- per-service policy files reviewed by service owners;
- production backup cadence and restore test;
- incident response runbook for Mesh outage, bad decision, stuck run, failed actuation, and leaked provider key;
- kill switch for watchers and live execution;
- pilot go/no-go generator that emits readiness snapshot, smoke results, allowed-target proof, denied-target proof, operator approvals, backup status, and rollback plan;
- production-certified connector matrix for the specific pilot integrations;
- release provenance for the exact image and config running in pilot, including commit, image digest, policy file hashes, migration version, and env profile;
- deployment target proof for the pilot substrate, including health, readiness, ingress, persistence, feedback, audit, rollback, and release-packet evidence;
- fork provenance for any imported agentic-operator code, including source commit, license carry-forward, renamed CRD groups, and validation evidence;
- production on-call drill for kill switch, rollback, denied action, stuck run, failed dependency, and provider-key rotation;
- pilot SLO and error budget: availability, run admission latency, evaluation latency, action latency, feedback latency, event persistence lag, and export success rate;
- design-partner packet: pilot charter, success metrics, data handling terms, integration scope, support model, rollback plan, and executive summary of observed evidence;
- documented customer/user consent for any real-user-impacting experiment.

Exit gates:

- no unauthenticated access path exists;
- `/api/readiness` is green for required integrations and explicit about optional or unavailable lanes;
- the pilot go/no-go packet is generated from observed run evidence, not manually assembled claims;
- live action proof shows allowlist enforcement on both allowed and denied targets;
- one approved production action succeeds or cleanly rejects with a human-review route;
- post-action feedback uses live metrics or live Kubernetes re-harvest, not only fixture observations;
- production drill evidence shows the operator can stop live execution, pause watchers, revoke a bad target, rotate a key, and restore state inside the declared recovery target;
- pilot review produces a signed go/no-go record.

### Phase 4: Production Expansion

Goal: graduate from controlled pilot to repeatable production operation.

Required features:

- Postgres-backed event and memory stores are the default production backend;
- multi-operator concurrency and locking are validated under load;
- watcher registry supports multiple named watchers with documented ownership;
- trust ladder is used per action class and service before autonomy expansion;
- external incident provider, audit sink, and feature flag provider adapters replace local deterministic seams;
- connector certification is required for every production integration and every certified connector has a tested degraded-state behavior;
- AgentWorkload/Tenant-style CRDs are available only after they encode Orbital Mesh ownership, tenant boundary, policy, evidence sufficiency, approval, rollback, artifact, and audit requirements;
- the failure-mode library is part of regression CI and includes replayable UI scenarios;
- formal release gates require SBOM, vulnerability scan, image digest pinning, policy hash diff, migration rehearsal, and rollback rehearsal;
- disaster recovery drills run on a schedule and include state restore, operator identity failure, observability outage, and corrupted-event replay;
- enterprise procurement package covers SSO/OIDC/SAML path, audit export, retention controls, data processing boundaries, deployment models, security review answers, and support escalation;
- deployment packaging covers Docker Compose, Kubernetes, and the first validated non-Kubernetes target without implying validated support for every container platform;
- public technical proof package is generated from reproducible runs: benchmark report, architecture paper, demo dataset, run export, and limitations statement;
- distribution channels cover open source/community adoption, cloud marketplaces, startup design partners, platform engineering communities, MSP/SI partners, and self-hosted private deployments;
- packaging tiers are explicit: community/local proof, startup/team, production platform, regulated/private deployment, and partner-managed deployment;
- SLO dashboards cover availability, run latency, queue depth, readiness, evaluation rejection rate, action success rate, feedback success rate, and unsafe-action blocks;
- release train includes migration tests, rollback tests, web contract drift checks, and smoke deployment.

Exit gates:

- each new service has service-owner approval, policy review, rollback review, and dry-run evidence;
- autonomous mode is enabled only for action classes with sufficient historical success and explicit owner approval;
- every production integration has a tested failure mode.

## Required Feature Backlog

| Capability | Required before | Status |
| --- | --- | --- |
| Ownership ontology and tenant boundary | private staging | Machine-readable ownership registry exists at `config/ownership.registry.json`; normal run creation stamps an `ownership_boundary` artifact and event with owner, tenant, customer, namespace, customer boundary, approver roles, rollback authority, policy refs, data boundary, reservoir refs, export policy, retention, legal-action scope, and allowed action classes. Staging readiness now blocks when the registry is absent or invalid; broader customer-specific registry onboarding remains. |
| Connector certification states | private staging | `config/connector-certification.registry.json` now records connector state, required tier, authority posture, credential policy, credential boundary, degraded behavior, allowed scopes, evidence refs, and blockers. `/api/connectors/certification`, `/api/readiness`, and release provenance expose the registry-backed matrix; staging readiness blocks when the registry is absent or invalid, and proposal-only lanes block if production actuator or repository write credentials appear at runtime. |
| Policy lifecycle with signed hashes | private staging | `config/policy-lifecycle.manifest.json` covers every JSON policy with owner, state, risk tier, effective window, review expiry, and rollback ref. `/api/policy/lifecycle` and release provenance now emit signed policy hashes when `MESH_POLICY_SIGNING_KEY` is configured; staging readiness blocks without the signature. |
| Evidence sufficiency by action and risk tier | private staging | Evaluation now emits `mesh.evidence_sufficiency.v1` under `stage_results.evidence_sufficiency` with action class, risk tier, required evidence refs, observed refs, missing markers, and a blocking reason when the gate fails. |
| High-resolution timeline and proof chain | production pilot | `GET /api/runs/{run_id}/timeline-proof` emits `mesh.timeline_proof.v1` with `time_unix_nano`, payload hashes, Merkle leaves, latest-event proof, and sequence/timestamp/proof checks. Run exports include the same packet and archive `timeline-proof.json`; broader clock-skew and cross-store replay drills remain. |
| Admission, queues, locks, quotas, cancellation, recovery | production pilot | Run creation now records `mesh.run_admission.v1` with queue depth, worker count, tenant active-run quota, target lock key, lock holder, decision, and blockers. Queue-full, tenant-quota, and required target-lock conflicts block before worker admission; existing cancellation and recovery paths remain event-backed. |
| Authenticated ingress and operator identity | any external human test | App accepts proxy identity headers, records operators, and has a local ingress rehearsal harness. `mesh.authenticated_ingress_deployment_proof.v1`, `scripts/verify_authenticated_ingress_deployment.py`, and staging/pilot readiness gate `authenticated_ingress_deployment_verified` now require deployed TLS, SSO, header stripping, role mapping, private upstream, audit identity, app rehearsal proof, and an environment match before external readiness claims. Target operators still need to capture the real proxy proof packet per environment. |
| RBAC roles for viewer, launcher, approver, admin | production pilot | App-level role checks are implemented and rehearsed for launch, approval, simulation, and kill-switch paths; proxy identity remains the trust boundary. |
| Tiered readiness profiles | private staging | Implemented in `/api/readiness` for `local`, `staging`, `pilot`, and `expansion`. |
| Policy simulator | private staging | Mutation-free API exists for fixture, captured-run, and inline-signal replay; UI surface is present for operator inspection. |
| Evidence graph as primary run surface | local production-like e2e | UI defaults to evidence-first run inspection with graph and proof surfaces. |
| Executable invariant suite | local production-like e2e | Focused production cut-list tests cover readiness, role gates, simulator non-mutation, kill switch, feedback gates, and proposal-lane isolation. |
| Distributed-systems fault tests | local production-like e2e | Focused tests cover duplicate/correlated signals, delayed deferred runs, queue backpressure, and packaging drift; broader clock-skew and partial-network coverage remains. |
| Threat model and abuse-case register | private staging | `config/threat-model.register.json`, `mesh.threat_model_register.v1`, and `scripts/verify_threat_model_register.py` now enforce owner, decision, expiry, compensating control, evidence refs, duplicate-id checks, and no open or expired findings; staging readiness blocks on `threat_model_register_reviewed`. |
| Data classification and retention controls | private staging | `config/data-classification.policy.json`, `mesh.data_classification_policy.v1`, and `scripts/verify_data_classification_policy.py` now enforce required classes, owners, retention windows, redaction requirements, storage locations, deletion controls, evidence refs, no secret export, and deletion controls for signals, logs, traces, model outputs, and training candidates; staging readiness blocks on `data_classification_policy_reviewed`. Target-environment deletion execution remains deployment-specific. |
| Supply-chain provenance | private staging | `scripts/generate_release_provenance.py` emits a release packet and `--require-complete` fails without CI artifacts, migration rehearsal, SBOM, vulnerability scan, CI attestation, image digest, and clean signed CI packet generation. CI collects built image/base-image metadata, runs pinned Syft and Grype scanners through `scripts/generate_release_image_assurance.py`, feeds the digest metadata into `mesh.ci_attestation.v1`, uploads failed-status attestation evidence when the release-image gate fails, and uploads an incomplete release-provenance draft for review. |
| Pilot go/no-go generator | production pilot | Implemented at `/api/pilot/go-no-go`; local stack generated `status: go` from observed smoke, approval, denied-action, Merkle, rollback, release-provenance, and on-call drill evidence. |
| Connector certification matrix | private staging | Registry-backed certification states are exposed in `/api/readiness`, `/api/connectors/certification`, release provenance, and the browser Connectors page with authority posture, credential boundary, allowed scopes, and blockers visible. |
| Failure-mode library | private staging | `mesh.failure_mode_library.v1`, `scripts/verify_failure_mode_library.py`, and `GET /api/failure-modes` now verify and expose required catalog coverage, UI replay ids, test refs, authority boundaries, operator actions, and entries; browser replay automation and target-environment live fault evidence remain. |
| Operator trust ladder UI | private staging | API and browser trust surface now expose current ceiling, next level, threshold requirements, blockers, manual override reason, and per-service/action evidence. |
| Kill-switch panel | production pilot | Consolidated API and UI panel exist for watcher pause, live execution disablement, namespace clearing, and approval-gate forcing. |
| Disaster recovery drills | production pilot | Postgres restart-proof harness, backup/restore rehearsal proof, and `mesh.on_call_drill.v1` contract now cover restore, kill switch, watcher pause, bad-target revocation, failed dependency, stuck run, and key-rotation evidence. Target-environment drill packets remain required. |
| Release provenance packet | production pilot | Local generator and completeness gate exist; CI now has the real release-image SBOM/vulnerability scan handoff path, and the local release image has been reduced from 517 to 18 blocking Grype findings. A live CI artifact, clean tree, signed policy key, target migration proof, and zero blocking scanner findings are still required before a signed pilot packet is valid. |
| Pilot SLO and error budget | production pilot | Initial contract exists in `docs/pilot-slo-error-budget.md` with hard stops, latency objectives, reliability budget, measurement sources, and review cadence; deployment-specific ingress, Prometheus, audit-sink, signed-release, and load evidence remain. |
| Enterprise evaluation kit | private staging | `docs/evaluation-kits.md`, `scripts/generate_evaluation_kit_packet.py`, `scripts/verify_evaluation_kit_packet.py`, and `scripts/verify_benchmark_run_artifacts.py` now emit and verify `mesh.evaluation_kit_packet.v1` with a sample run export package, zip archive, retrieval proof, formal golden-suite benchmark command packet, and completed benchmark output artifact proof. Target-environment exports and durable benchmark publication remain deployment-specific evidence. |
| Reference architectures | private staging | Initial active-path packet exists in `docs/reference-architectures.md` for local stack, single-VM private deployment, Kubernetes platform teams, private cloud/VPC-only, GPU/AI infrastructure, regulated enterprise, and air-gapped/offline-adjacent shapes; Helm, Terraform, marketplace, and ingress-controller-specific packages remain. |
| Hardened production arena builder | private staging | Needed. Should produce a declared deployment profile, component graph, image/chart source refs, digest pins, SBOM/provenance/attestation refs, RBAC and network boundaries, secret policy, Mesh probe curriculum, failure-mode pack, cleanup path, and readiness proof checklist. Docker Hardened Images and charts can be preferred supply-chain inputs when available, but the full catalog should be imported as machine-readable registry data rather than copied into prose. The arena is not validated until Mesh observes target health, readiness, feedback, audit, rollback, and release-packet evidence. |
| Startup and developer evaluation path | private staging | Five-minute and thirty-minute paths are documented in `docs/evaluation-kits.md`; `scripts/generate_evaluation_kit_packet.py` creates the local sample export artifact and benchmark handoff packet. Target-environment sample exports remain deployment-specific. |
| Community and open-source motion | private staging | Governance and community/commercial boundaries are documented in `docs/community-governance.md`; issue templates and example catalog remain. |
| Cloud and ecosystem marketplaces | production expansion | Need packaging for Docker, Helm, Terraform, Kubernetes, and major cloud marketplace listings once production controls are real. |
| Deployment compatibility matrix | private staging | `config/deployment-compatibility.registry.json`, `mesh.deployment_compatibility.v1`, `scripts/verify_deployment_compatibility.py`, and `GET /api/deployment/compatibility` now make deployment claims machine-checkable. Docker Compose and Kubernetes are validated paths; ECS/Fargate is the single next validated non-Kubernetes target with explicit promotion blockers and `scripts/verify_ecs_fargate_promotion.py` proof shape; recipe and not-planned targets cannot be promoted without target smoke, readiness, feedback, audit, rollback, and release-packet evidence. Staging readiness blocks on `deployment_compatibility_registry_reviewed`. |
| Agentic operator core fork-in | private staging | `config/agentic-operator-source.provenance.json`, `mesh.agentic_operator_source_provenance.v1`, and `scripts/verify_agentic_operator_source_provenance.py` now record the imported source-input snapshot, Apache-2.0 license path, required source surfaces, fork posture, authority-gate adaptation requirements, forbidden credential classes, and no active runtime or wholesale-copy posture; staging readiness blocks on `agentic_operator_source_provenance_recorded`. Actual CRD/controller/Helm forks remain blocked until adapted contracts and tests exist. |
| Partner/MSP/SI program | production expansion | Need managed-deployment playbook, support boundaries, partner certification, and escalation model. |
| Segment pricing and packaging | production expansion | Need packaging for community/local proof, startup/team, production platform, regulated/private deployment, and partner-managed deployment. |
| Design-partner packet | production pilot | `mesh.design_partner_packet.v1`, `scripts/verify_design_partner_packet.py`, `MESH_DESIGN_PARTNER_PACKET_PATH`, and pilot readiness gate `design_partner_packet_verified` now make the charter, success metrics, data handling, integration scope, support model, rollback plan, consent, go/no-go hash, release-provenance hash, run export ref, and readiness ref machine-checkable. Target pilot operators still need a partner-specific signed packet. |
| Procurement and security package | production expansion | `config/procurement-security.package.json`, `mesh.procurement_security_package.v1`, `scripts/verify_procurement_security_package.py`, and expansion readiness gate `procurement_security_package_verified` now bind SSO path, audit export, retention controls, data boundaries, deployment modes, security answers, support escalation, and known limitations into one maintained artifact set. Target operators still need deployed SSO proof, external audit sink receipts, complete signed release provenance, and customer-specific support evidence. |
| Reproducible public proof package | production expansion | `config/public-proof.package.json`, `mesh.public_proof_package.v1`, `scripts/verify_public_proof_package.py`, and expansion readiness gate `public_proof_package_verified` now require public proof claims to bind to benchmark report, architecture paper, demo dataset, run export, and limitations evidence. Durable public publication and target-environment benchmark/export artifacts remain deployment-specific evidence. |
| Durable external audit sink | compliance reliance | Local audit seam only. |
| External incident adapter | production incident creation | `mesh.provider_adapter_proof.v1` and `scripts/verify_provider_adapter_proof.py --adapter-id incident_provider` now define the proof required before incident-provider credentials can satisfy pilot readiness. Real target proof and connector certification remain required before production incident creation. |
| Real feature flag provider adapter | production flag rollback | `mesh.provider_adapter_proof.v1` and `scripts/verify_provider_adapter_proof.py --adapter-id feature_flag_provider` now define the proof required before feature-flag credentials can satisfy pilot readiness. Real target proof and connector certification remain required before production flag rollback. |
| Postgres default production store | multi-operator production | Production-like compose now defaults Mesh to Postgres and restart proof passed in-container; release provenance now requires `mesh.migration_rehearsal.v1` for complete packets, and `scripts/generate_migration_rehearsal.py` packages real rehearsal refs against the current migration hash. Load validation remains. |
| Backup and restore automation | private staging | `mesh.backup_restore_rehearsal.v1` and `scripts/verify_backup_restore_rehearsal.py` now verify operator, backup ref, restore ref, RPO/RTO, measured restore duration, state backend, restored state/vault/Merkle/integrations/research components, and optional expected environment/backend bindings. Staging and pilot readiness block on `backup_restore_rehearsal_verified` unless the packet matches the active readiness profile and runtime state backend; target environment rehearsal evidence remains required. |
| Live Prometheus feedback | production action validation | Pilot readiness requires live feedback; current local proof uses Kubernetes re-harvest, while Prometheus service metrics remain deployment-specific. |
| Watcher ownership and pause controls | production watchers | `GET /api/watchers/ownership` now resolves registered watcher targets through `config/ownership.registry.json` and embeds owner, tenant, customer boundary, approver roles, rollback authority, escalation route, allowed action classes, and blockers into `/api/watchers`; target private-staging runs from Kubernetes watcher plus webhook or OTel paths remain required. |
| Run export for postmortems | production pilot | API and UI can generate a portable JSON package and downloadable zip archive with timeline, Markdown postmortem, evidence artifacts, decision/evaluation/execution/feedback records, approvals, handoffs, independent override reviews, independent postmortem reviews, vault notes, Merkle snapshot, and latest-event proof; secret-shaped fields are redacted, `MESH_RUN_EXPORT_MAX_BYTES` compacts bulky fields, packages carry delete-after metadata, `scripts/purge_run_exports.py` purges expired generated files only with `--apply`, and pilot readiness blocks until `MESH_RUN_EXPORT_RETENTION_REVIEWED=1`. |
| Role-stamped approvals and handoffs | production pilot | Implemented; approvals record operator id, roles, source, and event id. `GET /api/approvals` emits `mesh.approval_queue.v1` with pending run, owner, approver roles, blockers, allowed commands, and evidence refs. Operator handoffs emit `mesh.operator_handoff.v1`, persist as run artifacts, and appear in run export packages and archives. |
| Integration readiness contract per deployment tier | private staging | Implemented in `/api/readiness` with required checks, optional checks, blockers, and connector certification. |
| Load and concurrency testing | production expansion | `mesh.load_concurrency_rehearsal.v1`, `scripts/verify_load_concurrency_rehearsal.py`, and expansion readiness gate `load_concurrency_rehearsal_verified` now define the proof required for multi-operator load, admission latency, event persistence latency, tenant quota, target-lock conflict, cancellation, stuck-run recovery, and backpressure evidence. Target-environment rehearsal evidence remains required. |
| Mesh Brain sustained training proof | model-serving production | Gap report says real posttraining is not ready. |
| MoE training and serving lane | any MoE claim | Not deployable; research only. |

## Production Test Environments

Use four lanes, not one shared environment:

| Lane | Purpose | Mutations allowed |
| --- | --- | --- |
| Local stack | fast full-system proof with disposable k3s | Yes, inside compose-only namespace. |
| Hardened production arena | user-shaped production-like system for Mesh probing, one-person projects, startup trials, and enterprise rehearsal | Yes, only inside the declared arena environment, namespaces, accounts, and cleanup scope. |
| Private staging | real integrations and real operators without customer impact | Approval-gated staging actions only. |
| Production pilot | narrow real-user environment | Approval-gated actions on approved services only. |

The hardened arena is a testing and service-delivery surface, not a shortcut to production claims. The production pilot must start in recommendation/approval mode. Autonomy is earned per action class, not enabled globally.

## Product Quality Priorities

These features make the product harder to dismiss because they expose proof instead of asking operators to trust an agent.

| Priority | Product surface | Why it matters |
| --- | --- | --- |
| 1 | Identity-first control plane | Real operations require named accountability for every launch, note, override, approval, and execution. |
| 2 | Evidence graph | The graph is the product's main explanation surface; operators should see why a run moved or stopped without reading raw JSON first. |
| 3 | Policy simulator | Buyers and service owners need to test policies and signals without mutation before they permit live authority. |
| 4 | Pilot go/no-go packet | Production entry should be an artifact generated from evidence, not a meeting note. |
| 5 | Connector certification matrix | "Wired" and "production-ready" must stay separate. Every connector needs a visible maturity state. |
| 6 | Failure-mode library | The system should prove expected behavior against known bad states, including denied action and degraded integration cases. |
| 7 | Trust ladder UI | Autonomy must be earned per action and service, with the current ceiling visible to operators. |
| 8 | Run export package | Teams need portable postmortem evidence for reviews, audits, and vendor/customer conversations. |
| 9 | Kill-switch panel | Operators need immediate authority to stop watchers, live execution, namespaces, action classes, and autonomy. |
| 10 | Hardened arena builder | Practitioners should be able to spin up a realistic system, let Mesh probe it, and leave with proof packets instead of a hand-built demo environment. |

Do not add product surfaces that obscure the core loop. Every new screen or API must reinforce one of three jobs: prove what happened, constrain what can happen next, or help an operator make a bounded decision.

## Enterprise Attention Package

Large platform, AI, hardware, cloud, and regulated-enterprise teams will not respond to a claim. They respond to proof that maps to their operational constraints.

| Audience archetype | Proof to ship |
| --- | --- |
| AI lab / model platform | Model-neutral control plane, prompt/tool boundary threat model, proposal-lane isolation, eval-gated actions, and private-model deployment path. |
| Cloud platform team | Kubernetes, OTel, Prometheus, webhook, IAM/SSO, audit, tenancy, and policy-simulation reference architecture. |
| GPU / AI infrastructure team | GPU-serving and model-lifecycle lane, hardware-aware routing proof, capacity metrics, and failure-mode evidence for expensive workloads. |
| Device / private-compute platform | local-first deployment, offline or VPC-only mode, minimal external dependency path, data-retention controls, and Apple Silicon / CPU fallback story. |
| High-reliability engineering team | kill switch, approval gate, action allowlists, rollback proof, disaster-recovery drill, failure-mode library, and postmortem export. |
| Regulated enterprise buyer | SSO, RBAC, audit export, retention policy, deployment boundary, support model, vulnerability/SBOM packet, and legal/data-processing boundaries. |

Required artifacts:

- a short technical whitepaper grounded in the actual architecture, not a marketing narrative;
- a reproducible benchmark report with commands, fixtures, pass/fail gates, and limitations;
- a five-minute flagship demo path that starts from a real signal and ends with evidence, decision, approval, execution, feedback, and export;
- a design-partner pilot brief with scope, success metrics, timeline, staffing, support, rollback, data handling, and proof artifacts;
- reference deployments for local compose, single VM, Kubernetes, private VPC, and air-gapped/offline-adjacent operation;
- hardened production-arena blueprints for single-person projects, startup SaaS, platform teams, AI infrastructure, and regulated/VPC-only evaluation;
- a deployment compatibility matrix that prevents Docker-alternative and Kubernetes-alternative names from becoming false support claims;
- a fork-in plan for the provenance-recorded `agentic-operator-core-main/` source input that converts Kubernetes-agent-runtime assets into Orbital Mesh authority contracts;
- an OpenAPI or equivalent API contract bundle for platform teams that want to inspect integrations before running the stack;
- a security review packet with threat model, SBOM, vulnerability scan, secret handling, auth boundary, audit model, and known limitations;
- a public limitations statement that names what is not production-ready yet.

The outreach standard is evidence density. One strong exported run, one reproducible benchmark, and one honest security packet beat broad claims.

## Addressable Market Coverage

Do not treat "enterprise" as one market. The product has to enter through multiple adoption paths while keeping one invariant: bounded authority with evidence.

| Segment | First buyer or user | First value | Required packaging |
| --- | --- | --- | --- |
| Individual SRE / platform engineer | Practitioner | Reproduce a production-like failure and inspect the evidence graph locally. | Community image, sample fixtures, five-minute demo, run export. |
| One-person project / startup engineering team | Founder, CTO, infra lead | Spin up a hardened default stack and add an approval-gated remediation control plane before hiring a full SRE team. | Startup/team tier, simple deployment, hardened arena defaults, Slack/PagerDuty/GitHub path, opinionated cleanup and proof export. |
| AI-native startup | AI infra lead | Keep expensive model-serving and agentic workflows bounded, observable, and reviewable. | GPU/AI reference architecture, model-serving lane, capacity and cost telemetry. |
| Open-source / cloud-native community | Maintainer, contributor | Transparent policy and evidence model that can be inspected, extended, and trusted. | Public examples, contribution guide, plugin surface, roadmap, issue templates. |
| Mid-market SaaS | VP Engineering, platform lead | Standardize incident response and rollback discipline across teams. | SSO-ready deployment, audit export, connector matrix, run export, support path. |
| Regulated enterprise | Security, compliance, platform | Prove every action has identity, policy, evidence, approval, and audit trail. | Private deployment, retention controls, SBOM, security packet, procurement artifact. |
| Managed service provider / systems integrator | Practice lead | Offer customers a repeatable AI operations control plane without custom building it. | Partner playbook, multi-customer isolation model, support escalation, certification. |
| Cloud marketplace buyer | Platform owner | Try and procure through existing cloud spend. | Hardened image, Helm chart, Terraform module, marketplace listing, quickstart. |
| Hardware / edge / private-compute team | Infra or device platform lead | Run bounded remediation close to private workloads with minimal external dependency. | Local-first mode, offline-adjacent docs, Apple Silicon/CPU path, VPC-only deployment. |
| Blockchain / validator operator | Protocol infra operator | Approval-gated node remediation with evidence and restart discipline. | Bare-metal node runbook, SSH/systemd safety envelope, validator-specific failure catalog. |

Market coverage artifacts:

- one landing path per segment, each ending in a working proof rather than a sales form;
- segment-specific demo fixtures and exported runs;
- buyer/user map that separates practitioner adoption from economic buyer approval;
- pricing and packaging boundaries that do not cripple the proof path;
- integration priority list by segment, not by internal preference;
- partner-ready deployment runbook for MSPs, SIs, and cloud marketplace installs;
- public examples that show limitations, denied actions, and failure behavior, not only successful runs.

The wedge is local proof for practitioners, then team safety, then platform governance. Do not start with a procurement-heavy enterprise motion when a small team can validate the core loop in one session.

## Systems Assurance Hardening

This is the extra layer that prevents the roadmap from failing under ordinary production physics.

| Boundary | Hardening requirement |
| --- | --- |
| Authority | Every mutating path must prove identity, role, policy allowance, target allowlist, evaluation pass, approval state, and rollback metadata before action. |
| Invariants | Encode non-bypassable properties as tests: proposal lanes cannot mutate, denied namespaces cannot execute, failed evaluation cannot execute, payload caps hold, and overrides re-enter evaluation. |
| Time | Treat clocks as unreliable. Use explicit timestamps, monotonic durations where available, replay-safe ordering, expiry on approvals, and bounded waiting at every external dependency. |
| Delivery | Treat signals and webhooks as at-least-once. Deduplicate by stable fingerprint, record replay attempts, and make action execution idempotent or explicitly non-repeatable. |
| Dependency failure | Every external dependency must have a timeout, degraded readiness state, operator-visible reason, and fail-closed behavior for authority-bearing paths. |
| Concurrency | Operators, watchers, and webhooks can race. Lock by run and target, reject conflicting live actions, and surface the winning authority path in the event log. |
| Capacity | Backpressure must be explicit: queue depth, worker saturation, state-store latency, SSE fanout, artifact size, and export size need limits and metrics. |
| Security | Threat model every ingress, secret, sandbox, file export, and actuator. Red-team prompt injection and tool-confusion paths as authority attacks, not only model-quality bugs. |
| Privacy | Classify and redact production logs, prompts, traces, model outputs, vault notes, and exported bundles before retention or training reuse. |
| Supply chain | Pin and attest build inputs. Record SBOM, vulnerability scan, image digest, dependency lock, policy hashes, and migration version in every release packet. |
| Hardened component catalog | Treat hardened images and charts as preferred ingredients, not as proof of system compliance. Pin by digest, bind SBOM/provenance/attestation refs, verify chart values, and still require runtime smoke, readiness, feedback, audit, rollback, and release-packet evidence. |
| Deployment compatibility | Keep the runtime contract at the OCI image, env/secret, network, persistence, ingress, readiness, audit, and release-packet layer. Do not add target-specific shortcuts that bypass authority gates. |
| Forked operator substrate | Preserve source provenance and license notices. Fork CRDs, controllers, Helm, Argo, MCP, LiteLLM, metering, and network policy only after each piece is renamed, threat-modeled, and wired through Orbital Mesh authority checks. |
| Recovery | Rehearse restore, key rotation, kill switch, watcher pause, bad-policy rollback, corrupted event replay, and state-store failover before pilot expansion. |

The standard is not "works on the happy path." The standard is "fails closed, explains why, preserves evidence, and lets an operator regain control."

## Differentiator

The defensible differentiator is not "AI for operations." That claim is generic.

The differentiator is an operator-control architecture where every remediation moves through:

1. signal admission;
2. trigger gating;
3. audited evidence;
4. scenario analysis;
5. deterministic policy;
6. optional model review that can only promote conservatism;
7. Mesh-native evaluation;
8. operator steering;
9. bounded execution;
10. live feedback;
11. durable memory, vault notes, and Merkle proofs.

Most agent systems optimize for broader autonomy. Mesh optimizes for accountable production authority. That is the product line: better production judgment through constrained action, inspectable reasoning, and reversible rollout discipline.

## Non-Negotiable Launch Rules

- No public Internet exposure without authenticated TLS.
- No production kubeconfig in proposal-lane sandboxes.
- No direct repo writes from Deep Agents, Goose, Hermes, or Mesh Brain lanes.
- No autonomous action without allowlists, policy pass, evaluation pass, rollback metadata, and trust-ladder evidence.
- No production claim for an adapter classified as unfinished in `docs/integrations.md`.
- No validated deployment claim for a runtime, orchestrator, or managed platform without target-specific health, readiness, persistence, feedback, audit, rollback, and release-packet evidence.
- No hardened-image or hardened-chart claim may be promoted into whole-system compliance without deployment-specific proof.
- No imported `agentic-operator-core-main/` code in the active runtime without source availability, source provenance, license preservation, renamed contracts, authority-gate adaptation, and focused tests.
- No public kagent or competitor claim from the NineVigil source material until independently verified.
- No broad blast-radius pilot. Start with one environment, one namespace, one service class, and approval gates.
- No "best in the world" claim in public material unless backed by external benchmark evidence. Use the defensible claim: bounded, auditable, operator-steerable production remediation.

## Immediate Cut List

Execution record for the first hardening slice: [`production-hardening-records.md`](production-hardening-records.md).
Evaluation and pilot packets: [`evaluation-kits.md`](evaluation-kits.md), [`community-governance.md`](community-governance.md), [`design-partner-packet.md`](design-partner-packet.md), [`postgres-restart-proof.md`](postgres-restart-proof.md), and [`release-provenance.md`](release-provenance.md).

This list is current-work guidance. Items already implemented stay here only as proof, drift, or target-environment tasks.

1. Keep orbital-mesh naming synchronized across active docs, package metadata, images, and release packets.
2. Keep readiness profiles aligned to code: `local`, `staging`, `pilot`, and `expansion`; `prod` and `production` are aliases for `pilot`.
3. Capture target authenticated-ingress proof for operator identity and app-level role gates around run creation, steering, approval, simulation, and kill-switch paths.
4. Verify the evidence graph remains the primary run-inspection surface where the UI claims it is primary.
5. Keep the policy simulator mutation-free for fixture, captured-run, and inline-signal replay.
6. Keep connector certification state visible in readiness, docs, release provenance, and operator surfaces.
7. Keep executable invariant tests covering authority boundaries, role gates, simulator non-mutation, and proposal-lane isolation.
8. Broaden distributed-systems fault coverage for duplicate, delayed, timed-out, clock-skewed, partially partitioned, and backpressured paths.
9. Keep threat model, data classification, policy lifecycle, and supply-chain provenance records current.
10. Generate pilot go/no-go packets only from observed evidence.
11. Keep live Prometheus or Kubernetes re-harvest mandatory for pilot feedback.
12. Prove Postgres-backed state for run events, memory, and Merkle roots under restart in the target environment.
13. Keep feature-flag and incident adapters disabled unless certified provider proof is mounted; require external audit-sink proof only before expansion or compliance reliance.
14. Keep kill-switch controls available before any production pilot and rehearse them in the target environment.
15. Package the enterprise evaluation kit and reference architectures from actual working paths, including `mesh.evaluation_kit_packet.v1` sample export and benchmark handoff evidence.
16. Keep the deployment compatibility matrix honest: Docker Compose and Kubernetes are validated paths; OCI/container runtime compatibility is supported by contract; non-core platforms remain recipes or not planned until proven.
17. Define the hardened production-arena builder as a deployment-profile registry plus generator before adding runtime controls; each profile must name component choices, authority boundaries, proof requirements, cleanup, and what Mesh is allowed to probe.
18. Package the provenance-recorded agentic-operator fork-in plan and import the first contract slice only after source availability, provenance, rename, authority-gate, and test requirements are explicit.
19. Keep the startup/developer evaluation path reproducible with a five-minute demo, thirty-minute staging guide, and generated sample exported run packet.
20. Keep community/open-source contribution and governance docs aligned with the commercial boundary.
21. Complete target design-partner packets with pilot scope, success metrics, data handling, rollback, and support model.
22. Run the all-in-one compose smoke, web e2e, prod smoke, and selected Python suites on the final staged diff.
23. Write the pilot go/no-go record from observed evidence, not intent.
