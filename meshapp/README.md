# Orbital Mesh Operator

Production pilot-serving operator app for Orbital Mesh. `meshapp/frontend` is a Next static export carrying the Mesh operator console; `meshapp/src` is the zero-native shell that hosts it in a native WebView.

State slices:

- `meshapp.operator_shell.v1`: zero-native app/window/source state.
- `meshapp.frontend.control_plane_api_client.v1`: control-plane HTTP and SSE client.
- `meshapp.operator_console.theme.v1`: operator UI styling and brand tokens.

## Setup

`zig build dev`, `zig build run`, and `zig build package` install frontend dependencies automatically. To install them explicitly, run:

```sh
npm install --prefix frontend
```

The generated native build defaults to this zero-native framework path:

```text
/Users/shaanp/.nvm/versions/node/v24.0.2/lib/node_modules/zero-native

```

Override it with `-Dzero-native-path=/path/to/zero-native` if you move this app.

## Commands

```sh
zig build dev
zig build run
zig build test
zig build package
zero-native doctor --manifest app.zon
```

`zig build dev` starts the frontend dev server from `app.zon`, waits for it, and launches the native shell with `ZERO_NATIVE_FRONTEND_URL`.

Frontend:

- Type: next
- Production assets: `frontend/out`
- Dev URL: `http://127.0.0.1:3000/`
- Default Mesh API URL outside HTTP(S) origins: `http://127.0.0.1:8787`

Set `NEXT_PUBLIC_MESH_API_URL` at build time or pass `?server=<url>` at runtime to target another control-plane API.

Local browser sessions on `localhost`, `127.0.0.1`, or `::1` send `X-Mesh-Operator: local-operator` and `X-Mesh-Roles: viewer,launcher,approver` by default so protected read paths such as `/api/approvals` do not stall the console. Override with `NEXT_PUBLIC_MESH_OPERATOR_ID` and `NEXT_PUBLIC_MESH_OPERATOR_ROLES`, `?operator=<id>&roles=<csv>`, `?operator_id=<id>&operator_roles=<csv>`, or `localStorage` keys `mesh.operator.id` and `mesh.operator.roles`. Production ingress must still strip client-supplied identity headers and stamp trusted identity, as documented in `docs/authenticated-ingress.md`.

## HelixDB Memory Projection

Enable HelixDB projection for the verified memory backend:

```bash
MESH_MEMORY_GRAPH_BACKEND=helix
MESH_HELIX_API_ENDPOINT=http://localhost:6969
MESH_HELIX_QUERY_NAMESPACE=mesh
```

See `docs/memory-architecture.md` for fullHelixDB projection configuration and the HelixQL query schema under `helix/mesh-memory/`.

## Web Engines

The generated app defaults to the system WebView. On macOS you can switch to Chromium/CEF with:

```sh
zero-native cef install
zig build run -Dplatform=macos -Dweb-engine=chromium
```

`zero-native cef install` downloads zero-native's prepared CEF runtime, including the native wrapper library.

For one-command local setup, opt into build-time install:

```sh
zig build run -Dplatform=macos -Dweb-engine=chromium -Dcef-auto-install=true
```

Use `-Dcef-dir=/path/to/cef` when you keep CEF outside the platform default under `third_party/cef`.

```sh
zero-native doctor --web-engine chromium
```

Diagnostics:

- Set `ZERO_NATIVE_LOG_DIR` to override the platform log directory during development.
- Set `ZERO_NATIVE_LOG_FORMAT=text|jsonl` to choose persistent log format.
