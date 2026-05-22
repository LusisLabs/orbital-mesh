# Agent Mesh

Mesh Intelligence exposes a supervised worker contract so external agents can participate in incident response without owning production side effects.

## State Slice

The agent-routing state slice is explicit:

- `mesh.orchestration_topology_profile.v1` in `config/orchestration-topology.profile.json`
- `mesh.orchestration_topology_resolution.v1` on each `AgentTask`
- `lane_routing` on run exports

Do not infer topology ownership from adapter imports. The topology resolver owns lane selection, lane roles, authority posture, blockers, source evidence, and reconciliation mode before proposal attempts are collected.
The same state slice now carries the organization profile and model-provider policy used for lane personalization; raw provider secrets stay in environment/runtime secret stores and are never copied into run artifacts.

## Boundary

Mesh owns:

- run state and audit events
- policy and evaluation gates
- test and smoke requirements
- Kubernetes actuation
- vault and Merkle evidence
- production promotion decisions

Agents own:

- investigation summaries
- root-cause hypotheses
- patch proposals
- review findings
- staging validation suggestions

Workers do not write production, mutate the real repo checkout, mutate `main`, or bypass Kubernetes allowlists. Code-writing adapters must stay inside isolated workspaces and return diffs, changed-file lists, summaries, and test results for Mesh evaluation.
Workers also do not mutate shared semantic or procedural memory directly. They
receive verified memory packets and may only return proposed observations,
claims, procedures, citations, and contradiction flags for Mesh review.

## Worker Contract

Each run that reaches evaluation records an `agent_tasks` artifact.

- `MESH_AGENT_FABRIC_MODE=native` keeps default read-only attempts for Goose, Hermes, Codex, Claude Code, OpenClaw, and native orchestration platform lanes: Airflow, Temporal, Dagster, Prefect, Flyte, Luigi, Oozie, Kubernetes, and n8n. These attempts are proposal and evaluator-contract artifacts, not real CLI/API invocations.
- `MESH_AGENT_FABRIC_MODE=deepagents` routes those lanes through `services/orchestrator/deepagents_adapter.py`. Mesh creates a per-run sandbox workspace under `MESH_DEEPAGENTS_WORKSPACE_ROOT`, copies only allowed files into that workspace for patch-shaped tasks, and records Deep Agents output as proposal artifacts. Mesh still owns policy, tests, audit, Kubernetes actuation, and production promotion.
- `MESH_AGENT_FABRIC_MODE=langgraph` routes non-LatentMAS lanes through `services/orchestrator/langgraph_adapter.py`. LangGraph records checkpoint and workflow metadata inside normal `AgentAttempt.output` records. It does not create a new authority path, execution record, approval, policy override, or actuation capability. Missing LangGraph packages or checkpointers degrade the attempt and leave the Mesh run alive.
- `MESH_AGENT_FABRIC_MODE=centaur` routes non-LatentMAS lanes through `services/orchestrator/centaur_adapter.py`. The adapter uses Centaur source-input sandbox lifecycle patterns and records only proposal-shaped `AgentAttempt` artifacts with `output.thread`, execution events, harness metadata, and placeholder-only credential policy. Mesh still owns policy, approval, actuation, final run state, Merkle proof, and promotion.

LatentMAS can be enabled as a first-class full-inference worker lane. It runs through a separate PyTorch/Hugging Face sidecar and records an additional `latentmas_http` attempt ahead of the native lanes. LatentMAS output is advisory only: Mesh still owns policy, tests, audit, Kubernetes actuation, and production promotion.

Operator ingress uses state slice `mesh.operator_agent_ingress.v1`. Slack and other external operator sources can create Mesh-owned `operator_ingress_investigation` proposal tasks with identity and evidence context, but the ingress record stays non-authoritative: it cannot execute remediation, approve actuation directly, or write memory without Mesh review and role-policy checks.

Sandbox tools use state slice `mesh.investigation_tool_registry.v1`. The sandbox bridge exposes read-only tools and explicit proposal-only mutation tools through internal metadata only. Proposal tools must declare `returns_proposal`, `executes_side_effects=false`, and `requires_mesh_approval`; runtime output is rejected unless it returns a Mesh-approval proposal with `side_effects_executed=false`. Every sandbox tool request records an audit decision, and `mutation_allowed` remains false.

