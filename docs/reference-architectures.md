# Reference Architectures

This packet maps production evaluation shapes to active `orbital-mesh` files. It is a deployment guide index, not a claim that Helm, Terraform, marketplace images, or customer-specific ingress are already packaged.

## Common Control Plane Contract

Every architecture keeps the same authority boundary:

- control-plane runtime: `control_plane_server.py` and `services/control_plane.py`;
- deployment compatibility: `docs/deployment-compatibility.md`;
- agentic operator fork-in: `docs/agentic-operator-core-import-plan.md`;
- deployment smoke: `scripts/prod_smoke.sh`;
- readiness: `GET /api/readiness`;
- pilot packet: `GET /api/pilot/go-no-go`;
- authenticated ingress boundary: `docs/authenticated-ingress.md`;
- state and Merkle proof restore: `scripts/verify_postgres_restart_proof.py`;
- release packet: `scripts/generate_release_provenance.py`.
- ownership registry: `config/ownership.registry.json`.
- policy lifecycle manifest: `config/policy-lifecycle.manifest.json`.
- release provenance mount: `MESH_RELEASE_PROVENANCE_PATH`.
- run export audit retrieval: `scripts/verify_run_export_retrieval.py`.
- run export durable upload proof: `scripts/verify_run_export_upload.py`.
- external audit-sink proof: `scripts/verify_audit_sink_contract.py` and `MESH_AUDIT_SINK_PROOF_PATH` before expansion or compliance reliance.
- credential rotation proof: `scripts/verify_credential_rotation.py` for runtime-secret and read-only-secret connectors.
- data-classification policy: `config/data-classification.policy.json` and `scripts/verify_data_classification_policy.py`.
- agentic-operator source provenance: `config/agentic-operator-source.provenance.json` and `scripts/verify_agentic_operator_source_provenance.py`.
- evaluation-kit packet: `scripts/generate_evaluation_kit_packet.py`, `scripts/verify_evaluation_kit_packet.py`, and `shared/mesh_runtime/schemas/evaluation-kit-packet.schema.json`.
- benchmark output proof: `scripts/verify_benchmark_run_artifacts.py` and `shared/mesh_runtime/schemas/benchmark-run-artifacts-verification.schema.json`.

Required production defaults:

- `MESH_OPERATOR_IDENTITY_REQUIRED=1`;
- `MESH_DEFAULT_STEERING_MODE=approval_gate`;
- `MESH_STATE_BACKEND=postgres`;
- `MESH_OWNERSHIP_REGISTRY_PATH=/app/config/ownership.registry.json` or an equivalent reviewed registry path;
- `MESH_RELEASE_PROVENANCE_PATH` pointing at the completed release packet for pilot and expansion profiles;
- `MESH_POLICY_SIGNING_KEY` supplied through the deployment secret store;
- explicit Kubernetes context and namespace allowlists before live execution;
- unfinished feature-flag and incident adapters disabled unless replaced by certified real providers;
- proposal lanes without kubeconfig, repository write, or actuator credentials.
- external audit sink proof at `MESH_AUDIT_SINK_PROOF_PATH` before expansion or compliance reliance.
- credential rotation proof matching the connector certification registry for every authority-bearing connector.
- reviewed data-classification policy at `MESH_DATA_CLASSIFICATION_POLICY_PATH`.
- reviewed source-input provenance at `MESH_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH` before any agentic-operator fork enters runtime packaging.

Compatibility posture:

- Docker Compose and Kubernetes are the validated deployment paths.
- OCI image compatibility is a contract for Docker Engine, Podman, containerd, runc, crun, BuildKit, Buildah, and Kaniko outputs, but direct runtime APIs are not a product surface.
- K3s, OpenShift, Rancher-managed Kubernetes, managed Kubernetes, Cloud Run, Azure Container Apps, Fly.io, Railway, and Render are recipes until target-specific release evidence exists.
- ECS/Fargate is the first non-Kubernetes production target candidate for validation.
- Swarm, Mesos/Marathon, Windows Containers, and direct runc/containerd integration are not active roadmap targets.
- `agentic-operator-core-main/` is source input for Kubernetes operator, CRD, Helm, Argo, MCP, LiteLLM, metering, and network-policy patterns. It is not active runtime until forked through Orbital Mesh authority gates.

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
scripts/verify_pilot_signoff.py --go-no-go dist/pilot-go-no-go.json --build-output dist/pilot-signoff.json --operator-id "$MESH_SIGNOFF_OPERATOR_ID" --role approver --json
scripts/verify_pilot_signoff.py --signoff dist/pilot-signoff.json --go-no-go dist/pilot-go-no-go.json --expected-release-provenance-sha "$MESH_RELEASE_PROVENANCE_SHA" --json
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

Fork-in candidate:

- `agentic-operator-core-main/api/v1alpha1/agentworkload_types.go`;
- `agentic-operator-core-main/api/v1alpha1/tenant_types.go`;
- `agentic-operator-core-main/charts/`;
- `agentic-operator-core-main/pkg/argo/`.

These provide useful Kubernetes-native packaging and scheduling material, but they must be renamed and wired through Orbital Mesh evidence, policy, approval, rollback, proof, and release provenance before this architecture can claim validated operator support.

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
- `scripts/verify_run_export_retrieval.py`;
- `scripts/generate_release_provenance.py`;
- `shared/mesh_runtime/schemas/`.

Deployment shape:

- SSO-backed operator identity with separate viewer, launcher, approver, and admin groups;
- Postgres-backed state and encrypted artifact storage;
- external audit sink before compliance reliance;
- run export packages and archives verified for checksum, redaction, Merkle proof, timeline proof, vault document retrieval, and retention metadata;
- durable upload proof for run export package and archive, including matching hashes, byte counts, durable URIs, and restore-test evidence;
- release packet with image digest, base-image digest, SBOM, vulnerability scan, CI attestation, policy hashes, migration hashes, builder identity, and clean git tree;
- external audit sink proof with append-only receipt, run-export hash, Merkle root, runtime-secret service account boundary, rotation evidence, break-glass recording evidence, and retention window;
- credential rotation proof for runtime-secret and read-only-secret connectors, including prior secret revocation, operator identity, evidence refs, and no raw secret material;
- documented retention, redaction, and deletion controls.
- data-classification verification for signals, logs, traces, model output, audit proof, and run exports.

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
