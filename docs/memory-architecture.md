# Memory Architecture

Mesh now treats memory as a verified substrate instead of a loose search sidecar.

## Principles

- Exact source-backed records are canonical.
- Hybrid retrieval is advisory. Lexical, graph, and optional vector channels generate candidates; verification decides what is usable.
- Shared memory is read-mostly for worker lanes. Agents can propose observations and claims, but Mesh owns promotion.
- Audit history is append-only. Decay changes retrieval priority and state, not historical existence.

## Tiers

- `working`: run-scoped and agent-scoped scratch context.
- `episodic`: immutable observations grounded in runs, artifacts, notes, and research.
- `semantic`: verified claims derived from supporting observations.
- `procedural`: conservative reusable guidance promoted from repeated, high-confidence semantic claims.

## Canonical Records

- `ObservationRecord`: source-grounded fact with scope and source refs.
- `ClaimRecord`: normalized statement with confidence factors, freshness, tier, and state.
- `RelationshipRecord`: typed graph edge between identifiers.
- `SupersessionRecord`: explicit old-claim to new-claim replacement.
- `RetrievalRecord`: audit log for memory reads.
- `MemoryPacket`: verified context bundle passed to scenario analysis and agent harnesses.

## Retrieval Flow

1. Lexical ranking over observations and claims.
2. Graph expansion over typed relationships.
3. Optional vector ranking.
4. Reciprocal-rank fusion.
5. Verification against exact source refs.
6. Supersession and contradiction filtering.
7. Memory-packet assembly for downstream consumers.

## HelixDB Projection

`MESH_MEMORY_GRAPH_BACKEND=helix` enables an optional HelixDB projection for
verified memory records. The canonical source of truth remains the configured
Mesh state backend (`file` or `postgres`); HelixDB receives observations,
claims, relationships, supersessions, retrieval records, and memory packets as
a graph-vector substrate for agent walkability, RAG, and MCP-facing exploration.

### Protocol Interface

The projection implements `HelixMemoryProjectionProtocol` with these methods:

- `upsert_observation(record)`: Insert or update an observation.
- `upsert_claim(record)`: Insert or update a claim.
- `upsert_relationship(record)`: Insert or update a relationship edge.
- `upsert_supersession(record)`: Record claim supersession.
- `record_retrieval(record)`: Log memory read events.
- `upsert_memory_packet(record)`: Persist context bundles.
- `replay_pending(limit)`: Replay failed outbox entries.
- `projection_status()`: Return projection health.

The outbox implements `HelixMemoryProjectionOutboxProtocol`:

- `enqueue(operation, record)`: Queue projection operation.
- `mark_applied(event_id)`: Mark operation successful.
- `mark_failed(event_id, error)`: Mark operation failed.
- `pending_events(limit)`: List pending operations.
- `status()`: Return outbox health.

Required configuration:

```bash
MESH_MEMORY_GRAPH_BACKEND=helix
MESH_HELIX_API_ENDPOINT=http://localhost:6969
MESH_HELIX_QUERY_NAMESPACE=mesh
```

The adapter calls `MESH_HELIX_API_ENDPOINT` directly when it is set. If the
endpoint is unset, it uses the optional `helix` Python extra when available and
otherwise falls back to `http://localhost:${MESH_HELIX_PORT}` (default `6969`).
Customize the namespace with `MESH_HELIX_QUERY_NAMESPACE` (default `mesh`);
it must start with a letter or underscore and contain only letters, numbers,
and underscores.
Enabling this mode requires compiled HelixQL queries matching the configured
namespace, for example `mesh_upsert_observation`, `mesh_upsert_claim`,
`mesh_upsert_relationship`, `mesh_upsert_supersession`, `mesh_record_retrieval`,
and `mesh_upsert_memory_packet`.

The checked-in Helix project lives under `helix/mesh-memory/`:

```bash
cd helix/mesh-memory
helix check
helix push dev
```

The projection is recoverable when enabled. Canonical writes land in the
configured Mesh state backend first, then the Helix operation is recorded in a
projection outbox before the query is attempted. File-backed state stores the
outbox at `helix_memory_projection_outbox.json` under `state_directory`;
Postgres-backed state stores it in `helix_memory_projection_outbox`. Endpoint
or query failures leave `failed` outbox entries for replay instead of silently
forking memory state. Record-shape errors still raise because they indicate a
contract bug before the projection boundary.

It is not a replacement for Postgres pilot persistence until equivalent
restart, migration, backup/restore, load, and release provenance gates exist
and pass.

## Zaxy Sidecar

State slice: `zaxy-langgraph-end-to-end-integration-prd`.

Zaxy is optional memory and audit infrastructure, not Mesh control-plane
authority. When `MESH_ZAXY_ENABLED=1`, Mesh mirrors persisted run events into a
sanitized Eventloom record after the Mesh event write and Merkle leaf are
complete. The mirror record carries Mesh `run_id`, `event_id`, sequence,
artifact key, integration name, status, Merkle leaf hash, source refs,
citations, tenant/project/service scope, and an explicit authority block that
marks Zaxy as non-authoritative.

Packet capture is non-default. Unless `MESH_ZAXY_PACKET_CAPTURE_ENABLED=1`, the
mirror stores summaries and redacted metadata instead of full event payloads.
Secrets are redacted by key name before an outbox or HTTP sidecar receives the
record.

Zaxy memory checkout can add external candidates to retrieval diagnostics, but
it cannot directly populate `MemoryPacket.observations` or
`MemoryPacket.claims`. Mesh still assembles packets only from verified first-party
records that pass the existing source-ref, active-state, supersession, and
contradiction filters. Checkout candidates remain scoped by tenant, project,
service, run, and agent/session metadata and are recorded as diagnostic
citations until Mesh verification admits matching records.

Configuration:

```bash
MESH_ZAXY_ENABLED=1
MESH_ZAXY_EVENTLOOM_URL=http://127.0.0.1:9008/eventloom
MESH_ZAXY_EVENTLOOM_OUTBOX_PATH=.mesh-runtime-state/zaxy-eventloom.jsonl
MESH_ZAXY_MCP_URL=http://127.0.0.1:9010/checkout
MESH_ZAXY_NEO4J_PROJECTION_ENABLED=1
MESH_ZAXY_PACKET_CAPTURE_ENABLED=0
```

Focused proof:

```bash
scripts/verify_helix_memory_projection.py --json --require-enabled --replay-pending
```

## Lifecycle

- Scenario analysis appends analyzer observations and supporting semantic claims.
- End-of-run crystallization distills runs into observations, claims, and relationships.
- Maintenance updates freshness, marks stale claims, promotes strong semantic claims to procedural memory, and records supersessions.
- `active_context.json` remains a bounded prompt-cache projection derived from canonical verified memory.
