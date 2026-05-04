# Authenticated Ingress

Mesh does not terminate external SSO itself. Production and staging deployments must put the control plane behind an authenticated TLS reverse proxy and must not expose the raw HTTP service to external clients.

## Runtime Contract

Set:

```bash
MESH_OPERATOR_IDENTITY_REQUIRED=1
MESH_OPERATOR_HEADER=X-Mesh-Operator
MESH_OPERATOR_ROLES_HEADER=X-Mesh-Roles
```

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
