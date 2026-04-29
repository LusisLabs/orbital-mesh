# Internal MeshControl

`MeshControl` is the internal Lusis OS companion for Mesh operator visibility. It runs as a native OS process under `lusisOS-main/components/apps/MeshControl`, opens automatically on OS boot, and is shipped by Compose as the `mesh-ui` sidecar.

## Launch topology

- `mesh` serves the Mesh API on port `8787`.
- `mesh-ui` serves the Lusis OS shell on `MESH_UI_PUBLISH_PORT`, default `3000`.
- `MeshControl` is registered as a singleton process and can be opened with `?app=MeshControl`.
- `MeshTerminal` remains secondary log visibility. `MeshControl` is the primary internal operator interface.

## Endpoint rules

Default endpoint resolution is hardened:

- Compose builds use `NEXT_PUBLIC_MESH_API_BASE_URL=http://mesh:8787`.
- Local dev without that variable falls back to `http://127.0.0.1:8787`.
- A process `url` argument or `?server=` query can override the endpoint only when the target is same-origin, localhost, a private-network host, `mesh`, or explicitly allowlisted.
- Public internet API origins are blocked unless listed in `NEXT_PUBLIC_MESH_API_ALLOWLIST`.

The app does not persist credentials or API tokens in browser storage. Requests omit browser credentials.

## Reverse-proxy auth

The Mesh API remains unauthenticated on the internal network. Do not expose `mesh:8787` or the published `MESH_PUBLISH_PORT` directly to the public internet.

Use Caddy, nginx, Cloudflare Access, Tailscale, SSO middleware, or an equivalent reverse-proxy auth boundary as the only public entrypoint. Put both the OS UI and Mesh API behind that boundary when remote access is needed.

## Compose sidecar

`docker-compose.yml` and `docker-compose.stack.yml` include:

```yaml
mesh-ui:
  depends_on:
    mesh:
      condition: service_healthy
  ports:
    - "${MESH_UI_PUBLISH_PORT:-3000}:3000"
  environment:
    NEXT_PUBLIC_MESH_API_BASE_URL: "${NEXT_PUBLIC_MESH_API_BASE_URL:-http://mesh:8787}"
```

Start the local stack:

```bash
docker compose up --build -d
```

Open the OS UI:

```text
http://127.0.0.1:3000/?app=MeshControl
```

For local development outside Compose, run Mesh on `127.0.0.1:8787` and start the OS shell from `lusisOS-main`.
