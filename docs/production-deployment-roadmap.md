# Production Deployment Roadmap

This is the deployment decision record for moving the fragmented Mesh pieces into one production-ready orbital-mesh release.

## Objective

Ship a bounded operator control plane that real users can test against real environments without giving an agent unrestricted production authority.

The first production test must prove:

- authenticated operators can launch, inspect, steer, approve, and audit runs;
- live signals can enter through manual replay, Kubernetes watchers, vendor webhooks, and OTel metrics;
- every proposed action is constrained by policy, evidence, evaluation, allowlists, and rollback metadata;
- production integrations are classified honestly as ready, proposal-only, safety-default, or unfinished adapter;
- state, events, artifacts, Merkle proofs, and feedback survive restart and can be reviewed after the fact.

## Current Integrated Surface

| Surface | Current repo anchor | Production posture |
| --- | --- | --- |
| Control plane API and SSE | `control_plane_server.py`, `services/control_plane.py` | Core runtime. Must be placed behind authenticated TLS before external access. |
| GPUI operator console | `apps/mesh-gpui/` | Target primary human application shell; uses the control plane API as the authority boundary. |
| Browser operator UI | `web/`, served by `run_server.py` | Compatibility and CI-visible human test surface while the GPUI console graduates. |
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
| Evo | `services/orchestrator/agent_mesh.py`, `docs/integrations.md` | Explicit operator-launched proposal lane for scoped repo patch runs. |
| Mesh Brain | `mesh_brain/`, `docs/post-training/` | Model-lifecycle plane. Runtime hooks are ready for controlled MVP proof, not broad model-serving production. |
| Readiness and SLO surfaces | `/api/readiness`, `/api/agent/slo`, `/metrics` | Existing observability base. Needs tier-specific readiness profiles before pilot. |
| Persistence | `.mesh-runtime-state`, Postgres-backed stores | JSON state is replay-friendly; Postgres projection is required before multi-operator production reliance. |
| Audit and proofs | vault mirror, run events, Merkle proofs | Core launch requirement. External compliance sink remains an integration gap. |

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
- `npm --prefix web run lint`
- `npm --prefix web run build`

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
- `npm --prefix web run test:e2e`
- `./scripts/prod_smoke.sh` against the running service

### Phase 2: Private Staging With Real Operators

Goal: let internal users test Mesh against non-customer-impacting real infrastructure.

Required features:

- authenticated reverse proxy with TLS;
- operator identity propagated into run creation, steering commands, notes, approvals, and audit events;
- app-level role enforcement for viewer, launcher, approver, and admin once proxy identity is present;
- tiered readiness profiles for `local`, `staging`, `pilot`, and `prod`, with required and optional integrations separated;
- threat model and abuse-case review for every authority boundary: HTTP API, SSE, webhooks, OTel ingest, kubeconfig, LLM keys, proposal lanes, state store, and exported run bundles;
- data classification, retention, redaction, and deletion rules for signals, logs, traces, prompts, model outputs, vault notes, and exported postmortem bundles;
- supply-chain record for the built image: pinned dependencies, SBOM, vulnerability scan, base-image digest, and build provenance;
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
- Deep Agents, Goose, Hermes, Evo, and Mesh Brain remain proposal/review planes unless separately approved.

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
- the failure-mode library is part of regression CI and includes replayable UI scenarios;
- formal release gates require SBOM, vulnerability scan, image digest pinning, policy hash diff, migration rehearsal, and rollback rehearsal;
- disaster recovery drills run on a schedule and include state restore, operator identity failure, observability outage, and corrupted-event replay;
- enterprise procurement package covers SSO/OIDC/SAML path, audit export, retention controls, data processing boundaries, deployment models, security review answers, and support escalation;
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
| Authenticated ingress and operator identity | any external human test | App accepts proxy identity headers, records operators, and has a local ingress rehearsal harness; real TLS/SSO proxy deployment proof remains required before external access. |
| RBAC roles for viewer, launcher, approver, admin | production pilot | App-level role checks are implemented and rehearsed for launch, approval, simulation, and kill-switch paths; proxy identity remains the trust boundary. |
| Tiered readiness profiles | private staging | Implemented in `/api/readiness` for `local`, `staging`, `pilot`, and `expansion`. |
| Policy simulator | private staging | Mutation-free API exists for fixture, captured-run, and inline-signal replay; UI surface is present for operator inspection. |
| Evidence graph as primary run surface | local production-like e2e | UI defaults to evidence-first run inspection with graph and proof surfaces. |
| Executable invariant suite | local production-like e2e | Focused production cut-list tests cover readiness, role gates, simulator non-mutation, kill switch, feedback gates, and proposal-lane isolation. |
| Distributed-systems fault tests | local production-like e2e | Focused tests cover duplicate/correlated signals, delayed deferred runs, queue backpressure, and packaging drift; broader clock-skew and partial-network coverage remains. |
| Threat model and abuse-case register | private staging | Initial authority-boundary register is documented; owner/expiry tracking remains before external staging. |
| Data classification and retention controls | private staging | Initial classification table is documented; run export redaction, size caps, retention metadata, pilot retention-review gate, and dry-run-first purge utility exist. Broader signal/log/trace deletion controls remain. |
| Supply-chain provenance | private staging | `scripts/generate_release_provenance.py` emits a release packet and `--require-complete` fails without CI artifacts; SBOM, vulnerability scan, image digest, and clean signed CI packet generation remain. |
| Pilot go/no-go generator | production pilot | Implemented at `/api/pilot/go-no-go`; local stack generated `status: go` from observed smoke, approval, denied-action, Merkle, and rollback evidence. |
| Connector certification matrix | private staging | Machine-readable certification states are exposed in `/api/readiness` and documented. |
| Failure-mode library | private staging | Core denied-action and fault tests exist; explicit product library and UI replay catalog remain. |
| Operator trust ladder UI | private staging | API and browser trust surface now expose current ceiling, next level, threshold requirements, blockers, manual override reason, and per-service/action evidence. GPUI parity remains. |
| Kill-switch panel | production pilot | Consolidated API and UI panel exist for watcher pause, live execution disablement, namespace clearing, and approval-gate forcing. |
| Disaster recovery drills | production pilot | Postgres restart-proof harness validates run events, memory, and Merkle roots; full drills for restore, key rotation, observability outage, and corrupted replay remain. |
| Release provenance packet | production pilot | Local generator and completeness gate exist; CI must supply image digests, base-image digests, SBOM, vulnerability scan, clean tree, build command, and builder identity before a signed pilot packet is valid. |
| Pilot SLO and error budget | production pilot | Initial contract exists in `docs/pilot-slo-error-budget.md` with hard stops, latency objectives, reliability budget, measurement sources, and review cadence; deployment-specific ingress, Prometheus, audit-sink, signed-release, and load evidence remain. |
| Enterprise evaluation kit | private staging | Initial kit is documented in `docs/evaluation-kits.md`; sample export packaging and formal benchmark packet remain. |
| Reference architectures | private staging | Initial active-path packet exists in `docs/reference-architectures.md` for local stack, single-VM private deployment, Kubernetes platform teams, private cloud/VPC-only, GPU/AI infrastructure, regulated enterprise, and air-gapped/offline-adjacent shapes; Helm, Terraform, marketplace, and ingress-controller-specific packages remain. |
| Startup and developer evaluation path | private staging | Initial five-minute and thirty-minute paths are documented in `docs/evaluation-kits.md`; sample export artifact remains. |
| Community and open-source motion | private staging | Governance and community/commercial boundaries are documented in `docs/community-governance.md`; issue templates and example catalog remain. |
| Cloud and ecosystem marketplaces | production expansion | Need packaging for Docker, Helm, Terraform, Kubernetes, and major cloud marketplace listings once production controls are real. |
| Partner/MSP/SI program | production expansion | Need managed-deployment playbook, support boundaries, partner certification, and escalation model. |
| Segment pricing and packaging | production expansion | Need packaging for community/local proof, startup/team, production platform, regulated/private deployment, and partner-managed deployment. |
| Design-partner packet | production pilot | Needed for serious enterprise conversations: charter, success metrics, data handling, integration scope, support model, rollback plan, and evidence summary. |
| Procurement and security package | production expansion | SSO path, audit export, retention, data boundaries, deployment modes, security answers, and support escalation need one maintained artifact set. |
| Reproducible public proof package | production expansion | Publish only evidence-backed benchmark reports, architecture paper, demo dataset, run export, and limitations statement. |
| Durable external audit sink | compliance reliance | Local audit seam only. |
| External incident adapter | production incident creation | Local deterministic seam only. |
| Real feature flag provider adapter | production flag rollback | Local deterministic seam only. |
| Postgres default production store | multi-operator production | Production-like compose now defaults Mesh to Postgres and restart proof passed in-container; migration gate and load validation remain. |
| Backup and restore automation | private staging | Runbook exists; rehearsal evidence required. |
| Live Prometheus feedback | production action validation | Pilot readiness requires live feedback; current local proof uses Kubernetes re-harvest, while Prometheus service metrics remain deployment-specific. |
| Watcher ownership and pause controls | production watchers | Watcher registry exists; operator ownership workflow needs polish. |
| Run export for postmortems | production pilot | API and UI can generate a portable JSON package and downloadable zip archive with timeline, Markdown postmortem, evidence artifacts, decision/evaluation/execution/feedback records, approvals, vault notes, Merkle snapshot, and latest-event proof; secret-shaped fields are redacted, `MESH_RUN_EXPORT_MAX_BYTES` compacts bulky fields, packages carry delete-after metadata, `scripts/purge_run_exports.py` purges expired generated files only with `--apply`, and pilot readiness blocks until `MESH_RUN_EXPORT_RETENTION_REVIEWED=1`. |
| Role-stamped approvals | production pilot | Implemented; approvals record operator id, roles, source, and event id. |
| Integration readiness contract per deployment tier | private staging | Implemented in `/api/readiness` with required checks, optional checks, blockers, and connector certification. |
| Load and concurrency testing | production expansion | Not a current release gate. |
| Mesh Brain sustained training proof | model-serving production | Gap report says real posttraining is not ready. |
| MoE training and serving lane | any MoE claim | Not deployable; research only. |

