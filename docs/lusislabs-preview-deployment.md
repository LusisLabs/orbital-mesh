# Lusis Labs Preview Deployment

State slice: `lusislabs-preview-deployment`.

`lusislabs.com` is served by nginx on the Hetzner host and proxied to the Mesh product preview service on `127.0.0.1:8788`. The old service on `127.0.0.1:8787` is intentionally separate.

## Server Layout

- `/opt/lusis-mesh-webapp/incoming/source`: source tree uploaded by GitHub Actions.
- `/opt/lusis-mesh-webapp/releases/<timestamp>-<commit>`: immutable release directories built on the server.
- `/opt/lusis-mesh-webapp/current`: symlink used by the systemd service.
- `/opt/lusis-mesh-webapp/shared/state`: persistent app-session state.
- `/etc/lusis-mesh-webapp-preview.env`: root-only OAuth provider secrets and callback URLs.
- `/usr/local/bin/deploy-lusis-mesh-webapp`: deployment entrypoint.
- `lusis-mesh-preview.service`: systemd unit that runs the preview API/web server.

## Deployment Flow

`.github/workflows/deploy-lusislabs-preview.yml` deploys after the `CI` workflow succeeds on `main`, and can also be run manually with `workflow_dispatch`.

The workflow:

1. Checks out the exact CI-validated commit.
2. Writes `.deploy-commit`.
3. Rsyncs the source tree to `/opt/lusis-mesh-webapp/incoming/source`.
4. Runs `sudo /usr/local/bin/deploy-lusis-mesh-webapp --source /opt/lusis-mesh-webapp/incoming/source`.

The server script:

1. Copies the incoming source into a new release directory.
2. Runs `pnpm --dir meshapp/frontend install --no-frozen-lockfile`.
3. Runs `NEXT_PUBLIC_MESH_API_URL=https://lusislabs.com pnpm --dir meshapp/frontend run build`.
4. Switches `/opt/lusis-mesh-webapp/current` atomically.
5. Restarts `lusis-mesh-preview.service`.
6. Verifies `http://127.0.0.1:8788/api/health`.
7. Rolls back the symlink and restarts the previous release if the restart or healthcheck fails.

## GitHub Secrets

Required repository secrets:

- `LUSIS_DEPLOY_HOST`: Hetzner host or IP.
- `LUSIS_DEPLOY_USER`: restricted deploy user, normally `lusis-deploy`.
- `LUSIS_DEPLOY_SSH_KEY`: private key for the deploy user.

The deploy user is allowed to run only `/usr/local/bin/deploy-lusis-mesh-webapp` through passwordless sudo.

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
