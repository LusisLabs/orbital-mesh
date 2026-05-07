# Postgres Restart Proof

Pilot deployments must prove that Postgres-backed run events, memory, and Merkle roots survive a store restart.

The executable harness is `scripts/verify_postgres_restart_proof.py`. It uses `shared/mesh_runtime/postgres_state.py` through the normal state-store factory rather than direct SQL fixtures.

## Command

```bash
scripts/verify_postgres_restart_proof.py --database-url "$MESH_DATABASE_URL" --json
```

The command:

- opens a Postgres state store;
- creates a proof run session;
- appends two run events;
- writes a memory observation;
- captures the Merkle root;
- closes the store;
- reopens a fresh store instance;
- verifies the run, event sequence, event proof, Merkle root, and memory observation.

`--skip-if-missing` is available for local validation jobs that do not have a database:

```bash
scripts/verify_postgres_restart_proof.py --skip-if-missing --json
```

That mode returns `status: skipped`; it is not a pilot proof.

## Pass Criteria

All checks must be true:

- `run_restored`;
- `events_restored`;
- `first_event_proof_restored`;
- `merkle_root_stable`;
- `memory_restored`.

The output `run_id` and `merkle_root` are part of the pilot release packet.

## Failure Handling

A failed proof blocks pilot readiness. Do not mark the pilot go/no-go packet as `go` from file-backed state or from a skipped proof.

Common causes:

- `MESH_DATABASE_URL` missing or pointing at a non-persistent database;
- migrations not applied;
- Postgres driver unavailable;
- vault side effects configured to a non-writable path;
- database permissions missing insert/select privileges for runs, run events, Merkle roots, and memory records.
