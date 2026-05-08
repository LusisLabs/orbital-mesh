# Pilot SLO And Error Budget

This document defines the first controlled production-pilot reliability contract. It uses existing `orbital-mesh` APIs and scripts only; it does not assume a separate managed monitoring product.

## Measurement Sources

Primary sources:

- `GET /api/health` for API liveness;
- `GET /api/readiness` for required integration state;
- `GET /api/agent/slo` for run-level SLO summary;
- `GET /metrics` for Prometheus exposition from the control plane;
- `GET /api/runs?summary=1` and `GET /api/runs/<run_id>/events` for stage timing;
- `GET /api/pilot/go-no-go` for evidence-backed pilot entry;
- `GET /api/approvals` for the machine-readable `mesh.approval_queue.v1` operator review queue;
- `scripts/prod_smoke.sh` for endpoint smoke;
- `scripts/verify_postgres_restart_proof.py` for state, memory, event, and Merkle restore proof;
- `scripts/verify_run_export_retrieval.py --package <path> --archive <path> --json` for saved run export audit retrieval;
- `scripts/verify_run_export_upload.py --package <path> --archive <path> --proof <path> --json` for durable run export upload and restore-test proof;
- `scripts/verify_pilot_signoff.py --go-no-go <path> --build-output <path> --operator-id <id> --role approver --json` for generating signed operator signoff over the captured pilot go/no-go packet; build mode refuses blocked packets and does not write a signoff file until the packet verifies as `go`;
- `scripts/verify_pilot_signoff.py --signoff <path> --go-no-go <path> --expected-release-provenance-sha <sha> --json` for signed operator signoff over the pilot go/no-go packet, including the release-provenance missing list, embedded checks, and CI SHA binding;
- `scripts/verify_design_partner_packet.py --packet "$MESH_DESIGN_PARTNER_PACKET_PATH" --json` for the design-partner scope, consent, support, rollback, go/no-go, and release-provenance packet;
- `scripts/generate_release_provenance.py --require-complete --json` for release-packet completeness.
- `scripts/verify_audit_sink_contract.py --proof "$MESH_AUDIT_SINK_PROOF_PATH" --json` for external audit-sink append-only proof before expansion or compliance reliance.
- `scripts/verify_credential_rotation.py --connector-id <id> --proof <path> --json` for service-account and provider-key rotation evidence.
- `scripts/verify_on_call_drill.py --proof "$MESH_ON_CALL_DRILL_PATH" --expected-environment pilot --json` for the production on-call drill packet required by pilot go/no-go.
- `scripts/verify_failure_mode_library.py --json` for private-staging failure-mode catalog coverage before relying on the replay library.
- `scripts/verify_threat_model_register.py --json` for owner, decision, expiry, and compensating-control coverage before external staging exposure.
- `scripts/verify_data_classification_policy.py --json` for data-class owner, retention, redaction, storage-location, deletion-control, and evidence-ref coverage before external staging exposure.
- `scripts/verify_agentic_operator_source_provenance.py --json` for source-input provenance, Apache-2.0 license, snapshot hash, fork posture, authority-gate adaptation, and no active runtime before any agentic-operator-derived runtime code is admitted.
- `scripts/generate_evaluation_kit_packet.py --output-dir <evaluation-kit-dir> --json` for local sample export package, zip archive, retrieval proof, and formal benchmark command packet generation.
- `scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json` for `mesh.evaluation_kit_packet.v1` verification.
- `scripts/verify_benchmark_run_artifacts.py --run-dir <benchmark-run-dir> --json` for benchmark output artifact, scorecard, scenario, pass-rate, unsafe-action, and hash verification.

Deployment-specific sources:

- ingress logs for TLS, SSO, header stripping, and role mapping;
- Prometheus or OTel collector data when `MESH_FEEDBACK_PROMETHEUS_ENABLED=1`;
- Kubernetes re-harvest records for live deployment feedback;
- platform logs for container restarts, database errors, and reverse-proxy errors.

## Hard Stop Conditions

These are not budgeted. Any occurrence stops the pilot until fixed or explicitly accepted with owner, expiry, and compensating control:

