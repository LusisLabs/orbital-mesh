# Lusis Labs Preview Deployment

State slice: `lusislabs-preview-deployment`.

`lusislabs.com` is served by nginx on the Hetzner host and proxied to the Mesh product preview service on `127.0.0.1:8788`. The old service on `127.0.0.1:8787` is intentionally separate.

## Server Layout

- `/opt/lusis-mesh-webapp/incoming/source`: optional source tree for manual server deploys; the self-hosted GitHub runner passes its checkout workspace directly.
- `/opt/lusis-mesh-webapp/releases/<timestamp>-<commit>`: immutable release directories built on the server.
- `/opt/lusis-mesh-webapp/current`: symlink used by the systemd service.
- `/opt/lusis-mesh-webapp/shared/state`: persistent app-session state.
- `/etc/lusis-mesh-webapp-preview.env`: root-only OAuth provider secrets and callback URLs.
- `/usr/local/bin/deploy-lusis-mesh-webapp`: deployment entrypoint.
- `lusis-mesh-preview.service`: systemd unit that runs the preview API/web server.

## Deployment Flow

`.github/workflows/deploy-lusislabs-preview.yml` deploys on every push to `main`, and can also be run manually with `workflow_dispatch`. It runs on the Hetzner self-hosted runner labeled `lusislabs-preview`, so it does not depend on GitHub-hosted runner minutes.

The workflow:

1. Checks out the pushed commit.
2. Writes `.deploy-commit`.
3. Runs `sudo /usr/local/bin/deploy-lusis-mesh-webapp --source "$GITHUB_WORKSPACE"` on the self-hosted runner.

The server script:

1. Copies the incoming source into a new release directory.
2. Runs `pnpm --dir meshapp/frontend install --no-frozen-lockfile`.
3. Runs `NEXT_PUBLIC_MESH_API_URL=https://lusislabs.com pnpm --dir meshapp/frontend run build`.
4. Switches `/opt/lusis-mesh-webapp/current` atomically.
5. Restarts `lusis-mesh-preview.service`.
6. Verifies `http://127.0.0.1:8788/api/health`.
7. Rolls back the symlink and restarts the previous release if the restart or healthcheck fails.

## GitHub Runner

The self-hosted runner is registered to `LusisLabs/orbital-mesh` with the label `lusislabs-preview`. It is intended only for trusted `main` pushes and manual dispatches from this repository.

The runner service account is allowed to run only `/usr/local/bin/deploy-lusis-mesh-webapp` through passwordless sudo.

## Manual Commands

Check service status:

```bash
ssh root@<server-host> 'systemctl status lusis-mesh-preview.service --no-pager'
```

Run a manual server deploy after uploading source:

```bash
ssh root@<server-host> 'sudo /usr/local/bin/deploy-lusis-mesh-webapp --source /opt/lusis-mesh-webapp/incoming/source'
```

Verify public ingress:

```bash
curl --noproxy "*" -u operator:<password> https://lusislabs.com/api/health
```
