# Deployment Compatibility

Orbital Mesh claims open deployment compatibility by contract, not first-class support for every runtime or orchestrator name. Compatibility must stay tied to observed evidence, release packets, documented deployment boundaries, and failure modes.

## Compatibility Levels

| Level | Meaning | Required evidence |
| --- | --- | --- |
| validated | The target is exercised by a maintained smoke or release gate. | Passing command, run id or packet, image digest when applicable, and readiness output. |
| supported | The runtime contract is intentionally kept compatible, but this exact target is not a recurring gate. | OCI image contract, configuration contract, documented caveats, and at least one manual proof before customer reliance. |
| recipe | The repo documents how to deploy there, but it is not a product support promise. | Setup notes, expected environment variables, known gaps, and validation commands the deployer must run. |
| not planned | The target is not part of the product surface. | Explicit reason so it is not rediscovered as an ambiguous gap. |

Do not use "supports" for a target unless it is at least `supported`. Do not use "validated" without a current smoke, readiness, or release artifact.

The machine-readable source for these claims is `config/deployment-compatibility.registry.json`. Verify it with:

```bash
python3 scripts/verify_deployment_compatibility.py --json
```

Runtime operators can inspect the current packet at `GET /api/deployment/compatibility`. Staging readiness blocks on `deployment_compatibility_registry_reviewed`, so compatibility claims fail closed if the registry is missing or invalid.

ECS/Fargate promotion requires a `mesh.ecs_fargate_promotion_proof.v1` packet verified by:

```bash
python3 scripts/verify_ecs_fargate_promotion.py --proof <ecs-fargate-promotion-proof.json> --json
```

The proof must show ECS health and readiness, proxy identity handling, Postgres persistence, live feedback, audit proof, rollback rehearsal, release provenance, image digest, scoped task roles, scoped secret refs, and no raw secret material. Passing this verifier is necessary but not sufficient by itself; the target remains `next_validated_target` until the registry is reviewed and updated.

## Runtime And Build Matrix

| Target | Category | Level | Product stance |
| --- | --- | --- | --- |
| Docker Compose | local and single-VM runtime | validated | Canonical local full-stack and single-VM proof path. |
| Docker Engine | container runtime | supported | Acceptable runtime for OCI images and Compose deployment. |
| Podman | container runtime | recipe | Keep OCI and env/volume assumptions portable; document Compose and networking caveats before claiming support. |
| containerd | lower-level runtime | supported | Supported through standard OCI images and Kubernetes/container platform use, not direct product integration. |
| runc / crun | OCI runtime layer | supported | Compatibility comes from OCI image discipline, not direct runtime APIs. |
| LXC / LXD | system container runtime | recipe | Possible wrapper environment for private installs; not a primary target. |
| Windows Containers / Hyper-V Containers | Windows runtime | not planned | Out of scope until Windows workloads become a defined pilot target. |
| BuildKit | image build | supported | Preferred modern build path when it emits standard OCI-compatible images. |
| Buildah | image build | recipe | Compatible when output image and labels match the release packet contract. |
| Kaniko | image build | recipe | CI build option only; deployment still depends on the resulting image digest and provenance. |
| Docker Hardened Images / DHI charts | supply-chain component source | recipe | Preferred input class for hardened arena profiles when the chosen component exists and the deployer can provide digest pins, SBOM/provenance/attestation refs, reviewed chart values, and target smoke evidence. Not a deployment target and not a whole-system compliance claim. |

## Orchestration And Platform Matrix

