# Postgres Persistence

Mesh supports two runtime state backends:

- `file`: default local mode. Runs, events, learning outcomes, vault mirrors, and Merkle audit output stay under `.mesh-runtime-state`.
- `postgres`: production mode. Canonical run state is stored in Postgres using `MESH_DATABASE_URL`.

HelixDB is supported separately as an optional verified-memory graph projection,
not as a canonical runtime state backend. Set `MESH_MEMORY_GRAPH_BACKEND=helix`
to mirror observations, claims, relationships, supersessions, retrieval records,
and memory packets into HelixDB while keeping run sessions, event streams,
Merkle roots, approvals, and pilot-readiness persistence on `file` or
`postgres`.

File mode uses lock files plus atomic replace writes for JSON state. If a state file is malformed, Mesh writes a `.corrupt.<timestamp>` backup and recreates an empty object instead of crashing the control-plane read path.

Supabase is supported as a hosted Postgres target by setting `MESH_DATABASE_URL`. Mesh does not use Supabase-specific APIs in this version.

## Configuration

```bash
MESH_STATE_BACKEND=postgres
MESH_DATABASE_URL=postgresql://mesh:mesh@postgres:5432/mesh
```

`MESH_STATE_BACKEND=file` remains the default. File mode preserves the local replay model and continues to write `.mesh-runtime-state`.

Optional HelixDB memory projection:

```bash
MESH_MEMORY_GRAPH_BACKEND=helix
MESH_HELIX_API_ENDPOINT=http://localhost:6969
MESH_HELIX_QUERY_NAMESPACE=mesh
```

Run `scripts/verify_helix_memory_projection.py --json --require-enabled`
against a running HelixDB instance after deploying the matching HelixQL queries.
The checked-in query project is `helix/mesh-memory/`. The Python adapter calls
`MESH_HELIX_API_ENDPOINT` directly when set; without an endpoint it uses the
optional `helix` Python extra if present and otherwise probes
`http://localhost:${MESH_HELIX_PORT}`.

## Docker Stack

`docker-compose.stack.yml` starts a `postgres` service and wires `MESH_DATABASE_URL` to it. The stack still defaults Mesh to file mode to avoid breaking local demos:

```bash
docker compose -f docker-compose.stack.yml up --build
```

To exercise Postgres-backed runtime state in the stack:

```bash
MESH_STATE_BACKEND=postgres docker compose -f docker-compose.stack.yml up --build
```

## Migration Rehearsal

Release provenance requires a rollback-verified `mesh.migration_rehearsal.v1` proof for the current Postgres migration inventory. For disposable CI or staging databases, run:

```bash
MESH_MIGRATION_REHEARSAL_DATABASE_URL=postgresql://mesh:mesh@127.0.0.1:5432/mesh \
  python3 scripts/run_postgres_migration_rehearsal.py \
    --output dist/migration-rehearsal.json \
    --operator-id "$MESH_OPERATOR_ID" \
    --environment "$MESH_ENVIRONMENT" \
    --json
```

The runner requires an empty public schema unless `--allow-existing-schema` is set, applies every SQL file under `migrations/postgres` inside a transaction, checks that schema objects were created, rolls the transaction back, and verifies that the schema returned to its pre-migration snapshot. It fails closed on destructive migration statements unless `--allow-destructive-statements` is set after operator review.

## Schema

The initial schema is in `migrations/postgres/001_live_persistence.sql`.

It creates:

- `goals`: persisted operator goals required by the existing control-plane API.
- `runs`: one row per control-plane run.
- `run_events`: append-only typed event stream keyed by `run_id` and sequence.
- `run_snapshots`: latest materialized run state for UI/API reads.
- `approvals`: operator steering commands, approvals, pauses, cancels, and overrides.
- `learning_outcomes`: durable replacement for local `learning/outcomes.json`.
- `artifacts`: metadata and URI/path references for artifacts.
- `memory_items`: relational memory records for facts, summaries, notes, and decisions.
- `merkle_roots`: persisted audit roots linked to runs/events.

Additional migrations extend the same production store:

- `002_memory_substrate.sql`: canonical observations, claims, relationships,
  supersessions, retrieval records, and memory packets.
- `004_incident_corpus.sql`: normalized incident-corpus rows, labels, artifact
  refs, text indexes, and row-to-memory projection refs.

Incident-corpus payloads keep the full JSON row as the compatibility boundary.
Prefer explicit `labels.coverage` and `training_fact.quality_measurements`
fields for Breakthrough evidence; legacy payload scanning is retained for older
rows.

Large artifacts should not be stored directly in Postgres. Store URI/path plus content hash in `artifacts`.

## Runtime Behavior

Event append is canonical. In Postgres mode, appending an event, updating the latest run snapshot, and recording the corresponding Merkle root happen in one transaction. Snapshots are materialized for fast UI/API reads and are rebuildable from `run_events`.

Vault and Merkle outputs are still produced from the canonical event stream. File mode and Postgres mode both expose the same `MeshStateStore` interface to the control plane.

Both backends preserve the latest event cursor when an older run snapshot is saved after an event append. Run snapshot saves merge artifact keys and do not allow late background writers to roll a final lifecycle stage back to a running stage. Async vault mirrors are flushed during state-store close, and terminal run states force a vault materialization so shutdown does not leave the local audit mirror behind the canonical event stream.
