# Perennial, Darkharness, and Darkmesh Architecture

## Decision

Perennial is a proposed quantum-safe psychohistorical governance substrate for
operational systems. In this context, "psychohistorical" means longitudinal
governance over human, agent, and service actions using observed evidence,
policy state, operator authority, and cryptographic proofs. It does not mean
deterministic prediction of society or unsupported autonomous control.

Darkharness is the hardened governance product layer. It packages Perennial
governance records, policy review, approvals, crypto assurance, run exports,
and board/operator audit packets.

Darkmesh is the on-prem runtime built over `orbital-mesh`. It keeps the existing
runtime shape and extends it through docs-first contracts before code changes.
This phase does not rename the repo, fork the runtime, or implement new runtime
behavior.

## Product Boundary

Implemented today in `orbital-mesh`:

- evidence packs and evidence graphs;
- scenario analysis between trigger and final decision;
- decision and evaluation gates;
- remediation safety scoring and hard stops;
- trust ladder evidence for autonomy ceilings;
- operator identity, roles, approvals, and steering;
- run events, vault notes, Merkle roots, and event proofs;
- readiness profiles;
- run export packages;
- pilot go/no-go packet generation from observed evidence.

Proposed by this document:

- Perennial reservoir governance and action ledger contracts;
- Darkharness governance product packet;
- Darkmesh on-prem pilot runtime profile;
- concurrent epistemic and ontological state records;
- signed governance records;
- crypto-agile PQC-ready signature/KEM interfaces;
- zero-knowledge proof hooks for selective disclosure.

Not implemented today:

- production post-quantum cryptography;
- production zero-knowledge proofs;
- global decentralized agent registry;
- public-chain governance;
- automated liability adjudication;
- internet-scale action ingestion beyond configured sources;
- autonomous production-impacting remediation without existing Mesh gates.

## External Thesis Grounding

Reference files read from the adjacent local `mesh/docs/lit/` folder:

- `2412.17114v3.pdf`;
- `AI Governance Gaps_ Where CEOs and Boards Disagree _ BCG.pdf`;
- `WEF_Empowering_Defenders_AI_for_Cybersecurity_2026.pdf`.

`2412.17114v3.pdf` argues for decentralized AI-agent governance using an agent
registry, dynamic risk classification, compliance monitoring, zero-knowledge
proofs, audit trails, dispute handling, and liability framing. Perennial adapts
those ideas to an enterprise on-prem control plane. The first version uses local
registry records, local Merkle/event proofs, signed governance commits, and
selective-disclosure hooks. It does not require or claim a public blockchain.

The BCG governance gaps PDF frames a CEO/board mismatch: leaders agree on the
need for AI governance in theory but diverge on hype versus reality, speed
versus oversight, responsibility allocation, and accountability. The Darkharness
packet exists to give executives, boards, CISOs, platform leaders, and operators
the same evidence object instead of separate narrative summaries.

The WEF cybersecurity PDF frames defender-side AI as useful for cyber
governance, risk identification, protection, detection, incident response, and
recovery, but warns that deployment must be validated through pilots, matched to
risk and reversibility, and preserve human judgment under automation. The first
Darkmesh pilot follows that pattern: pre-emptive anomaly detection is allowed,
but production-impacting remediation remains approval-required.

## Operating Principles

1. Sensitive data stays on-prem by default.
2. Reservoir access is explicit, scoped, logged, and revocable.
3. Evidence and policy are necessary but not sufficient for action.
4. Production-impacting actions require operator authority unless an existing
   trust-ladder level, service policy, rollback proof, and deterministic safety
   gate all allow narrower autonomy.
5. Denied actions are first-class outcomes and must be exportable as proof.
6. Concurrent states are preserved instead of overwritten when facts conflict.
7. Crypto assurance is agile: Merkle proofs are the implemented baseline;
   signatures, PQC interfaces, and ZK hooks are proposed extension points.
8. Claims must label implemented runtime capability separately from roadmap
   capability.

## Existing Orbital-Mesh Anchors

| Anchor | Current repo surface | Perennial use |
| --- | --- | --- |
| Evidence packs | `services/evidence`, run evidence artifacts | Input to `GovernanceCommit.evidence_refs` |
| Scenario analysis | `docs/scenario-analysis.md`, `services/scenario_analysis` | Advisory multi-state evidence before final decision |
| Decision/evaluation | `services/decision`, `services/evaluation`, `docs/architecture/api-and-runtime-map.md` | Governance kernel action recommendation and gate result |
| Remediation safety | `shared/mesh_runtime/remediation_safety.py`, `docs/remediation-safety-loop.md` | Deterministic safety gate before commit |
| Trust ladder | `shared/mesh_runtime/trust_ladder.py`, `/api/trust-ladder` | Earned autonomy ceiling per action class and service |
| Operator approvals | authenticated ingress and steering APIs | Authority proof for production actions |
| Run events | `RunEvent`, state stores, run APIs | Append-only action and governance timeline |
| Vault/Merkle proofs | `shared/mesh_runtime/merkle.py`, vault mirror | Implemented proof baseline |
| Readiness profiles | `MESH_READINESS_PROFILE`, `/api/readiness` | Pilot entry and hard-stop state |
| Run exports | `/api/runs/{run_id}/export` | Audit-ready Darkharness packet material |
| Pilot go/no-go | `/api/pilot/go-no-go` | Pilot packet readiness source |

