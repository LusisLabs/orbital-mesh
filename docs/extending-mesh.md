# Extending Mesh

Mesh is built around a small set of stable contracts that third parties can plug into. This guide covers the seven extension points and the conventions each follows.

| Extension point | What you add | Where it lands |
|---|---|---|
| **Diagnostic tool pack** | New read-only tools the LLM can call during investigation (Datadog, Splunk, internal API, …) | `services/investigation/tools/` |
| **MCP server bridge** | Any tool the Model Context Protocol exposes | `MESH_MCP_SERVERS` env var |
| **Probe selector / rule pack** | Deterministic probes the harness runs before the LLM (per-trigger logic) | `services/investigation/harness/native_selector.py` |
| **Orchestration adapter** | A new orchestration mode beyond `native_hermes` / `goose` / `hermes` | `services/orchestrator/` |
| **Actuator adapter** | A new mutating-action target (Argo, custom load balancer, …) | `services/actuators/` |
| **Signal ingester** | A new way to ingest signals (Datadog webhook, AWS EventBridge, …) | `services/ingest/` |
| **Webhook source format** | A new wire format for `POST /api/webhooks/:source_id` | `services/ingest/webhook_service.py` |

All extension points share the same conventions:

- **Read-only by default.** Mutation goes through `policies/` and the evaluation gate, never through the investigation loop.
- **Opt-in registration.** Backends without your dependency installed pay zero cost.
- **Frozen dataclass contracts.** All inputs/outputs are immutable; you write pure functions.
- **Test in isolation.** Every existing pack ships fakes; copy the pattern.

---

## 1. Diagnostic tool pack

A "tool pack" is a module that registers one or more `ToolDefinition`s into a `ToolRegistry`. The LLM planner sees every read-only tool in the registry on every trigger.

### Anatomy of an existing pack

Look at `services/investigation/tools/aws.py` for the simplest template:

```python
from typing import Any
from ..harness import RawToolOutput, ToolDefinition, ToolRegistry

DOMAIN = "aws"

def _build_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="execute_aws_operation",
            domain=DOMAIN,
            description="Run a read-only AWS describe/list operation.",
            args_schema={
                "operation": {"type": "str", "required": True},
                "params":    {"type": "dict", "required": False},
            },
            mutation_class="read_only",     # critic rejects anything else
            timeout_seconds=10.0,
            budget_cost=2.0,
            citations_kind="aws_api",
        ),
    ]

TOOL_DEFINITIONS = tuple(_build_definitions())

def register(registry: ToolRegistry, *, default_region: str | None = None) -> None:
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_invoker(default_region))

def maybe_register_at_root(registry: ToolRegistry) -> bool:
    import os
    if os.environ.get("MESH_AWS_TOOLS_ENABLED", "").lower() not in {"1", "true", "yes", "on"}:
        return False
    region = os.environ.get("MESH_AWS_DEFAULT_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    register(registry, default_region=region)
    return True

def _make_invoker(default_region):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        # …call backend, build output, citations, summary…
        return RawToolOutput(
            output={"items": [...]},
            output_summary="describe-instances returned 3 EC2 instances",
            citations=[{"source_type": "aws_api", "source_ref": "ec2:describe-instances"}],
            valid=True,
            redaction_status="clean",
            status="completed",
        )
    return invoke
```

### Required pieces

1. **`DOMAIN`** — string used to namespace tool names (`aws:execute_aws_operation`).
2. **`TOOL_DEFINITIONS`** — immutable tuple of `ToolDefinition`s. Each has:
   - `name`, `domain`, `description` — what the LLM sees in its tool list
   - `args_schema` — typed argument hints (`type`, `required`, `nullable`, `default`)
   - `mutation_class` — must be `"read_only"` for the investigation loop. The critic rejects anything else.
   - `timeout_seconds`, `budget_cost` — planner uses these for budget weighting
   - `citations_kind` — citation source-type stamped on outputs
