# GPUI Operator Console

Orbital Mesh now has a first-party Rust desktop client under `apps/mesh-gpui/`. The goal is to make the core application feel like a professional operations console rather than a themed web dashboard.

## Architecture

The GPUI console is a client of the existing Mesh control plane.

- Runtime authority remains in `control_plane_server.py` and `services/control_plane.py`.
- The desktop app reads `/api/health`, `/api/readiness`, `/api/runs`, `/api/watchers`, `/api/trust-ladder`, `/api/simulations`, `/api/benchmarks`, `/api/service-agents`, and `/api/pilot/go-no-go`.
- Kill-switch actions call `POST /api/kill-switch` with the same admin boundary used by the web UI.
- The app accepts `MESH_GPUI_API_URL` or `MESH_API_URL`; default is `http://127.0.0.1:8787`.
- Operator identity can be forwarded with `MESH_GPUI_OPERATOR`; roles are forwarded with `MESH_GPUI_ROLES`.
- The HTTP client has a default 3000 ms timeout, configurable with `MESH_GPUI_API_TIMEOUT_MS`.

This keeps policy, audit, RBAC, readiness, run state, Merkle proofs, and connector certification in one backend contract.

## Hardening

- Every request sends `Accept: application/json` and a stable `User-Agent`.
- Mutating requests include `Content-Type: application/json`.
- Operator and role headers are added only when operator identity is configured.
- Endpoint failures are captured per surface so one degraded backend route does not blank the entire console.
- The local e2e test covers snapshot load, kill-switch POST, operator headers, role headers, and error preservation.

## Roadmap Mapping

| Roadmap requirement | Desktop surface |
| --- | --- |
| Identity-first control plane | Command Center and mutating controls use backend operator/RBAC boundaries. |
| Evidence-first run inspection | Runs surface highlights stage, status, event count, steering, and Merkle state. |
| Policy simulator | Simulator surface lists mutation-free scenarios and benchmark evidence. |
| Pilot go/no-go packet | Pilot Packet surface renders generated checks and missing evidence. |
| Connector certification matrix | Component Integrations surface renders readiness connector states and service-agent scope. |
| Trust ladder | Trust surface renders service/action autonomy evidence. |
| Kill switch | Kill Switch surface can stop watchers, disable live execution, clear namespaces, and force approval gates through the backend API. |

## Migration Position

The browser UI remains useful for CI and web-based review, but the GPUI client is the target primary operator shell. Do not reimplement backend policy or run orchestration in GPUI. Add UI capability by extending the HTTP contract first, then binding the Rust client to that contract.
