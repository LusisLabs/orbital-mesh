# Auto Canvas Workspace

## Scope

The web control plane is now organized around the run graph as the primary auto canvas.

- Left drawer: sessions, run sessions, research sessions, goals, launch configuration, and integration readiness.
- Center canvas: active goal, run state, React Flow execution graph, Kubernetes topology view, Merkle proof view, artifact graph, and the live event timeline.
- Right drawer: steering console, operator notes, advanced overrides, and inspector tabs.
- Header controls: session drawer and steering drawer toggles.

## Canvas Modes

The center canvas exposes four views, all backed by current run data:

- `Run Flow`: ordered event graph for the live session.
- `Kubernetes`: cluster, namespace, deployment, pods, and recent cluster events when the run was launched from a live Kubernetes deployment signal.
- `Merkle`: Merkle root, snapshot, proof path, siblings, and selected leaf for the active event proof.
- `Artifacts`: session artifacts across ingestion, triggering, decision, evaluation, execution, and feedback.

Canvas nodes route into the right-side inspector where the backing data exists:

- Run nodes keep the selected event synchronized with overview and steering.
- Kubernetes nodes open evidence context.
- Merkle nodes open the Merkle inspector.
- Artifact nodes jump to the inspector tab that matches the artifact family.

## Reproduce Locally

Run from the repository root unless stated otherwise.

```bash
git checkout codex/ui-overhaul-auto-canvas
cd web
npm ci
npm run lint
npm run build
npm run dev
```

Open the Vite URL printed by `npm run dev`.

## Control Plane Data Contract

The UI only exposes actions backed by the current API:

- `POST /api/runs` for launch.
- `POST /api/runs/{run_id}/steer` for approval, resume, cancel, auto-mode, notes, decision overrides, and execution parameter overrides.
- `GET /api/runs`, `GET /api/research-sessions`, `GET /api/goals`, and `GET /api/readiness` for the session drawer.
- `GET /api/runs/{run_id}` and `GET /api/stream/runs/{run_id}` for the auto canvas.

Session rename and archive controls are intentionally not rendered until backend endpoints exist. Required backend contract:

- Rename run session: stable run display name field plus an update endpoint.
- Archive run session: archived status or timestamp plus list filtering semantics.
- Rename research session: stable display name field plus an update endpoint.
- Archive research session: archived status or timestamp plus list filtering semantics.

## Production Use

The UI change does not alter deployment, inference routing, Kubernetes access, or remediation policy. Production rollout remains governed by `docs/production-live-runbook.md`.