## End-to-End Runtime Blueprint

Darkmesh should be implemented as a projection over the existing Mesh control
loop before introducing new execution paths.

```text
source signal or reservoir projection
  -> existing Mesh ingest where supported
  -> evidence pack
  -> scenario analysis
  -> concurrent epistemic and ontological state snapshots
  -> existing decision service
  -> existing evaluation service
  -> remediation safety case
  -> trust-ladder ceiling check
  -> operator authority check
  -> governance commit
  -> proof envelope
  -> existing actuator only if allowed
  -> feedback evidence
  -> run export and Darkharness pilot packet
```

Implementation rule: every Perennial object must be derivable from existing run
state, registered reservoir metadata, or a signed operator/policy input. If an
object cannot be traced to one of those sources, it is not admissible evidence.

## Source Adapter Map

| Source | Current support | Darkmesh v1 behavior | Pilot limit |
| --- | --- | --- | --- |
| Kubernetes signals | Existing live signal and watcher paths | Convert deployment health, events, pod state, and remediation output into `AgentActionRecord`, `EpistemicState`, and `GovernanceCommit` inputs | One context, namespace, and service group |
| OTel metrics | Existing OTLP receiver and Prometheus feedback/pull support | Use metrics as anomaly and feedback evidence; raw high-cardinality storage remains future work unless the metrics engine plan lands first | One collector or Prometheus endpoint |
| Vendor/security webhooks | Existing webhook templates for alert sources | Normalize security, compliance, and vendor alerts into advisory governance triggers and denied/allowed action evidence | One security webhook source |
| Audit/compliance signals | Proposed | Ingest signed or hashed findings as policy/evidence records without granting actuator authority | One audit source |
| Policy documents | Existing docs/policy files plus proposed reservoir registration | Treat policy docs as governed reservoirs with owner, hash, version, and effective window | One policy collection |
| Service ownership metadata | Proposed | Bind services, owners, escalation paths, allowed actions, and approval authorities into `OntologicalState` | One ownership registry |
| Sensitive internal reservoirs | Proposed | Register on-prem data sources, expose only redacted/hash/aggregate projections, log all access attempts | One reservoir class |

## Governance Gate Matrix

Production-impacting remediation requires every gate below to pass. Failure at
any gate emits a denied `GovernanceCommit`, not a silent no-op.

| Gate | Implemented anchor | Required evidence |
| --- | --- | --- |
| Signal admissibility | Ingest schema validation and normalized events | Valid signal or explicit unsupported-source denial |
| Evidence sufficiency | Evidence pack and scenario analysis | Evidence refs, analyzer outputs, missing-evidence list |
| Decision boundedness | `DecisionService` | Existing decision type, target, risk, autonomy tier |
| Evaluation pass | `EvaluationService` | Recommendation, blockers, policy allowlist result |
| Remediation safety | `shared/mesh_runtime/remediation_safety.py` | Safety score, hard stops, rollback/idempotency readiness |
| Trust ladder | `TrustLadder` | Current level, blockers, promotion requirements, override reason if present |
| Operator authority | Authenticated ingress and steering records | Operator id, roles, source, approval event id |
| Target boundary | Runtime config and allowlists | Environment, namespace, host/service allowlist, customer boundary |
| Rollback proof | Decision/evaluation/execution metadata | Rollback plan, rollback drill or reviewed rollback metadata |
| Crypto proof | Merkle baseline, proposed signed records | Merkle root/proof, signature status, proof envelope |
| Exportability | Run export package | Redacted timeline, decision, evaluation, proof, feedback, retention metadata |

## Data Boundary Modes

Darkmesh must treat data movement as an explicit governance choice.

| Mode | Raw data leaves reservoir | Allowed use |
| --- | --- | --- |
| `hash_only` | No | Presence, equality, integrity, policy attestation |
| `aggregate_only` | No | Counts, rates, percentiles, compliance summary |
| `redacted_projection` | No raw data; redacted snippets only | RCA and audit packet context |
| `in_place` | No | Local model/tool execution inside on-prem boundary |
| `approved_egress` | Only with explicit scoped approval | External model or external auditor handoff |

Default pilot mode is `hash_only` or `aggregate_only` for sensitive reservoirs,
with `redacted_projection` allowed only for operator-reviewed evidence.

## Darkharness Registry Configuration

The read-only Darkharness packet export can load pilot scope and sensitive
reservoir definitions from `MESH_DARKHARNESS_REGISTRY_PATH`. The file is a JSON
object with:

- `tenant_id`;
- `pilot_scope`, validated by
  `shared/mesh_runtime/schemas/perennial/pilot-scope.schema.json`;
- `sensitive_reservoirs`, a non-empty list validated by
  `shared/mesh_runtime/schemas/perennial/sensitive-reservoir.schema.json`;
- optional `trust_ladder_ref`, `owner_registry_ref`, and `policy_refs`.

