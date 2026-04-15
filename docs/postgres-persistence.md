# Postgres Persistence

Mesh supports two runtime state backends:

- `file`: default local mode. Runs, events, learning outcomes, vault mirrors, and Merkle audit output stay under `.mesh-runtime-state`.
- `postgres`: production mode. Canonical run state is stored in Postgres using `MESH_DATABASE_URL`.

Supabase is supported as a hosted Postgres target by setting `MESH_DATABASE_URL`. Mesh does not use Supabase-specific APIs in this version.

## Configuration

```bash
MESH_STATE_BACKEND=postgres
MESH_DATABASE_URL=postgresql://mesh:mesh@postgres:5432/mesh
```

`MESH_STATE_BACKEND=file` remains the default. File mode preserves the local replay model and continues to write `.mesh-runtime-state`.

## Docker Stack

`docker-compose.stack.yml` starts a `postgres` service and wires `MESH_DATABASE_URL` to it. The stack still defaults Mesh to file mode to avoid breaking local demos:

```bash
docker compose -f docker-compose.stack.yml up --build
```

To exercise Postgres-backed runtime state in the stack:

```bash
MESH_STATE_BACKEND=postgres docker compose -f docker-compose.stack.yml up --build
```

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

Large artifacts should not be stored directly in Postgres. Store URI/path plus content hash in `artifacts`.

## Runtime Behavior

Event append is canonical. In Postgres mode, appending an event, updating the latest run snapshot, and recording the corresponding Merkle root happen in one transaction. Snapshots are materialized for fast UI/API reads and are rebuildable from `run_events`.

Vault and Merkle outputs are still produced from the canonical event stream. File mode and Postgres mode both expose the same `MeshStateStore` interface to the control plane.
