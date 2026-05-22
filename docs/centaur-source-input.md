# Centaur Source Input

State slice: `mesh.centaur_source_input.v1`

This record tracks Centaur as a source-input architecture kit for Mesh. Mesh remains the authority for policy, approval, actuation, final run state, Merkle proof, and promotion. Centaur patterns may inform sandbox runtime, lifecycle, workflow, tool, and credential-egress implementation, but Centaur is not vendored as a subtree and does not become a second Mesh control plane.

## Source

- Local source path: `/Users/shaanp/Documents/venture/source-inputs/centaur`
- Remote: `https://github.com/paradigmxyz/centaur.git`
- Source commit: `7627e5f8afb2f584e2c542441e44426b8bf22c45`
- Commit subject: `fix: fall back when Slack live answer is missing (#140)`
- Source tree status at inventory time: clean on `main`
- License: `Apache-2.0 OR MIT`
- License evidence: `/Users/shaanp/Documents/venture/source-inputs/centaur/LICENSE:6`

## Reused Patterns

| Centaur source | Mesh use | Copy status |
| --- | --- | --- |
| `README.md` | High-level primitives: Kubernetes sandbox, harnesses, shared tools, durable workflows, credential boundaries, replayable state. | Pattern only |
| `docs/pages/architecture.mdx` | Durable lifecycle: spawn/reuse runtime, persist input, execute, replay events, release; Kubernetes sandbox as active runtime path; tool/workflow and proxy-mediated credential model. | Pattern only |
| `services/api/api/runtime_control.py` | Lifecycle shape for durable agent execution. Mesh adapts this into `AgentAttempt` and run events, not a new control plane. | Pattern only |
| `services/api/api/sandbox/` | Sandbox backend abstraction and Kubernetes implementation shape. Mesh may implement an adapter that submits proposal work and returns `AgentAttempt`. | Pattern only |
| `services/sandbox/harness_adapter.py` | Harness translation model for Anthropic-shaped content and plain-text CLIs. Mesh may adapt prompt shaping inside `services/orchestrator/centaur_adapter.py`. | Pattern only |
| `services/api/api/tool_manager.py` | Tool discovery model. Mesh keeps its typed investigation `ToolRegistry` and exposes read-only/proposal-only tools only. | Pattern only |
| `centaur_sdk/tool_sdk.py` | Tool credential accessor and plugin conventions. Mesh records credential policy metadata and does not pass raw secrets into sandbox env/output. | Pattern only |
| `services/api/api/workflow_engine.py` | Checkpoint/replay workflow semantics. Mesh workflows must reference or annotate Mesh runs and never own remediation. | Pattern only |
| `services/api/api/iron-proxy.base.yaml` | Proxy-mediated egress model with placeholder credentials and host-bound substitution. Mesh starts with a contract/readiness proof before optional sidecar deployment. | Pattern only |
| `contrib/chart` | Deployment patterns: namespace, service account, network policy, labels, warm pool, proxy sidecar, health endpoints. | Pattern only |

## Exclusions

- No Centaur subtree, service tree, Helm chart, SDK package, workflow implementation, Slackbot, or database schema is copied wholesale into Mesh.
- No Centaur API is allowed to own Mesh run state, policy decisions, approval, actuation, Merkle history, promotion, or operator identity.
- No raw Centaur credential wiring is copied into sandbox configuration.
- No copied file is accepted without either an inline provenance comment or a row in this source-input inventory.

## Authority Boundary

Centaur-derived work must terminate in Mesh-native records:

- Agent execution becomes `AgentAttempt`.
- Lifecycle events become Mesh `RunEvent` payloads.
- Tool calls are read-only or proposal-only by contract.
- Credential access is represented by named secret references, allowed egress locations, and audit events.
- Workflows create or annotate Mesh runs and reference `run_id`; they do not replace `RunSession`.
- Operators inspect proposals and approvals through Mesh UI/API; Mesh alone executes remediation.

## Validation Commands

Run the root validation ladder after non-trivial implementation:

```bash
git status --short --branch
pnpm run lint:fast
pnpm run verify:contracts
pnpm run test:focused
pnpm run verify:full
git diff --check
```

Slice-specific gates:

- `mesh.agent_sandbox_runtime.v1`: fake Centaur API unit tests.
- `mesh.investigation_tool_registry.v1`: read-only registry tests.
- `mesh.credential_egress_policy.v1`: no-secret-leak fixture test.
- `mesh.durable_workflow_run.v1`: crash/replay checkpoint test.
- `meshapp.agent_fabric_observability.v1`: `pnpm --dir meshapp/frontend run test`.
- `mesh.centaur_deployment_profile.v1`: compose/kubernetes manifest render checks, with live execution claims blocked until egress proof and namespace policy pass.

## Cautions

- The short commit `7627e5f8` is expanded above to the full source SHA.
- The SPDX license evidence is on `LICENSE:6`; `LICENSE:1` is only the prose opening.
- `iron-proxy.base.yaml` is a pattern source only. Production Mesh policy must use explicit allowed hosts rather than a wildcard egress posture.
- Centaur credentials are deployment-scoped in the inspected source; Mesh must not claim per-operator credential isolation until it implements and verifies it.
