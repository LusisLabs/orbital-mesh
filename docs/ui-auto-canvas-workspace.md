# Mesh Agentic Console

## Scope

The web UI is a self-hosted Mesh agent control console for monitoring, evidence review, approval, agent interaction, integration readiness, and audit continuity. It is Mesh-native, not a clone of VS Code, Cursor, Codex, or Claude Code.

The interface uses the visual language of modern terminal and editor-based agent tools: dense dark surfaces, project/session rails, run-thread workspaces, review/context drawers, transcript blocks, tool-call rows, and a terminal-style runtime strip. The current static color-role source is the Islands Dark VS Code theme: deep canvas, slightly lifted surfaces, directional glass borders, pill controls, subdued status chrome, and warm diagnostic accents.

The default page is `Overview`. Topology and graph canvases are secondary investigation tools under run detail.

## Product Model

- `Overview`: active Mesh command center for the current run thread, launch/review actions, incidents, agents, integrations, evidence, watchers, and audit continuity.
- `Runs`: run-thread list plus detail tabs for `Timeline`, `Evidence`, `Approvals`, `Actions`, `Audit`, `Agents`, and `Topology`.
- `Hermes`: default connected agent surface for blocker explanation, run-scoped chat, proposed action review, and evidence context.
- `Agents`: connected and connectable workers. Hermes is primary by default; Goose, Codex, Claude Code, OpenClaw, Evo, LatentMAS, Deep Agents, and custom HTTP agents are modeled as bounded proposal workers.
- `Integrations`: modular connection catalog grouped by Web3, Web2 Production, Development, and Operations.
- `Control Plane`: secondary runtime diagnostics for readiness, storage paths, API stream state, connector inventory, and low-level health.

## Connector States

Connection surfaces use these states:

- `ready`: available and operational.
- `degraded`: configured but warning or partial failure exists.
- `config-only`: known to Mesh but not live-ready.
- `unsafe`: present but blocked by production safety constraints.
- `stub`: explicitly unfinished production adapter.
- `disconnected`: not configured.

Raw secrets must stay outside run artifacts. Events may reference connection ids, scopes, readiness state, and audit evidence, but not OAuth tokens, API keys, kubeconfigs, SSH keys, or service-account credentials.

## Agent Boundary

Agents can propose investigation summaries, root-cause hypotheses, patch plans, reviews, validation suggestions, and benchmark advice.

Mesh owns:

- policy gates
- evaluation
- approval
- execution
- audit records
- Merkle proof continuity
- action allowlists

Hermes remains the default operator interaction agent, but it does not replace Mesh. Hermes explains and proposes; Mesh decides and records.

## Integration Domains

Initial domain packs:

- `Web3`: Reth/geth nodes, validators, Kurtosis/devnets, RPC health, peer/sync/finality telemetry.
- `Web2 Production`: Kubernetes, ArgoCD, Prometheus/OpenTelemetry, logs, incident systems.
- `Development`: GitHub/GitLab, PRs/issues, CI, repos, test/build gates, Promptfoo.
- `Operations`: PagerDuty/Opsgenie, Linear/Jira, cloud providers, audit sinks.

OAuth/OIDC is preferred where providers support it. API keys and service accounts are reserved for providers that do not expose an appropriate OAuth flow.

## Canvas Placement

React Flow canvases are available only inside `Runs > Detail > Topology`.

Canvas modes:

- `Overview`: operation map from run flow and evidence boundaries.
- `Run Flow`: ordered event graph for the selected run.
- `Evidence`: scenario-analysis evidence/subdecision graph.
- `Signal`: Reth/Kurtosis or Kubernetes signal topology.
- `Merkle`: Merkle root, snapshot, proof steps, and selected leaf.
- `Artifacts`: input, readiness, trigger, decision, execution, and feedback artifacts.

Canvas node clicks keep the context drawer evidence-first: Merkle nodes open audit context, signal nodes open evidence context, artifact nodes route to the matching inspector tab, and run nodes keep event selection synchronized.

## Visual System

- Static dark tokens are adapted from Islands Dark workbench colors. Mesh does not install the VS Code extension, load Custom UI Style, or run upstream installer scripts at runtime.
- Codicons are used for editor and agent-console semantics where they fit. Existing lucide icons remain for gaps.
- Surfaces keep Mesh's 8px radius cap while using Islands-style floating spacing, glass borders, focused-list gradients, pill status controls, and compact editor-console density.
- The bottom runtime strip summarizes local API target, selected run, SSE connection state, integration readiness, and agent readiness.
- The left workstream rail and bottom runtime strip are wired controls. They route directly to run threads, review queue, Hermes, evidence, agents, integrations, and control-plane diagnostics.
- The right drawer is a review/context panel for evidence, policy, execution, agents, Merkle audit, code, and research output.

## Current API Use

The first implementation is UI-first and uses existing routes:

- `GET /api/runs`, `GET /api/runs/{run_id}`, `GET /api/stream/runs/{run_id}`
- `GET /api/runs/{run_id}/scenario-analysis`
- `GET /api/runs/{run_id}/evidence-graph`
- `GET /api/runs/{run_id}/memory-crystallization`
- `GET /api/runs/{run_id}/agent-tasks`
- `GET /api/watchers`
- `POST /api/runs`
- `POST /api/runs/{run_id}/steer`
- `GET /api/readiness`, `GET /api/health`, `GET /api/research-sessions`, `GET /api/research-corpus`, `GET /api/vault/tree`

Future backend registry routes should add dynamic agents, integrations, domains, and connection records while preserving these existing routes.

## Verification Gates

Run from the repository root:

```bash
npm --prefix web run test
npm --prefix web run lint
npm --prefix web run build
npm --prefix web run test:e2e
```

The E2E suite verifies:

- `Overview` is default and not canvas-centered.
- `Control Plane` is secondary and reachable.
- `Hermes` opens and renders readiness/chat surfaces.
- `Agents` lists default and available workers.
- `Integrations` groups providers by domain and state.
- Run detail topology still renders canvas modes.
- Steering notes still submit through `/api/runs/{run_id}/steer`.
- No user-facing Labyrinth language appears.
- Desktop and mobile shells avoid horizontal overflow outside React Flow internals.

## Non-Goals For This Pass

- No backend registry endpoints yet.
- No OAuth token storage yet.
- No RBAC implementation yet.
- No backend mutation behavior change.
- No full external dashboard fork.
