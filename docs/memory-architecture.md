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

## Lifecycle

- Scenario analysis appends analyzer observations and supporting semantic claims.
- End-of-run crystallization distills runs into observations, claims, and relationships.
- Maintenance updates freshness, marks stale claims, promotes strong semantic claims to procedural memory, and records supersessions.
- `active_context.json` remains a bounded prompt-cache projection derived from canonical verified memory.
