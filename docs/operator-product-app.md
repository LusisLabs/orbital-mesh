# Operator Product App

State slices:

- `auth-identity`: users, password credentials, OAuth account links, sessions.
- `team-tenancy`: team profile, active team, membership, role mapping.
- `mesh-dashboard-read-model`: product dashboard aggregation over Mesh-owned APIs.
- `mesh.agent_flow.dashboard.v1`: Agent Flow endpoint/readiness posture in the product dashboard read model.
- `mesh.agent_flow.chat_response.v1`: Harper-696 chat response envelope over read-only dashboard state.
- `mesh.agent_flow.livekit_session.v1`: short-lived LiveKit browser session bootstrap for Harper-696 voice.
- `mesh.agent_flow.mutation_preview.v1`: draft-only mutation preview and confirmation record.
- `mesh-settings-control`: validated UI/CLI settings stored in operator identity state.
- `mesh.operator-preferences.v1`: scoped operator setup preferences for agent fabric, preferred agents, model defaults, approval posture, pause points, target defaults, and run templates.
- `meshapp.run-preflight.v1`: product launch preflight read model over operator identity, preferences, topology, connector scopes, readiness, and target lock posture.
- `meshapp.run-workbench.v1`: product run review model over Mesh run detail, events, evidence, decisions, agent tasks, timeline proof, and export endpoints.
- `ui-product-shell`: `meshapp/frontend` production product shell.

## Auth Modes

Mesh still supports proxy-header auth as the default production ingress model:

```bash
MESH_AUTH_MODE=proxy_header
MESH_OPERATOR_IDENTITY_REQUIRED=1
```

The product app can also run with first-party app sessions:

```bash
MESH_AUTH_MODE=app_session
MESH_OPERATOR_IDENTITY_PATH=.mesh-runtime-state/operator-identity.json
MESH_SESSION_COOKIE_NAME=mesh_session
```

App-session identity scopes the product dashboard and supplies the operator context used by existing Mesh role checks. It does not make Mesh runtime stores multi-tenant. Mesh remains the authority for policy, approvals, run state, readiness, evidence, and actuation.

## Email Signup And Captcha

Email/password signup is enabled by:

```bash
MESH_SIGNUP_ENABLED=1
MESH_PASSWORD_AUTH_ENABLED=1
```

Partner-facing signup can be constrained with invite state before live external use:

```bash
# Exact emails, bare domains, or @domain entries are accepted.
MESH_AUTH_INVITE_ALLOWLIST=alice@example.com,@partner.example
MESH_AUTH_INVITE_CODES=pilot-2026-redacted
```

When configured, `/api/auth/signup` requires a matching allowlisted email and, when `MESH_AUTH_INVITE_CODES` is non-empty, an invite code. The product UI hides unconfigured OAuth providers, asks for password confirmation, requires data-handling consent, and maps provider/captcha/invite failures to partner-safe messages. Runtime auth events record only redacted invite/provider proof metadata under `auth-provider-proof.v1`; raw invite codes, OAuth secrets, captcha responses, cookies, and passwords are not persisted in proof artifacts.

For non-local app-session signup, configure one captcha provider:

```bash
MESH_CAPTCHA_PROVIDER=turnstile
MESH_CAPTCHA_SITE_KEY=...
MESH_CAPTCHA_SECRET_KEY=...
```

Supported providers are `turnstile`, `hcaptcha`, and `recaptcha`. The UI requires the site key to render the browser challenge, and the API requires the secret key to verify the returned token. Local development can use:

```bash
MESH_CAPTCHA_DEV_BYPASS=1
```

The dev bypass only accepts the fixed `dev-captcha-ok` token and should not be enabled for staging or pilot.

If the browser reports `ERR_CONNECTION_REFUSED` for `127.0.0.1:8787/api/auth/...`, the Mesh control-plane API is not running or the frontend is pointed at the wrong `NEXT_PUBLIC_MESH_API_URL`. Start the API before using signup, login, OAuth, or captcha:

```bash
MESH_AUTH_MODE=app_session \
MESH_CAPTCHA_DEV_BYPASS=1 \
MESH_AUTH_PRODUCT_REDIRECT_URL=http://127.0.0.1:3000 \
MESH_AUTH_ALLOWED_ORIGINS=http://127.0.0.1:3000 \
python run_server.py

NEXT_PUBLIC_MESH_API_URL=http://127.0.0.1:8787 \
pnpm --dir meshapp/frontend run dev --hostname 127.0.0.1 --port 3000
```

Local browser session cookies require the frontend and API to use the same loopback hostname. If the frontend is opened at `http://localhost:3000` while the API base is `http://127.0.0.1:8787`, the browser can reject or withhold the API session cookie and product routes will report `session required`. The product client normalizes loopback defaults to the opened frontend hostname; explicit `?server=` overrides are left unchanged for operator testing.

If `/api/auth/config` succeeds but `/api/auth/me` fails with a backend-unavailable error, the product login screen keeps the degraded session-probe message visible and disables auth actions instead of rendering a normal login form over a broken API. A plain unauthenticated `/api/auth/me` response remains the normal login path.

Logout only clears the product UI after `/api/auth/logout` succeeds. If the API is unavailable during logout, the current session stays visible and the product shell shows an error instead of pretending the cookie was cleared.

## Agent Flow And Harper-696

The Agent Flow product page uses three operator-session endpoints:

```text
POST /api/operator/agent-flow/livekit-session
POST /api/operator/agent-flow/chat
POST /api/operator/agent-flow/confirm-preview
```

All three routes use the same app-session/team scope as `/api/operator/dashboard`. Chat responses are grounded in the dashboard read model and return explicit state slices, evidence references, lifecycle tasks, and a `mesh.agent_flow.mutation_preview.v1` draft. The confirmation route records that an operator reviewed a draft, but it does not execute `/api/runs` or `/api/runs/{run_id}/steer`; Mesh-owned routes remain the only mutation authority.

