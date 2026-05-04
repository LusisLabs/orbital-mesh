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
| Browser operator UI | `web/`, served by `run_server.py` | Primary human test surface. |
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
| Persistence | `.mesh-runtime-state`, Postgres-backed stores | JSON state is replay-friendly; Postgres projection is required before multi-operator production reliance. |
| Audit and proofs | vault mirror, run events, Merkle proofs | Core launch requirement. External compliance sink remains an integration gap. |

## Release Phases

### Phase 0: Source Consolidation

Goal: orbital-mesh is the only active runtime target.

Exit gates:

- repository name, docs, Docker image tags, and public copy use orbital-mesh consistently;
- deprecated mesh-intelligence references are either compatibility import paths or documented migration notes;
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
- least-privilege kubeconfig or in-cluster RBAC limited to staging namespaces;
- webhook source registration per vendor with HMAC verification;
- OTel ingest protected by bearer token or private ingress;
- persistent state on encrypted storage;
- backup and restore rehearsal for state, vault, Merkle proof data, integrations config, and research artifacts;
- structured logs shipped to the staging log system;
- Prometheus scrape of `/metrics`;
- documented rollback for the Mesh service itself.

Exit gates:

- at least three operators complete launch, inspect, approve, override, cancel, and postmortem review paths;
- at least one Kubernetes watcher path and one webhook or OTel path create real runs;
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
- documented customer/user consent for any real-user-impacting experiment.

Exit gates:

- no unauthenticated access path exists;
- `/api/readiness` is green for required integrations and explicit about optional or unavailable lanes;
- live action proof shows allowlist enforcement on both allowed and denied targets;
- one approved production action succeeds or cleanly rejects with a human-review route;
- post-action feedback uses live metrics or live Kubernetes re-harvest, not only fixture observations;
- pilot review produces a signed go/no-go record.

### Phase 4: Production Expansion

Goal: graduate from controlled pilot to repeatable production operation.

Required features:

- Postgres-backed event and memory stores are the default production backend;
- multi-operator concurrency and locking are validated under load;
- watcher registry supports multiple named watchers with documented ownership;
- trust ladder is used per action class and service before autonomy expansion;
- external incident provider, audit sink, and feature flag provider adapters replace local deterministic seams;
- SLO dashboards cover availability, run latency, queue depth, readiness, evaluation rejection rate, action success rate, feedback success rate, and unsafe-action blocks;
- release train includes migration tests, rollback tests, web contract drift checks, and smoke deployment.

Exit gates:

- each new service has service-owner approval, policy review, rollback review, and dry-run evidence;
- autonomous mode is enabled only for action classes with sufficient historical success and explicit owner approval;
- every production integration has a tested failure mode.

## Required Feature Backlog

| Capability | Required before | Status |
| --- | --- | --- |
| Authenticated ingress and operator identity | any external human test | Missing in app; must be enforced by proxy first. |
| RBAC roles for viewer, launcher, approver, admin | production pilot | Not built into app. Proxy identity plus app-level role checks needed. |
| Durable external audit sink | compliance reliance | Local audit seam only. |
| External incident adapter | production incident creation | Local deterministic seam only. |
| Real feature flag provider adapter | production flag rollback | Local deterministic seam only. |
| Postgres default production store | multi-operator production | Store code exists; production default and migration gate need validation. |
| Backup and restore automation | private staging | Runbook exists; rehearsal evidence required. |
| Live Prometheus feedback | production action validation | Supported when configured; must be mandatory for pilot services. |
| Watcher ownership and pause controls | production watchers | Watcher registry exists; operator ownership workflow needs polish. |
| Run export for postmortems | production pilot | Vault and API exist; one-click/export packaging remains backlog. |
| Role-stamped approvals | production pilot | Needs identity propagation into steering/audit records. |
| Integration readiness contract per deployment tier | private staging | Readiness exists; tier-specific required/optional profiles needed. |
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

1. Normalize orbital-mesh naming across docs and image tags.
2. Add tiered readiness profiles: local, staging, pilot, expansion.
3. Add operator identity and role checks around run creation and steering.
4. Make live Prometheus or Kubernetes re-harvest mandatory for pilot feedback.
5. Prove Postgres-backed state for run events, memory, and Merkle roots under restart.
6. Replace or explicitly disable unfinished feature-flag, incident, and audit adapters for pilot deployments.
7. Run the all-in-one compose smoke, web e2e, prod smoke, and selected Python suites on the final staged diff.
8. Write the pilot go/no-go record from observed evidence, not intent.
