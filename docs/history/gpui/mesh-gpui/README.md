# Mesh GPUI Operator Console

Archived under `docs/history/gpui/mesh-gpui/`. The active operator surface is
the browser UI in `web/`.

This is the first-party Rust desktop surface for Orbital Mesh. It uses GPUI plus `gpui-component` and talks to the existing control-plane HTTP API instead of duplicating runtime logic.

## Run

Start the Mesh control plane first:

```bash
PYTHONPATH=. python3 run_server.py
```

Then start the desktop client:

```bash
MESH_GPUI_API_URL=http://127.0.0.1:8787 cargo run --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml
```

`MESH_API_URL` is also accepted. `MESH_GPUI_API_URL` wins when both are set.

The crate enables GPUI's `runtime_shaders` feature so local checks work with Apple Command Line Tools. Release packaging on macOS should still use a full Xcode install so Metal shaders can be compiled ahead of time.

## Operator Context

The client can forward proxy-style operator context to the API:

```bash
MESH_GPUI_API_URL=http://127.0.0.1:8787 \
MESH_GPUI_OPERATOR=ops@example.com \
MESH_GPUI_ROLES=viewer,launcher,approver,admin \
cargo run --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml
```

`MESH_GPUI_API_TIMEOUT_MS` controls HTTP timeout behavior. Default is 3000 ms. Endpoint failures are surfaced in the UI without discarding successfully loaded panels.

## Validation

```bash
cargo fmt --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml -- --check
cargo check --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml
cargo clippy --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml -- -D warnings
cargo test --manifest-path docs/history/gpui/mesh-gpui/Cargo.toml
```

The e2e-style test in `tests/api_e2e.rs` starts a local fake Mesh API, loads every console surface, applies the kill switch, and verifies `X-Mesh-Operator`, `X-Mesh-Roles`, and the full-stop payload.

## Product Surface

The console is organized around the production deployment roadmap:

- Command Center: health, readiness, runs, watchers, pilot entry, and full stop.
- Runs: run status, steering mode, evidence count, and Merkle signal.
- Readiness: tiered profile status, required blockers, and integration posture.
- Policy Simulator: scenario and benchmark visibility for mutation-free review.
- Trust Ladder: service and action-class autonomy evidence.
- Component Integrations: connector certification and service-agent scope.
- Pilot Packet: generated go/no-go evidence.
- Kill Switch: watcher pause, live-execution disablement, namespace clearing, and forced approval.
- Roadmap: phase-aligned production UX model.

The app intentionally keeps the Python control plane authoritative. Mutating controls call documented HTTP endpoints and inherit the same RBAC, audit, and policy boundaries as the browser UI.
