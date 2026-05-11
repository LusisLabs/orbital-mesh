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

Required configuration:

```bash
MESH_MEMORY_GRAPH_BACKEND=helix
MESH_HELIX_API_ENDPOINT=http://localhost:6969
MESH_HELIX_QUERY_NAMESPACE=mesh
```

The adapter calls `MESH_HELIX_API_ENDPOINT` directly when it is set. If the
endpoint is unset, it uses the optional `helix` Python extra when available and
otherwise falls back to `http://localhost:${MESH_HELIX_PORT}` (default `6969`).
Enabling this mode requires compiled HelixQL queries matching the configured
namespace, for example `mesh_upsert_observation`, `mesh_upsert_claim`, and
`mesh_upsert_relationship`.

The checked-in Helix project lives under `helix/mesh-memory/`:

```bash
cd helix/mesh-memory
helix check
helix push dev
```

The projection is fail-closed when enabled: an unreachable instance or missing
compiled query raises a runtime error instead of silently forking memory state.
It is not a replacement for Postgres pilot persistence until equivalent
restart, migration, backup/restore, load, and release provenance gates exist
and pass.

Focused proof:

```bash
scripts/verify_helix_memory_projection.py --json --require-enabled
```

## Lifecycle

- Scenario analysis appends analyzer observations and supporting semantic claims.
- End-of-run crystallization distills runs into observations, claims, and relationships.
- Maintenance updates freshness, marks stale claims, promotes strong semantic claims to procedural memory, and records supersessions.
- `active_context.json` remains a bounded prompt-cache projection derived from canonical verified memory.