- unauthenticated request reaches a mutating API;
- client-supplied `X-Mesh-Operator` or `X-Mesh-Roles` reaches Mesh without trusted proxy stamping;
- live action executes without policy pass, evaluation pass, approval state, target allowlist, and rollback metadata;
- proposal lane receives production kubeconfig, actuator credentials, or repository write authority;
- `GET /api/readiness` loses a required pilot check and the degraded state is not visible to operators;
- event persistence, Merkle proof, or Postgres restore proof fails;
- run export packages lack retrieval proof, redaction, retention metadata, Merkle proof, timeline proof, or vault document archive coverage;
- run export package or archive upload proof is missing, hash-mismatched, local-only, or lacks restore-test evidence;
- pilot review lacks a signed `mesh.pilot_signoff.v1` packet from an `approver` or `admin` role that verifies against the captured `pilot.go_no_go.v1` packet, complete release-provenance hash, empty release-provenance missing list, passing release-provenance checks, and CI attestation SHA binding;
- kill switch cannot disable live execution or force approval gates;
- release provenance lacks image digest, base-image digest, SBOM, vulnerability scan, policy hashes, migration hashes, builder identity, or clean git tree for the deployed image.
- threat-model findings are open, expired, ownerless, or missing compensating controls before external staging or pilot exposure.
- data-classification policy is missing required classes, allows secret export, lacks redaction, lacks deletion controls for signal/log/trace/model/training data, or lacks owner/evidence coverage before external staging or pilot exposure.
- agentic-operator-derived code enters runtime before `mesh.agentic_operator_source_provenance.v1` passes and the imported path has adapted authority gates, license notice preservation, and focused tests.
- expansion or compliance reliance proceeds without a passing external audit-sink append-only proof and reviewed connector certification.
- provider-key or service-account rotation proof fails, includes raw secret material, or lacks required break-glass recording evidence.

## Pilot SLOs

Initial pilot window: 30 days or the design-partner period in `docs/design-partner-packet.md`, whichever is shorter.

| Objective | Target | Measured by |
| --- | --- | --- |
| Control-plane availability | 99.0% during staffed pilot hours | `/api/health`, ingress logs, container restarts |
| Required readiness visibility | Required pilot checks visible and accurate within 5 minutes | `/api/readiness`, operator review |
| Run admission latency | p95 <= 10 seconds from `POST /api/runs` to queued event | run events |
| Decision and evaluation latency | p95 <= 120 seconds in native pilot mode | run events |
| Operator approval auditability | 100% of approvals record operator id, roles, source, event id | run events, run artifacts |
| Action latency | p95 <= configured action timeout plus 30 seconds | execution record, run events |
| Feedback evidence latency | Kubernetes re-harvest within 2 minutes; Prometheus feedback at configured windows | feedback artifact |
| Event persistence lag | p95 <= 5 seconds from event creation to API visibility | run events, `/api/runs/<run_id>` |
| Run export reviewability | 100% of pilot runs have events, Merkle root, decision, evaluation, execution or denial, feedback or missing-evidence reason | run APIs, vault artifacts |
| Smoke reliability | `scripts/prod_smoke.sh` passes before and after every pilot release | smoke output |
| Restore proof | Postgres restart proof passes before pilot and after state-store changes | `scripts/verify_postgres_restart_proof.py` |

Human wait time is tracked separately from system latency. Approval latency is an operator-workflow metric, not a control-plane latency failure.

## Error Budget

The pilot error budget covers reliability failures only. Safety failures are hard stops.

Budget for one 30-day pilot:

- control-plane unavailability: 0.5 staffed business days maximum;
- failed run admissions not caused by denied policy or missing approval: <= 1% of attempted launches;
- stuck non-terminal runs requiring operator cleanup: <= 2 runs;
- missing feedback evidence on approved live actions: 0 allowed unless the action is explicitly marked as no-op, denied, or feedback source unavailable before approval;
- failed endpoint smoke after release: 0 allowed for promotion;
- Postgres restart proof failure: 0 allowed for promotion;
- release provenance completeness failure: 0 allowed for production pilot promotion.

Denied actions, policy rejections, failed evaluation gates, and human-review outcomes are not budget consumption when they are expected safety behavior and preserve evidence.

## Review Cadence

Before pilot:

1. Run `scripts/prod_smoke.sh`.
2. Run `scripts/verify_authenticated_ingress.py --json`.
3. Run `scripts/verify_authenticated_ingress_deployment.py --proof "$MESH_AUTHENTICATED_INGRESS_PROOF_PATH" --json` against the deployed proxy proof.
4. Run `scripts/verify_postgres_restart_proof.py --database-url "$MESH_DATABASE_URL" --json`.
5. Run `scripts/verify_run_export_retrieval.py --package <path> --archive <path> --json` against at least one generated pilot run export.
6. Run `scripts/verify_run_export_upload.py --package <path> --archive <path> --proof <path> --json` after the package and archive are replicated to durable storage.
7. Run the Mesh Brain model-kernel probe, live-serving smoke, and rollback drill. The pilot go/no-go packet requires a passed model-kernel gate, a canary live-serving smoke run, a single CROPS canary lane, and rollback-drill evidence.
8. Run `scripts/verify_mesh_brain_artifact_registry.py --artifacts-json .mesh-runtime-state/artifacts.json --proof-manifest dist/mesh-brain-artifact-upload-proof.json --require-upload-proof --json`.
9. Run `scripts/generate_release_provenance.py --require-complete --json`, write the packet to a deployment-readable path, and set `MESH_RELEASE_PROVENANCE_PATH` to that file before go/no-go capture.
10. Before expansion or compliance reliance, run `scripts/verify_audit_sink_contract.py --proof "$MESH_AUDIT_SINK_PROOF_PATH" --json` and set `MESH_AUDIT_SINK_PROOF_PATH` for readiness.
11. Run `scripts/verify_credential_rotation.py --connector-id <id> --proof <path> --json` for every pilot connector with runtime-secret or read-only-secret credentials.
12. Run `scripts/verify_data_classification_policy.py --json` and review deletion controls for deployment log and trace systems.
13. Run `scripts/generate_evaluation_kit_packet.py --output-dir <evaluation-kit-dir> --json` and `scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json`.
14. Run the packet's benchmark command and verify the resulting directory with `scripts/verify_benchmark_run_artifacts.py --run-dir <benchmark-run-dir> --json`.
15. Run `scripts/verify_on_call_drill.py --proof "$MESH_ON_CALL_DRILL_PATH" --expected-environment pilot --json` after the staffed drill proves kill switch, watcher pause, bad-target revocation, stuck-run recovery, failed-dependency handling, provider-key rotation, and restore.
16. Capture `GET /api/readiness`, `GET /api/agent/slo`, `GET /metrics`, and `GET /api/pilot/go-no-go`.
17. Capture `GET /api/approvals` and confirm every pending production-impacting item has owner, approver roles, blockers, allowed commands, and evidence refs before approval.
18. Run `scripts/verify_design_partner_packet.py --packet "$MESH_DESIGN_PARTNER_PACKET_PATH" --json` against the partner-specific packet bound to the captured go/no-go and release provenance hashes.
19. For public proof or expansion claims, run `scripts/verify_public_proof_package.py --json` and confirm `public_proof_package_verified` is green in `/api/readiness`.
20. Before production expansion, run `scripts/verify_load_concurrency_rehearsal.py --proof "$MESH_LOAD_CONCURRENCY_REHEARSAL_PATH" --json` and confirm `load_concurrency_rehearsal_verified` is green in `/api/readiness`.
21. Before enabling feature-flag or incident-provider credentials, run `scripts/verify_provider_adapter_proof.py --proof <proof.json> --adapter-id feature_flag_provider --json` or `--adapter-id incident_provider --json`.
22. Run `scripts/verify_pilot_signoff.py --go-no-go <captured-go-no-go.json> --build-output <pilot-signoff.json> --operator-id <id> --role approver --json` with the signoff key injected from the platform secret store. This command exits nonzero and writes no signoff file while the captured go/no-go packet is blocked.
23. Run `scripts/verify_pilot_signoff.py --signoff <pilot-signoff.json> --go-no-go <captured-go-no-go.json> --expected-release-provenance-sha <sha> --json` against the signed operator signoff packet.

During pilot:

- review readiness, failed admissions, stuck runs, approval latency, action latency, and feedback evidence at least once per staffed day;
- review every hard-stop condition immediately;
- keep `approval_gate` as the default unless the trust ladder and service owner explicitly allow a narrower mode.

After pilot:

- export the go/no-go packet;
- review every run with missing feedback, missing rollback metadata, or manual cleanup;
- update service policy and trust-ladder limits from observed evidence only.

## Current Status

Implemented sources:

- `/api/health`;
- `/api/readiness`;
- `/api/agent/slo`;
- `/metrics`;
- `/api/pilot/go-no-go`;
- `scripts/verify_pilot_signoff.py`;
- run event APIs;
- production smoke;
- authenticated ingress rehearsal;
- Postgres restart proof;
- release provenance generator.

Still deployment-specific:

- ingress availability and SSO logs;
- Prometheus service-metric coverage;
- external audit sink;
- external audit-sink proof path and reviewed connector certification;
- connector credential-rotation proof packets;
- target-environment log and trace deletion execution evidence;
- production on-call drill packet from the target environment;
- target-environment run export retrieval proof and durable upload evidence;
- signed CI release packet;
- long-window load and concurrency evidence.
