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
- `scripts/prod_smoke.sh` for endpoint smoke;
- `scripts/verify_postgres_restart_proof.py` for state, memory, event, and Merkle restore proof;
- `scripts/generate_release_provenance.py --require-complete --json` for release-packet completeness.

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
- kill switch cannot disable live execution or force approval gates;
- release provenance lacks image digest, base-image digest, SBOM, vulnerability scan, policy hashes, migration hashes, builder identity, or clean git tree for the deployed image.

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
3. Run `scripts/verify_postgres_restart_proof.py --database-url "$MESH_DATABASE_URL" --json`.
4. Run the Mesh Brain model-kernel probe, live-serving smoke, and rollback drill. The pilot go/no-go packet requires a passed model-kernel gate, a canary live-serving smoke run, a single CROPS canary lane, and rollback-drill evidence.
5. Run `scripts/verify_mesh_brain_artifact_registry.py --artifacts-json .mesh-runtime-state/artifacts.json --proof-manifest dist/mesh-brain-artifact-upload-proof.json --require-upload-proof --json`.
6. Run `scripts/generate_release_provenance.py --require-complete --json`.
7. Capture `GET /api/readiness`, `GET /api/agent/slo`, `GET /metrics`, and `GET /api/pilot/go-no-go`.

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
- run event APIs;
- production smoke;
- authenticated ingress rehearsal;
- Postgres restart proof;
- release provenance generator.

Still deployment-specific:

- ingress availability and SSO logs;
- Prometheus service-metric coverage;
- external audit sink;
- signed CI release packet;
- long-window load and concurrency evidence.