## Topology-Aware Personalization

Mesh personalizes the agent mesh from domain and infrastructure evidence rather than from a fixed adapter list. The resolver reads the topology profile, then matches run context such as service, signal source, action class, risk tier, tenant, organization domain, team, deployment substrate, namespace, data boundary, ownership boundary, connector certification, readiness, historical outcomes, and trust-ladder state.

The shipped profile includes a versioned organization/infra profile with domain, teams, tenants, ownership boundaries, deployment substrates, data boundaries, preferred agents, allowed model providers, allowed models, autonomy tier, risk thresholds, and required evidence refs. `GET /api/readiness` exposes that profile summary under `orchestration_topology.organization_profile` plus `org_profile_ready`.

Supported topologies:

| Topology | Role model | Default reconciliation |
| --- | --- | --- |
| `centralized` | Mesh-assigned workers | `mesh_authoritative_single_decision` |
| `hierarchical` | Supervisor plus workers | `mesh_reconciles_supervisor_and_worker_outputs` |
| `decentralized` | Peer proposals | `mesh_reconciles_parallel_peer_proposals` |
| `federated` | Tenant or ownership-bounded lanes | `mesh_reconciles_with_tenant_data_and_credential_boundaries` |
| `hybrid` | Rule-specific mixed topology | `mesh_reconciles_per_rule_topology_outputs` |

The shipped profile declares all five modes as active routing choices: centralized default, tenant-aware hybrid search rollback routing, generic hybrid Kubernetes rollback routing, hierarchical workflow supervision, decentralized data-pipeline peer proposals, and federated tenant model-workflow evidence. Hybrid is expected to be common because real organizations rarely map cleanly to one topology. For example, a tenant search rollback can route through a Temporal supervisor lane, a Hermes peer-proposal lane, a Dagster federated-tenant evidence lane, and a Kubernetes bounded-actuator lane at the same time while Mesh remains the final reconciler.

Every selected lane records `role`, `topology_role`, `model_binding`, `authority`, `authority_posture`, `credential_boundary`, `source_evidence`, blockers, and a lane-level `reconciliation_mode`. Model bindings include provider/model/route/config-source metadata and env-var names for secrets, not secret values.

`MESH_AGENT_MESH_AGENTS` is a hard runtime filter. If it excludes lanes requested by a profile rule, the resolver records blockers such as `topology_rule_lanes_filtered_by_agent_mesh_agents`; profile rules cannot silently re-enable excluded lanes.

API:

```text
GET /api/runs/:run_id/agent-tasks
```

Artifact shape:

```json
{
  "task_id": "task_run_..._rollback_plan_...",
  "run_id": "run_...",
  "kind": "root_cause|patch|review|rollback_plan",
  "status": "completed",
  "allowed_paths": [],
  "test_commands": [],
  "kubernetes_scope": {
    "context": "k3d-mesh-e2e",
    "namespace": "search",
    "deployment_name": "semantic-search"
  },
  "memory_scope": {
    "shared": true,
    "service": "search",
    "run_id": "run_..."
  },
  "memory_packet": {
    "packet_id": "mpkt_...",
    "claims": [],
    "procedures": [],
    "contradictions": [],
    "citations": []
  },
  "attempts": [
    {
      "agent": "goose",
      "adapter": "native_contract",
      "status": "completed",
      "summary": "Operational plan...",
      "risk_flags": [],
      "recommended_action": "execute",
      "observations_proposed": [],
      "claims_proposed": [],
      "citations": [],
      "memory_actions_requested": ["defer"]
    }
  ],
  "selected_attempt_id": "attempt_..."
}
```

The task also carries `orchestration_topology` and `lane_routing`. Those artifacts are `mesh.orchestration_topology_resolution.v1` records with `active_topology`, `selected_lanes`, lane-level model bindings, connector-derived credential boundaries, source evidence refs, blockers, and reconciliation mode.

With LatentMAS enabled, the first attempt may look like:

```json
{
  "agent": "latentmas",
  "adapter": "latentmas_http",
  "status": "completed",
  "summary": "LatentMAS recommends the gated execution path.",
  "risk_flags": [],
  "recommended_action": "execute",
  "output": {
    "confidence": 0.91,
    "raw_prediction": "{\"summary\":\"...\"}",
    "agent_traces": [],
    "metrics": {
      "model_name": "Qwen/Qwen3-4B",
      "elapsed_time_sec": 12.4,
      "latent_steps": 10,
      "prompt_mode": "sequential",
      "backend": "transformers"
    }
  }
}
```

If the sidecar is unavailable, Mesh records a failed LatentMAS attempt with `latentmas_unavailable` and continues with the remaining worker lanes for the active agent fabric mode.
LatentMAS health is preflight-aware: the sidecar now reports readiness detail from `/health`, and Mesh skips the inference call when the sidecar reports `ready: false`. This prevents a false-green readiness check followed by an immediate `500` on `/infer`.

With Deep Agents enabled, a lane attempt looks like:

```json
{
  "agent": "codex",
  "adapter": "deepagents",
  "status": "completed",
  "summary": "Bounded patch proposal prepared in sandbox workspace.",
  "risk_flags": [],
  "recommended_action": "human_review",
  "changed_files": ["fixtures/codebases/search_service/app/search.py"],
  "test_results": [
    {
      "name": "pytest",
      "passed": true,
      "detail": "2 checks passed"
    }
  ],
  "output": {
    "workspace_path": "/app/.mesh-runtime-state/deepagents/run_.../task_.../codex",
    "effective_model": "openai:MiniMax-M2.7",
    "model_binding": {
      "provider": "openai",
      "model": "MiniMax-M2.7",
      "route": "deepagents_sandbox",
      "secret_ref_envs": ["OPENAI_API_KEY", "MINIMAX_API_KEY"],
      "secret_material_present": false
    },
    "diff": "--- a/...\n+++ b/...\n@@ ...",
    "deepagents_final_message": "{...}"
  }
}
```

If Deep Agents is enabled but the dependency or provider credentials are unavailable, Mesh records a failed or degraded attempt with non-blocking risk flags such as `deepagents_dependency_missing` or `deepagents_model_credentials_missing`.
Agent-task collection is best-effort and bounded by `MESH_AGENT_TASK_TIMEOUT_SECONDS` so proposal lanes cannot block control-plane execution. Slow lanes degrade into recorded failed attempts with `agent_mesh_timeout`.
For `openai:MiniMax-*` Deep Agents models, Mesh resolves credentials from `OPENAI_API_KEY` and falls back to `MINIMAX_API_KEY` for the OpenAI-compatible MiniMax route.

## Native Orchestration Platform Lanes

Native platform lanes let Mesh ingest orchestration evidence from any external platform without letting that platform override Mesh policy. Each lane records:

- the platform category and best-fit workload
- whether the platform has an agentic execution surface
- the native evaluator signal Mesh expects from that platform
- the adapter contract fields a real integration must supply
- the authority boundary: external platforms provide evidence and proposals; Mesh remains authoritative for evaluation, audit, actuation, and promotion

Current native platform lanes:

| Lane | Best fit | Agentic surface | Native evaluator signal |
| --- | --- | --- | --- |
| `airflow` | Data/ML pipelines | No; DAGs only | DAG dependency coverage |
| `temporal` | Durable execution | Yes; workflows and activities | Durability, retries, and idempotency |
| `dagster` | Asset-centric pipelines | No | Asset lineage and materialization checks |
| `prefect` | Python workflows | No | Flow state and observability |
| `flyte` | Reproducible ML | No | Cache, version, and reproducibility checks |
| `luigi` | Simple DAGs | No | Task dependency completion |
| `oozie` | Big data jobs | No | Hadoop workflow and action state |
| `kubernetes` | Microservices | Yes; operators and controllers | Controller reconciliation health |
| `n8n` | Automation | Yes; nodes plus AI workflows | Node execution trace |

## LatentMAS Sidecar

LatentMAS is disabled unless all of these are set:

```bash
MESH_LATENTMAS_ENABLED=1
MESH_LATENTMAS_URL=http://127.0.0.1:8791
```

