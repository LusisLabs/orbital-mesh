# Praxis Agent-Tool Mesh Overnight Milestone

State slice: `praxis-tmux-whip-milestone-automation`

HTML context: `docs/plans/praxis-agent-tool-mesh-overnight-plan.html`

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
- Do not stage unrelated dirty worktree changes.
- Generated MCP tools are candidates until Mesh connector certification admits their exact scopes.
- Akto is a security evidence lane, not an authority lane.
- ACP is an operator/session surface, not tool execution authority.
- Mesh owns policy, certification, approval, audit, proof continuity, bounded execution, and revocation.

## P0 Scope Lock

State slice: `praxis.product-boundary.v1`

- Praxis generates candidate MCP contracts and tool-server manifests.
- Akto supplies advisory security evidence; missing or critical evidence can block certification but cannot grant policy authority.
- ACP supplies supervised operator-session artifacts; ACP permission prompts become Mesh approval records and cannot grant runtime authority directly.
- MCP exposes only the exact connector scopes admitted by Mesh connector certification.
- Mesh owns connector policy, certification, approval, audit, bounded execution, proof continuity, readiness posture, and revocation.
- Managed hosting, marketplace distribution, live DAST triggers, and pilot runtime authority are out of scope until the P8 proof packet path exists.

## Repeated Error Rule

When the same error appears twice:

1. Stop editing.
2. Record the exact command and error in Work Log.
3. Research 3-5 plausible fixes.
4. Choose the smallest fix consistent with repo authority boundaries.
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
| P0 | pending | `praxis.product-boundary.v1` | Scope lock and doctrine | Plan states Praxis generates, Akto scans, ACP supervises, MCP exposes, Mesh certifies and revokes. No replacement-control-plane language. | `git diff --check` |
| P1 | pending | `praxis.contracts.v1` | Schema-only contracts | Generation request, source bundle, generated MCP contract, Akto evidence, ACP session, and certification binding schemas fail closed. | `pnpm run verify:contracts` |
| P2 | pending | `praxis.source-ingest.v1` | Source intake fixture | OpenAPI, Postman JSON, SOP Markdown, and redacted traffic refs normalize into cited source packets. | `pnpm run lint:fast` plus focused source tests |
| P3 | pending | `praxis.generated-mcp-contract.v1` | MCP candidate generator | Candidate tool manifest includes endpoint, args schema, auth scope, mutation class, workflow hints, test plan, and blockers. | Golden fixture tests |
| P4 | pending | `praxis.akto-security-evidence.v1` | Akto evidence importer | Akto fixture findings import into normalized endpoint/security evidence without live DAST by default. | Importer fixture tests |
| P5 | pending | `mesh.connector-certification.praxis.v1` | Certification bridge | Generated tools plus Akto evidence downgrade, block, or admit connector scopes through Mesh certification semantics. | `pnpm run verify:contracts` plus readiness tests |
| P6 | pending | `praxis.acp-session.v1` | ACP supervised proposal session | ACP permission prompts map to Mesh operator decisions and cannot grant runtime authority directly. | Fake ACP client tests |
| P7 | pending | `meshapp.praxis-operator-ui.v1` | Operator UI review panel | Operator can inspect source bundle, generated tools, Akto findings, certification state, approvals, and MCP readiness. | `pnpm --dir meshapp/frontend run lint` |
| P8 | pending | `praxis.e2e-proof-packet.v1` | Vertical proof packet | Source to generated contract to security evidence to certification to MCP readiness to operator decision is bound in one export. | `pnpm run verify:full` plus proof verifier when present |
| P9 | pending | `praxis.security-readiness.v1` | Security docs and readiness | Threat model, data classification, procurement/security package, and credential boundaries cover Praxis/Akto/ACP/MCP. | Security verifier once added |
| P10 | pending | `praxis.pilot-runtime.v1` | Bounded pilot runtime | Generated MCP server runs in bounded runtime with revocation, credential boundary checks, audit refs, and deactivate controls. | Production-like proof packet plus `pnpm run lint` |
| Pn | pending | `praxis.expansion-roadmap.v1` | Expansion backlog | Marketplace templates, private cloud, continuous scans, tenant isolation, pricing, and packaging are separated from overnight MVP. | Separate milestone gates |

## Active Run Checklist

- [ ] Run directory created under `.mesh-runtime-state/praxis-tmux-whip/`.
- [ ] `manifest.json` exists.
- [ ] `automator-prompt.md` exists.
- [ ] Run-local `milestone.md` exists.
- [ ] Automator read both HTML and Markdown before editing.
- [ ] Work Log updated after each concrete action.
- [ ] Blockers recorded instead of hidden.
- [ ] Final report written before the tmux session exits.

## Work Log

Append newest entries at the bottom.

<!-- worklog -->
