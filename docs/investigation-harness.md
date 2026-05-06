# Investigation Harness — Tool Surface

The investigation harness is the seam where Mesh stops running fixed pipeline probes and starts being a registry of read-only diagnostic tools that planners (deterministic rule-pack or LLM) invoke under a critic. This document is the **tool surface** reference: what packs exist, how they auto-register, and how the full RCA-with-tools loop is wired.

For the harness primitives themselves (`ToolDefinition`, `ToolRegistry`, `LoopCritic`, `NativeProbeSelector`, `RootCauseCandidate`), see the docstrings in `services/investigation/harness/`.

## The full loop in one diagram

```
                                    MeshRuntimeEngine.run_sync(raw_signal)
                                                    │
                          ┌─────────────────────────┴─────────────────────────┐
                          │                                                   │
                          │   __init__:                                       │
                          │     root_registry := ToolRegistry()               │
                          │     _register_root_diagnostic_packs(...)          │
                          │       └── prometheus / aws / kubectl / github     │
                          │           loki / jaeger / postgres                │
                          │           (each gated on config / env)            │
                          │                                                   │
                          │   run_sync:                                       │
                          │     ingest → trigger                              │
                          │     _auto_wire_investigation_harness(             │
                          │         raw_signal, trigger, config,              │
                          │         root_registry=self.root_registry)         │
                          │       │                                           │
                          │       ├── if cloudops_snapshot present:           │
                          │       │     per_run = ToolRegistry()              │
                          │       │     register_cloudops_tools(per_run)      │
                          │       │     _overlay_root_registry(per_run, root) │
                          │       │     planner = LlmProbeSelector(           │
                          │       │       rule_pack=CloudOpsRulePack,         │
                          │       │       decision_provider=llm or None)      │
                          │       │     OR CloudOpsLoopPlanner(trigger)       │
                          │       │                                           │
                          │       └── else: (None, None) — harness disabled   │
                          │                                                   │
                          │   InvestigationService.investigate(               │
                          │       trigger, evidence_pack, registry, planner)  │
                          │     ┌─────── run_investigation_loop ──────┐       │
                          │     │  while not stop:                    │       │
                          │     │    decision = planner.plan(state)   │       │
                          │     │    filtered = critic.review(...)    │       │
                          │     │    for call in filtered.next_calls: │       │
                          │     │      result = registry.invoke(call) │       │
                          │     │      state.record(call, result)     │       │
                          │     └─────────────────────────────────────┘       │
                          │                                                   │
                          │   InvestigationReport carries:                    │
                          │     probe_results, citations, root_cause_         │
                          │     candidates (from RootCauseRanker pass)        │
                          │                                                   │
                          │   HypothesisEngine reads root_cause_candidates    │
                          │   DecisionService consumes ranked hypotheses      │
                          │   RcaReport cites candidates + supporting tools   │
                          │                                                   │
                          └───────────────────────────────────────────────────┘
```

## Why layered (root + per-run)

A single global registry is too coarse: per-scenario CloudOps snapshot tools need run-scoped data (the snapshot itself), and Reth probes need a specific node payload. A purely per-domain registry is too narrow: the LLM planner should be able to query Prometheus or read GitHub commits *while* investigating a CloudOps scenario.

Resolution: **`root_registry` is built once at engine construction with always-on diagnostic packs** (gated on config/env presence). When a per-run domain match fires (e.g. CloudOps snapshot in `raw_signal`), the engine builds a per-run registry, overlays the root onto it via `_overlay_root_registry`, and the resulting union is what the planner and critic see.

Per-run tools win on name conflicts — the LLM should see the freshest snapshot data without losing access to root diagnostics that share a name.

## Boundary

The harness owns:

- The `ToolRegistry` of `(ToolDefinition, invoke_fn)` pairs.
- The `LoopCritic` that rejects unknown / mutating / duplicate / invalid-args calls.
- The `run_investigation_loop` orchestrator (planner → critic → registry → state).
- The `NativeProbeSelector` substrate that turns rule packs into planner decisions, and the `LlmProbeSelector` that uses the same shape with an LLM as the chooser.

The harness does not own:

- Decision-making — `DecisionService` + `HypothesisEngine` consume `root_cause_candidates`.
- Production mutation — `OrchestratorService` + actuators behind policy / evaluation.
- Evidence assembly — `EvidenceService`.

The harness produces evidence; downstream stages decide what to do with it.

## Domain packs

Ten domains in production today. Each is one file under `services/investigation/`. The first two (CloudOps, Reth) are per-run augmentations bound to a specific signal payload. The other eight auto-register at the engine root if their config/env signal is present.

### `cloudops` — 8 tools, per-run augmentation

`services/investigation/cloudops_tools.py`

Snapshot-bound k8s diagnostics for Cloud-OpsBench scenarios. Auto-wired when `raw_signal["cloudopsbench_snapshot"]` is present.

| Tool | Args |
|---|---|
| `GetResources` | resource_type, namespace, name, label_selector, output_wide, show_labels |
| `DescribeResource` | resource_type, name, namespace |
| `GetAppYAML` | resource_type, name, namespace, app_name |
| `GetErrorLogs` | resource_type, name, namespace |
| `GetAlerts` | namespace |
| `CheckServiceConnectivity` | resource_type, name, namespace |
| `GetClusterConfiguration` | (none) |
| `GetRecentLogs` | resource_type, name, namespace |

Read-only by construction — backed by an immutable snapshot tool cache.

### `reth` — 5 tools, per-run augmentation

`services/investigation/reth_tools.py`

Reth node observation, backed by `services/evidence/reth_probe_registry.snapshot_for_probe`. Wired by `RethRulePack` (peer-starvation slice).

| Tool | Reads |
|---|---|
| `read_peer_sync` | execution.peer_count, min_peer_count, syncing, block_lag |
| `read_consensus_status` | consensus.engine_api_reachable, client_kind, jwt state |
| `read_rpc_health` | rpc.http_reachable, latency_ms, error_rate |
| `read_disk_jwt` | storage.disk_used_pct + redacted JWT metadata |
| `read_recent_logs` | logs.error_signatures + redacted recent errors |

### `prometheus` — 2 tools, root pack

`services/investigation/prometheus_tools.py`

Auto-registered at root when `RuntimeConfig.prometheus_url` is set. Backed by `shared.mesh_runtime.otel.PrometheusClient`.

| Tool | Args |
|---|---|
| `query_metrics_instant` | query |
| `query_metrics_range` | query, start_ts, end_ts, step_seconds |

### `aws` — 1 tool, root pack

`services/investigation/aws_tools.py`

Auto-registered at root when `MESH_AWS_TOOLS_ENABLED=1`. boto3 lazy-imported.

| Tool | Args |
|---|---|
| `execute_aws_operation` | service, operation, parameters, region |

One generic tool covers ~all read-only AWS APIs because the boto3 surface is uniform. Two-layer enforcement:

1. Critic blocks anything not classified `read_only`.
2. Invoke fn rejects any operation whose verb isn't `Describe` / `Get` / `List` / `Search` / `Lookup` (snake_case or CamelCase). Mis-classification can't slip through.

Conservative redaction drops any key matching `secret` / `password` / `token` / `credential` / `private` recursively.

### `kubectl` — 3 tools, root pack

`services/investigation/kubectl_tools.py`

Auto-registered at root when `KUBECONFIG` (or `~/.kube/config`) exists *and* `kubectl` is on PATH. Subprocess; no Python kubernetes-client dep.

| Tool | Args |
|---|---|
| `kubectl_get` | resource_type, namespace, name, label_selector, output_wide, show_labels, all_namespaces, context |
| `kubectl_describe` | resource_type, name, namespace, context |
| `kubectl_logs` | name, namespace, container, tail_lines, previous, context |

Each tool builds an explicit argv with a fixed verb. There is no "exec arbitrary kubectl" surface. Output bounded to 64 KiB per call.

### `github` — 4 tools, root pack

`services/investigation/github_tools.py`

Auto-registered when `gh auth status` succeeds. All hard-coded `gh api -X GET`. No "create issue" or "post comment" surface.

| Tool | Args |
|---|---|
| `github_recent_commits` | repo, branch, limit |
| `github_file_contents` | repo, path, ref |
| `github_search_code` | repo, query, limit |
| `github_pr_diff` | repo, pr_number |