Live Harper-696 voice uses LiveKit when these variables are present:

```bash
MESH_LIVEKIT_URL=wss://livekit.example.com
MESH_LIVEKIT_API_KEY=...
MESH_LIVEKIT_API_SECRET=...
MESH_LIVEKIT_TOKEN_TTL_SECONDS=600
MESH_LIVEKIT_AGENT_NAME=Harper-696
```

For local/manual recovery, the same endpoint can use a pre-minted browser token when `MESH_LIVEKIT_URL` and `MESH_LIVEKIT_ACCESS_TOKEN` are present. This mode returns the token-bound room, identity, and expiry from the JWT payload and does not mint replacement tokens; API key plus API secret remain the durable configuration.

The API secret remains server-side. `/api/operator/agent-flow/livekit-session` returns a short-lived browser join token, scoped room, per-session participant identity, and configuration status. Voice publishing uses the requested team scope roles, requires a launcher, approver, or admin role, and grants microphone-only track publishing with data publishing disabled; viewer-only team sessions receive `status=permission_required` and no publish token. Expired or malformed pre-minted tokens receive `status=expired` or `status=invalid_token` and no publish token. When LiveKit is unconfigured, Agent Flow stays usable as a draft-first text workspace and returns `status=unconfigured` instead of failing the page.

Room names are scoped by the dashboard operator scope (`harper-696-<scope>` plus an optional sanitized suffix) so a caller cannot mint a browser token for an arbitrary LiveKit room. The browser refreshes near-expired voice tokens before connecting, publishes the local microphone only after a fresh session is minted, and attaches remote audio tracks for the Harper room. Preview confirmation validates the preview schema, id, draft status, endpoint, resource type, target Mesh state slice, proof state slice, issued scope, issued operator, and session-bound HMAC proof before recording confirmation.

## OAuth Providers

Google:

```bash
MESH_GOOGLE_OAUTH_CLIENT_ID=...
MESH_GOOGLE_OAUTH_CLIENT_SECRET=...
MESH_GOOGLE_OAUTH_REDIRECT_URL=https://mesh.example.com/api/auth/oauth/google/callback
```

GitHub:

```bash
MESH_GITHUB_OAUTH_CLIENT_ID=...
MESH_GITHUB_OAUTH_CLIENT_SECRET=...
MESH_GITHUB_OAUTH_REDIRECT_URL=https://mesh.example.com/api/auth/oauth/github/callback
```

When provider credentials are missing, OAuth start routes return `503` and the UI shows the path as unavailable.

P2 provider proof posture:

- Dummy OAuth client IDs and secrets are only route-shape checks. They can prove that `/api/auth/oauth/{provider}/start` emits Google/GitHub authorize URLs with the configured redirect URI, but they do not prove provider login.
- OAuth callback failures redirect back to the product shell with `auth_error` query codes. The product shell expands known callback codes into explicit Google/GitHub or missing-code messages.
- `MESH_AUTH_PRODUCT_REDIRECT_URL` controls where OAuth callbacks return after the API exchanges a provider code. It is accepted only for loopback URLs or origins listed in `MESH_AUTH_ALLOWED_ORIGINS`; otherwise the API falls back to `/?auth=...` on the API host instead of acting as an open redirect.
- Real provider proof requires an ignored local env file plus provider console redirects for `127.0.0.1`. Record only presence, absence, and redirect URL match status; never paste raw OAuth or captcha secrets into docs, logs, or committed artifacts.
- Real hCaptcha proof requires `MESH_CAPTCHA_PROVIDER=hcaptcha`, a site key, a secret key, the provider domain allowlist for `127.0.0.1` and `localhost`, and a successful browser token verification. Without those local/provider prerequisites, mark the provider proof blocked and keep signup fail-closed.
- Current local checkpoint: ignored root `.env.local` contains OAuth and hCaptcha variable names with values present, and `meshapp/frontend/.env.local` points the product app at the local Mesh API. Raw values stay local and uncommitted; live provider-console/browser proof is still a separate gate.

## Teams

New users can continue solo or create a team. The product team settings page now mutates the `team-tenancy` state slice through `/api/auth/team/update`, and the members page can invite or update members through `/api/auth/team/members`. Teams hold display metadata, members, and roles:

- `owner` and `admin` map to Mesh `admin`.
- `approver` maps to `approver`, `launcher`, and `viewer`.
- `launcher` maps to `launcher` and `viewer`.
- `viewer` maps to `viewer`.

Team state scopes the product dashboard and settings. Owner/admin members can update team profile metadata and invited member role mappings; viewers cannot. It does not rewrite historical Mesh runs or add tenant predicates to Mesh runtime persistence.

## CLI Settings

The UI settings surface, `/api/operator/settings`, and CLI share the same `operator-identity.json` settings slice.

Show settings:

```bash
python scripts/operator_config.py show --scope global
python scripts/operator_config.py show --scope team:<team_id>
```

Set settings non-interactively:

```bash
python scripts/operator_config.py set \
  --scope team:<team_id> \
  --operator-id admin@example.com \
  --reason "set team default" \
  default_orchestration_mode=hermes
```

The same settings slice also controls product launch defaults such as `default_run_scenario` and `default_target_lock`; the Evaluations page reads those values when preparing a new Mesh-admitted run. `default_run_scenario` is limited to signal fixtures that the backend can admit today: `reth_peer_starvation`, `reth_sync_stalled_disk_pressure`, `kubernetes_crashloop_patch`, and `search_latency_regression`.

Validate:

```bash
python scripts/operator_config.py validate --scope team:<team_id>
```

UI, API, and CLI mutations require an audit reason and append redacted audit records to `operator-config-audit.jsonl` next to the configured operator identity store. Audit records name `state_slice=mesh-settings-control`, operator id, scope, changed fields, config hash, and git/build commit.