When the env var is not set, local development keeps using the existing shadow
fixture. When it is set, the file must exist and must preserve the pilot
boundaries: on-prem reservoirs, raw reservoir egress denied, external model
calls denied by default, and production-impacting actions approval-required.
Invalid registry files block packet export instead of fabricating Perennial
records.

## Packet Persistence Policy

Darkharness pilot packets are ephemeral read-only exports in this phase.
`GET /api/runs/{run_id}/darkharness-packet` materializes a packet from current
run state and returns it without writing packet files, run events, vault notes,
or audit artifacts. `MESH_DARKHARNESS_PACKET_PERSISTENCE_MODE` exists to make
that policy explicit and currently only accepts `ephemeral`.

Persisted Darkharness packets require a later audited write path with Postgres
remaining authoritative for runs, events, memory, and audit state. Until that
path exists, unsupported persistence modes fail configuration validation rather
than silently writing side effects.

## Packet Eligibility Policy

Darkharness packet materialization now passes through an explicit policy
evaluator before a full packet is returned. The evaluator blocks export when:

- production-impacting allowed actions have no operator approval record;
- production approval is not required by the pilot scope;
- raw reservoir egress is not denied;
- external model calls are not denied by default.

Policy failures return a blocked packet with `policy_violation:*` entries in
`missing_evidence` and policy booleans in `checks`. The blocked response still
does not write run events, packet files, vault notes, or audit artifacts.

## Proof Signing

`MESH_DARKHARNESS_SIGNING_KEY` enables a local HMAC-SHA256 proof over the
Darkharness proof-envelope subject, Merkle root, leaf ids, and redaction
profile. `MESH_DARKHARNESS_SIGNING_KEY_ID` identifies the configured key in the
proof envelope. When configured, `implemented_proofs.signature` is present and
the governance commit carries a `signature_ref`.

This is an implemented local integrity signature for pilot packet verification,
not a public-key signature system and not post-quantum cryptography. PQC
signatures, KEM, and ZK selective disclosure remain proposed hooks until a real
provider interface and audited key-management path are added.

## Mesh Brain Linkage

Darkharness packet export maps recorded Mesh Brain artifacts into additional
`AgentActionRecord` attestations through
`materialize_mesh_brain_action_records()`. The adapter covers dataset
provenance, training job, eval score, serving smoke, model-kernel proof, and
quality/trust-ladder update records when those artifacts already exist on the
run session.

This linkage is evidence projection only. Packet export does not launch Mesh
Brain training, model serving, backend evaluation, rollback drill, or promotion
work. Mesh Brain records are marked as on-prem, non-production-impacting
attestations so the primary remediation or denial action remains the governance
commit subject.

## Architecture Layers

### 1. Reservoir Layer

Purpose: enclave sensitive data reservoirs and expose only bounded, policy
reviewed projections to the governance runtime.

In v1, an enclave means an on-prem governance and access boundary: raw data is
processed in place, projected through redaction/hash/aggregate modes, and denied
external egress by default. Hardware TEEs can be added later as an assurance
backend, but this document does not claim TEE enforcement exists in code.

Responsibilities:

- register each sensitive reservoir with owner, data classes, locality,
  residency, retention, and allowed compute mode;
- default-deny egress for raw content;
- support on-prem-only retrieval, redaction, summarization, and hashing;
- record reservoir access as run events and `AgentActionRecord` entries;
- mark whether data is trainable, audit-only, or decision-context-only;
- maintain policy documents and service ownership metadata as governed
  reservoirs, not informal side inputs.

Inputs:

- Kubernetes object metadata and event summaries;
- OTel metrics and Prometheus pull results;
- vendor/security webhooks;
- audit and compliance signals;
- policy documents;
- service ownership metadata;
- internal logs, docs, tickets, and runbooks that the customer explicitly
  registers.

Outputs:

- redacted evidence snippets;
- content hashes;
- provenance refs;
- retrieval summaries;
- reservoir access denial records.

### 2. Agentic Action Ledger

Purpose: track human, agent, and service actions at governance resolution.

Responsibilities:

- model internet-scale action streams as partitioned, append-only records by
  tenant, actor, source, action class, target, and time, while the pilot only
  enables the configured on-prem sources;
- record every proposed action, denial, approval, execution, rollback, and
  evidence access attempt;
- attach actor identity for human, agent, service account, watcher, or model;
- normalize external agent activity into action records without granting action
  authority;
- preserve failed, denied, and abandoned actions as audit facts;
- feed trust-ladder scoring and dispute review.

The ledger is append-only at the contract level. Implementation should map it
to existing run events first, then add typed materialized views if needed.

### 3. Concurrent State Layer

Purpose: preserve multiple live interpretations of an incident, policy state,
asset model, and agent state without forcing premature convergence.

Epistemic state records answer: "What do we believe, with what confidence, and
from which evidence?"

Ontological state records answer: "What entities, relationships, ownership
claims, and policy categories currently define the world?"

Responsibilities:

- keep competing hypotheses from scenario analysis and investigation;
- mark contradiction sets and evidence gaps;
- preserve old state as superseded rather than deleted;
- distinguish raw observed fact, inferred claim, policy assertion, operator
  assertion, and model-generated claim;
