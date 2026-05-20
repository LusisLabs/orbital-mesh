# Operator Product Overnight Milestone

State slice: `operator-product-tmux-whip-milestone-automation`

HTML context: `docs/plans/operator-product-overnight-buildout-plan.html`

Canonical purpose: this Markdown file is the milestone template. The tmux whip launcher copies it into each run directory as the active burndown file. The automator must update the run-local copy after every concrete action.

## Operating Contract

- Plan first, act after.
- Measure twice, cut once policy.
- Every mutation must name the state slice it touches.
- Use `pnpm`, not `npm`.
- Do not run `tail`.
- Keep `pnpm run lint` as the heavy root gate.
- Use `pnpm run lint:fast`, `pnpm run test:focused`, `pnpm run verify:contracts`, and `pnpm run verify:full` as the normal ladder.
- Keep the codebase clean: no tmp files, no dead code, no dead files, no unnecessary folders.
- Do not use no-mistakes.
- Preserve unrelated dirty worktree changes.
- Do not stage, commit, push, or open PRs unless explicitly instructed by the human.
- Do not write raw OAuth or captcha secrets into source, docs, logs, or committed artifacts.
- Mesh remains the authority for policy, approvals, readiness, evidence, run state, and actuation.

## P0 Scope Lock

State slice: `ui-product-shell`

- Treat `web/` as the complete source inventory.
- Treat `meshapp/frontend` as the production product destination.
- Inventory every production-relevant route, component, API adapter, asset, UX state, and operator workflow in `web/`.
- Classify each inventory item as `port`, `reuse`, `replace`, or `deprecate`.
- Do not add new product UI before the parity inventory exists.
- No production-relevant `web/` surface can remain unaccounted for.
- Deprecated or demo-only surfaces must be documented explicitly.

## Auth Field Notes

State slices: `auth-identity`, `API route`, `persisted artifact`

- Dummy-value inspection already showed `hcaptcha` config is accepted.
- Dummy-value inspection already showed Google OAuth start returns `200`.
- Dummy-value inspection already showed GitHub OAuth start returns `200`.
- Real provider proof requires ignored local environment values and exact provider console redirects.
- If `127.0.0.1:8787/api/auth/...` returns `ERR_CONNECTION_REFUSED`, the Mesh API is not running or the frontend is pointed at the wrong `NEXT_PUBLIC_MESH_API_URL`.
- Use an ignored `.env.local` only. Do not commit it.
- Provider callback URLs for local smoke:
  - `http://127.0.0.1:8787/api/auth/oauth/google/callback`
  - `http://127.0.0.1:8787/api/auth/oauth/github/callback`
- hCaptcha local smoke requires `127.0.0.1` and `localhost` allowed in the hCaptcha site configuration.
- If real credentials were pasted into chat or logs, rotate them before staging or production use.

## Repeated Error Rule

When the same error appears twice:

1. Stop editing.
2. Record the exact command and error in Work Log.
3. Research 3-5 plausible fixes.
4. Choose the smallest fix consistent with Mesh authority boundaries.
5. Implement one fix.
6. Re-run the narrowest trustworthy validation.

## Status Vocabulary

Use only these values in the burndown table:

- `pending`
- `in_progress`
- `blocked`
- `done`
- `deferred`

## Burndown

| ID | Status | State slice | Deliverable | Done criteria | Validation |
| --- | --- | --- | --- | --- | --- |
| P0 | pending | `ui-product-shell`, `dashboard read model`, `API route`, `persisted artifact` | Web-to-meshapp parity lock | `web/` routes, components, adapters, assets, UX states, and operator workflows are inventoried and classified as `port`, `reuse`, `replace`, or `deprecate`. | `git diff --check` plus inventory review |
| P1 | pending | `auth-identity`, `API route`, `UI shell` | Local boot and auth reliability | API-down state is clear. API-up signup, team create, logout, login, and dashboard path work without raw browser errors. | `pnpm run lint:fast` plus focused auth tests |
| P2 | pending | `auth-identity`, `API route`, `schema` | Production OAuth and captcha proof | Google/GitHub start routes produce valid authorize URLs, callback failures are clear, and real hCaptcha is smoke-tested or blocked by missing local env/provider console setup. | Auth config curl checks plus browser smoke |
| P3 | pending | `team state`, `user profile state`, `API route` | Team tenancy and access checks | Users cannot access another team dashboard. Expired session recovery and role mapping are tested. | Focused auth/team tests |
| P4 | pending | `dashboard read model`, `contracts-and-schemas` | Dashboard read model completeness | Product cards load from real Mesh APIs/contracts or show explicit read-only/degraded reasons. | `pnpm run verify:contracts` |
| P5 | pending | `Mesh runtime config`, `API route`, `UI shell` | Product-native operator workflows | Launch, approval, evidence, readiness, connector, and settings flows call existing Mesh APIs or show read-only reasons. | Focused API/UI tests |
| P6 | pending | `mesh-settings-control`, `CLI config`, `persisted artifact` | UI and CLI settings parity | UI and `scripts/operator_config.py` mutate the same validated settings slice with audit reasons. | CLI validation plus focused tests |
| P7 | pending | `dashboard read model`, `UI shell` | Evidence, approvals, and RCA polish | Operators can trace signal to evidence to policy to decision without confusing UI authority with Mesh authority. | `pnpm --dir meshapp/frontend run lint` |
| P8 | pending | `auth state`, `API route`, `persisted artifact` | Deployment and ingress hardening | Local, staging, and pilot env matrices are documented. Missing provider/captcha credentials fail closed. | Docs review plus auth tests |
| P9 | pending | `tests-and-validation`, `contracts-and-schemas` | Browser e2e and contract drift guard | One command exercises first-run signup through dashboard. Contract drift breaks validation before stale UI ships. | `pnpm run verify:full` |
| Pn | pending | `docs-and-operator-guide`, `persisted artifact` | Launch package and evidence binder | Final report lists changed state slices, files, validations, browser smoke, blockers, risks, and exact next-operator commands. | `pnpm run lint` and final artifact review |

## Active Run Checklist

- [ ] Run directory created under `.mesh-runtime-state/operator-product-tmux-whip/`.
- [ ] `manifest.json` exists.
- [ ] `automator-prompt.md` exists.
- [ ] Run-local `milestone.md` exists.
- [ ] Automator read `AGENTS.md`, `architecture.md`, `docs/repo-truth-audit.md`, `docs/future-agent-operating-guide.md`, package scripts, `web/`, `meshapp/frontend`, the HTML plan, and this milestone before editing.
- [ ] Work Log updated after each concrete action.
- [ ] Blockers recorded instead of hidden.
- [ ] Final report written before the tmux session exits.

## Work Log

Append newest entries at the bottom.

<!-- worklog -->