| Target | Category | Level | Product stance |
| --- | --- | --- | --- |
| Kubernetes | orchestration | validated | Primary production platform-team target. Live authority still requires allowlists, RBAC, policy, evaluation, approval, and rollback metadata. |
| Orbital Mesh Kubernetes operator | orchestration and packaging | backlog | Fork candidate from the provenance-recorded `agentic-operator-core-main/` source input when available. Validated only after CRDs, controllers, Helm, Argo scheduling, tenant isolation, MCP, LiteLLM, metering, and network policy are renamed and wired through Orbital Mesh authority gates. |
| K3s | Kubernetes distribution | recipe | Valid local or edge shape; not a separate orchestration abstraction. |
| OpenShift | Kubernetes platform | recipe | Treat as Kubernetes plus stricter image, SCC, route, and identity constraints. |
| Rancher-managed Kubernetes | Kubernetes management plane | recipe | Rancher manages clusters; Mesh still targets the underlying Kubernetes API and ingress boundary. |
| EKS / GKE / AKS | managed Kubernetes | recipe | Covered through Kubernetes contract plus cloud IAM and ingress-specific evidence. |
| Amazon ECS / Fargate | orchestration and serverless containers | next validated target | Best non-Kubernetes production target candidate after the Kubernetes pilot path is repeatable. |
| HashiCorp Nomad | orchestration | backlog | Plausible second non-Kubernetes orchestrator after ECS/Fargate. |
| Google Cloud Run | serverless containers | recipe | Good for stateless review or API deployments; authority-bearing production use needs persistence, identity, audit, and feedback evidence. |
| Azure Container Apps | managed container apps | recipe | Same constraints as other managed container app platforms. |
| Fly.io / Railway / Render | managed container platforms | recipe | Useful evaluation paths, not enterprise control-plane validation. |
| Docker Swarm | orchestration | not planned | Too little strategic relevance for first production expansion. |
| Apache Mesos / Marathon | orchestration | not planned | Legacy target; document only if a design partner explicitly requires it. |

## Contract Boundaries

All deployment targets must preserve the same authority contract:

- standard OCI image;
- explicit environment variables and secret injection;
- persistent state through Postgres or reviewed volume storage;
- machine-readable ownership registry with owner, tenant, customer, approver, rollback, policy, and data-boundary fields;
- registry-backed connector certification with authority posture, credential policy, degraded behavior, allowed scopes, and release-packet visibility;
- signed policy lifecycle hashes covering every active policy file;
- reviewed threat-model register with owner, decision, expiry, compensating control, and evidence refs for every authority boundary;
- reviewed data-classification policy with retention, redaction, deletion controls, storage locations, and evidence refs for signals, logs, traces, prompts, model output, audit proof, and exports;
- action/risk-tier evidence sufficiency gate before mutating execution;
- authenticated ingress that strips and stamps operator identity headers;
- no production kubeconfig or actuator credential inside proposal lanes;
- `/api/health`, `/api/readiness`, `/api/pilot/go-no-go`, `/api/failure-modes`, `/api/watchers/ownership`, `/metrics`, run export, and release packet visibility;
- signed or hash-addressed release evidence for image, policy, migration, and connector state;
- agentic-operator source provenance with Apache-2.0 license verification, source snapshot hash, source-input-only posture, and authority-gate adaptation requirements before any CRD, controller, Helm, MCP, LiteLLM, Argo, or CLI fork enters runtime;
- hardened-image or hardened-chart selection recorded as supply-chain evidence only, with digest pins, SBOM/provenance/attestation refs, reviewed chart values, and no promotion from image-level hardening to system-level compliance without target proof;
- external audit-sink append-only proof before expansion or compliance reliance;
- operator-visible degraded state when a target cannot provide required identity, persistence, feedback, or audit guarantees.

Compatibility work must not add orchestrator-specific authority bypasses. A target adapter can only translate deployment mechanics; it cannot weaken policy, evidence, evaluation, approval, or rollback requirements.

Active validation anchors:

- local full-stack proof: `docker-compose.stack.yml`;
- production-like single-VM proof: `docker-compose.prod.yml`;
- authenticated ingress boundary: `docs/authenticated-ingress.md`;
- production endpoint smoke: `scripts/prod_smoke.sh`.
- agentic operator fork-in plan: `docs/agentic-operator-core-import-plan.md`.

## Validation Order

1. Keep Docker Compose validated for local and single-VM proof.
2. Keep Kubernetes validated for the first production pilot path.
3. Add ECS/Fargate as the first validated non-Kubernetes production target.
4. Define the hardened production-arena profile registry and generator as a recipe layer over the validated Docker Compose and Kubernetes contracts.
5. Add Podman, OpenShift, K3s, and managed container recipes only after the base contracts are stable.
6. Move a recipe to validated only when it has a maintained smoke path and release evidence.
