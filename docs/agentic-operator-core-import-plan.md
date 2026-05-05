# Agentic Operator Core Import Plan

This plan governs how `agentic-operator-core-main/` is forked into Orbital Mesh. The source tree is useful because it already contains a Kubernetes-native agent workload operator, tenant CRD, Helm packaging, Argo orchestration, LiteLLM routing, MCP surface, per-workload metering hooks, network isolation policy, and operator CLI/web surfaces.

Do not copy the whole tree blindly. Fork contracts, tests, and deployable packaging in phases. Keep Orbital Mesh as the production authority layer: signal, evidence, decision, evaluation, operator approval, bounded execution, feedback, persistence, proof, Perennial, and Darkharness remain authoritative.

## Source Surfaces

| Source path | Import value | Fork posture |
| --- | --- | --- |
| `agentic-operator-core-main/api/v1alpha1/agentworkload_types.go` | `AgentWorkload` CRD shape for objective, agents, provider refs, model routing, Argo workflow refs, proposed actions, executed actions, and status conditions. | Adapt into an Orbital Mesh workload schema. Do not preserve auto-approval as an execution bypass. |
| `agentic-operator-core-main/api/v1alpha1/tenant_types.go` | Tenant namespace, provider, quota, SLA, network policy, and status model. | Use as the seed for tenant and boundary contracts. Add data-boundary, export, owner, approver, and action authority fields. |
| `agentic-operator-core-main/internal/controller/` | Reconciliation patterns for AgentWorkload, Tenant, finalizers, status updates, routing, and cost-aware behavior. | Reuse as controller reference only until Orbital Mesh authority checks are embedded. |
| `agentic-operator-core-main/pkg/argo/` | Argo Workflow creation, status tracking, timeout, artifact mapping, and suspend-gate lifecycle. | Fork as the admission/scheduling substrate after policy, evidence, approval, and rollback gates are wired. |
| `agentic-operator-core-main/pkg/multitenancy/` | Tenant resolver, quota, SLA, and isolation primitives. | Fold into the tenant boundary layer and connect to readiness, run admission, and audit events. |
| `agentic-operator-core-main/pkg/finops/` | Cost reporter interface and license validator boundary. | Use the interface shape for OpenMeter or no-op metering. Keep billing enforcement separate from safety gates. |
| `agentic-operator-core-main/pkg/llm/`, `charts/charts/litellm/` | Provider routing and LiteLLM proxy deployment. | Import as an optional connector lane with certification state and degraded readiness. |
| `agentic-operator-core-main/pkg/mcp/`, `cmd/agentctl/mcp_serve.go` | MCP server/client pattern for agent-callable workload provisioning. | Adapt as a proposal-lane interface. It cannot receive production actuator credentials. |
| `agentic-operator-core-main/charts/` | Helm umbrella chart, subcharts, network policy, RBAC, webhook, license secret, web UI, and shared services. | Fork into Orbital Mesh packaging after chart values are renamed and readiness gates are added. |
| `agentic-operator-core-main/config/crd/`, `config/rbac/`, `config/webhook/` | Generated CRDs, RBAC, and validating webhook manifests. | Treat as seed manifests. Regenerate after schema names, groups, and authority fields are changed. |
| `agentic-operator-core-main/config/policies/` | OPA policy samples for budget, egress, and model allowlists. | Convert into policy lifecycle fixtures with version, owner, dry-run, impact preview, and rollback. |
| `agentic-operator-core-main/config/grafana/` | Cost dashboard and Prometheus alert examples. | Use as observability recipe only until tied to Orbital Mesh SLO and evidence timelines. |
| `agentic-operator-core-main/cmd/agentctl*`, `pkg/agentctl/` | CLI and simple web operator surfaces for workload status, approve/reject, cost, and descriptions. | Mine workflows and API verbs. Do not replace the Orbital Mesh operator UI. |
| `agentic-operator-core-main/docs/`, `README.md`, `ROADMAP.md` | Positioning, install, architecture, multi-tenancy, cost, security, tracing, and threat-model material. | Use as internal source context. Do not publish comparative claims until independently verified. |

## Missing-Layer Mapping