- feed governance commits with a bounded state snapshot.

### 4. Governance Kernel

Purpose: decide whether Perennial has enough evidence, policy, authority, and
proof to permit, deny, or defer a remediation.

Responsibilities:

- consume evidence packs, scenario analysis, decision, evaluation, remediation
  safety, trust-ladder state, policy docs, operator authority, and proof state;
- classify risk using local policy and dynamic action history;
- force approval-required governance for production-impacting actions in v1;
- emit explicit denied-action commits when gates fail;
- record why an action is allowed, denied, deferred, or escalated;
- preserve board/operator-readable rationale without exposing raw reservoirs.

The existing `DecisionService` and `EvaluationService` remain authoritative for
current Mesh actions. Perennial governance commits wrap their outputs; they do
not bypass them.

### 5. Remediation Commit Layer

Purpose: convert a policy-allowed remediation into an auditable commit record
before execution, or a denied commit when gates fail.

Responsibilities:

- require evidence refs, policy refs, operator authority refs, rollback metadata,
  safety-gate output, and proof envelope;
- bind action target, namespace, service owner, customer boundary, and
  rollback plan;
- record allowed and denied actions symmetrically;
- route execution only through existing allowlisted actuators;
- attach post-action feedback and recovery evidence.

### 6. Crypto Assurance Layer

Purpose: make governance records verifiable while preserving on-prem data
boundaries.

Implemented baseline:

- per-run Merkle roots over run events;
- Merkle proofs for selected events;
- vault mirror and run export packets;
- Postgres restart proof for run events, memory, and Merkle roots when Postgres
  mode is configured.

Proposed v1 extension:

- signed governance records using a configured signing profile;
- key identifiers and algorithm metadata on every `ProofEnvelope`;
- crypto-agile interfaces for classical signatures and PQC-ready signatures;
- KEM interface placeholder for future sealed proof sharing;
- ZK proof hook fields for selective disclosure of compliance facts.

Boundary:

- Do not claim production PQC or ZK until implementation and verification exist.
- Do not export raw sensitive reservoir content to prove compliance by default.
- Selective disclosure proves predicates over records, not unrestricted data
  access.

### 7. Pilot Runtime

Purpose: run the first Perennial/Darkmesh pilot as a bounded on-prem production
suite.

Included domains:

- Ops;
- Cyber;
- AI governance;
- infrastructure remediation.

Required sources:

- Kubernetes signals;
- OTel metrics;
- vendor/security webhooks;
- audit/compliance signals;
- policy documents;
- service ownership metadata;
- sensitive internal reservoirs registered with default-deny egress.

Allowed pilot behavior:

- predict anomalies before existing chaos or incident thresholds;
- open advisory hypotheses and governance commits;
- recommend remediation;
- prove allowed and denied action paths;
- export audit-ready evidence;
- update trust-ladder evidence from observed outcomes.

Restricted pilot behavior:

- no raw sensitive data leaves on-prem by default;
- no production-impacting action executes without approval-required governance;
- no external model receives private repo state, reservoir contents, traces, or
  customer data unless a separate explicit approval and redaction policy exists;
- no repo rename, code fork, runtime fork, or hidden actuator path;
- no autonomy expansion without trust-ladder evidence, policy review, rollback
  proof, and deterministic safety gates.

## Proposed v1 Contracts

These are proposed contracts. They are not implemented schemas yet.

### `AgentActionRecord`

Purpose: normalize human, agent, service, watcher, and model actions.

```yaml
contract: perennial.agent_action_record.v1
required:
  action_record_id: string
  observed_at: string
  actor:
    actor_type: human | agent | service | watcher | model | external_system
    actor_id: string
    display_name: string | null
    authority_source: proxy_header | service_account | registry | inferred | unknown
  action:
    action_class: observe | retrieve | propose | approve | deny | execute | rollback | export | attest
    action_type: string
    target:
      environment: string
      service: string | null
      namespace: string | null
      resource_ref: string | null
      reservoir_id: string | null
    production_impact: none | possible | direct
  context:
    run_id: string | null
    run_event_id: string | null
    decision_id: string | null
    evaluation_id: string | null
    feedback_id: string | null
    source_system: string
  governance:
    risk_tier: minimal | moderate | high | unacceptable | unknown
    autonomy_tier: no_action | advisory | approval_required | autonomous | escalated
    policy_refs: list[string]
    evidence_refs: list[string]
    proof_refs: list[string]
    operator_authority_refs: list[string]
  outcome:
    status: observed | proposed | approved | denied | executed | failed | rolled_back | superseded
    denial_reasons: list[string]
    rollback_ref: string | null
    side_effect_refs: list[string]
  boundary:
    tenant_id: string
    data_boundary: on_prem | approved_egress | public_demo
    reservoir_refs: list[string]
```

### `SensitiveReservoir`

Purpose: register sensitive internal data reservoirs and allowed processing.

