# Reference Architectures

This packet maps production evaluation shapes to active `orbital-mesh` files. It is a deployment guide index, not a claim that Helm, Terraform, marketplace images, or customer-specific ingress are already packaged.

## Common Control Plane Contract

Every architecture keeps the same authority boundary:

- control-plane runtime: `control_plane_server.py` and `services/control_plane.py`;
- deployment smoke: `scripts/prod_smoke.sh`;
- readiness: `GET /api/readiness`;
- pilot packet: `GET /api/pilot/go-no-go`;
- authenticated ingress boundary: `docs/authenticated-ingress.md`;
- state and Merkle proof restore: `scripts/verify_postgres_restart_proof.py`;
- release packet: `scripts/generate_release_provenance.py`.

Required production defaults:

- `MESH_OPERATOR_IDENTITY_REQUIRED=1`;
- `MESH_DEFAULT_STEERING_MODE=approval_gate`;
- `MESH_STATE_BACKEND=postgres`;
- explicit Kubernetes context and namespace allowlists before live execution;
- unfinished feature-flag and incident adapters disabled unless replaced by certified real providers;
- proposal lanes without kubeconfig, repository write, or actuator credentials.

## Local Full-Stack Proof

Use for developer and evaluator proof on one machine.

Active paths:

- `docker-compose.stack.yml`;
- `docs/all-in-one-compose-stack.md`;
- `scripts/compose_stack_smoke.sh`;
- `scripts/e2e_run_mesh.sh`;
- `scripts/e2e_ui_operator.sh`;
- `services/ingest/kubernetes_live_signal.py`;
- `services/watchers/kubernetes.py`.

Validation:

```bash
docker compose -f docker-compose.stack.yml up --build
docker compose -f docker-compose.stack.yml run --rm mesh-smoke
```

Posture:

- proves the live Kubernetes loop in a disposable k3s environment;
- proves app-level operator identity headers through stack smoke defaults;
- does not prove external TLS, SSO, cloud IAM, or production network isolation.

## Single-VM Private Deployment

Use for a private staging box, lab appliance, or narrow pilot where Compose is acceptable.

Active paths:

- `docker-compose.prod.yml`;
- `docs/production-live-runbook.md`;
- `docs/authenticated-ingress.md`;
- `scripts/prod_smoke.sh`;
- `scripts/generate_release_provenance.py`.

Required surrounding infrastructure:

- TLS reverse proxy on the same host or private load balancer;
- SSO/OIDC/SAML gateway that stamps `X-Mesh-Operator` and `X-Mesh-Roles`;
- protected Docker volume or mounted disk for `/app/.mesh-runtime-state`;
- Postgres service or managed Postgres endpoint;
- read-only kubeconfig mount if Mesh acts on an external cluster;
- host-level backup and restore automation.

Validation:

```bash
MESH_SMOKE_BASE_URL=https://mesh.private.example ./scripts/prod_smoke.sh
scripts/verify_authenticated_ingress.py --json
scripts/generate_release_provenance.py --require-complete --json
```

`scripts/verify_authenticated_ingress.py` is a local app-level rehearsal. The deployed proxy still needs its own evidence for TLS, header stripping, and group mapping.

## Kubernetes Platform Team

Use when Mesh runs inside or next to the platform cluster it observes.

Active paths:

- `services/ingest/kubernetes_live_signal.py`;
- `services/watchers/kubernetes.py`;
- `services/ingest/kubernetes_topology.py`;
- `services/actuators/service.py`;
- `shared/mesh_runtime/schemas/kubernetes-signal.schema.json`;
- `tests/test_kubernetes_live_execution.py`;
- `tests/test_kubernetes_actions.py`.

Deployment shape:

- Mesh API Deployment with a PVC for runtime state or Postgres-backed state;
- service account with least-privilege RBAC limited to reviewed namespaces;
- authenticated ingress controller enforcing TLS and identity headers;
- Prometheus or OTel collector reachable from Mesh for feedback;
- Kubernetes namespace and context allowlists set explicitly.

Validation:

```bash
python3 -m unittest tests.test_kubernetes_live_execution tests.test_kubernetes_actions
scripts/prod_smoke.sh
```

Gaps before reusable distribution:

- Helm chart;
- Kustomize overlays;
- cloud-specific IAM examples;
- ingress-controller-specific SSO templates.

## Private Cloud Or VPC-Only

Use when the control plane must stay inside a customer network.

Active paths:

- `docker-compose.prod.yml`;
- `docs/authenticated-ingress.md`;
- `docs/production-readiness-validation.md`;
- `docs/integrations.md`;
- `scripts/prod_smoke.sh`.

Deployment shape:

- private load balancer or internal ingress only;
- no public control-plane listener;
- Postgres and vault storage on encrypted private storage;
- webhook and OTel ingest reachable only from trusted network sources;
- external LLM/model providers disabled unless approved by the deployment owner.

Readiness expectations:

- staging or pilot profile must fail closed when auth, Postgres, live feedback, or allowlists are missing;
- optional proposal lanes may remain unavailable without blocking core readiness;
- any external provider route must have timeout, degraded state, and operator-visible failure reason.

## GPU And AI Infrastructure

Use when the evaluator cares about expensive model-serving or GPU-backed proposal lanes.

Active paths:

- `docker-compose.latentmas.yml`;
- `Dockerfile.latentmas`;
- `Dockerfile.latentmas.cpu`;
- `docs/all-in-one-compose-stack.md`;
- `docs/post-training/runtime.md`;
- `mesh_brain/`;
- `services/orchestrator/latentmas_adapter.py`;
- `services/orchestrator/latentmas_server.py`.

Deployment shape:

- Mesh control plane remains the authority boundary;
- GPU services run as optional proposal or model-lifecycle lanes;
- GPU workers receive no production kubeconfig or actuator credentials;
- proposal output re-enters deterministic policy, evaluation, approval, and bounded execution gates.

Validation:

```bash
python3 -m unittest tests.test_mesh_brain_agent_runtime
docker compose -f docker-compose.stack.yml -f docker-compose.latentmas.yml up --build
```

GPU-specific production proof still needs hardware-specific smoke, capacity metrics, and cost telemetry from the target environment.

## Regulated Enterprise

Use when auditability, retention, evidence review, and separation of duties are the main buying constraints.

Active paths:

- `docs/production-hardening-records.md`;
- `docs/release-provenance.md`;
- `docs/design-partner-packet.md`;
- `scripts/verify_postgres_restart_proof.py`;
- `scripts/generate_release_provenance.py`;
- `shared/mesh_runtime/schemas/`.

Deployment shape:

- SSO-backed operator identity with separate viewer, launcher, approver, and admin groups;
- Postgres-backed state and encrypted artifact storage;
- external audit sink before compliance reliance;
- release packet with image digest, base-image digest, SBOM, vulnerability scan, policy hashes, migration hashes, builder identity, and clean git tree;
- documented retention, redaction, and deletion controls.

Current gap:

- external audit sink certification is not complete;
- signed CI provenance remains incomplete until CI supplies image and scan artifacts.

## Air-Gapped Or Offline-Adjacent

Use only for environments that can preload images, dependencies, policies, and fixtures.

Active paths:

- `docker-compose.prod.yml`;
- `docs/evaluation-kits.md`;
- `docs/integrations.md`;
- `fixtures/signals/`;
- `policies/`;
- `scripts/prod_smoke.sh`.

Deployment shape:

- run native evaluation and native orchestration by default;
- disable external model providers and remote proposal lanes unless they are hosted inside the boundary;
- preload Docker images, Python wheels, Node artifacts, policies, and fixture packs;
- use private OTel or webhook ingress only;
- export run packets through an approved offline review path.

Validation:

```bash
MESH_EVALUATION_MODE=native MESH_ORCHESTRATION_MODE=native ./scripts/prod_smoke.sh
python3 scripts/verify_release_cut_list.py --json
```

This shape is not a full air-gap product package yet. It is the current offline-adjacent contract that can be hardened into a distributable package.