### `loki` — 3 tools, root pack

`services/investigation/loki_jaeger_tools.py`

Auto-registered when `MESH_LOKI_URL` is set. Pure-HTTP `urllib.request` (no `requests` dep).

| Tool | Args |
|---|---|
| `query_range` | query (LogQL), start_ts, end_ts, limit, direction |
| `labels` | start_ts, end_ts |
| `label_values` | label, start_ts, end_ts |

Timestamps converted to nanoseconds for Loki's API.

### `jaeger` — 3 tools, root pack

`services/investigation/loki_jaeger_tools.py`

Auto-registered when `MESH_JAEGER_URL` is set.

| Tool | Args |
|---|---|
| `get_services` | (none) |
| `get_traces` | service, operation, lookback_seconds, limit, tags |
| `get_dependencies` | lookback_seconds |

Timestamps converted to microseconds for Jaeger's API.

### `postgres` — 3 tools, root pack

`services/investigation/db_tools.py`

Auto-registered when `MESH_PG_DSN` is set *and* `psql` is on PATH. Subprocess; no `psycopg` dep. DSN captured at registration via closure — tool args cannot supply or override it.

| Tool | Args |
|---|---|
| `pg_describe_table` | table_name |
| `pg_explain_query` | query (SELECT only — DML rejected) |
| `pg_active_queries` | min_duration_seconds, limit |

Defense in depth:

- Identifier validation regex rejects anything not matching `[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?` (blocks injection via `table_name`).
- DML verb scan in `pg_explain_query` rejects INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / GRANT / REVOKE / CREATE before psql sees the query.

### `mcp` — dynamic, root pack

`services/investigation/mcp_tools.py`

Bridge — not transport. Mesh does not implement the MCP wire protocol. Callers supply an opaque `MCPClientProtocol` (duck-typed: `list_tools()` + `call_tool(name, args)`); the bridge translates each MCP-advertised tool into a registered `ToolDefinition`.

```python
class MCPClientProtocol(Protocol):
    def list_tools(self) -> list[MCPToolMeta]: ...
    def call_tool(self, name: str, args: dict) -> Any: ...
```

Real implementations: official `mcp` SDK, FastMCP, hand-rolled stdio JSON-RPC. Whatever the caller wants.

Safety floor:

- Discovery turns each MCP tool into a separate `ToolDefinition` so the critic can see it.
- Default `mutation_class="read_only"`; mutating tools are filtered out unless the operator explicitly opts in via `mutation_class_map={"tool": "hard_mutation"}` AND `block_mutating=False`.
- Per-server `allow_tools` allowlist gives operators final say.
- Tools namespaced under `server_id` (`mcp:sregym__get_metrics`) so multiple MCP servers can advertise the same tool name.

Auto-registration via `MESH_MCP_SERVERS=id1=url1,id2=url2` env requires a caller-supplied `client_factory` callable — Mesh does not pick a transport for you.

## Total surface

| Domain | Tools | Auto-register signal | Mutation? |
|---|---:|---|---|
| `cloudops` | 8 | per-run (snapshot in signal) | read-only |
| `reth` | 5 | per-run (rule pack on reth trigger) | read-only |
| `prometheus` | 2 | `RuntimeConfig.prometheus_url` | read-only |
| `aws` | 1 | `MESH_AWS_TOOLS_ENABLED=1` | read-only enforced |
| `kubectl` | 3 | kubeconfig + `kubectl` on PATH | read-only verbs only |
| `github` | 4 | `gh auth status` ok | read-only (`gh api -X GET`) |
| `loki` | 3 | `MESH_LOKI_URL` | read-only |
| `jaeger` | 3 | `MESH_JAEGER_URL` | read-only |
| `postgres` | 3 | `MESH_PG_DSN` + `psql` | read-only verbs only |
| `mcp` | dynamic | `MESH_MCP_SERVERS` + factory | configurable per-server |
| **Total native** | **32** | | |

## How tool results reach RCA

This is the deliberate wiring. When the harness loop completes:

1. **`InvestigationLoopState`** carries `tool_calls`, `tool_results`, `observed_text`, `planner_decisions`.
2. **`NativeProbeSelector` / `LlmProbeSelector`** runs `RootCauseRanker` over the loop's observed text after each iteration. `cloudops_ontology.rank_root_causes` is the canonical example — text patterns → `RootCauseCandidate` objects.
3. **`InvestigationReport.root_cause_candidates`** is a first-class field on the report (not buried in findings). `services.benchmark.scoring` and `HypothesisEngine` consume it directly.
4. **`HypothesisEngine.generate(trigger, evidence_pack)`** reads the candidates from the report (via decision service) and produces ranked hypotheses with `recommended_action`.
5. **`DecisionService.decide`** picks the action; `decision.reasoning.ranked_hypotheses` carries the labels.
6. **`build_rca_report(trigger, decision, evidence_pack)`** cites `supporting_tools` per candidate so the audit trail names the calls that proved each cause.

The whole chain is read-only on the LLM's side: it picks tools, the critic gates them, the registry invokes, the ontology ranks, and the deterministic decision/RCA layers consume the structured output. Mutation goes through `OrchestratorService` after policy + evaluation — not through this loop.

## Safety summary

| Layer | What enforces it |
|---|---|
| Critic blocks mutating tools | `LoopCritic.allowed_mutation_classes = ("read_only",)` |
| Critic blocks duplicate calls | `state.call_signatures()` check |
| Critic blocks invalid args | flat `args_schema` type + required check |
| Tool-level read-only enforcement | AWS verb check, PG DML scan, hard-coded `gh api -X GET`, hard-coded kubectl verbs |
| Credential isolation | DSN/URL/auth captured at registration via closure; tool args cannot replace |
| Conservative redaction | AWS recursively drops secret-shaped keys; Reth strips secret material via `_redact_value` |
| MCP safety floor | Read-only by default, explicit opt-in for mutating, per-server allowlist |
| Mutation surface separation | Actuators (`services/actuators/`) outside the registry; reachable only through `OrchestratorService.execute(decision)` after policy + evaluation |

The harness itself is not a policy engine. It carries the agent's *eyes*. Decisions and actions remain authoritative through the existing policy, evaluation, and orchestrator gates.

## Files

```
services/investigation/
  harness/
    __init__.py        — public exports
    contracts.py       — ToolDefinition, ToolCall, ToolResult, InvestigationLoopState, LoopDecision, LoopRejection
    registry.py        — ToolRegistry, RawToolOutput, make_call
    critic.py          — LoopCritic, _validate_args
    loop.py            — run_investigation_loop
    planner.py         — LoopPlanner Protocol
    native_selector.py — NativeProbeSelector, ObservationIndex, ProbeRule, RootCauseCandidate, LlmProbeSelector, ShadowProbeSelector
  cloudops_ontology.py  — text-pattern → canonical Cloud-OpsBench root-cause table
  cloudops_tools.py     — cloudops domain pack + CloudOpsRulePack + CloudOpsLoopPlanner (compat)
  reth_tools.py         — reth domain pack + RethRulePack + RethLoopPlanner (compat)
  prometheus_tools.py   — prometheus domain pack          (root)
  aws_tools.py          — aws domain pack (verb enforcement, redaction)  (root)
  kubectl_tools.py      — kubectl domain pack (subprocess)  (root)
  github_tools.py       — github domain pack (subprocess `gh api`)  (root)
  loki_jaeger_tools.py  — loki + jaeger domain packs (HTTP)  (root)
  db_tools.py           — postgres domain pack (subprocess psql, identifier validation, DML scan)  (root)
  mcp_tools.py          — MCP bridge (dynamic registration, opaque transport)  (root)
  service.py            — InvestigationService.investigate orchestrates deterministic + harness modes
  llm_planner.py        — build_llm_decision_provider for LlmProbeSelector
  rca.py                — build_rca_report
  reth_planner.py       — legacy Reth planner (drives evidence_pack assembly)
```

Tests in `tests/test_investigation_harness.py` cover registry / critic / loop primitives, the CloudOps and Reth rule packs end-to-end, every root pack, and the MCP bridge with a stub client.