The product settings page renders a parity row for every key in `settings_schema`. Mutable rows show both `/api/operator/settings` and the equivalent `python scripts/operator_config.py set --scope ... --operator-id ... --reason ... key=...` command. Deployment-owned values such as API base URL, build commit, state backend, and captcha provider render as read-only rows with an explicit reason instead of pretending to be dashboard settings.

## Operator Setup

The Operator Setup page mutates `mesh.operator-preferences.v1` through `/api/operator/preferences`. It is separate from `mesh-settings-control`: settings remain launch defaults with CLI parity, while preferences describe the operator's desired agent fabric, preferred proposal lanes, model provider/model, approval policy, pause points, target environment, target namespace/service, target lock default, and run template.

`/api/operator/dashboard` returns both the raw `operator_preferences` fields and an explicit `operator_preferences_state` wrapper with `schema_version`, `state_slice`, `scope`, `operator_preferences`, and `operator_preferences_schema`. The wrapper is the product source of truth for the setup page and run preflight.

Preference updates require an audit reason and append redacted audit records to `operator-config-audit.jsonl` with `state_slice=mesh.operator-preferences.v1`. Preferences never store provider secrets, kubeconfigs, bearer tokens, passwords, or raw API keys. Runtime environment variables and Mesh policy can still narrow or block requested lanes.

The Evaluations launch panel now renders `meshapp.run-preflight.v1` before `POST /api/runs`. It shows operator id, roles, team, auth source, selected topology, preferred agents, model binding, pause points, target environment/namespace/service, target lock posture, connector scopes, readiness, and blockers. Run creation stamps the preflight context into `simulation_context`; Mesh remains responsible for actual admission, target locks, policy, evidence, and actuation.

The proof drill-in now renders `meshapp.run-workbench.v1` after loading run detail, events, evidence graph, RCA, Merkle, timeline proof, and export package. It translates raw artifacts into current stage, operator, evidence summary, decision summary, agent task summary, blockers, and next valid operator action without replacing Mesh authority.

## Console Workflow Parity

`meshapp/frontend/src/product/ProductApp.tsx` is the default production product shell. It now exposes the migrated control-plane console from `meshapp/frontend/src/App.tsx` as first-class dashboard navigation under **Control Console**. Those entries open the full Mesh console in-place for Command, Evidence Runs, Approvals, Launch, Simulator, Trust Ladder, Pilot Packet, Readiness, Evidence, Connectors, Proposal Lanes, Signals, Hermes, Audit, and Roadmap.

The product shell also keeps product-native pages for Praxis, connector status, evaluations, topology, memory projection, readiness, kill switch, policy state, team, members, keys, and settings. The console bridge is UI wiring only: run admission, approvals, policy, evidence, readiness, and actuation remain Mesh-owned API and state slices.

## Validation

Use pnpm root gates:

```bash
git status --short
pnpm run lint:fast
pnpm run test:focused
pnpm run test:product:e2e
pnpm run verify:operator-goal
pnpm run verify:contracts
pnpm run verify:full
pnpm run lint
git diff --check
```

## P0 Web-To-Meshapp Parity Inventory

State slice: `ui-product-shell`

Source inventory is scoped to `web/` production-relevant source, assets, UX states, API adapters, and operator workflows. Generated dependencies and historical build output under `web/node_modules/` and `web/dist/` are not product source surfaces; they are explicitly deprecated as standalone artifacts and must not drive new product behavior.

| `web/` source | Classification | `meshapp/frontend` destination | State slice | Product disposition |
| --- | --- | --- | --- | --- |
| `web/index.html` | replace | `meshapp/frontend/app/page.tsx` loads `ProductApp` | `ui-product-shell` | Standalone Vite boot is replaced by the Next product route. |
| `web/src/main.tsx` | deprecate | `meshapp/frontend/app/page.tsx` | `ui-product-shell` | Vite-only mount is not production product entry. |
| `web/src/App.tsx` | port | `meshapp/frontend/src/App.tsx` and embedded `ProductApp` dashboard summaries | `ui-product-shell` | Use as a workflow inventory only. The production shell is `ProductApp`; high-value control-plane read models are embedded directly instead of exposed as a visible legacy tab. |
| `web/src/api.ts` | replace | `meshapp/frontend/src/api.ts` | `API route` | Do not wholesale-copy the web adapter; the meshapp adapter owns the pilot API default plus local operator identity headers. Port missing endpoints selectively. |
| `web/src/types.ts` | reuse | `meshapp/frontend/src/types.ts` | `contracts-and-schemas` | Keep as a generated legacy contract canary. The active product contract is `meshapp/frontend/src/types.ts`, which also carries product-only additions such as delivery context. |
| `web/src/index.css` | port | `meshapp/frontend/src/index.css`, `meshapp/frontend/src/mesh-tokens.css`, `src/product/product.css` | `ui-product-shell` | Treat as legacy-console CSS. Product-auth and account-shell styles stay separated to avoid global collisions. |
| `web/src/components/AmbientAsciiSignal.tsx` | reuse | `meshapp/frontend/src/components/AmbientAsciiSignal.tsx` | `ui-product-shell` | Preserved for legacy signal and overview surfaces. |
| `web/src/components/Inspector.tsx` | reuse | `meshapp/frontend/src/components/Inspector.tsx` | `dashboard read model` | Preserved as the run/evidence detail inspector. |
| `web/src/components/Toaster.tsx` | replace | `meshapp/frontend/src/components/Toaster.tsx` | `UI shell` | Use the meshapp copy; it is the active product/legacy feedback component. |
| `web/src/components/rca/*` | deprecate | `meshapp/frontend/src/components/rca/*` | `dashboard read model` | The web copies are not imported by `web/src/App.tsx`; meshapp owns the active RCA confidence, decision, event, candidate, and tool-call components. |
| `web/src/lib/asciiSignal.ts` | reuse | `meshapp/frontend/src/lib/asciiSignal.ts` | `dashboard read model` | Signal rendering helper remains shared. |
| `web/src/lib/format.ts` | reuse | `meshapp/frontend/src/lib/format.ts` | `dashboard read model` | Formatting helper remains shared. |
| `web/src/lib/labyrinth.ts` | reuse | `meshapp/frontend/src/lib/labyrinth.ts` | `dashboard read model` | Labyrinth view graph helper remains shared. |
| `web/src/lib/runGraph.ts` | reuse | `meshapp/frontend/src/lib/runGraph.ts` | `dashboard read model` | Run, evidence, RCA, Merkle, Kubernetes, and artifact graph helpers remain shared. |
| `web/src/*.test.tsx` and `web/src/lib/*.test.ts` | port | `meshapp/frontend/src/*.test.tsx`, `meshapp/frontend/src/lib/*.test.ts` | `tests-and-validation` | Legacy behavioral tests are carried into the product frontend. |
| `web/branding/logo.svg` | port | Product shell logo rendering in `src/product/ProductApp.tsx` | `ui-product-shell` | Brand signal is first-screen product shell identity. |
| `web/branding/mesh-tokens.css` | port | `meshapp/frontend/src/mesh-tokens.css` | `ui-product-shell` | Tokens are available to product and legacy surfaces. |
| `web/branding/README.md` | deprecate | Documentation only | `persisted artifact` | Branding notes are reference material, not a runtime product surface. |
| `web/branding/brand-guide.html` | deprecate | Documentation only | `persisted artifact` | Static brand guide is not a runtime product surface. |
| `web/e2e/operator-ui.spec.ts` | port | Root validation ladder and product-focused HTTP/unit tests | `tests-and-validation` | Browser intent is preserved by first-run signup/dashboard validation; full browser proof depends on local provider/server setup. |
| `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/playwright.config.ts` | deprecate | Root `package.json` and `meshapp/frontend` package config | `tests-and-validation` | Standalone web package remains only for legacy lint coverage until removed by a separate cleanup. |
| `web/dist/*` | deprecate | Fresh `meshapp/frontend` build output | `persisted artifact` | Historical Vite build output must not be shipped as product truth. |
| `web/node_modules/*`, `web/package-lock.json` | deprecate | Root `pnpm` workspace and lock discipline | `persisted artifact` | Node dependencies and npm lock state are not product source surfaces. |

