# Mesh Business Plan

## Executive Summary

Mesh is a local, policy-guided operator control plane for bounded remediation and model-lifecycle work. The business should start with the product shape the repository already proves: a self-hosted control plane that turns infrastructure signals into inspected, evaluation-gated, operator-steerable remediation runs with durable audit artifacts.

The wedge is not observability, alerting, ITSM, or open-ended autonomous agents. The wedge is the missing control layer between detection systems and production-impacting action: evidence capture, deterministic policy, evaluation, approval, execution, feedback, run memory, and verifiable history.

Initial commercialization should target design partners that already have observability and incident systems but do not trust unbounded automation in production. Mesh should sell controlled remediation pilots, not broad production autonomy. The first business milestone is a narrow paid pilot that proves one allowed action, one denied action, operator approval, rollback metadata, live feedback, and reviewable run exports inside a customer-controlled environment.

## Long-Term Protocol Ambition

The long-term ambition is for Mesh to become the everything preservation and remediation protocol: a common evidence, policy, memory, proof, and action-control layer for systems that need to preserve operational state, explain what changed, and remediate bounded failures.

This does not mean Mesh currently supports every target or should sell universal autonomy. "Everything" is a direction, not a present-tense claim. A domain can enter the protocol only when it exposes enough structure for state ownership, invariants, authority boundaries, rollback semantics, evidence capture, and feedback verification.

Protocol-level Mesh means four contract families:

- preservation contracts: state snapshots, intent, ownership, policy refs, evidence, memory, lineage, retention, redaction, and proof metadata;
- remediation contracts: divergence classification, bounded action proposals, evaluation gates, approval requirements, certified execution adapters, rollback metadata, and feedback checks;
- trust contracts: operator identity, role authority, timeline proofs, Merkle proofs, run exports, replay, and external audit bindings;
- extension contracts: connector-declared state slices, read/write scopes, degraded behavior, credential posture, allowed actions, and target-specific proof packets.

The immediate commercial product remains bounded infrastructure remediation. The protocol becomes real by adding domains one at a time, with proof packets and certified connectors replacing unsupported claims.

## Current Defensible Position

Mesh can currently be positioned as:

- a bounded remediation control plane for Kubernetes, feature-flag-style regressions, OpenTelemetry metric signals, simulation-backed CROPS scenarios, and selected bare-metal node workflows;
- a browser-first operator surface with stage-by-stage inspection, approval, steering, timeline, evidence, feedback, vault preview, and Merkle proof surfaces;
- a self-hosted runtime with Docker Compose and Kubernetes-oriented validation paths;
- an evaluation-gated orchestration layer where proposal lanes such as Goose, Hermes, Deep Agents, and Mesh Brain do not own production authority by default;
- an audit and evidence system that records run events, artifacts, vault notes, exports, and proof packets.

Mesh must not currently be sold as:

- a replacement for Datadog, Grafana, Prometheus, PagerDuty, ServiceNow, or any customer's existing detection system;
- a broad autonomous production operator;
- a generic automation engine for arbitrary infrastructure changes;
- a mature multi-tenant SaaS;
- a production-complete feature-flag or incident-provider writer unless target-specific provider proof packets exist;
- a production-ready model-serving platform beyond the controlled Mesh Brain proof scope.

## Product Thesis

Engineering teams already have too many systems that detect, alert, summarize, and chat. The unresolved operational problem is controlled action. Teams either keep humans in the loop and lose speed, or they wire automation directly to production and lose trust.

Mesh creates a third path:

1. Signals enter from existing systems.
2. Mesh normalizes the signal into a run.
3. Evidence and hypotheses are assembled.
4. A bounded decision is proposed from an explicit action surface.
5. Policy and evaluation gates decide whether the run can proceed.
6. Operators can approve, pause, override, cancel, or attach notes.
7. Actuation is limited by live-execution flags, allowlists, policy, and rollback metadata.
8. Feedback and proof artifacts persist after the run.

The product promise is controlled preservation and remediation: preserve the evidence, authority, memory, and proof chain around operational change, then remediate only when policy, evaluation, and operator authority permit it.

## Customer

### Initial ICP

The first ideal customer profile is a 20 to 300 person engineering organization with:

- Kubernetes or production-like container operations;
- an existing observability or incident-management stack;
- recurring operational incidents that are understood enough to remediate but risky enough to require approval;
- platform, SRE, or infrastructure owners who need auditability;
- willingness to run a self-hosted control plane in a private environment;
- one low-blast-radius service that can be used for a 90-day pilot.

The sharpest initial verticals are:

- SaaS companies with small platform teams;
- AI infrastructure teams operating model-serving, GPU, or data services;
- crypto and high-availability node operators where restarts, rollbacks, and bare-metal actions require strict approval;
- managed service providers that need repeatable, auditable remediation workflows across client environments;
- regulated or security-sensitive teams that reject opaque SaaS remediation agents.

Bad-fit customers:

- teams looking for a hosted chatbot;
- teams looking for broad multi-cloud automation before target evidence exists;
- teams that want arbitrary shell access or unrestricted production agents;
- teams that need Mesh to replace their incident-management or observability stack;
- teams that require multi-tenant SaaS as the first deployment model.

### Buyer And Users

Economic buyer:

- VP Engineering;
- Head of Platform;
- Director of Infrastructure;
- SRE or Reliability leader;
- CTO at smaller companies.

Daily users:

- on-call SREs;
- platform engineers;
- service owners;
- incident commanders;
- security or compliance reviewers for audit exports.

Decision influencers:

- security engineering;
- compliance;
- infrastructure finance or FinOps when Mesh controls expensive resources;
- developer experience leads when Mesh becomes part of the paved road.

## Market Positioning

Mesh should be positioned as a controlled remediation layer after detection and before action.

Current market reference points:

- PagerDuty AIOps positions around alert-noise reduction, incident visibility, triage, event orchestration, and automation, with public AIOps pricing starting at $699/month on annual billing as checked on May 11, 2026: [PagerDuty AIOps](https://www.pagerduty.com/platform/aiops/) and [PagerDuty AIOps pricing](https://www.pagerduty.com/pricing/aiops/).
- Datadog Workflow Automation positions around automating remediation across the customer's stack with out-of-box actions, blueprints, and monitor-triggered workflows: [Datadog Workflow Automation](https://www.datadoghq.com/product/workflow-automation/).
- Resolve.ai positions as AI for production across code, infrastructure, and telemetry, including incident investigation, cost optimization, code snippets, postmortems, and remediation command generation: [Resolve.ai](https://resolve.ai/).
- OpenSRE positions as open-source agentic alert investigation and RCA before paging: [OpenSRE](https://www.opensre.com/).

Mesh should not claim it is bigger, better, or more complete than these categories. The defensible claim is narrower: Mesh is the self-hosted, evidence-first remediation authority layer for teams that need controlled action, explicit approval, rollback evidence, and customer-owned run history.

## Competitive Map

| Category | Buyer expectation | Mesh posture |
| --- | --- | --- |
| Observability | Detect, visualize, alert, retain telemetry | Integrates downstream; does not replace detection |
| Incident management | Page, route, coordinate, communicate | Integrates downstream; does not replace paging or ITSM |
| AIOps | Reduce noise, correlate events, accelerate triage | Competes only where AIOps claims action authority without enough local proof |
| Workflow automation | Build reusable automations across systems | Complements or wraps high-risk workflows with policy, evidence, and approval |
| AI SRE / RCA | Investigate incidents and recommend fixes | Mesh goes beyond RCA only for bounded, evaluated, audited actions |
| Internal platform | Paved-road operational workflows | Mesh can become the remediation and action-control surface |

## Wedge

The initial wedge is a Kubernetes remediation pilot:

- one service;
- one namespace;
- approval gate forced;
- live execution off until allowlists and ingress are verified;
- one allowed remediation action;
- one denied or escalated action;
- rollback metadata;
- live feedback or live re-harvest;
- exported run packet;
- design-partner signoff.

This wedge is narrow enough to prove safely and valuable enough to expose the product's differentiated control loop.

## Product Packaging

### Community / Local Proof

Purpose:

- developer adoption;
- local demonstrations;
- reproducible proof artifacts;
- contributor trust.

Includes:

- local runtime;
- fixtures and simulations;
- browser operator UI;
- local vault and Merkle proof surfaces;
- public proof package generation where available.

Commercial role:

- lead generation;
- technical proof for buyers;
- repeatable demo path.

### Team Pilot

Purpose:

- paid 90-day design-partner engagement.

Includes:

- private deployment support;
- one environment;
- one namespace or bounded target class;
- one to two services;
- approval-gated live action;
- run export and postmortem package;
- readiness and go/no-go review.

Pricing hypothesis:

- $15,000 to $30,000 fixed pilot fee for 90 days;
- credited toward an annual contract only when the pilot converts.

The pilot can include a 30-day controlled live window inside the 90-day engagement. The remaining time is for qualification, private deployment, policy review, evidence capture, and conversion planning.

### Production Platform

Purpose:

- ongoing use by platform, SRE, and infrastructure teams.

Includes:

- private deployment;
- Postgres-backed persistence;
- authenticated ingress;
- operator roles;
- readiness profiles;
- connector certification;
- policy lifecycle;
- run exports;
- support SLA;
- quarterly proof review.

Pricing hypothesis:

- $4,000 to $8,000 per month platform base;
- usage component by protected service, namespace, or action class;
- premium support for production incident windows.

Do not make token usage the main price lever. Track model and inference cost internally, but charge for controlled remediation scope, proof burden, protected environments, and support tier.

### Regulated / Private Deployment

Purpose:

- regulated, air-gapped, VPC-only, or security-sensitive buyers.

Includes:

- procurement security package;
- audit export package;
- custom deployment runbooks;
- private model and Mesh Brain proof lanes where approved;
- longer retention, backup, restore, and compliance evidence.

Pricing hypothesis:

- $60,000 to $150,000 annual platform minimum;
- services package for deployment, validation, and proof packet capture;
- separate pricing for Mesh Brain model-lifecycle work.

These are validation bands, not final SKUs. Price around controlled production authority and proof burden, not seats alone.

## Go-To-Market

### Entry Motion

Lead with proof, not broad category messaging.

Do not start with a procurement-heavy enterprise motion. Start with practitioner proof, convert it into a team safety case, then expand into platform governance after observed runs justify it.

Primary entry assets:

- five-minute local demo;
- thirty-minute staging guide;
- enterprise evaluation kit;
- design partner packet;
- production readiness validation record;
- public proof package;
- one recorded Kubernetes rollback or denied-action walkthrough.

Primary call to value:

- "Bring one low-blast-radius service. Mesh will prove one allowed action, one denied action, approval, feedback, and audit export without bypassing your existing monitoring stack."

### Sales Motion

1. Technical discovery:
   - target service;
   - incident class;
   - existing detection source;
   - allowed action;
   - rollback path;
   - approval authority;
   - data classes;
   - deployment constraints.

2. Local proof:
   - run fixture or simulation;
   - inspect evidence graph;
   - show approval gate and Merkle proof;
   - generate evaluation kit packet.

3. Private staging:
   - deploy behind authenticated ingress;
   - configure operator identity;
   - bind one live signal source;
   - keep live action disabled until allowlist review.

4. Controlled pilot:
   - enable one reviewed action;
   - capture allowed-action and denied-action evidence;
   - verify readiness and go/no-go packets;
   - produce post-pilot review.

5. Expansion:
   - add services only after owner approval, policy review, rollback review, dry-run evidence, and connector certification.

### Distribution

Initial channels:

- open-source repository and technical proof docs;
- platform engineering communities;
- SRE and incident-response communities;
- AI infrastructure operators;
- crypto and bare-metal node operators;
- MSP and SI partners for managed operational environments.

Avoid broad paid acquisition until the design-partner package converts reliably.

## 90-Day Pilot Plan

### Days 0-15: Qualification And Scope

Deliverables:

- signed pilot scope;
- one service and one incident class;
- data handling terms;
- action and rollback definition;
- operator roles;
- deployment target;
- success metrics.

Exit criteria:

- no unrestricted action surface;
- no raw secrets required;
- customer accepts approval-gated default;
- target can provide signal and feedback evidence.

### Days 16-35: Private Deployment

Deliverables:

- Mesh deployed in private environment;
- authenticated ingress;
- operator headers or equivalent identity propagation;
- Postgres or agreed persistence mode;
- readiness profile visible;
- live action still disabled by default.

Exit criteria:

- health and readiness inspectable;
- mutating APIs record operator identity;
- run export works;
- kill switch verified.

### Days 36-60: Dry Runs And Policy Review

Deliverables:

- fixture and captured-signal runs;
- policy simulator output;
- denied-target test;
- rollback metadata review;
- service-owner approval.

Exit criteria:

- one dry run reaches expected decision;
- one unsafe or out-of-scope request blocks;
- service owner can explain the decision path from artifacts.

### Days 61-80: Controlled Live Action

Deliverables:

- one approved live action or clean human-review rejection;
- live feedback or live Kubernetes re-harvest;
- post-action artifact package;
- run export and proof review.

Exit criteria:

- allowed action evidence captured;
- denied action evidence captured;
- no proposal lane receives production credentials;
- rollback path remains available.

### Days 81-90: Business Review

Deliverables:

- pilot report;
- go/no-go packet;
- expansion backlog;
- conversion proposal.

Exit criteria:

- buyer agrees on measured value;
- operator team agrees on trust posture;
- expansion service candidates have explicit owners.

## Metrics

### Product Metrics

- run completion rate;
- correct pause or escalation rate;
- unsafe autonomous action rate;
- approval latency;
- evaluation latency;
- action latency;
- feedback success rate;
- denied-action clarity;
- run export success rate;
- evidence sufficiency pass rate;
- rollback metadata coverage.

### Business Metrics

- design-partner qualification rate;
- local demo to staging conversion;
- staging to paid pilot conversion;
- paid pilot to annual conversion;
- average contract value;
- time to first private run;
- time to first approved live action;
- support hours per pilot;
- expansion services per customer.

### North-Star Metric

The strongest near-term north-star metric is not raw automation count. It is "reviewed remediation runs with complete evidence, correct gate behavior, and accepted operator outcome."

This rewards safe pauses and denials when they are the correct product behavior.

The long-term protocol metric is preserved state slices with verified remediation paths: domains where Mesh can prove ownership, evidence, policy, approval, action, feedback, rollback, and replay across repeated runs.

## 12-Month Operating Plan

### Quarter 1: Proof And Design Partners

Goals:

- package local proof and 90-day pilot assets;
- record a reproducible Kubernetes demo;
- sign 2 to 3 design partners;
- keep every public claim tied to evidence.

Product priorities:

- simplify onboarding for one pilot scenario;
- tighten run export and evaluation-kit flow;
- improve denied-action explanations;
- make the sales demo repeatable without private credentials.

### Quarter 2: Pilot Conversion

Goals:

- complete at least two controlled pilots;
- convert one or more pilots to annual platform contracts;
- prove private staging deployment without core-team handholding.

Product priorities:

- authenticated ingress proof capture;
- Postgres persistence path;
- provider action-scope proof;
- live feedback source proof;
- operator approval queue rehearsal.

### Quarter 3: Expansion

Goals:

- expand within converted customers from one service to multiple services;
- add MSP or SI partner pipeline;
- publish a public proof package with limitations.

Product priorities:

- connector certification maturity;
- service-owner workflow;
- multi-operator load and concurrency proof;
- incident coverage proof from target environments.

### Quarter 4: Platform Maturity

Goals:

- reach repeatable production-platform packaging;
- establish annual contracts as the default sales motion;
- choose whether Mesh Brain remains an advanced add-on or separate product line;
- publish a protocol v0 draft for preservation and remediation contracts.

Product priorities:

- external audit sink;
- procurement security package completion;
- backup and restore rehearsal automation;
- regulated deployment runbooks;
- target-specific provider adapters;
- connector manifest shape for state slice, preservation capability, remediation capability, authority, rollback, and proof requirements.

## Financial Planning Model

Use a conservative bottoms-up model until real conversion data exists.

Planning assumptions:

- 2 to 3 paid design partners in the first quarter;
- 60 to 90 days from signed pilot to conversion decision;
- 30% to 60% pilot conversion target after the first two pilots establish the runbook;
- $48,000 to $96,000 annual contract value for early production-platform customers;
- higher ACV only when private deployment, compliance, or Mesh Brain model-lifecycle support is included;
- services revenue should pay for deployment and proof capture without becoming the main business.

Do not publish top-down market-size claims until the company has a defensible account universe, win-rate, and pricing data from pilots.

## Product Roadmap Boundaries

### Must Ship Before Broad Pilot Claims

- authenticated ingress proof from target environment;
- operator identity on every mutating event;
- backup and restore rehearsal;
- complete release provenance for the runtime image;
- live feedback source proof;
- design-partner packet;
- allowed-action and denied-action evidence;
- clean current-head readiness or explicit blocker report.

### Must Ship Before Production Expansion Claims

- Postgres-backed production persistence as default;
- multi-operator load and concurrency rehearsal;
- live watch-mode packet;
- live incident coverage packet;
- live production target proof;
- aggregate production-autonomy clearance without fixture exceptions;
- target-specific connector certification;
- external audit export path;
- documented support and escalation model.

### Must Ship Before Protocol Claims

- versioned preservation and remediation contract schemas;
- connector manifest verification for explicit state slices;
- replayable proof packets for at least three distinct domains;
- adapter certification that separates preservation-only, advisory remediation, approval-gated remediation, and autonomous remediation scopes;
- public limitations statement that names unsupported targets and unsupported action classes;
- governance process for adding new domains without weakening existing authority boundaries.

### Mesh Brain Commercial Boundary

Mesh Brain should be framed as an expansion lane, not the first commercial dependency.

Near-term commercial use:

- private model-lifecycle proof;
- eval-gated agent runtime;
- posttraining and artifact registry demos;
- hardware-aware serving economics for design partners that already need private AI infrastructure.

Do not make Mesh Brain the core paid pilot unless the customer is specifically buying private model lifecycle and has the data, hardware, and governance posture to validate it.

## Risks And Mitigations

| Risk | Business impact | Mitigation |
| --- | --- | --- |
| Overclaiming production readiness | Loss of buyer trust | Tie every claim to readiness, go/no-go, and proof packets |
| Competing directly with observability platforms | Bad positioning and long sales cycles | Sell downstream controlled remediation, not detection replacement |
| Pilot setup is too heavy | Slow conversion | Narrow to one service, one action, one environment, one owner |
| Exposing the control plane without auth | Production security failure | Require private network or authenticated TLS reverse proxy before external human testing |
| Live action without complete gates | Customer-impacting incident | Keep approval, policy, evaluation, allowlist, rollback, and kill switch gates non-negotiable |
| Automation fear blocks adoption | No live-action approval | Treat denied actions and correct pauses as success cases |
| Support burden overwhelms product work | Services trap | Standardize evaluation kit, deployment guide, packet verifier, and run export review |
| Competitors have stronger UX and integrations | Buyer prefers packaged SaaS | Win on self-hosted control, audit, policy, and customer-owned data |
| Connector proof gaps block expansion | Limited ACV | Prioritize certified high-value connectors only after pilots prove demand |
| Mesh Brain distracts from remediation wedge | Diffuse roadmap | Keep Mesh Brain as controlled add-on until remediation GTM converts |
| Dirty or stale proof artifacts leak into sales | Credibility loss | Use current-head, runtime-bound proof only; mark historical evidence clearly |

## Public Messaging Rules

Use:

- policy-guided;
- bounded remediation;
- preservation and remediation protocol;
- operator-steerable;
- evaluation-gated;
- evidence-first;
- customer-owned run history;
- controlled production action;
- verifiable remediation records.

Avoid:

- self-healing;
- generic AI-powered operations;
- full autonomy;
- all orchestrators supported;
- production-ready for every environment;
- replaces observability;
- replaces incident management;
- unrestricted agents in production.

One-line positioning:

Near term: Mesh is the self-hosted control plane that lets platform and SRE teams turn existing alerts into bounded, evaluated, operator-approved remediation runs with replayable audit evidence.

Long term: Mesh is the preservation and remediation protocol for systems that need verifiable state history, explicit authority, and controlled recovery.

## Immediate Next Actions

1. Create a one-page design-partner offer from this plan.
2. Record the local Kubernetes proof path end to end.
3. Generate one sample evaluation-kit packet and use it as the standard sales artifact.
4. Choose one pilot wedge and remove secondary narratives from the first sales motion.
5. Keep production-readiness claims blocked until the target runtime produces current proof.
6. Draft `mesh.protocol.v0` around state slices, preservation contracts, remediation contracts, trust contracts, and connector extension rules.