## Production Test Environments

Use three lanes, not one shared environment:

| Lane | Purpose | Mutations allowed |
| --- | --- | --- |
| Local stack | fast full-system proof with disposable k3s | Yes, inside compose-only namespace. |
| Private staging | real integrations and real operators without customer impact | Approval-gated staging actions only. |
| Production pilot | narrow real-user environment | Approval-gated actions on approved services only. |

The production pilot must start in recommendation/approval mode. Autonomy is earned per action class, not enabled globally.

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
- an OpenAPI or equivalent API contract bundle for platform teams that want to inspect integrations before running the stack;
- a security review packet with threat model, SBOM, vulnerability scan, secret handling, auth boundary, audit model, and known limitations;
- a public limitations statement that names what is not production-ready yet.

The outreach standard is evidence density. One strong exported run, one reproducible benchmark, and one honest security packet beat broad claims.

## Addressable Market Coverage

Do not treat "enterprise" as one market. The product has to enter through multiple adoption paths while keeping one invariant: bounded authority with evidence.

| Segment | First buyer or user | First value | Required packaging |
| --- | --- | --- | --- |
| Individual SRE / platform engineer | Practitioner | Reproduce a production-like failure and inspect the evidence graph locally. | Community image, sample fixtures, five-minute demo, run export. |
| Startup engineering team | Founder, CTO, infra lead | Add an approval-gated remediation control plane before hiring a full SRE team. | Startup/team tier, simple deployment, Slack/PagerDuty/GitHub path, opinionated defaults. |
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
- No direct repo writes from Deep Agents, Goose, Hermes, Evo, or Mesh Brain lanes.
- No autonomous action without allowlists, policy pass, evaluation pass, rollback metadata, and trust-ladder evidence.
- No production claim for an adapter classified as unfinished in `docs/integrations.md`.
- No broad blast-radius pilot. Start with one environment, one namespace, one service class, and approval gates.
- No "best in the world" claim in public material unless backed by external benchmark evidence. Use the defensible claim: bounded, auditable, operator-steerable production remediation.

## Immediate Cut List

Execution record for the first hardening slice: [`production-hardening-records.md`](production-hardening-records.md).
Evaluation and pilot packets: [`evaluation-kits.md`](evaluation-kits.md), [`community-governance.md`](community-governance.md), [`design-partner-packet.md`](design-partner-packet.md), [`postgres-restart-proof.md`](postgres-restart-proof.md), and [`release-provenance.md`](release-provenance.md).

1. Normalize orbital-mesh naming across docs and image tags.
2. Add tiered readiness profiles: local, staging, pilot, expansion.
3. Add operator identity and role checks around run creation and steering.
4. Make the evidence graph the default run-inspection surface in the UI.
5. Add a mutation-free policy simulator for fixture and captured signals.
6. Add connector certification state to readiness and docs.
7. Add executable invariant tests for authority boundaries and proposal-lane isolation.
8. Add distributed-systems fault tests for duplicate, delayed, timed-out, and backpressured paths.
9. Add threat model, data classification, and supply-chain provenance records.
10. Add a pilot go/no-go packet generator.
11. Make live Prometheus or Kubernetes re-harvest mandatory for pilot feedback.
12. Prove Postgres-backed state for run events, memory, and Merkle roots under restart.
13. Replace or explicitly disable unfinished feature-flag, incident, and audit adapters for pilot deployments.
14. Add a consolidated kill-switch panel before any production pilot.
15. Package the enterprise evaluation kit and reference architectures from actual working paths.
16. Package the startup/developer evaluation path with a five-minute demo, thirty-minute staging guide, and sample exported run.
17. Write community/open-source contribution and governance docs that preserve the commercial boundary.
18. Write the design-partner packet with pilot scope, success metrics, data handling, rollback, and support model.
19. Run the all-in-one compose smoke, web e2e, prod smoke, and selected Python suites on the final staged diff.
20. Write the pilot go/no-go record from observed evidence, not intent.