3. **`register(registry, …)`** — the per-run entrypoint. Adds tools to the registry with whatever per-run context they need.
4. **`maybe_register_at_root(registry)`** — optional. For "always-on" packs, called at engine startup. Reads env vars; if backing config is present, calls `register`. Returns `True` if registered.
5. **Invoker function** — takes `args: dict[str, Any]`, returns `RawToolOutput`. Pure function — no global state.

### Wire it into the engine

Append your pack to `services/investigation/tools/__init__.py:register_root_packs`:

```python
try:
    from . import my_pack
    results["my_pack"] = my_pack.maybe_register_at_root(registry)
except Exception:
    log.exception("root tool registration: my_pack failed (non-fatal)")
    results["my_pack"] = False
```

Per-pack failures are swallowed and logged so one mis-configured pack never blocks engine startup.

### Test it

Mirror `tests/test_investigation_harness.py`:

```python
from services.investigation.tools import my_pack
from services.investigation.harness import ToolRegistry, make_call

registry = ToolRegistry()
my_pack.register(registry, fake_client=FakeClient())
defn, _ = registry.get(my_pack.DOMAIN, "my_tool")
result = registry.invoke(make_call(tool=defn, args={"x": 1}))
assert result.valid
```

### The contract the LLM enforces

- The LLM **only sees read-only tools** — `LlmProbeSelector` filters by `mutation_class == "read_only"` before any prompt is built.
- The critic (`services/investigation/harness/critic.py`) rejects unknown tools, mutating tools, duplicate calls within a budget window, and arg-schema violations. You don't need to validate args inside the invoker — the critic does it first.
- Output summaries are the **contract surface** for downstream rule packs. If you want a hypothesis ranker to fire on your tool's output, include the canonical phrase in `output_summary`.

---

## 2. MCP server bridge

If the tool you want already exists as an MCP server, you don't write a pack — just register it via env:

```bash
MESH_MCP_SERVERS=name=stdio://path/to/server,other=stdio:///usr/local/bin/mcp-foo
```

The MCP bridge (`services/investigation/tools/mcp.py`) discovers the server's tools dynamically and registers each one under domain `mcp`. The bridge is transport-opaque; it ignores per-server auth (assume MCP servers run on the trusted operator host).

If your server requires more than `stdio://`, write a tiny wrapper in `services/investigation/tools/mcp.py:_default_client_factory` — that's the only place transport details live.

---

## 3. Probe selector / rule pack

Before the LLM gets a turn, the harness runs an optional **deterministic** probe selector. This is where you encode "if the trigger looks like X, always check Y" logic.

The contract is in `services/investigation/harness/contracts.py:LoopDecision`. A selector is any callable that takes an `InvestigationLoopState` and returns a `LoopDecision`.

Built-in selectors:

- `NativeProbeSelector` — wraps a `ProbeRulePack` with rules like "always run kubectl describe pod when the trigger is a CrashLoop". Used by CloudOpsBench and Reth.
- `LlmProbeSelector` — falls through to the LLM. Used when no domain rules match.
- `ShadowProbeSelector` — runs a native pack alongside the LLM and records disagreement for offline review.
- `GenericRulePack` — empty rule pack; defers to the LLM entirely. Used for arbitrary triggers.

### Adding a domain rule pack

```python
from services.investigation.harness.native_selector import ProbeRulePack
from services.investigation.harness.contracts import LoopDecision, LoopAction, ToolCall, make_call

class MyDomainRulePack(ProbeRulePack):
    domain = "my_domain"
    root_cause_ranker = None      # or a callable that maps summaries → labels

    def decide(self, state, tool_definitions):
        # Inspect state.tool_results + state.budget_remaining + state.trigger
        if "my_signal_kind" in state.trigger.signatures:
            defn = tool_definitions["my_domain:my_tool"]
            return LoopDecision(
                action="continue",
                tool_calls=[make_call(tool=defn, args={"foo": "bar"})],
                rationale="canonical probe for my_signal_kind",
            )
        return LoopDecision(action="stop", tool_calls=[], rationale="no rule fired")
```

Then wire it into `services/runtime.py:_auto_wire_investigation_harness` in the appropriate path.