| Thin Orbital Mesh layer | Fork source | Required Orbital Mesh adaptation |
| --- | --- | --- |
| Ownership ontology | `Tenant`, `AgentWorkload`, namespace labels, status conditions | Add service owner, approver, rollback authority, customer boundary, escalation route, and allowed action classes. |
| Tenant and boundary layer | Tenant CRD, namespace isolation, quotas, network policy | Add run ownership, data boundary, export permissions, retention, reservoirs, and per-tenant policy scope. |
| Connector certification layer | provider refs, LiteLLM, Browserless, MCP, shared service charts | Expose mock/read-only/staging-ready/pilot-ready/production-ready states through readiness and release packets. |
| Policy lifecycle layer | OPA samples, webhook validation, network policy | Add versioning, owner approval, effective window, dry-run simulation, impact preview, rollback, and signed policy hash. |
| Evidence sufficiency layer | AgentWorkload status, proposed/executed actions, workflow artifacts | Map status into machine-checkable evidence sufficiency by action class and risk tier. |
| High-resolution timeline layer | Argo workflow refs, workflow phase, conditions, artifact locations | Normalize workflow events into Mesh run timeline, Perennial commits, and Darkharness proof material. |
| Admission, scheduling, and concurrency layer | Argo workflow manager, tenant quotas, reconcile tests | Add target locks, queue priority, cancellation, stuck-run recovery, backpressure, and race handling across operators/watchers/webhooks. |
| Secrets and workload identity layer | SecretKeyRef, RBAC manifests, license secret, network policy | Add least-privilege identities, scoped kubeconfigs, secret rotation evidence, break-glass recording, and no credential bleed into proposal lanes. |
| Durable artifact movement layer | MinIO chart, workflow artifact mapping, target bucket/prefix | Replace local-only artifact assumptions with upload proofs, hashes, retention, purge, restore, and audit retrieval. |
| External assurance layer | Helm chart, CRDs, tests, secret-scan scripts, boundary checks | Add signed release, SBOM, vulnerability scan, image digest, clean tree, CI attestation, and reproducible benchmark records. |
| Operator workflow layer | `agentctl`, `agentctl-web`, approve/reject/status/cost verbs | Adapt workflows into Orbital Mesh approval queues, handoff, override review, postmortem, audit export, and pilot signoff. |
| Business deployment layer | Helm chart, docs, private boundary manifest, licensing and metering interfaces | Package Docker/Helm/Terraform, marketplace path, design-partner packet, security questionnaire, support model, and deployment tiers. |

## Competitive Thesis Handling

The source repo contains NineVigil positioning against kagent. Treat it as an internal hypothesis:

- kagent validates demand for Kubernetes-native agent operations;
- Orbital Mesh should compete on offline-first and private deployment, governed remediation authority, tenant isolation, cost attribution, policy/evidence proof, and air-gapped operation;
- external claims about kagent capabilities, contributors, or deficiencies require independent verification before publication;
- avoid "only option" claims unless backed by current market evidence;
- public wording should say what Orbital Mesh demonstrably provides, not what another project allegedly cannot do.

The durable product claim is narrower and stronger: Orbital Mesh is a governed remediation control plane that can run in private, restricted, and air-gapped environments while preserving identity, policy, evidence, approval, feedback, and proof.

## Fork Sequence

1. **Inventory and provenance**
   - Record source commit, license, file list, and imported paths before copying code.
   - Preserve Apache-2.0 notices where code is copied.
   - Mark the current `agentic-operator-core-main/` tree as source input, not active runtime.

2. **Schema fork**
   - Create Orbital Mesh CRD schemas for `MeshAgentWorkload` and tenant/boundary objects.
   - Carry forward useful fields: objective, agents, providers, orchestration, resources, timeouts, workflow refs, artifacts, conditions, quotas, SLA, and network policy.
   - Add missing authority fields: owner, approver, customer boundary, action class, policy hash, evidence sufficiency, rollback authority, retention, and export permissions.

3. **Controller substrate**
   - Fork reconciliation patterns only after authority invariants are encoded.
   - Every reconcile path must call Orbital Mesh admission, policy, evidence, evaluation, approval, and rollback gates before mutation.
   - Status updates must emit run events and proof material, not only Kubernetes conditions.

4. **Argo scheduling**
   - Import Argo Workflow creation as a bounded scheduler.
   - Add target locks, run cancellation, stuck-run recovery, queue metrics, timeout policy, and approval-expiry behavior.
   - Preserve suspend gates only when they map to Orbital Mesh operator approval.

5. **Tenant isolation and network policy**
   - Fork tenant namespace, quota, RBAC, and network-policy patterns.
   - Add data-boundary, customer-boundary, service-owner, export, and retention semantics.
   - Treat Cilium FQDN egress as a validated target only after a live cluster proof exists.

6. **Provider routing, MCP, and cost attribution**
   - Bring LiteLLM and MCP in as certified connectors, not core authority.
   - Add OpenMeter-compatible usage events behind a no-op default.
   - Enforce budget/quota as admission blockers without weakening safety gates.

7. **Packaging**
   - Fork Helm chart structure after schema/controller names settle.
   - Rename chart values, labels, namespaces, image names, and CRD groups to Orbital Mesh.
   - Add readiness, release provenance, SBOM, vulnerability scan, signed policy hash, and go/no-go packet requirements.

8. **Operator workflows**
   - Mine `agentctl` verbs for CLI parity.
   - Keep browser UI and production operator workflow as Orbital Mesh surfaces.
   - Add approval queues, handoff, override review, and audit export flows before pilot expansion.

9. **Validation**
   - Add schema compatibility tests against the forked CRDs.
   - Add controller invariant tests for denied namespace, proposal-lane isolation, budget exceeded, missing evidence, missing approval, expired policy, stuck workflow, and artifact upload failure.
   - Promote a forked feature from recipe to validated only after health, readiness, persistence, feedback, audit, rollback, and release-packet evidence exists.

## Do Not Import

- Do not import landing-page or product-site assets into the active Orbital Mesh UI.
- Do not import comparative claims as docs without verification.
- Do not preserve auto-approval semantics as production autonomy.
- Do not let MCP, LiteLLM, Browserless, Argo, or agent runtimes hold production actuator credentials.
- Do not move billing/licensing into the critical safety path.
- Do not replace the existing Orbital Mesh evidence, policy, evaluation, Perennial, or Darkharness contracts with Kubernetes conditions alone.