```yaml
contract: perennial.sensitive_reservoir.v1
required:
  reservoir_id: string
  name: string
  owner:
    team: string
    service_owner: string
    data_steward: string
  classification:
    data_classes: list[operational | security | compliance | customer | source_code | secret_adjacent | regulated | audit_only]
    sensitivity: public | internal | confidential | restricted | regulated
    trainable: prohibited | opt_in | allowed_redacted
  locality:
    boundary: on_prem
    region: string
    storage_ref: string
    external_egress_default: deny
  access_policy:
    allowed_purposes: list[rca | feedback | audit | policy_check | training | export]
    allowed_compute_modes: list[in_place | redacted_projection | hash_only | aggregate_only]
    approval_required: boolean
    retention_days: integer
  projection:
    redaction_profile: string
    max_snippet_chars: integer
    hash_algorithm: string
    allowed_index_fields: list[string]
  crypto:
    encryption_profile: string
    signing_profile: string | null
    pqc_profile: string | null
```

### `EpistemicState`

Purpose: preserve concurrent beliefs, hypotheses, confidence, and evidence.

```yaml
contract: perennial.epistemic_state.v1
required:
  epistemic_state_id: string
  subject_ref: string
  run_id: string | null
  created_at: string
  claims:
    - claim_id: string
      claim_type: observation | hypothesis | inference | policy_assertion | operator_assertion | model_assertion
      statement: string
      confidence: number
      evidence_refs: list[string]
      contradicted_by: list[string]
      source: string
      status: active | disputed | superseded | rejected
  uncertainty:
    missing_evidence: list[string]
    competing_hypotheses: list[string]
    confidence_floor: number
    confidence_ceiling: number
  governance_use:
    usable_for_decision: boolean
    usable_for_execution: boolean
    review_required: boolean
```

### `OntologicalState`

Purpose: preserve concurrent entity, ownership, policy, and relationship state.

```yaml
contract: perennial.ontological_state.v1
required:
  ontological_state_id: string
  namespace: string
  created_at: string
  schema_version: string
  entities:
    - entity_id: string
      entity_type: service | deployment | host | agent | model | policy | reservoir | owner | control
      labels: map[string,string]
      source_refs: list[string]
      confidence: number
      status: active | disputed | superseded
  relationships:
    - relationship_id: string
      subject_id: string
      predicate: owns | deploys | depends_on | controls | observes | remediates | stores | governs
      object_id: string
      evidence_refs: list[string]
      confidence: number
      status: active | disputed | superseded
  conflict_sets:
    - conflict_id: string
      entity_or_relationship_refs: list[string]
      resolution: unresolved | operator_selected | policy_selected | time_bounded
      selected_ref: string | null
```

### `GovernanceCommit`

Purpose: bind evidence, policy, authority, safety, and proof into a decision to
allow, deny, defer, or escalate action.

```yaml
contract: perennial.governance_commit.v1
required:
  governance_commit_id: string
  created_at: string
  commit_type: allow_action | deny_action | defer_action | escalate | export_attestation
  subject:
    run_id: string
    trigger_id: string | null
    decision_id: string | null
    evaluation_id: string | null
    action_record_id: string | null
  state_refs:
    epistemic_state_id: string
    ontological_state_id: string
  inputs:
    evidence_refs: list[string]
    scenario_analysis_ref: string | null
    policy_refs: list[string]
    remediation_safety_ref: string | null
    trust_ladder_ref: string | null
    readiness_ref: string | null
  authority:
    operator_required: boolean
    operator_approval_refs: list[string]
    service_owner_refs: list[string]
  action:
    action_type: string | null
    target_ref: string | null
    production_impact: none | possible | direct
    rollback_ref: string | null
  proof:
    proof_envelope_id: string
    merkle_root: string | null
    signature_ref: string | null
  outcome:
    gate_result: allowed | denied | deferred | escalated
    reasons: list[string]
    expires_at: string | null
```

### `ProofEnvelope`

Purpose: carry Merkle, signature, PQC-ready, and ZK-selective disclosure proof
metadata for governance records.

```yaml
contract: perennial.proof_envelope.v1
required:
  proof_envelope_id: string
  created_at: string
  subject_refs: list[string]
  implemented_proofs:
    merkle:
      run_id: string | null
      root_hash: string | null
      leaf_event_ids: list[string]
      proof_refs: list[string]
      verifier: orbital_mesh_merkle_v1
  proposed_proofs:
    signature:
      signing_profile: string
      algorithm: string
      key_id: string
      signature: string | null
      status: proposed | present | verified | failed
    pqc_signature:
      interface: pqc_signature_v1
      algorithm: string | null
      key_id: string | null
      signature: string | null
      status: proposed
    kem:
      interface: pqc_kem_v1
      algorithm: string | null
      encapsulated_key_ref: string | null
      status: proposed
    zk:
      hook: selective_disclosure_v1
      statement: string
      public_inputs: map[string,string]
      proof_ref: string | null
      status: proposed
  disclosure:
    raw_sensitive_data_included: false
    redaction_profile: string
    exported_fields: list[string]
```

### `PilotScope`

Purpose: define the bounded on-prem pilot.