Operator workflow coverage:

Cleanliness note: `web/package-lock.json` and `meshapp/frontend/package-lock.json` are tracked npm lockfiles. They conflict with the pnpm-only operating rule and should be removed in a dedicated cleanup slice, not as an incidental P0 inventory edit in a dirty worktree.

| Workflow in `web/src/App.tsx` | Classification | Product disposition |
| --- | --- | --- |
| Overview, incidents, fleet, runs, approvals, agents, integrations, evidence, audit, automation, Hermes, control-plane, simulator, trust, packets, roadmap, settings views | reuse | Important runtime, run, approval, evidence, connector, topology, memory, and kill-switch summaries are embedded in the product dashboard. Detailed legacy workflows remain source inventory until rebuilt as product-native panels. |
| Run launch and scenario execution | reuse | Mutating calls still go through `/api/runs` and existing Mesh authorization. Product shell summarizes admission state and does not bypass approval or run policy. |
| Approval queue and policy simulation | port | Product evaluations page renders approval queue items from `/api/operator/dashboard` and sends allowed steering commands to Mesh-owned `/api/runs/{run_id}/steer`. |
| Evidence graph, RCA, Merkle, export, darkharness packet | port | Product evaluations page exposes read-only proof drill-ins for evidence graph, RCA/scenario analysis, Merkle, timeline proof, and export package through Mesh proof endpoints. |
| Delivery context | replace | Not a `web/` source surface; the production app owns it through `meshapp/frontend/src/App.tsx`, `meshapp/frontend/src/api.ts`, and generated `meshapp/frontend/src/types.ts`. |
| Connector certification, readiness, trust ladder, kill switch, watcher, graph, memory read models | port | Summarized by product home/settings/capability cards and still fetched from Mesh-owned APIs. |
| First-run signup, login, team create, session recovery, OAuth, captcha, team switch, product settings | port | Implemented in `meshapp/frontend/src/product/*` and `/api/auth/*` plus `/api/operator/*`. |

## Product Workflow Authority Matrix

State slices: `Mesh runtime config`, `API route`, `UI shell`, `dashboard read model`

