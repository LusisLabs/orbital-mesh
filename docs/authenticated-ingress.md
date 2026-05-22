# Authenticated Ingress

Mesh does not terminate external SSO itself. Production and staging deployments must put the control plane behind an authenticated TLS reverse proxy and must not expose the raw HTTP service to external clients.

`MESH_AUTH_MODE=proxy_header` remains the default production ingress model. `MESH_AUTH_MODE=app_session` enables the product app's first-party session, OAuth, captcha, and team setup layer for deployments that choose it. App-session identity scopes product dashboards and feeds the same Mesh role checks, but it does not replace the Mesh control plane authority or add runtime tenant isolation. See `docs/operator-product-app.md`.

## Runtime Contract

Set:

```bash
MESH_OPERATOR_IDENTITY_REQUIRED=1
MESH_OPERATOR_HEADER=X-Mesh-Operator
MESH_OPERATOR_ROLES_HEADER=X-Mesh-Roles
```

For the operator UI proxy layer, also configure:

```bash
MESH_CONTROL_PLANE_URL=https://control-plane.mesh.internal
MESH_OPERATOR_IDENTITY_HEADER=X-Mesh-Operator
```

- `MESH_CONTROL_PLANE_URL` — URL of the backend control-plane service (default: `http://127.0.0.1:8000`).
- `MESH_OPERATOR_IDENTITY_HEADER` — Header name(s) containing operator identity, used by the proxy to extract and propagate identity to backend requests.

`docker-compose.prod.yml` binds the Mesh container to `127.0.0.1` on the host by default through `MESH_PUBLISH_HOST`. Keep that default when the reverse proxy runs on the same host, or set `MESH_PUBLISH_HOST` only to a private interface reachable by the authenticated proxy. Do not set it to `0.0.0.0` for Internet-facing deployments.

The production compose contract also defaults to:

```bash
MESH_READINESS_PROFILE=pilot
MESH_STATE_BACKEND=postgres
MESH_OPERATOR_IDENTITY_REQUIRED=1
MESH_FORCE_APPROVAL_GATE=1
MESH_LIVE_FEEDBACK_REQUIRED=1
MESH_FEEDBACK_PROMETHEUS_ENABLED=1
```

It requires deployment-specific `MESH_DATABASE_URL`, `MESH_PROMETHEUS_URL`, `MESH_BRAIN_ARTIFACT_URI_PREFIX`, `MESH_BRAIN_ARTIFACT_REGISTRY_PATH`, `MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH`, `MESH_BRAIN_SERVING_BASE_URL`, and `MESH_BRAIN_SERVING_MODEL` values before startup.

Staging and pilot readiness require `MESH_AUTHENTICATED_INGRESS_PROOF_PATH` to point at a passing `mesh.authenticated_ingress_deployment_proof.v1` packet. Production compose refuses to start without that path because `MESH_OPERATOR_IDENTITY_REQUIRED=1` is not enough by itself; Mesh also needs evidence that the deployed proxy terminates TLS, enforces identity, strips client-supplied Mesh headers, stamps trusted role headers, keeps the raw upstream private, and records operator/source identity for audit.

The proxy is responsible for:

- terminating TLS;
- enforcing SSO, OIDC, SAML, or equivalent identity;
- stripping any client-supplied `X-Mesh-Operator`, `X-Mesh-Roles`, `X-Mesh-Role`, `X-Forwarded-User`, and `X-Auth-Request-Email` headers before authentication;
- setting the trusted operator identity header after authentication;
- setting the trusted role header from the identity provider group or role claim;
- denying direct access to the upstream Mesh port.

Mesh treats the configured headers as the trust boundary. If a deployment allows clients to set those headers directly, role enforcement is bypassable at the ingress layer.

## Header Shape

`X-Mesh-Operator` should contain one stable operator identifier, usually an email address or identity-provider subject.

`X-Mesh-Roles` should contain comma-separated or semicolon-separated roles. Supported app roles:

| Role | App capability |
| --- | --- |
| `viewer` | Call the mutation-free policy simulator. |
| `launcher` | Create runs and send non-approval steering commands. |
| `approver` | Approve or override decisions and execution parameters. |
| `admin` | Use every mutating control, watcher mutation, trust-ladder override, and kill switch. |

Read-only inspection routes are protected by the reverse proxy. Mutating app routes additionally enforce these roles inside `control_plane_server.py`.

## Proxy Sketch

This is a shape reference, not a complete vendor config:

```nginx
# Public TLS listener.
# 1. Authenticate the request with the chosen SSO/OIDC/SAML gateway.
# 2. Strip any user-supplied Mesh identity headers.
# 3. Stamp identity and roles only from trusted auth claims.

proxy_set_header X-Mesh-Operator "";
proxy_set_header X-Mesh-Roles "";
proxy_set_header X-Mesh-Role "";
proxy_set_header X-Forwarded-User "";
proxy_set_header X-Auth-Request-Email "";

proxy_set_header X-Mesh-Operator $authenticated_email;
proxy_set_header X-Mesh-Roles $authenticated_mesh_roles;
proxy_set_header X-Forwarded-Proto https;
proxy_pass http://mesh-control-plane:8787;
```

The deployment-specific config must prove that the blanking step runs before upstream forwarding and that only the authenticated claim source can populate the final operator headers.

## Rehearsal

Run:

```bash
scripts/verify_authenticated_ingress.py --json
```

The rehearsal starts a local ephemeral control plane with `operator_identity_required=True` and exercises the HTTP API with proxy-stamped headers.

It proves:

- anonymous run creation is rejected with `401`;
- a `viewer` cannot create a run;
- a `viewer` can call `POST /api/policy/simulate` and the response remains `mutates: false`;
- a `launcher` can create a run and the run stores the proxy-header operator artifact;
- a `launcher` cannot approve an approval gate;
- an `approver` can approve the run and the steering event stores the approver identity;
- a `launcher` cannot use the kill switch;
- an `admin` can force the approval gate through `POST /api/kill-switch`.

It does not prove external TLS, SSO, group mapping, or network isolation. Those remain deployment evidence and must be captured from the actual ingress.

## Deployment Proof

Capture the deployed proxy evidence as JSON and verify it before claiming private-staging or pilot readiness:

```bash
scripts/verify_authenticated_ingress_deployment.py --proof "$MESH_AUTHENTICATED_INGRESS_PROOF_PATH" --json
```

The proof must include:

- non-local environment and operator id;
- HTTPS ingress URL;
- TLS termination evidence, public listener evidence, minimum TLS version, and certificate ref;
- SSO/OIDC/SAML or equivalent identity enforcement evidence;
- identity and role claim mapping;
- proof that client-supplied `X-Mesh-Operator` and `X-Mesh-Roles` are stripped before upstream forwarding;
- proof that the proxy stamps `X-Mesh-Operator` and `X-Mesh-Roles` only from trusted identity claims;
- viewer, launcher, approver, and admin group mappings;
- proof that the raw Mesh service is not publicly reachable and that the upstream path is private;
- a passing `mesh.authenticated_ingress_rehearsal.v1` app-level rehearsal reference;
- audit evidence that operator identity and source IP or proxy identity are recorded;
- `raw_secret_material_present: false`.