```yaml
contract: perennial.pilot_scope.v1
required:
  pilot_scope_id: string
  customer_boundary: string
  environment:
    name: string
    readiness_profile: pilot
    on_prem_only: true
    postgres_required: true
  domains:
    ops: true
    cyber: true
    ai_governance: true
    infrastructure_remediation: true
  sources:
    kubernetes_signals: enabled
    otel_metrics: enabled
    vendor_security_webhooks: enabled
    audit_compliance_signals: enabled
    policy_docs: enabled
    service_ownership_metadata: enabled
    sensitive_reservoirs: enabled
  authority:
    default_steering_mode: approval_gate
    production_actions_approval_required: true
    proposal_lanes_advisory_only: true
    trust_ladder_can_expand: false
  action_limits:
    allowed_action_classes: list[string]
    denied_action_classes: list[string]
    allowed_namespaces: list[string]
    allowed_services: list[string]
    max_parallel_live_actions: integer
  evidence_requirements:
    allowed_action_proof: true
    denied_action_proof: true
    rollback_metadata: true
    merkle_proof: true
    run_export: true
    go_no_go_packet: true
  data_boundary:
    raw_reservoir_egress: deny
    external_model_calls: deny_by_default
    export_redaction_required: true
```

## Governance Flow

1. Ingest signal from Kubernetes, OTel, webhook, audit/compliance stream,
   policy document change, service ownership change, or reservoir projection.
2. Normalize the signal through existing Mesh ingest paths where supported.
3. Attach reservoir and action-ledger context without exporting raw reservoir
   content.
4. Build evidence pack and scenario analysis.
5. Preserve concurrent epistemic and ontological state snapshots.
6. Run existing decision and evaluation gates.
7. Run remediation safety and trust-ladder ceiling checks.
8. Require operator approval for production-impacting pilot actions.
9. Build `GovernanceCommit`.
10. Bind the commit to `ProofEnvelope` using Merkle baseline and proposed
    signature/PQC/ZK fields.
11. Execute only through existing allowlisted actuators when allowed.
12. Record feedback, rollback evidence, denied-action evidence, and export
    packet material.

## Darkharness Packet Shape

Darkharness should emit a single audit packet per pilot checkpoint.

```yaml
packet: darkharness.pilot_packet.v1
required:
  packet_id: string
  generated_at: string
  customer_boundary: string
  pilot_scope_id: string
  implemented_evidence:
    readiness: object
    go_no_go: object
    run_exports: list[object]
    merkle_proofs: list[object]
    denied_action_proofs: list[object]
    allowed_action_proofs: list[object]
    postgres_restart_proof: object | null
  perennial_records:
    sensitive_reservoirs: list[SensitiveReservoir]
    agent_action_records: list[AgentActionRecord]
    epistemic_states: list[EpistemicState]
    ontological_states: list[OntologicalState]
    governance_commits: list[GovernanceCommit]
    proof_envelopes: list[ProofEnvelope]
  boundaries:
    raw_reservoir_egress: deny | approved_exception
    external_model_calls: deny | approved_exception
    production_actions_approval_required: true
  claim_boundary:
    implemented: list[string]
    proposed: list[string]
    not_implemented: list[string]
```

Packet invariant: `implemented_evidence` can cite only real observed Mesh
outputs. `perennial_records` may be proposed/shadow records until their schemas
and materializers exist, but the packet must label that status.

## Pilot Packet

The first pilot packet is a Darkharness export over existing Mesh packet
material plus proposed Perennial records.

Required implemented evidence:

- `/api/readiness` with `pilot` profile ready;
- `/api/pilot/go-no-go` generated from observed evidence;
- one approved production-shaped action or controlled live action with rollback
  metadata;
- one denied action with explicit blocker evidence;
- operator identity and role on mutating actions;
- Merkle root and selected event proof;
- run export package with timeline, decision, evaluation, execution or denial,
  feedback or missing-evidence reason, vault notes, and redacted artifacts;
- Postgres restart proof where `MESH_STATE_BACKEND=postgres`.

Required proposed evidence for Perennial pilot readiness:

- `PilotScope` approved by customer owner and service owner;
- at least one registered `SensitiveReservoir` with egress denied by default;
- `AgentActionRecord` entries for observe, propose, approve or deny, and export;
- `EpistemicState` preserving at least two competing hypotheses or one explicit
  no-contradiction set;
- `OntologicalState` with service owner, deployment, policy, and reservoir
  relationships;
- `GovernanceCommit` for an allowed path and a denied path;
- `ProofEnvelope` showing implemented Merkle proof plus proposed signature/PQC/ZK
  extension status.

## Production-Safe Pilot Scope

Default pilot:

- one customer boundary;
- one on-prem environment;
- one Kubernetes context;
- one namespace;
- one service group;
- one security webhook source;
- one OTel/Prometheus metric source;
- one audit/compliance source;
- one policy document collection;
- one service ownership registry;
- one sensitive reservoir class.

Hard stops:

- mutating API without operator identity;
- raw reservoir data egress without explicit approval;
- production action without approval, policy pass, evaluation pass, safety pass,
  target allowlist, rollback metadata, and proof envelope;
- trust ladder promotion without enough observed outcomes;
- missing denied-action proof in pilot packet;
- missing run export redaction;
- failed Merkle proof;
- failed Postgres restart proof when Postgres mode is in pilot scope;
- external model call receiving private reservoir data by default.

Success metrics:

- anomaly detected or predicted before configured chaos/incident threshold in at
  least one controlled scenario;
- allowed action path proves evidence, policy, authority, rollback, and Merkle
  continuity;
- denied action path proves blocker reasons without operator ambiguity;
- audit packet is reviewable without raw reservoir access;
- no sensitive reservoir raw content leaves on-prem boundary by default;
- operators can explain why autonomy was capped.

## Pilot Day-0 Runbook

1. Freeze `PilotScope`.
2. Register the service owner, data steward, operator approvers, and escalation
   owner.
3. Register one `SensitiveReservoir` with `external_egress_default: deny`.
4. Configure one Kubernetes context and namespace.
5. Configure one OTel/Prometheus metric source.
6. Configure one security webhook source.
7. Register policy documents and service ownership metadata with content hashes.
8. Set readiness profile to `pilot`.
9. Keep steering mode at `approval_gate`.
10. Run readiness, production smoke, authenticated ingress proof, Postgres
    restart proof when applicable, and pilot go/no-go.
11. Execute one controlled allowed path and one controlled denied path.
12. Export the run package and Darkharness packet.

## Pilot Exit Criteria

Exit as `go` only when all are true:

- readiness profile is `pilot` and ready;
- at least one allowed action path has rollback metadata and feedback evidence;
- at least one denied action path has blocker evidence;
- all mutating events have operator identity;
- raw reservoir egress is denied or explicitly exceptioned;
- no external model call received private reservoir data by default;
- Merkle proof validates for selected evidence events;
- run export is redacted and retention metadata is present;
- trust ladder does not silently expand production autonomy;
- service owner and operator can explain the allowed and denied paths from the
  packet alone.

Exit as `no-go` when any hard stop in this document occurs. A no-go packet is
still a valid Darkharness artifact and should be retained for audit.

## Crypto-Agile Design

Baseline now:

- Merkle root over run events;
- event proof endpoint;
- vault mirror;
- run export package;
- Postgres restart proof in Postgres mode.

v1 implementation target:

- sign `GovernanceCommit` and `ProofEnvelope` with a configured classical
  signing key;
- store algorithm, key id, signature bytes, verification status, and rotation
  metadata;
- support multiple signing profiles for customer, operator, and system records.

PQC-ready interface:

- define signature provider interface with algorithm name, key id, sign, verify,
  and public key export;
- define KEM provider interface for future sealed proof sharing;
- make algorithm identifiers data-driven so ML-DSA, SLH-DSA, or other accepted
  post-quantum algorithms can be plugged in later;
- do not mark PQC as production until dependency choice, key management,
  verification tests, and interop evidence exist.

ZK hook:

- support proof statements such as "reservoir policy allowed aggregate-only
  access" or "operator role satisfied approver requirement";
- expose public inputs and proof refs in `ProofEnvelope`;
- keep raw data and witness generation inside the on-prem boundary;
- do not require ZK for v1 pilot go/no-go.

## Implementation Plan

Phase 0: docs-only.

- Add this document.
- Do not rename the repo.
- Do not fork code.
- Do not implement runtime changes.

Phase 1: schema proposal.

- Add JSON schemas under `shared/mesh_runtime/schemas/perennial/`.
- Add contract dataclasses in a new bounded module only after schema review.
- Add fixtures for allowed action, denied action, reservoir denial, and export.

Phase 2: projection over existing Mesh state.

- Build `AgentActionRecord` from run events, operator commands, approvals, and
  run exports.
- Build `GovernanceCommit` from existing decision, evaluation, remediation
  safety, trust ladder, readiness, and Merkle state.
- Keep records local and file/Postgres-backed according to existing state
  backend boundaries.

Phase 3: pilot packet.

- Add Darkharness packet generator that wraps existing run export and
  go/no-go packet output.
- Require `PilotScope`.
- Include implemented/proposed capability labels in the packet.
- Expose read-only packet export at
  `GET /api/runs/{run_id}/darkharness-packet`.
- Return a schema-valid `darkharness.pilot_packet.v1` only when existing run
  evidence is sufficient; otherwise return a blocked response with explicit
  missing evidence.
- Do not write DB state, execute actions, relax approval gates, call external
  models, or export raw reservoir contents from this endpoint.

Phase 4: reservoir controls.

- Add `SensitiveReservoir` registry.
- Enforce default-deny raw egress.
- Add redacted projection and hash-only evidence modes.

Phase 5: crypto extension.

- Add signed governance records.
- Add crypto provider interfaces.
- Add PQC and ZK fields as non-required hooks until implementation is verified.

## Proposed File Layout After Docs Phase

No files in this section are created by this docs-only phase.

```text
shared/mesh_runtime/schemas/perennial/
  agent-action-record.schema.json
  sensitive-reservoir.schema.json
  epistemic-state.schema.json
  ontological-state.schema.json
  governance-commit.schema.json
  proof-envelope.schema.json
  pilot-scope.schema.json

services/perennial/
  __init__.py
  contracts.py
  materialize.py
  reservoir_registry.py
  packet.py
  crypto.py

tests/
  test_perennial_contracts.py
  test_perennial_materialization.py
  test_darkharness_packet.py
  test_sensitive_reservoir_boundaries.py
```