| Product surface | Runtime call path | Mutation posture | Authority boundary |
| --- | --- | --- | --- |
| Signup, login, logout, session recovery | `/api/auth/signup`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me` | Mutates `auth-identity` only | App session scopes dashboard/operator context; Mesh runtime stores remain authoritative. |
| OAuth start and callback | `/api/auth/oauth/{provider}/start`, `/api/auth/oauth/{provider}/callback` | Mutates OAuth state and session only | Missing provider config fails closed; provider callback errors redirect with explicit auth error. |
| Captcha | `/api/auth/config`, `/api/auth/signup` | Verification gate before local identity creation | Local bypass is development-only; non-local signup needs provider, site key, and secret. |
| Team create, update, member invite, and switch | `/api/auth/team`, `/api/auth/team/update`, `/api/auth/team/members`, `/api/auth/switch-team` | Mutates `team-tenancy` only | Team scope gates dashboard read model and operator roles; it does not rewrite historical Mesh records. |
| Dashboard cards | `/api/operator/dashboard` | Read-only aggregation | Mesh remains owner of readiness, approvals, evidence, run state, connectors, memory, and pilot packets. |
| Praxis MCP generator | `/api/operator/dashboard` `mesh.praxis` and `/api/operator/praxis/*` | Product-native workflow over `praxis.managed-dry-run-runtime.v1` | Home dashboard exposes source intake, generated tools, Akto evidence, certification, dry-run MCP readiness, revocation posture, and blocked managed-runtime deployment without granting authority. |
| Run launch | `/api/runs` | Product-native form, Mesh-authorized mutation | The product launch form requires an audit reason and posts to Mesh-owned `/api/runs`; role checks, ownership boundary, policy, and `mesh.run_admission.v1` still decide. |
| Approvals | `/api/operator/dashboard` `mesh.approvals`, `/api/runs/{run_id}/steer` | Product-native steering through Mesh authorization | Product UI can submit allowed queue commands, but Mesh role checks, command validation, and approval records decide. |
| Evidence, RCA, Merkle, timeline proof, export | `/api/runs/{run_id}/events`, `/scenario-analysis`, `/evidence-graph`, `/merkle`, `/timeline-proof`, `/export` | Read-only proof drill-in | Product UI can load proof packets and export packages; it cannot rewrite evidence or promote evidence into authority. |
| Readiness, connectors, topology, memory, kill switch, policy state | `/api/operator/dashboard` section read models | Navigable read-only product pages | Each runtime page binds to real Mesh read models and avoids legacy tab shortcuts; kill-switch mutation remains Mesh admin-only. |
| Settings | `/api/operator/settings` and `scripts/operator_config.py` | Mutates validated `mesh-settings-control` settings | UI and CLI share schema and persisted store; runtime-critical deployment config stays read-only. |
| Keys and provider posture | `/api/auth/config`, `/api/operator/dashboard` | Read-only deployment posture | Product UI names configured/unconfigured provider state and required env variable ownership without exposing raw secrets. |

Dashboard read-model contract:

- `/api/operator/dashboard` includes `mesh.read_model` metadata naming the product API source, `read_only` authority, and the degraded-section convention.
- Each Mesh-owned dashboard section is loaded through the existing control-plane coordinator. If a section call fails, that section returns `status=unavailable` plus an error instead of hiding the failure.
- Product cards render real section status/state when present. Empty cards state that the read model returned no payload and that the product surface is read-only until Mesh exposes data.
- Dashboard tile states are explicit: `ready`, `empty`, `degraded`, and `blocked` come from `/api/operator/dashboard` section payloads; `unauthorized` and `backend-unavailable` come from the top-level dashboard fetch state.
- Dashboard team scope controls product read access only. It does not rewrite or tenant-partition Mesh runtime run state, evidence, policy, readiness, approvals, or actuation.

Product-native workflow posture:

| Workflow | Product posture | Mesh call path | UI behavior |
| --- | --- | --- | --- |
| Launch | Native product mutation through Mesh authority | `/api/operator/dashboard` `mesh.runs`, plus `POST /api/runs` for launch | Product form requires scenario, modes, and audit reason, then shows admitted or blocked `mesh.run_admission.v1` response. |
| Approval | Native steering through Mesh authority | `/api/operator/dashboard` `mesh.approvals`, plus `/api/runs/{run_id}/steer` | Product approval queue renders allowed commands and requires a reason before submitting to Mesh. |
| Evidence | Read-only proof drill-in | `/api/runs/{run_id}/events`, `/scenario-analysis`, `/evidence-graph`, `/merkle`, `/timeline-proof`, `/export` | Product proof views inspect evidence, RCA trace, Merkle, timeline, and export packages without editing Mesh records. |
| Readiness | Product-native read page | `/api/readiness` through `/api/operator/dashboard` | Readiness page shows blockers and degraded reasons from real Mesh read models. |
| Connectors | Product-native read page | `/api/connectors/certification` through `/api/operator/dashboard` | Connectors page filters certification state, domain, credential/authority posture, and blocker badges. |
| Topology | Product-native read page | `/api/operator/dashboard` `mesh.readiness.orchestration_topology` and `mesh.graph` | Topology page prefers orchestration topology and falls back to graph status. |
| Memory projection | Product-native read page | `/api/operator/dashboard` `mesh.memory.active` and `mesh.memory.graph` | Memory page shows active memory and projection graph as Mesh-owned read models. |
| Kill switch | Product-native read page | `/api/operator/dashboard` `mesh.kill_switch` | Kill switch page shows emergency control state; admin mutation stays behind Mesh-owned `/api/kill-switch`. |
| Settings | Native scoped mutation | `/api/operator/settings` and `scripts/operator_config.py` | UI and CLI share the validated settings slice; runtime-critical deployment config remains read-only. |
| Team tenancy | Native scoped mutation | `/api/auth/team/update`, `/api/auth/team/members`, `/api/auth/switch-team` | Product UI can update team display metadata and member roles; only owner/admin role mappings can mutate team state. |

Praxis product posture:

- State slice: `meshapp.praxis-product-home.v1` renders Praxis on the signed-in Home dashboard and as a dedicated product-native `Praxis` view.
- State slice: `praxis.managed-dry-run-runtime.v1` is exposed through `/api/operator/dashboard` under `mesh.praxis` and product-native `/api/operator/praxis/*` controls.
- The product path binds source bundle -> generated MCP contract -> Akto evidence -> Mesh certification binding -> proof packet -> dry-run MCP readiness.
- Docker Dynamic MCP is modeled as a session-only dry-run bridge for catalog discovery and gateway-managed credentials; dynamic servers are not profile-persisted, `code-mode` stays blocked, and Docker does not grant production runtime authority.
- `Start dry-run MCP endpoint` and `Revoke generated connector` are visible as bounded pilot controls. Managed pilot runtime deployment stays blocked until production-like proof, live target ownership, and credential rotation evidence exist.
- The UI can show certified read-only tools and denied mutation tools; it cannot promote advisory Akto evidence, ACP permission prompts, or generated MCP candidates into production authority.

Evidence, approval, and RCA trace posture:

- The product evaluations view renders a read-only Signal -> Evidence -> Policy -> Decision trace from `/api/operator/dashboard`.
- Each trace step names the Mesh-owned authority behind the state: run state, evidence artifacts, policy/approvals, and decision record.
- Detailed RCA, evidence graph, approval steering, export, and audit actions are surfaced through product-native panels or CLI paths; no visible legacy control-plane tab is used as a product shortcut.
- The product trace and proof drill-ins are navigational context only. They cannot approve, deny, execute, promote, or rewrite Mesh evidence.

## Deployment And Ingress Matrix

State slices: `auth state`, `API route`, `persisted artifact`

| Environment | Required auth posture | Required captcha/OAuth posture | Ingress notes | Result when missing |
| --- | --- | --- | --- | --- |
| Local development | `MESH_AUTH_MODE=app_session` with `MESH_CAPTCHA_DEV_BYPASS=1` allowed | OAuth optional; captcha bypass accepts only `dev-captcha-ok` | Frontend points at `NEXT_PUBLIC_MESH_API_URL=http://127.0.0.1:8787` | API-down state renders a clear backend banner. |
| Local provider smoke | `MESH_AUTH_MODE=app_session` | Real hCaptcha/Turnstile/reCAPTCHA keys and provider redirect URLs for `127.0.0.1:8787` | Use ignored `.env.local` only | Mark blocked when local provider console/env is missing. |
| Staging | `MESH_AUTH_MODE=proxy_header` behind trusted ingress or app-session with secure deployment secrets | Captcha required for password signup; OAuth secrets must be injected by deployment config | TLS ingress owns cookie transport and proxy identity headers | Signup/OAuth fail closed when provider credentials are incomplete. |
| Pilot | Proxy-header identity required unless app-session has production secret management and provider proofs | Captcha and OAuth provider console setup are required before external signup | Audit, approval, readiness, evidence, and run state stay Mesh-owned | No production authority from advisory Akto or ACP evidence. |

P8 deployment fail-closed checks:

- `proxy_header` remains the default production ingress posture. `app_session` is allowed outside local only when the deployment owns secure session secret handling and provider evidence.
- Non-local `app_session` password signup fails configuration when captcha is disabled or missing either the site key or secret key.
- OAuth start routes fail closed with `503` until provider client ID, client secret, and redirect URI are all configured.
- A complete captcha/OAuth environment proves only deployment configuration shape. Real provider proof still requires ignored local environment values plus provider-console redirect/domain evidence.
- Mesh remains the authority for policy, approvals, readiness, evidence, run state, and actuation; ingress/auth configuration only establishes operator identity for product access.

## Browser E2E And Contract Drift Guard

State slices: `tests-and-validation`, `contracts-and-schemas`

`pnpm run test:product:e2e` starts an isolated app-session Mesh API and the Next product shell, then drives clean-browser paths for first-run signup, solo dashboard, team dashboard, team profile update, member invite, provider posture, connector filtering, settings-backed launch defaults, run admission, logout, expired-session cookie clearing, login recovery, and `/api/operator/dashboard`. The active Playwright artifacts are `scripts/operator_product_e2e.py`, `meshapp/frontend/playwright.config.ts`, and `meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts`.

`python3 scripts/operator_auth_provider_smoke.py` reads ignored `.env.local` files, verifies they are ignored/untracked, checks OAuth local callback shape, checks optional `MESH_AUTH_PRODUCT_REDIRECT_URL` trust, checks hCaptcha env readiness, scans tracked files for the exact local secret values, and writes a redacted readiness artifact to `.mesh-runtime-state/operator-auth-proof/latest.json`. It does not print or persist raw OAuth or captcha values. Its expected status before real external login/challenge completion is `blocked_provider_console_unverified`.

`pnpm run test:auth-provider:smoke` is the pnpm entrypoint for that local provider smoke. It is intentionally separate from `pnpm run lint` because clean CI or fresh clones may not have the ignored local provider files. When local provider env exists, run it before browser/product gates and bind the result to `.mesh-runtime-state/operator-auth-proof/latest.json`.

`pnpm run test:auth-provider:live` requires `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` with redacted clean-browser evidence for Google OAuth, GitHub OAuth, and hCaptcha. The live proof schema is `mesh.operator_auth_provider_live_proof.v1`; it must name `state_slice=auth-provider-proof.v1`, `clean_browser_session=true`, provider callback paths, session establishment booleans, hCaptcha challenge/token verification booleans, and `raw_secret_material_present=false`. The verifier rejects raw token, cookie, password, authorization, or client-secret fields by key name.

The runtime identity store also records redacted `auth_events` under `auth-provider-proof.v1`. Those events produce `mesh.operator_auth_runtime_evidence.v1` inside `runtime_auth_evidence`, proving that Google OAuth, GitHub OAuth, and hCaptcha-backed signup established sessions without storing provider tokens, captcha tokens, cookies, OAuth client secrets, or raw passwords. A complete live proof now needs both the clean-browser proof file and matching runtime auth evidence.

`pnpm run auth-provider:live-template` prints the redacted JSON shape for that ignored live proof artifact. The template is intentionally fail-closed: booleans are `false` until the clean browser run actually completes.

`pnpm run auth-provider:live-capture` opens a fresh Playwright browser profile for the operator and polls redacted Mesh `auth_events` until hCaptcha-backed email signup, Google OAuth, and GitHub OAuth have all established sessions after the capture start time. It writes `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` only when complete unless `--write-partial` is supplied. The capture proof is derived from event ids and timestamps only; it does not read or store browser cookies, OAuth codes, provider tokens, captcha responses, passwords, or client secrets.

`pnpm run auth-provider:live-stack` runs the same capture with `--manage-local-stack`: it starts the Mesh API and Next product shell from ignored `.env.local`, points OAuth callbacks back to the product URL, uses `.mesh-runtime-state/operator-identity.json` so `pnpm run test:auth-provider:live` validates the same runtime evidence, and redacts known local secret values from captured process output. Managed mode now fails closed when the API or product ports are already occupied; use `--reuse-local-stack` only when intentionally binding proof to already-running local endpoints.

`pnpm run auth-provider:reuse-stack` runs the live capture against already-running loopback Mesh API and product shell endpoints with explicit `stack_mode=reused_local_stack` provenance. It never claims ownership of those processes and still requires the same clean-browser Google, GitHub, and hCaptcha completion before writing `live-provider-proof.json`.

`pnpm run auth-provider:live-attempt` is the bounded managed-stack capture entrypoint. It opens the clean browser, prints operator steps immediately, waits up to five minutes, and writes `.mesh-runtime-state/operator-auth-proof/live-capture-attempt.json` even when provider completion is still missing. That attempt artifact is redacted, records `stack_mode` plus `managed_processes_owned`, and records missing proof components without replacing `live-provider-proof.json`. This attempt command exits zero for a clean blocked attempt because the blocked provider completion is external evidence; `pnpm run auth-provider:live-stack`, `pnpm run auth-provider:live-capture`, and `pnpm run test:auth-provider:live` still fail until the real provider proof is complete.

`pnpm run auth-provider:reuse-attempt` is the same bounded capture attempt for already-running loopback endpoints. It records `managed_processes_owned=false` and is the default local path when ports 8787 and 3000 are intentionally occupied by an operator-run stack.

`pnpm run auth-provider:live-preflight` writes `.mesh-runtime-state/operator-auth-proof/live-preflight.json` and exits zero only when local callback URLs, product redirect, hCaptcha env readiness, identity path binding, and redacted preflight posture are ready for the clean-browser run.

`pnpm run auth-provider:live-stack-smoke` starts the managed local Mesh API and Next product shell, proves `/api/auth/config` and the product shell are reachable with the ignored provider env, writes `.mesh-runtime-state/operator-auth-proof/live-stack-smoke.json`, then shuts the stack down. If an API or product server is already listening, the managed smoke fails closed instead of silently reusing it; rerun with `python3 scripts/operator_auth_live_provider_capture.py --stack-smoke-only --reuse-local-stack` to bind explicit reused-stack provenance. This artifact narrows P0 to external browser/provider completion only; it does not prove Google, GitHub, or hCaptcha completion.

`pnpm run auth-provider:reuse-stack-smoke` is the pnpm entrypoint for that reused-stack smoke proof. It verifies the already-running loopback API and product shell, writes `live-stack-smoke.json`, and records `managed_processes_owned=false`.

`pnpm run auth-provider:checkpoint` writes `.mesh-runtime-state/operator-auth-proof/checkpoint.json`, binding provider readiness, live preflight, explicit local stack smoke, latest capture-attempt status, capture-attempt blockers, source artifact `generated_at` values, and live-provider proof status into one redacted P0 checkpoint. Its local evidence can be complete while the checkpoint remains `blocked_external_provider_proof`; only the live clean-browser proof can move it to `complete`. The checkpoint's `next_required_command` follows the current stack provenance, so reused-stack evidence points back to `pnpm run auth-provider:reuse-stack`.

The live-stack capture fails closed before launching the browser when Google or GitHub redirect URLs do not exactly match the local API callback URL, when `MESH_AUTH_PRODUCT_REDIRECT_URL` does not match the product URL, when hCaptcha provider/site/secret values are incomplete, or when managed-mode local ports are already occupied. The preflight schema is `mesh.operator_auth_live_capture_preflight.v1` and reports only URL shape, readiness booleans, and blockers.

`pnpm run verify:operator-goal` emits `mesh.operator_product_goal_audit.v1`, a machine-readable P0-P6 audit. The current expected status is `blocked_external_provider_proof` when all local product evidence is present but `live_provider_proof_missing` remains. It exits non-zero for local evidence gaps and only requires full completion when invoked with `python3 scripts/operator_product_goal_audit.py --require-complete`.

The goal audit now treats `live-preflight.json`, `live-stack-smoke.json`, `checkpoint.json`, and `live-capture-attempt.json` as local P0 evidence. A missing or locally blocked preflight, stack smoke, checkpoint, capture attempt, ambiguous stack provenance, stale checkpoint/capture-attempt binding, stale checkpoint evidence timestamp binding, stale checkpoint `next_required_command`, or checkpoint completion state that disagrees with provider readiness is `blocked_local_evidence`; ready local artifacts with explicit `managed_local_stack` or `reused_local_stack` provenance and missing live provider proof remain `blocked_external_provider_proof`.

`scripts/generate_operator_product_contracts.py --check` verifies the generated product schema and TypeScript contract surface. The source contract is `shared/mesh_runtime/operator_product_contracts.py`; generated artifacts are `shared/mesh_runtime/schemas/operator-product.schema.json` and `meshapp/frontend/src/product/types.ts`. The `/api/operator/dashboard` schema requires the Mesh section set consumed by the product home surface: health, read model, readiness, connectors, approvals, kill switch, pilot go/no-go, Praxis, trust ladder, watchers, graph, runs, and memory. `tests/test_operator_product_contracts.py` exercises `/api/auth/config`, `/api/auth/signup`, `/api/auth/team`, `/api/operator/dashboard`, and `/api/operator/settings` against the schema before product UI can drift.

## Evidence Binder

State slice: `docs-and-operator-guide`

Changed product state slices for this buildout are `ui-product-shell`, `auth-identity`, `auth-provider-proof.v1`, `team-tenancy`, `mesh-dashboard-read-model`, `mesh-settings-control`, `API route`, `tests-and-validation`, `contracts-and-schemas`, and `persisted artifact`.

Files that form the proof path:

- `docs/operator-product-app.md`
- `shared/mesh_runtime/operator_identity.py`
- `control_plane_server.py`
- `scripts/operator_config.py`
- `scripts/operator_auth_provider_smoke.py`
- `scripts/operator_product_goal_audit.py`
- `scripts/generate_operator_product_contracts.py`
- `scripts/operator_product_e2e.py`
- `scripts/verify_operator_product_buildout.py`
- `shared/mesh_runtime/operator_product_contracts.py`
- `shared/mesh_runtime/schemas/operator-product.schema.json`
- `tests/test_operator_identity.py`
- `tests/test_operator_auth_provider_smoke.py`
- `tests/test_operator_product_goal_audit.py`
- `tests/test_operator_auth_http.py`
- `tests/test_operator_product_contracts.py`
- `meshapp/frontend/playwright.config.ts`
- `meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts`
- `meshapp/frontend/src/product/ProductApp.tsx`
- `meshapp/frontend/src/product/api.ts`
- `meshapp/frontend/src/product/types.ts`
- `meshapp/frontend/src/product/product.css`
- `package.json`
- `.mesh-runtime-state/operator-auth-proof/latest.json` (local ignored artifact, generated on demand)
- `.mesh-runtime-state/operator-auth-proof/live-preflight.json` (local ignored artifact, generated on demand)
- `.mesh-runtime-state/operator-auth-proof/live-stack-smoke.json` (local ignored artifact, generated on demand)
- `.mesh-runtime-state/operator-auth-proof/checkpoint.json` (local ignored artifact, generated on demand)
- `.mesh-runtime-state/operator-auth-proof/live-capture-attempt.json` (local ignored artifact, generated on demand)
- `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` (local ignored artifact, required only for final live provider proof)

Required validation ladder:

```bash
pnpm run lint:fast
pnpm run test:auth-provider:smoke
pnpm run auth-provider:live-template
pnpm run auth-provider:live-preflight
pnpm run auth-provider:live-stack-smoke
pnpm run auth-provider:reuse-stack-smoke
pnpm run auth-provider:checkpoint
pnpm run auth-provider:live-attempt
pnpm run auth-provider:reuse-attempt
pnpm run auth-provider:live-capture
pnpm run auth-provider:live-stack
pnpm run auth-provider:reuse-stack
pnpm run verify:operator-goal
# Final P0 only, after live clean-browser provider completion:
pnpm run test:auth-provider:live
pnpm run test:focused
pnpm run test:product:e2e
pnpm run verify:contracts
pnpm run verify:full
pnpm run lint
git diff --check
```

Validation transcript from this buildout:

| Command | Result |
| --- | --- |
| `uv run --with-editable . python scripts/verify_operator_product_buildout.py` | Passed. |
| `PYTHONPATH=. uv run --with-editable . python -m unittest tests.test_operator_identity tests.test_operator_auth_http` | Passed 12 tests. |
| `python3 scripts/operator_auth_provider_smoke.py` | Passed redacted readiness generation with `blocked_provider_console_unverified`, no tracked env files, no tracked secret hits, local OAuth callback matches, and hCaptcha env readiness. |
| `pnpm run test:auth-provider:smoke` | Passes the same redacted provider smoke through the pnpm gate surface; current blocker is `live_provider_proof_missing`. When a live proof file is present, it also requires matching runtime `auth_events`. |
| `pnpm run auth-provider:live-template` | Prints the redacted fail-closed live proof template. |
| `pnpm run auth-provider:live-preflight` | Passed local redirect/hCaptcha/identity-path preflight and wrote the ignored redacted preflight artifact. |
| `pnpm run auth-provider:reuse-stack-smoke` | Verified already-running local Mesh API and product shell with explicit `reused_local_stack` provenance, wrote the ignored redacted stack-smoke artifact, and did not claim process ownership. |
| `pnpm run auth-provider:checkpoint` | Writes the ignored redacted P0 checkpoint with local evidence complete, source artifact timestamp bindings, explicit reused-stack provenance, latest capture-attempt blockers, and `live_provider_proof_missing` as the remaining external blocker. |
| `pnpm run auth-provider:reuse-attempt --headless --timeout-seconds 5 --poll-interval 1` | Opened the clean reused-stack browser and wrote the ignored redacted capture-attempt artifact; current attempt remains blocked because no provider auth events were completed. |
| `pnpm run auth-provider:live-stack` | Starts the local Mesh API, product shell, and clean-browser live capture together when ports are free; fails closed when an existing local stack is already bound to those ports. |
| `pnpm run verify:operator-goal` | Reports `blocked_external_provider_proof` with only `live_provider_proof_missing` as the known external blocker when local P0-P6 evidence is intact. |
| `pnpm run test:auth-provider:live` | Blocked as expected until `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` records clean-browser Google, GitHub, and hCaptcha completion. |
| `pnpm run lint:fast` | Passed contracts, operator verifier, Praxis verifier, and Python compile checks. |
| `pnpm run test:focused` | Passed 207 Python tests and 35 frontend tests. |
| `pnpm run test:product:e2e` | Passed 7 Playwright tests covering first-run team dashboard, settings-backed launch defaults, member invite, provider posture, connector filtering, console workflow handoff, Praxis P10 proof flow, solo dashboard, logout cookie clearing, and expired-session recovery. |
| `pnpm run verify:contracts` | Passed control-plane contract checks, Praxis verifier, and operator product verifier. |
| `pnpm run verify:full` | Passed contracts, focused tests, Praxis proof packet verifier, web lint, and meshapp frontend lint. |
| `pnpm run lint` | Passed the heavy root gate. |
| `git diff --check` | Clean. |

Known proof limits:

- Browser provider smoke is blocked until provider-console redirects/domain allowlists are verified and a clean browser completes Google, GitHub, and hCaptcha flows. Ignored local OAuth/hCaptcha values are present, but raw secrets stay out of committed proof artifacts.
- Product teams scope identity, roles, dashboard, and settings. They are not tenant isolation for first-party Mesh runtime persistence.
- ACP remains a supervised session surface and cannot grant runtime authority.
- Akto evidence is advisory security evidence and cannot grant production authority.