---

## 4. Orchestration adapter

Adding a new mode beyond `native_hermes` / `goose` / `hermes`:

1. Add the mode name to `RuntimeConfig.orchestration_mode` (`shared/mesh_runtime/config.py`).
2. Implement an adapter that looks like the existing ones in `services/orchestrator/`:
   - `services/orchestrator/goose_bridge.py` — CLI-bridged
   - `services/orchestrator/deepagents_adapter.py` — in-process LangChain agent
3. Register it in `services/orchestrator/service.py:OrchestratorService` — extend the `_select_adapter` dispatch.
4. Add a readiness probe to `setup_integrations.py` so `/api/readiness` reports your mode.

Orchestration adapters return `OrchestrationResult` (also in `shared/mesh_runtime/contracts.py`). They never invoke mutating actions directly — they propose, the actuator layer disposes.

---

## 5. Actuator adapter

Actuators are the only part of Mesh that performs mutating actions, and they're heavily gated:

- **Allowlists** — every actuator checks `MESH_KUBERNETES_ALLOWED_CONTEXTS` / `_NAMESPACES` (or the equivalent for its domain).
- **Policy gate** — every action class has a corresponding entry in `policies/metric-actions.policy.json`. Without a policy entry, the action is rejected.
- **Trust ladder** — per-(action_class, service) trust levels gate auto vs approval-required.
- **Approval gate** — even on a trusted path, the operator must approve unless `interruptible_auto` is on.

Existing adapters:

```
services/actuators/
├── service.py         — dispatch + audit
├── argocd.py          — Argo CD app sync
├── load_balancer.py   — flag-routed traffic shifting
├── systemd_ssh.py     — bare-metal restart via SSH
└── repo_patch.py      — Evo-driven repo patches
```

Adding a new one (skeleton):

```python
from typing import Any
from .service import ActuatorResult

class MyAdapter:
    name = "my_adapter"

    def execute(self, parameters: dict[str, Any], audit: AuditLogAdapter) -> ActuatorResult:
        audit.record("my_adapter:start", parameters)
        try:
            # do the bounded thing — single API call, no retries inside this adapter
            ...
        except Exception as exc:
            audit.record("my_adapter:error", {"error": str(exc)})
            return {"status": "failed", "error": str(exc)}
        audit.record("my_adapter:ok", {"result": "..."})
        return {"status": "succeeded", "result_payload": {...}}
```

Then:

1. Register in `services/actuators/service.py:ActuatorService._select_adapter`.
2. Add a policy stanza in `policies/metric-actions.policy.json` declaring the action class, allowed parameters, and trust ladder defaults.
3. Add an entry to the trust ladder bootstrap so the live-execution gate is meaningful.

---

## 6. Signal ingester

Ingesters turn external signals (webhooks, OTLP pushes, K8s informers) into the `Trigger` shape the rest of the engine consumes.

Existing ingesters:

```
services/ingest/
├── webhook_service.py            — generic webhook (HMAC-signed)
├── otel_signal.py                — OTLP/HTTP metrics push
├── kubernetes_live_signal.py     — K8s events poller
├── kubernetes_summary.py         — kubectl-summary fixture path
├── kubernetes_topology.py        — topology snapshot ingester
└── bare_metal_node.py            — SSH-based health collector
```

A new ingester is just a class with one method:

```python
class MyIngester:
    name = "my_ingester"

    def ingest(self, raw_payload: dict[str, Any], metadata: dict[str, Any]) -> AuditedTrigger:
        # Validate, normalise, build the Trigger
        return AuditedTrigger(
            trigger_type="my_signal_kind",
            service=raw_payload["service"],
            signatures=[...],
            confidence=...,
            ...
        )
```

Then register it with the `IngestService` so calls hit your ingester (e.g., HTTP route in `control_plane_server.py` for an HTTP-shaped signal).

---

## 7. Webhook source format

If you want a new on-the-wire format for `POST /api/webhooks/:source_id` without writing a whole ingester:

1. Add a format name (e.g., `"my_format"`) to `services/ingest/webhook_service.py`.
2. Implement a parser that turns the raw body + headers into the standard alert event shape.
3. Add a corresponding entry to the `format` discriminator in `POST /api/webhook-sources`.

The webhook layer handles HMAC validation, dedupe, and Mesh-run spawning automatically — you only own the parsing.

---

## Configuration as a contract

Every extension point is gated by an env var or config flag, never by code presence:

| Extension | Gate |
|---|---|
| Tool packs | `maybe_register_at_root` returns `False` if the gate is unset |
| MCP servers | `MESH_MCP_SERVERS` |
| Orchestration mode | `MESH_ORCHESTRATION_MODE` |
| Live actuator execution | `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED`, allowlists |
| Observer LLM (for LLM planner) | `MESH_OBSERVER_API_KEY` + `MESH_OBSERVER_BASE_URL` |
| Postgres state | `MESH_STATE_BACKEND=postgres` + `MESH_DATABASE_URL` |
| OTLP receiver | `MESH_OTEL_RECEIVER_ENABLED=1` (+ optional token) |

This means production deployments without a backend pay **zero cost** for it — the registry stays empty, the LLM never sees those tools, no import is attempted.

---

## Testing extensions

Every extension lands with:

1. **Unit tests** for the parser / invoker in isolation (no I/O, fake clients).
2. **Integration tests** that register the extension and verify the engine wires it correctly (`tests/test_investigation_harness.py` is the template).
3. **End-to-end test** if it touches actuation — fixture-driven, no live cluster required (use `kubernetes_live_signal` fakes).

Run the suite with:

```bash
uv run python -m unittest discover tests -v
```

CI runs the same on every PR.

---

## Embedding Mesh as a library

Mesh runs without the HTTP server too. The `MeshRuntimeEngine` is the runtime core:

```python
from shared.mesh_runtime import RuntimeConfig
from services.runtime import MeshRuntimeEngine

config = RuntimeConfig(
    state_directory=".mesh-state",
    evaluation_mode="native",
    orchestration_mode="native_hermes",
    prometheus_url="http://prom:9090",      # enables prometheus tool pack
)

engine = MeshRuntimeEngine(config=config)

run = engine.run_sync(
    raw_signal={
        "trigger_type": "metric_regression",
        "service": "frontend",
        "metric": "request_latency_p95_ms",
        "value": 850,
        "baseline": 200,
    },
    trigger_metadata={"source": "my-embed"},
)

print(run.stage)            # "completed" / "awaiting_operator" / etc.
print(run.decision.action)  # "rollback_deployment" / "no_action" / etc.
print(run.feedback)
```

Programmatic steering:

```python
engine.steer_run(run.run_id, {"command": "approve", "metadata": {"by": "embed"}})
```

The engine's `infra_graph` is exposed as `engine.infra_graph` and is populated per-run from any topology signal in the raw payload, so your embedding code can query it directly:

```python
neighbors = engine.infra_graph.neighbors(
    "service", "frontend", "boutique",
    edge_kinds=["selects"], direction="out",
)
```

---

## Stability contract

These public surfaces are versioned and won't break across minor releases:

- `ToolDefinition`, `ToolCall`, `ToolResult`, `RawToolOutput`, `InvestigationLoopState`, `LoopDecision`, `LoopRejection` — frozen dataclasses in `services/investigation/harness/contracts.py`.
- `ToolRegistry.register`, `.get`, `.list_definitions`, `.invoke`, `.has`, `.clone` — in `services/investigation/harness/registry.py`.
- `register_root_packs` signature — in `services/investigation/tools/__init__.py`.
- `RuntimeConfig` field names (additions only, never removals) — in `shared/mesh_runtime/config.py`.
- `MeshRuntimeEngine.run_sync`, `.steer_run`, `.infra_graph` — in `services/runtime.py`.
- HTTP routes documented in [`docs/api-reference.md`](./api-reference.md) — semver-aligned.

Anything not on this list is internal; it can move under your feet without notice. If you need to depend on an internal symbol, file an issue first.