## Implementation Acceptance Tests

Contract tests:

- each proposed contract validates required fields and rejects missing authority,
  proof, boundary, or owner fields;
- `ProofEnvelope` rejects `raw_sensitive_data_included: true` in default pilot
  mode;
- `PilotScope` rejects `production_actions_approval_required: false` for v1.

Materialization tests:

- allowed Mesh run materializes `AgentActionRecord`, `GovernanceCommit`, and
  `ProofEnvelope`;
- denied Mesh run materializes the same objects with denial reasons;
- scenario analysis evidence becomes `EpistemicState` without collapsing
  competing hypotheses;
- service ownership and policy metadata become `OntologicalState` relationships.

Boundary tests:

- reservoir raw-content export is denied by default;
- redacted projection is allowed only when purpose and policy match;
- external model call with reservoir data is blocked unless an approved egress
  exception exists.

Packet tests:

- Darkharness packet includes readiness, go/no-go, allowed action proof, denied
  action proof, Merkle proof, and run export refs;
- packet labels implemented, proposed, and not-implemented capabilities;
- packet can be generated for `no-go` and retains missing evidence.

Integration tests:

- controlled Kubernetes signal creates the expected governance commit chain;
- OTel/Prometheus metric evidence is included without raw customer payloads;
- security webhook evidence can deny remediation without actuator credentials;
- trust-ladder ceiling prevents autonomy expansion in the pilot.

## Documentation Required After Implementation Starts

- Update `docs/architecture/api-and-runtime-map.md` with Perennial projection
  points.
- Update `docs/postgres-persistence.md` if new Perennial records become
  Postgres-backed state.
- Update `docs/production-hardening-records.md` with Darkharness packet evidence
  once executable.
- Add `docs/perennial-contracts.md` after schemas land.
- Add pilot operator runbook for reservoir registration and export review.

## Claim Discipline

Safe claim now:

- `orbital-mesh` already has the control-plane spine needed for governance:
  evidence, decisions, evaluation, approvals, safety gates, trust ladder,
  readiness, run events, Merkle proofs, and exports.
- Perennial/Darkharness/Darkmesh is a docs-first architecture and pilot packet
  proposal over that spine.

Unsafe claim now:

- production PQC is implemented;
- ZK proofs are implemented;
- internet-scale agent registry is implemented;
- sensitive reservoirs are technically enforced by code;
- production-impacting actions can run autonomously in the first pilot;
- Perennial replaces existing compliance, SIEM, GRC, or observability systems.

## Prompt-to-Artifact Checklist

| Requirement | Evidence in this document |
| --- | --- |
| Define Perennial, Darkharness, Darkmesh | Decision, Product Boundary |
| Enclave sensitive reservoirs | Reservoir Layer, `SensitiveReservoir`, Pilot Scope |
| Track human/agent/service actions | Agentic Action Ledger, `AgentActionRecord` |
| Preserve epistemic and ontological concurrency | Concurrent State Layer, `EpistemicState`, `OntologicalState` |
| Commit remediation only with evidence, policy, authority, proofs | Governance Kernel, Remediation Commit Layer, `GovernanceCommit`, Governance Flow |
| Ground in existing orbital-mesh runtime | Existing Orbital-Mesh Anchors |
| First pilot combines Ops, Cyber, AI governance, infrastructure remediation | Pilot Runtime, `PilotScope` |
| Ingest listed signal classes | Reservoir Layer, Pilot Runtime, Governance Flow |
| Predict anomalies before chaos thresholds | Pilot Runtime, Production-Safe Pilot Scope success metrics |
| Approval-required governance for production remediation | Operating Principles, Governance Kernel, Pilot Runtime, Hard Stops |
| Prove allowed and denied actions | Pilot Packet, `GovernanceCommit`, `ProofEnvelope` |
| Export audit-ready evidence | Pilot Packet, Remediation Commit Layer |
| Preserve customer data boundaries | Operating Principles, Reservoir Layer, Production-Safe Pilot Scope |
| Proposed v1 contracts | Proposed v1 Contracts |
| Required architecture layers | Architecture Layers |
| Crypto-agile design without false PQC claims | Crypto Assurance Layer, Crypto-Agile Design, Claim Discipline |
| External references grounded | External Thesis Grounding |
| Proposed vs implemented separated | Product Boundary, Claim Discipline |

## Completion Audit for This Docs Phase

Deliverables:

- new branch: `docs/perennial-darkmesh-end-to-end`;
- docs artifact: `docs/perennial-darkmesh-architecture.md`;
- no runtime implementation changes;
- no repository rename;
- no hard fork.

Verification commands:

```bash
git branch --show-current
git status --short
rg -n "AgentActionRecord|SensitiveReservoir|EpistemicState|OntologicalState|GovernanceCommit|ProofEnvelope|PilotScope" docs/perennial-darkmesh-architecture.md
rg -n "Reservoir Layer|Agentic Action Ledger|Concurrent State Layer|Governance Kernel|Remediation Commit Layer|Crypto Assurance Layer|Pilot Runtime" docs/perennial-darkmesh-architecture.md
git diff --check -- docs/perennial-darkmesh-architecture.md
```
