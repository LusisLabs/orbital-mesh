# Design Partner Packet

This packet defines the pilot scope a design partner can validate without expanding authority faster than the evidence supports.

## Pilot Scope

Default pilot boundary:

- one environment;
- one Kubernetes context;
- one namespace;
- one service class;
- approval gate forced;
- live execution limited to reviewed Kubernetes actions;
- feature-flag and incident adapters disabled unless separately certified;
- proposal lanes advisory only.

Required references:

- hardening record: `docs/production-hardening-records.md`;
- live runbook: `docs/production-live-runbook.md`;
- readiness validation: `docs/production-readiness-validation.md`;
- production compose template: `docker-compose.prod.yml`;
- production smoke: `scripts/prod_smoke.sh`;
- Postgres restart proof: `scripts/verify_postgres_restart_proof.py`;
- design-partner packet verifier: `scripts/verify_design_partner_packet.py --packet "$MESH_DESIGN_PARTNER_PACKET_PATH" --json`.

Pilot readiness requires `MESH_DESIGN_PARTNER_PACKET_PATH` to point at a passing `mesh.design_partner_packet.v1` packet. The packet is the machine-readable version of this document and must bind the scope, success metrics, data handling terms, support model, rollback plan, real-user experiment consent, go/no-go packet hash, release provenance hash, run export ref, and readiness ref.

## Success Metrics

Operational metrics:

- one allowed action completes with rollback metadata and live feedback evidence;
- one denied action is captured with explicit blocker evidence;
- no proposal lane receives production credentials;
- every mutating API event has operator identity;
- kill switch disables live execution and forces approval gates;
- Merkle roots and event proofs are available for pilot runs;
- Postgres restart proof passes before pilot go/no-go is marked `go`.

Product metrics:

- operator can inspect evidence graph before approving;
- operator can explain why a denied action was blocked;
- pilot packet can be reviewed without reading raw logs;
- support team can rehearse rollback using documented metadata.

## Data Handling

Allowed pilot data:

- operational metrics;
- Kubernetes object metadata needed for remediation;
- operator identity and roles;
- Mesh run events;
- model/proposal outputs marked advisory.

Disallowed pilot data:

- raw secrets;
- kubeconfig contents;
- private keys;
- unrestricted production logs;
- customer payloads not required for remediation decisions.

Retention:

- run events and Merkle proofs are retained for audit;
- vault exports are retained only for the agreed pilot period;
- training use is opt-in and must exclude audit-only records unless explicitly labeled trainable.

## Rollback And Support Model

Rollback requirements:

- every admitted action must include rollback metadata;
- Kubernetes rollback uses only allowlisted context and namespace;
- kill switch must remain available to disable live execution;
- failed or ambiguous executions require human review, not retry loops without idempotency proof.

Support model:

- design partner provides a technical owner and escalation channel;
- `orbital-mesh` maintainers provide pilot support for agreed hours and environments;
- emergency production action remains with the operator;
- postmortem packet includes run id, Merkle root, decision, evaluation, execution, feedback, operator events, and missing evidence.

## Go/No-Go Standard

The pilot moves forward only when `GET /api/pilot/go-no-go` is generated from observed evidence and returns `status: go`.

Intent does not satisfy the standard. Missing evidence remains blocking until a run, smoke, proof, or packet records it.

Verify the packet before pilot signoff:

```bash
scripts/verify_design_partner_packet.py --packet "$MESH_DESIGN_PARTNER_PACKET_PATH" --json
```

The verifier rejects packets that expand beyond one environment, one Kubernetes context, one namespace, and two service classes; omit consent for real-user-impacting experiments; allow proposal-lane credentials; omit rollback or kill-switch references; retain data longer than the agreed 30-day pilot window; or fail to bind the packet to a `go` pilot go/no-go hash and complete release-provenance hash.