Optional controls:

```bash
MESH_LATENTMAS_TIMEOUT_SECONDS=600
MESH_LATENTMAS_MODEL_NAME=Qwen/Qwen3-4B
MESH_LATENTMAS_DEVICE=cuda
MESH_LATENTMAS_PROMPT_MODE=sequential
MESH_LATENTMAS_LATENT_STEPS=10
MESH_LATENTMAS_MAX_NEW_TOKENS=1024
MESH_LATENTMAS_USE_VLLM=0
MESH_LATENTMAS_MAX_ARTIFACT_CHARS=20000
```

Run the opt-in Docker profile:

```bash
docker compose -f docker-compose.yml -f docker-compose.latentmas.yml --profile latentmas up --build
```

In the all-in-one stack, use the stack profile and set Mesh to expect LatentMAS readiness:

```bash
COMPOSE_PROFILES=latentmas MESH_STACK_ENABLE_LATENTMAS=1 docker compose -f docker-compose.stack.yml up --build
```

The sidecar exposes:

```text
GET /health
POST /infer
```

`GET /api/readiness` includes `latentmas.ready`, `latentmas.detail`, and `latentmas.url`.

## Deep Agents Fabric

Deep Agents is disabled unless:

```bash
MESH_AGENT_FABRIC_MODE=deepagents
```

In the all-in-one stack, enable it through the stack-scoped variable so the smoke verifier also expects Deep Agents readiness:

```bash
MESH_STACK_AGENT_FABRIC_MODE=deepagents OPENAI_API_KEY=... docker compose -f docker-compose.stack.yml up --build
```

Optional controls:

```bash
MESH_DEEPAGENTS_MODEL=openai:MiniMax-M2.7
MESH_DEEPAGENTS_TIMEOUT_SECONDS=120
MESH_DEEPAGENTS_WORKSPACE_ROOT=.mesh-runtime-state/deepagents
MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS=20000
```

Readiness behavior:

- If `MESH_AGENT_FABRIC_MODE` is not `deepagents`, `/api/readiness` reports Deep Agents as disabled.
- If the vendored `deepagents` package is unavailable on `PYTHONPATH`, readiness reports Deep Agents unavailable.
- If Deep Agents is enabled and importable, readiness reports the configured model and workspace path.
- Provider-key warnings are surfaced through `deepagents.warnings`; missing keys do not block the Mesh control plane from running.

Operational boundary:

- Deep Agents never executes Mesh actuation.
- Deep Agents never runs live `kubectl`.
- Deep Agents never edits the real repository checkout.
- Patch-shaped lanes only see copied `allowed_paths` files inside the sandbox workspace.
- Any sandbox-created file outside the allowlist is flagged and withheld as a safe proposal artifact.

## Frontend

Open the `Agents` tab on any run. The panel shows:

- task kind and scope
- participating worker lanes
- topology role and lane reconciliation mode
- per-lane model/provider binding without raw secret values
- connector certification and lane source-evidence refs
- selected attempt
- adapter
- recommended action
- risk flags
- allowed paths and test counts
- changed files
- test results
- workspace path
- diff artifact when present

## Codex Plugin

The repo includes a legacy-named local Codex plugin at `plugins/mesh-intelligence` and a repo marketplace entry at `.agents/plugins/marketplace.json`.

The plugin contributes the `mesh-intelligence` compatibility skill. Codex workers using that skill should call the bundled read-only helper:

```bash
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py health
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py summary --run-id run_...
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py agent-tasks --run-id run_...
```

The helper defaults to `http://127.0.0.1:8787` and honors `MESH_BASE_URL`. It does not mutate Mesh state. If it reports `stale_agent_tasks_route: true`, the running Mesh server predates the agent-task route and must be restarted from the current tree before Codex can read first-class `agent_tasks` payloads.

## Production Rule

Treat LatentMAS, Deep Agents, Goose, Hermes, Codex, Claude Code, OpenClaw, and native orchestration platform lanes as bounded workers. They can propose and provide evidence. Mesh decides. Production execution remains behind Mesh policy, smoke checks, and approval gates.
