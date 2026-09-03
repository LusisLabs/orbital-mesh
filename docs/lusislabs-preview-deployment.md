# Lusis Labs Preview Deployment

State slice: `lusislabs-preview-deployment`.

`app.lusislabs.com` is served by nginx on the Hetzner host and proxied to the Mesh product preview service on `127.0.0.1:8788`. The old service on `127.0.0.1:8787` is intentionally separate.

The static marketing landing page also has a GitHub Pages deployment path in `.github/workflows/deploy-lusislabs-pages.yml`. Its canonical hostname is `lusislabs.com` with `www.lusislabs.com` as the alias; the operator app and control-plane API remain on `https://app.lusislabs.com`. GitHub Pages hosts only the exported frontend, so the API origin remains a separately deployed Mesh service.

## Server Layout

- `/opt/lusis-mesh-webapp/incoming/source`: optional source tree for manual server deploys; the self-hosted GitHub runner passes its checkout workspace directly.
- `/opt/lusis-mesh-webapp/releases/<timestamp>-<commit>`: immutable release directories built on the server.
- `/opt/lusis-mesh-webapp/current`: symlink used by the systemd service.
- `/opt/lusis-mesh-webapp/shared/state`: persistent app-session state.
- `/etc/lusis-mesh-webapp-preview.env`: root-only OAuth provider secrets and callback URLs.
- `/etc/systemd/system/lusis-mesh-preview.service.d/20-lusis-product-domain.conf`: deployment-managed public product origin and API CORS override.
- `/usr/local/bin/deploy-lusis-mesh-webapp`: deployment entrypoint.
- `lusis-mesh-preview.service`: systemd unit that runs the preview API/web server.
- `lusis-mesh-release`: Docker container name used only for verified release-image deployments.

## Deployment Flow

`.github/workflows/deploy-lusislabs-preview.yml` deploys on every push to `main`, and can also be run manually with `workflow_dispatch`. It runs on the Hetzner self-hosted runner labeled `lusislabs-preview`, so it does not depend on GitHub-hosted runner minutes.

The source-preview workflow:

1. Checks out the pushed commit.
2. Writes `.deploy-commit`.
3. Installs the repository deployment entrypoint to `/usr/local/bin/deploy-lusis-mesh-webapp`.
4. Runs `sudo /usr/local/bin/deploy-lusis-mesh-webapp --source "$GITHUB_WORKSPACE"` on the self-hosted runner.

The server script:

1. Copies the incoming source into a new release directory.
2. Installs the product-domain systemd override and reloads systemd.
3. Runs `pnpm --dir meshapp/frontend install --frozen-lockfile`.
4. Runs `NEXT_PUBLIC_MESH_API_URL=https://app.lusislabs.com pnpm --dir meshapp/frontend run build`.
5. Switches `/opt/lusis-mesh-webapp/current` atomically.
6. Restarts `lusis-mesh-preview.service`.
7. Verifies `http://127.0.0.1:8788/api/health`.
8. Rolls back the symlink and restarts the previous release if the restart or healthcheck fails.

## Release-Image Deployment

State slice: `release-image-runtime-binding`.

Use the manual `Deploy Lusis Labs Preview` workflow with:

- `deploy_mode=release-image`;
- `handoff_run_id=<successful Release Image Handoff run ID>`.

The release-image path:

1. Downloads the `release-image-handoff-<sha>` artifact from the named handoff run.
2. Installs the current deployment entrypoint on the self-hosted runner.
3. Runs `sudo /usr/local/bin/deploy-lusis-mesh-webapp --release-artifact-root <artifact-root>`.
4. Loads `release-image-handoff/orbital-mesh-handoff-image.tar.gz` with Docker.
5. Runs `scripts/verify_release_image_handoff.py` with `--require-artifacts`, `--image-ref`, the signed complete provenance packet, and `--env-output`.
6. Copies the signed `release-provenance-draft.json` to `/opt/lusis-mesh-webapp/shared/state/release-provenance.json`.
7. Starts the actual verified image as Docker container `lusis-mesh-release`, bound to `127.0.0.1:8788:8787`, with app-session auth enabled for `mesh.lusislabs.com` and `app.lusislabs.com`, `MESH_RELEASE_PROVENANCE_PATH=/app/.mesh-runtime-state/release-provenance.json`, `MESH_BUILD_COMMIT`, and `MESH_BUILD_IMAGE_DIGEST` from the verifier-generated env.
8. Healthchecks `http://127.0.0.1:8788/api/health`.
9. Rolls back to the previous release container or the source preview service if startup or healthcheck fails.

Do not copy `MESH_BUILD_IMAGE_DIGEST` into the source-preview service to force a green runtime-binding check. The release-image path must run the actual verified image that produced the handoff digest.

## GitHub Runner

The self-hosted runner is registered to `LusisLabs/orbital-mesh` with the label `lusislabs-preview`. It is intended only for trusted `main` pushes and manual dispatches from this repository.

The runner service account must be allowed to run `/usr/local/bin/deploy-lusis-mesh-webapp` through passwordless sudo. If passwordless sudo is restricted to that entrypoint, install the updated script once out of band before using `deploy_mode=release-image`; the workflow fails closed when the installed entrypoint does not expose `--release-artifact-root`.

## Manual Commands

Check service status:

```bash
ssh root@<server-host> 'systemctl status lusis-mesh-preview.service --no-pager'
```

Run a manual server deploy after uploading source:

```bash
ssh root@<server-host> 'sudo /usr/local/bin/deploy-lusis-mesh-webapp --source /opt/lusis-mesh-webapp/incoming/source'
```

Run a manual release-image deploy after uploading a handoff artifact directory:

```bash
ssh root@<server-host> 'sudo /usr/local/bin/deploy-lusis-mesh-webapp --release-artifact-root /opt/lusis-mesh-webapp/incoming/release-image-handoff'
```

Verify public ingress:

```bash
curl --noproxy "*" -u operator:<password> https://app.lusislabs.com/api/health
```
