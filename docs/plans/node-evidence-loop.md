# Plan: Evidence-driven node loop (Reth, first slice)

## Current Status

This plan is historical for the first Reth evidence-loop slice. The current
implementation wires `reth_node_degraded` through Reth-specific hypothesis
templates, scenario-analysis evidence, decision biasing, and the bounded
Kurtosis restart path documented in
[`docs/reth-kurtosis-testing.md`](../reth-kurtosis-testing.md). Remaining work
is repeatable full-stack gating and wider client coverage, not initial wiring
of the Reth trigger.

## Problem

Today the Reth path treats the inbound signal as the truth. The bare-metal
ingester polls a node, builds a `reth_node` signal, and that signal is
simultaneously the *alert* (what tripped) and the *snapshot* (what's true now).
The trigger fires on threshold breaches, the decision service branches on
signature strings, and the action is chosen with no falsification step in
between.

Concretely:

- [services/ingest/bare_metal_node.py](../../services/ingest/bare_metal_node.py)
  is the only place node state is gathered. It runs once at signal-build time.
  If a webhook arrives instead (Prometheus alert, oncall ping), the signal is
  whatever the alerter chose to put in the payload — usually sparse.
- `DecisionService._decide_reth_node` ([services/decision/service.py:95](../../services/decision/service.py)) reads the
  signal directly and matches against [policies/reth-node.policy.json](../../policies/reth-node.policy.json).
  No alternative hypotheses are considered, no probes are issued, no second
  look is taken before action.
- The original `HypothesisEngine` ([services/decision/hypothesis_engine.py](../../services/decision/hypothesis_engine.py))
  carried only k8s templates and was not wired for `reth_node_degraded`.
  Current code now includes the Reth path; keep this section as the historical
  reason for the first slice.

The user-visible gap: when an alert says "peer count low," Mesh cannot
distinguish *peer starvation from network isolation* or *sync stalled from
consensus disconnect* without a structured second look. It can only re-read
what the alert told it.

## Goal

A run for a Reth node passes through three stages instead of one:

1. **Lead** — the inbound signal (rich or sparse) is treated as a *claim that
   something is wrong*, not as ground truth.
2. **Evidence** — Mesh assembles a `NodeEvidencePack` by issuing a small,
   typed set of read-only probes against the named node.
3. **Hypothesis** — Mesh ranks candidate causes against the pack via
   falsification predicates; the top hypothesis biases (does not override)
   the deterministic policy match.

Each stage is a versioned event on the run log, audited like any action.

## Non-goals (deferred to later phases)

- **No diagnostic-probe action class.** Probes in this phase run synchronously
  inside the evidence stage with a fixed list. Operator-approvable, on-demand
  probes are a phase 3 concern.
- **No LLM in the critical path.** The engine's falsification logic is pure
  deterministic predicate evaluation. LLM reasoning stays as the existing
  `LlmActionProposer` fallback for genuinely ambiguous cases.
- **No new action types.** The decision surface remains
  `restart_systemd_service`, `cordon_node`, `escalate`, `no_action`. We are
  changing the *path* to those decisions, not the set.
- **No Solana, no geth.** Reth-only first slice. The probe library is
  structured so the same shape extends to other clients later.
- **No replacement of the existing `bare_metal_node` ingester for proactive
  polling.** Cron-driven runs continue to work as-is. The new stage runs
  *after* the trigger, regardless of how the signal arrived.

## Scope of the first slice

Three signatures, all already named in [policies/reth-node.policy.json](../../policies/reth-node.policy.json):

- `peer_starvation` (peer count below floor, head not advancing)
- `sync_stalled` (sync object active but block lag growing)
- `rpc_degraded` (RPC reachable but error rate above threshold)

These three share a probe set, share an output decision (`restart_systemd_service`
gated by `max_restarts_per_window`), and have falsifiable competing hypotheses
(`network_isolation`, `consensus_disconnect`, `disk_pressure`,
`bad_release`). That's enough surface to validate the loop end-to-end without
fanning out.

## Pipeline change

Before:
```
ingest → trigger → scenario_analysis → decision → evaluation → orchestrator → feedback
```

After (Reth path only — other paths unchanged):
```
ingest → trigger → evidence → scenario_analysis → decision → evaluation → orchestrator → feedback
                       │            │
                       │            └── reads NodeEvidencePack from envelope
                       │
                       └── HypothesisEngine.generate(trigger, evidence) called
                           inside scenario_analysis; ranked hypotheses stamped
                           on subdecisions
```

Run-event additions:

- `evidence_pack_assembling` — stage entry, lists the probes about to run
- `evidence_probe_completed` — one event per probe, with result + latency
- `evidence_pack_ready` — full pack stamped on the envelope
- `hypothesis_ranked` — top-N hypotheses with posteriors, supporting/disconfirming predicates

These are *audit*, not decision inputs to anything but the next stage.

## Data model

`NodeEvidencePack` is the existing
[reth-node-signal.schema.json](../../shared/mesh_runtime/schemas/reth-node-signal.schema.json)
shape, promoted to a first-class run artifact. **No schema change required.**
The schema already has `node`, `execution`, `consensus`, `storage`, `rpc`,
`logs`, and `resource_attributes` — that's the pack.

What changes:

- The pack is stored separately from the inbound signal on the envelope.
  Field: `envelope.evidence_pack` (typed `RethNodeSignal`, but used as
  evidence rather than trigger source).
- A new field `evidence_pack.assembled_at` records when the pack was built
  (separate from `signal.observed_at`).
- A new field `evidence_pack.probe_results` records per-probe latency,
  success/failure, and source (`json_rpc`, `systemd`, `filesystem`,
  `posture_check`). This is what makes the pack *auditable*.

Add `evidence_pack.probe_results` as an additive optional property to the
existing schema rather than creating a parallel schema. This keeps tooling
that already reads `reth_node` signals working.

## Component changes

### 1. Probe library — `services/evidence/probes/`

Extract the JSON-RPC + filesystem polling currently inside
`bare_metal_node.py` into a reusable probe module. The ingester keeps
working but delegates to the same probe code.

Files to add:
- `services/evidence/__init__.py`
- `services/evidence/probes/__init__.py`
- `services/evidence/probes/jsonrpc.py` — typed wrappers for `eth_syncing`,
  `eth_blockNumber`, `net_peerCount`, `web3_clientVersion`,
  `engine_exchangeCapabilities` (auth-rpc reachability sniff). One function
  per RPC method; no generic call-by-name.
- `services/evidence/probes/systemd.py` — `systemctl is-active`,
  `systemctl status` parsing for unit state. Read-only; no `restart`.
- `services/evidence/probes/filesystem.py` — `df` on data dir, `stat` on
  JWT secret (mode + presence). No reads of secret contents.
- `services/evidence/probes/posture.py` — port reachability sniff for RPC
  and authrpc against the *public* interface, to detect exposure.

Each probe returns a typed result `(value, latency_ms, source, error)`.
Errors do not raise — they surface as `error` strings on the result and
become `null` fields on the pack with a corresponding `probe_results`
entry.

Files to modify:
- `services/ingest/bare_metal_node.py` — replace inline RPC calls with
  imports from `services.evidence.probes.jsonrpc`. Behavior preserved;
  this is a refactor.

### 2. Evidence assembly service — `services/evidence/service.py`

`EvidenceService.assemble(trigger, target) -> NodeEvidencePack`:

- Resolve `target` (host, service, RPC URL) from
  `MESH_BARE_METAL_NODE_TARGETS` keyed by `(service, host)` from the trigger.
  If no target is configured, the pack is built from the inbound signal
  alone and `probe_results` is empty.
- Run probes in parallel with a 2s per-probe timeout and a 4s overall budget.
  A timeout is a `null` field in the pack, not a failure of the run.
- Stamp `assembled_at`, `probe_results`, populate the `RethNodeSignal`
  fields.
- Persist the pack to the run state directory; emit run events.

Constructor takes a `probe_runner` so tests can inject a deterministic stub.

### 3. HypothesisEngine — Reth templates

Files to modify:
- `services/decision/hypothesis_engine.py`

Add four templates keyed off `error_signatures`:

- `peer_starvation` → competing causes:
  - `h_peer_local_isolation` (network/firewall) — predicate
    `peer_count_zero AND rpc_http_reachable` (we can talk to it; the world can't)
  - `h_peer_static_misconfig` — predicate `static_peers_configured_but_unreachable`
  - `h_peer_transient` — predicate `peer_count_recovering_in_window`
- `sync_stalled` → competing causes:
  - `h_sync_consensus_disconnect` — predicate
    `engine_api_unreachable OR forkchoice_updates_stale`
  - `h_sync_disk_pressure` — predicate `disk_used_pct > 88`
  - `h_sync_bad_release` — predicate `client_version_changed_within(1800)`
- `rpc_degraded` → competing causes:
  - `h_rpc_saturation` — predicate `rpc_error_rate > 0.05 AND latency_p95 > 2s`
  - `h_rpc_exposed_overload` — predicate
    `rpc_publicly_exposed AND error_rate > 0.05` → forces escalate
- `unknown` fallback — predicate `default_unknown` → escalate

New predicate kinds to add to `_test_predicate`:
- `peer_count_zero`, `peer_count_recovering_in_window`
- `engine_api_unreachable`, `forkchoice_updates_stale`
- `disk_used_pct_above`, `client_version_changed_within`
- `rpc_publicly_exposed`, `authrpc_publicly_exposed`
- `static_peers_configured_but_unreachable`

All resolve against `evidence_pack` fields. None of them call the network at
predicate-eval time — that's the evidence stage's job. The engine is pure.

### 4. Decision wiring

Files to modify:
- `services/decision/service.py`

In `_decide_reth_node`:
- Accept the evidence pack on the trigger or via a passed
  `scenario_analysis` argument (already plumbed).
- If `hypothesis_engine` is bound and `error_signatures` resolve to a known
  template, call `engine.generate(trigger, evidence_pack)`.
- Stamp the top hypothesis on the decision's `reasoning_record`.
- Use the top hypothesis to **bias** the existing rule match:
  - If the deterministic policy says `restart_systemd_service` AND the top
    hypothesis is escalation-bound (`h_rpc_exposed_overload`,
    `h_sync_disk_pressure` with disk > 90%), promote to `escalate`.
  - If the policy says `escalate` and the top hypothesis is
    `h_peer_transient` with high posterior, do **not** downgrade —
    deterministic safety wins. The engine can promote, never demote.

### 5. Runtime wiring

Files to modify:
- `services/control_plane.py` — `MeshRuntimeEngine` chains the new evidence
  stage after trigger, before scenario_analysis. Stage is skipped (no-op,
  no event) for non-Reth signals.
- `shared/mesh_runtime/run_events.py` — add the four new event types listed
  above to the canonical event enum.
- `shared/mesh_runtime/__init__.py` — re-export `EvidenceService` if
  callers want to instantiate it directly.

### 6. Policy

[policies/reth-node.policy.json](../../policies/reth-node.policy.json) —
add an `evidence_sufficiency` block:

```json
"evidence_sufficiency": {
  "min_populated_fields": ["execution.peer_count", "execution.syncing", "rpc.http_reachable"],
  "max_null_fields_for_action": 2,
  "on_insufficient_evidence": "escalate"
}
```

If the assembled pack does not satisfy `min_populated_fields`, the decision
is forced to `escalate` regardless of the hypothesis. This is the
"don't act on rumor" guardrail.

## Test plan

### Unit
- `tests/test_evidence_probes.py` — each probe with a stubbed network
  client, including timeout, malformed JSON, and connection refused.
- `tests/test_evidence_service.py` — assemble pack with all probes
  succeeding, with a subset failing, with no target configured.
- `tests/test_hypothesis_engine_reth.py` — for each new template, table
  test of `(evidence_pack, expected_top_hypothesis, expected_posterior_band)`.

### Fixtures
Add to [fixtures/signals/](../../fixtures/signals/):
- `reth_peer_starvation.json` — sparse Prometheus-style alert + matching
  evidence pack
- `reth_sync_stalled_disk_pressure.json` — sync stalled with disk > 90%
  (must escalate)
- `reth_sync_stalled_consensus.json` — sync stalled with engine_api
  unreachable (must escalate, root cause is CL)
- `reth_rpc_degraded_internal.json` — internal-only exposure, restart-eligible
- `reth_rpc_degraded_exposed.json` — public exposure (must escalate)

Paired expected outcomes in `fixtures/decisions/`.

### End-to-end
- `tests/test_node_evidence_loop_e2e.py` — replays each fixture through
  `MeshRuntimeEngine`. Asserts: evidence pack on envelope, hypothesis
  ranked, decision matches expected, four new run events present.

### Promptfoo
Add a Promptfoo case set under `fixtures/promptfoo/node-evidence/` covering:
- "evidence pack populated → action allowed"
- "evidence pack sparse → escalate"
- "top hypothesis demands escalation → never auto-restart"
- "restart count this window already at cap → escalate"

Existing Promptfoo wiring in
[services/evaluation/service.py:36](../../services/evaluation/service.py)
runs these alongside current cases.

## Resolved decisions

These were open at first draft; resolutions below are what the
implementation builds against.

1. **Probe budget vs. trigger latency.** 4s overall budget, 2s per probe,
   probes run in parallel. Add a *safety fast-path*: if the inbound signal
   has any of `rpc_publicly_exposed=true`, `authrpc_publicly_exposed=true`,
   `jwt_secret_exists=false`, or `jwt_secret_mode` indicating world-readable,
   the evidence stage skips assembly and stamps a minimal pack with
   `fast_path_reason` set. Decision goes straight to `escalate`. This keeps
   credential/exposure incidents from waiting on probes.

2. **Target config location.** Stay with `MESH_BARE_METAL_NODE_TARGETS`
   env var. Share the loader from
   [services/ingest/bare_metal_node.py](../../services/ingest/bare_metal_node.py).
   No config migration in this slice. A future phase can move to YAML in
   `policies/` once the loop is proven.

3. **Validator state awareness.** Defer to phase 3. The pack *captures*
   `consensus.client_kind` and `consensus.client_healthy`, but
   attestation-duty awareness needs its own probe set, its own policy file
   (`policies/validator-safety.policy.json`), and CL-client-specific
   probes (Lighthouse REST, Prysm gRPC, etc.). Mixing that into this slice
   triples the surface. Note as a known limitation in operator docs:
   *Reth-only first-slice does not check validator attestation duty before
   restart; only deploy execution-only nodes for now*.

4. **Replay determinism.** Stub `probe_runner` in fixture mode.
   `EvidenceService.__init__(probe_runner=...)` accepts a callable; live
   mode uses the network probe runner, fixture mode passes a deterministic
   dict-backed runner. Fixtures stamp expected probe results inline so
   replay is exact.

## What this does NOT do

This plan is the loop, not the full SRE-cautious agent. Explicitly out of
scope:

- An audited *diagnostic action* class (operator-approvable on-demand probes
  that run outside the evidence stage). That's phase 3.
- LLM "did we collect enough evidence" judgment. The
  `evidence_sufficiency` policy block is a deterministic stand-in.
- Cross-run memory queries from the decision service ("we've restarted this
  3x this hour"). The policy already enforces `max_restarts_per_window=1`
  but the engine doesn't visualize the count yet. Phase 6.
- Solana, geth, archive nodes, or non-systemd deployments. Reth + systemd
  only.

If this loop ships and the Promptfoo gates pass on the fixture set,
phases 3–6 become incremental additions on top of a working evidence
pipeline.
