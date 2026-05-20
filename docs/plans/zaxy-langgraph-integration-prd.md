# PRD: Zaxy and LangGraph integration for Mesh Intelligence

State slice: `zaxy-langgraph-end-to-end-integration-prd`

## Problem Statement

Mesh Intelligence already has the right control-plane shape: runs are admitted
through Mesh, events are persisted through the Mesh state store, memory is
verified before use, agents are proposal-only, policy gates remain authoritative,
and production actuation is bounded by Mesh.

The missing piece is durable, cross-session agent memory and replayable
agent-workflow state around that control plane. Today, Mesh can crystallize run
memory into first-party `ObservationRecord`, `ClaimRecord`, `RelationshipRecord`,
`RetrievalRecord`, and `MemoryPacket` records, and it can route proposal lanes
through native contracts or DeepAgents. It does not yet have a dedicated external
memory fabric that can:

1. mirror run and agent lifecycle events into an immutable, replayable log,
2. project agent memory into a temporal graph that survives process restarts,
3. expose bounded memory checkout to agents through MCP or Python APIs,
4. checkpoint multi-step agent proposal workflows without confusing those
   checkpoints for Mesh run authority,
5. support cross-run handoff, audit replay, and retrieval diagnostics without
   weakening Mesh policy, approval, or actuation gates.

Zaxy and LangGraph solve adjacent but different parts of this gap. Zaxy should
be the durable memory and audit sidecar. LangGraph should be the workflow runtime
inside bounded proposal lanes. Mesh remains the production control plane.

## Solution

Integrate Zaxy and LangGraph as layered support systems around the existing Mesh
runtime:

```text
Mesh RunCoordinator / MeshStateStore / policy gates / actuation
  -> authoritative run state, Merkle evidence, approvals, execution

Zaxy Eventloom / MemoryFabric / MCP / Neo4j projection
  -> durable memory mirror, temporal retrieval, handoff, replay, citations

LangGraph proposal workflows
  -> checkpointed per-agent reasoning graphs that emit AgentAttempt artifacts
```

Target posture:

```text
Mesh decides and executes.
Zaxy remembers and replays.
LangGraph coordinates bounded proposal work.
```

The integration must be optional, observable, and degraded-safe. If Zaxy or a
LangGraph checkpointer is unavailable, Mesh runs continue through the native
runtime and record the missing enrichment as readiness or agent-lane warnings.

## Why This Is Needed

### Durable memory needs an external replay fabric

Mesh memory is source-backed and verified, but it is still local to Mesh's state
store and active context projections. Zaxy's Eventloom gives agent memory an
append-only log with hash-linked provenance, replay, event diffs, and a graph
projection that can be rebuilt from immutable records. That is useful for
operator audit, agent handoff, and cross-run retrieval.

### Agent workflows need checkpointing, not control-plane replacement

LangGraph provides durable execution, persistence, streaming, and
human-in-the-loop workflow primitives for long-running stateful agents. Those
capabilities fit Mesh's proposal lanes. They do not replace Mesh's run event
spine, approval model, evaluation gates, or actuation adapters.

### Mesh needs tighter continuity across agents

Mesh already routes Goose, Hermes, Codex, Claude Code, OpenClaw, Evo, DeepAgents,
and LatentMAS as advisory lanes. Zaxy gives those lanes a common memory checkout
contract. LangGraph gives complex lanes a deterministic workflow shape. Together,
they reduce repeated context loading, stale handoffs, and ungrounded proposal
drift.

## Goals

1. Mirror selected Mesh run events into Zaxy Eventloom with sanitized payloads,
   Mesh event IDs, run IDs, sequences, artifact keys, Merkle roots, and source
   citations.
2. Expose Zaxy Memory Checkout as a bounded input to Mesh `MemoryPacket`
   assembly without bypassing Mesh verification.
3. Add a first-party LangGraph workflow adapter for bounded agent proposal lanes.
4. Preserve the current worker contract: agents propose; Mesh owns policy,
   approval, tests, audit, production promotion, and actuation.
5. Add readiness, health, and degraded-mode reporting for Zaxy, Eventloom,
   Neo4j projection, MCP, and LangGraph checkpointing.
6. Support per-run, per-service, and per-agent session scoping so memory can be
   replayed without cross-tenant or cross-project leakage.
7. Make packet capture optional and explicitly non-default.
8. Provide enough tests and docs that future agents cannot accidentally promote
   Zaxy or LangGraph into the control-plane authority path.

## Implementation Status

Completed for state slice `zaxy-langgraph-end-to-end-integration-prd`.

- Zaxy is wired as an optional non-blocking sidecar. File and Postgres state
  stores mirror persisted Mesh `RunEvent` records after Mesh event persistence
  and Merkle leaf generation. Mirror payloads are sanitized, scoped, and marked
  non-authoritative.
- Zaxy memory checkout is exposed to memory retrieval as diagnostic-only
  external context. It cannot populate `MemoryPacket.observations` or
  `MemoryPacket.claims` unless Mesh first admits matching first-party verified
  records.
- LangGraph is wired as a proposal-only `AgentAttempt` adapter behind
  `MESH_AGENT_FABRIC_MODE=langgraph`. Checkpoint metadata stays inside
  `AgentAttempt.output`; policy, approval, tests, promotion, and actuation
  remain Mesh-owned.
- Readiness and connector certification now expose `zaxy`, `eventloom`,
  `neo4j_projection`, `zaxy_mcp`, and `langgraph_checkpointing` as optional
  degraded-safe surfaces.
- Packet capture remains off by default through
  `MESH_ZAXY_PACKET_CAPTURE_ENABLED=0`.
- Operator UI contracts and readiness displays were regenerated for both
  `web` and `meshapp/frontend`.

Validation:

```bash
pnpm run lint
```
