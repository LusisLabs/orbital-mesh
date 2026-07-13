# Production Ready E2E Goal

State slice: `docs.production-ready-e2e-goal.v1`

Canonical purpose: this is the execution-grade goal document for taking this codebase from strong pilot candidate to production-ready system. It is a work order for agentic engineering, validation, release assurance, and production proof. It is not a production-readiness claim by itself.

## Target Outcome

Ship a production-ready Mesh product and control plane that can be operated by real teams against real environments with bounded authority, complete proof packets, current-head release provenance, authenticated ingress, durable state, validated integrations, and operator-facing workflows that all work end to end.

Production-ready means all of these are true for the same committed head, built image, configuration profile, deployed runtime, and target environment:

- Operators can sign in, create or join teams, configure preferences, launch runs, inspect evidence, steer approvals, export postmortems, and use product-native workflows from `meshapp/frontend`.
- The control plane behind `control_plane_server.py` enforces operator identity, roles, policy, evidence sufficiency, connector certification, target allowlists, approval gates, kill switches, and audit events.
- Live signals can enter through Kubernetes watchers, vendor webhooks, OTel metrics, manual replay, and hardened arena probes without bypassing Mesh authority.
- Every action is constrained by policy, evaluation, allowlists, rollback metadata, evidence, operator approval, audit, and release-bound runtime identity.
- Postgres-backed state, run events, Merkle proofs, vault artifacts, exports, settings, identity state, and proof packets survive restart and restore.
- Authenticated TLS ingress, SSO or app-session hardening, OAuth/captcha provider proof, role propagation, header stripping, and private upstream boundaries are proven in the target environment.
- Release provenance is complete for current `HEAD`: commit, image digest, base image digests, build command, policy signatures, migration rehearsal, SBOM, vulnerability scan, CI attestation, and runtime binding.
- Production pilot gates pass from observed evidence, not hand-written claims: `/api/readiness`, `/api/pilot/go-no-go`, `scripts/verify_pilot_clearance.py`, and signoff artifacts agree.
- All product "bells and whistles" have proof-backed posture: Praxis, Agent Flow and Harper-696, LiveKit, hardened arena builder, connector certification, run export, memory projection, trust ladder, topology, kill switch, policy state, provider adapters, Mesh Brain controlled canary, and deployment packaging.
- The public/protected host split is explicit: public landing can exist without implying production control; protected app/control-plane access requires auth, private upstream, and evidence-bound readiness.

## Hard Rules

- Plan first, act after.
- Measure twice, cut once policy.
- Every mutation must name the state slice it touches before editing.
- Use `pnpm`, not other Node package managers.
- Do not run `tail`.
- Keep `pnpm run lint` as the heavy root gate.
- Use `pnpm run lint:fast`, `pnpm run test:focused`, `pnpm run verify:contracts`, and `pnpm run verify:full` as the normal iteration ladder.
- Keep the codebase clean: no tmp files, no dead code, no dead files, no unnecessary folders.
- Preserve unrelated dirty worktree changes. Stage narrowly.
- Raw secrets, OAuth codes, captcha tokens, cookies, kubeconfigs, API keys, SSH keys, provider tokens, and service account material must never enter source, docs, logs, committed fixtures, or proof packets.
- Proposal lanes cannot become authority lanes by UI language. Hermes, Goose, Deep Agents, ACP, Akto, Praxis, Centaur-style adapters, LiveKit, and Mesh Brain remain bounded by Mesh policy, certification, approval, and audit.
- If the same error appears twice, stop patching, record the exact command and error, research 3-5 plausible fixes, choose the smallest fix consistent with Mesh authority boundaries, implement one fix, and rerun the narrowest trustworthy validation.
- Use `MAKE NO MISTAKES.` at the end of every delegated task prompt for this goal.

## Source Of Truth

Read these before non-trivial work:

- `AGENTS.md`
- `architecture.md`
- `docs/repo-truth-audit.md`
- `docs/future-agent-operating-guide.md`
- `docs/production-deployment-roadmap.md`
- `docs/production-readiness-validation.md`
- `docs/production-live-runbook.md`
- `docs/operator-product-app.md`
- `docs/reference-architectures.md`
- `docs/authenticated-ingress.md`
- `docs/lusislabs-preview-deployment.md`
- `docs/hardened-arena-implementation-task-list.md`
- `package.json`
- `meshapp/frontend/package.json`

Current code and config beat prose. JSON Schemas in `shared/mesh_runtime/schemas/` plus Python contract models beat inferred payload shapes. `meshapp/frontend` is the active product surface. `web/` is the legacy/reference surface until removed in a separate cleanup slice. Historical evidence under `docs/history/` and local ignored state are provenance only.

## Current Production Blockers To Retire

These are blockers to track from the current repo posture. Revalidate before editing because blocker names can change.

- Current-head release provenance is incomplete until a clean release packet binds image digest, base image digests, policy signature, migration rehearsal, SBOM, vulnerability scan, CI attestation, and build command.
- CI artifacts must be downloaded and verified as a bundle before they feed runtime deployment. Use `scripts/verify_release_artifact_bundle.py` to bind the CI attestation, release provenance draft, SBOM, vulnerability scan, migration rehearsal, and release-image metadata for the same commit; later commits need fresh CI artifacts.
- Pilot readiness is runtime-bound. Historical green packets do not clear the current branch or deployed image.
- Authenticated ingress deployment proof is required for target TLS, identity enforcement, header stripping, private upstream, role mapping, app rehearsal, audit identity, and no raw secret material.
- Operator auth provider proof remains blocked until clean-browser Google OAuth, GitHub OAuth, and captcha proof are captured and matched to runtime auth events without raw secret material.
- Mesh Brain production model-serving remains controlled MVP/canary proof only until artifact registry, upload proof, live serving backend, rollback drill, canary smoke, and release binding pass.
- Feature-flag writes, incident-provider writes, and external audit sink writes remain blocked until provider proof packets and connector certification registry states authorize exact scopes.
- Watch mode, incident coverage, repeatability, production-target proof, provider action-scope proof, on-call drill, load/concurrency, backup/restore, credential rotation, and production-autonomy aggregate clearance need live target packets before broad production autonomy claims.
- Hardened arena implementation exists as a builder/proof lane, but each target arena still needs target-specific observed proof.
- Helm, Terraform, marketplace packaging, and cloud-specific deployment recipes remain expansion work until validated against target proof packets.

## Operating Model

The orchestrator owns the plan, dependency order, status, staging boundaries, and final proof interpretation. Worker agents own bounded slices with explicit state slices and file ownership. No worker edits outside its assigned files without reporting the conflict first.

Default worker lanes:

| Worker | Read scope | Write scope | State slices | Output |
| --- | --- | --- | --- | --- |
| Truth and roadmap | docs, config, package scripts | docs only unless assigned | `docs.production-ready-e2e-goal.v1`, release docs | gap map, blocker map, doc patches |
| Runtime contracts | `control_plane_server.py`, `services/`, `shared/mesh_runtime/`, `scripts/`, `tests/` | assigned runtime/schema/test files | contracts, readiness, admission, proof packets | schema-safe implementation plus tests |
| Product UI | `meshapp/frontend`, product contracts, UI tests | assigned product files | `ui-product-shell`, product read models | production UI workflows plus e2e proof |
| Auth and identity | auth docs, operator identity, provider capture scripts | assigned auth files | `auth-identity`, `team-tenancy`, `auth-provider-proof.v1` | fail-closed auth/provider proof |
| Deployment and release | compose, workflows, runbooks, release scripts | assigned deploy/release files | release provenance, runtime binding, ingress proof | current-head release and deploy proof |
| Validation | tests, scripts, proof packets | tests and verifier fixes only | tests-and-validation | validation transcript and blocker report |

Worker prompt template:

```text
Repo: /Users/shaanp/Documents/venture/lusis-mesh

Task: <one bounded deliverable>
State slice touched: <explicit state slice>
Read first: AGENTS.md, docs/repo-truth-audit.md, docs/future-agent-operating-guide.md, package.json, and the files listed below.
Owned write paths: <exact paths>
Forbidden write paths: unrelated dirty files, vendored/source-input trees, generated state, secrets.
Rules: plan first, act after; Measure twice, cut once policy; use pnpm; do not run tail; preserve dirty worktree; no tmp/dead files; no production claims without proof.
Validation: <exact focused commands plus escalation ladder>
Report: changed files, state slices, validation output, blockers, residual risk, next exact command.

MAKE NO MISTAKES.
```

## Execution Cadence

For every slice:

1. Run preflight:

```bash
git status --short --branch
pnpm run lint:fast
```

2. Name the state slice and files.
3. Create or update a task list with `pending`, `in_progress`, `blocked`, `done`, or `deferred`.
4. Inspect source truth and current implementation before editing.
5. Patch the smallest coherent vertical slice.
6. Run the narrowest validation that can falsify the change.
7. If the slice touches contracts, run:

```bash
pnpm run verify:contracts
```

8. If the slice touches executable behavior, run:

```bash
pnpm run test:focused
```

9. If the slice touches product browser behavior, run:

```bash
pnpm run test:product:e2e
pnpm --dir meshapp/frontend run test
pnpm --dir meshapp/frontend run lint
```

10. If the slice touches release, deployment, readiness, or production claims, run the relevant proof verifier and then:

```bash
scripts/verify_release_cut_list.py --json
pnpm run verify:full
```

11. Before any PR handoff:

```bash
pnpm run lint
git diff --check
git status --short --branch
```

12. Run the recursive goal-maintenance function before selecting the next slice.

## Recursive Agentic Engineering Function

State slice: `docs.recursive-agentic-goal-maintenance.v1`

Purpose: keep this goal document alive while the codebase moves. Each engineering pass must feed new evidence, blocker changes, feature seams, validation failures, and product/runtime discoveries back into the plan before more implementation work begins.

The function is recursive because production readiness is not a linear checklist. Each completed or blocked slice can reveal missing contracts, feature wiring, proof gaps, stale docs, CI drift, UI gaps, deployment blockers, or new validation requirements. Those discoveries must be woven into this document, then dispatched as smaller state-sliced tasks until no new production-readiness work is discovered.

```text
function recursive_production_ready_goal(
  goal_doc,
  current_slice,
  evidence_packet,
  depth,
  max_depth
):
  state_slice = "docs.recursive-agentic-goal-maintenance.v1"

  assert current_slice.names_state_slice
  assert evidence_packet.names_commands_artifacts_blockers
  assert no_raw_secret_material(evidence_packet)
  assert depth <= max_depth

  refreshed_truth = read_current_truth(
    files=[
      "AGENTS.md",
      "docs/repo-truth-audit.md",
      "docs/future-agent-operating-guide.md",
      "docs/production-readiness-validation.md",
      "docs/operator-product-app.md",
      "package.json",
      "changed files from evidence_packet"
    ]
  )

  insights = extract_insights(
    evidence_packet=evidence_packet,
    refreshed_truth=refreshed_truth,
    categories=[
      "new blocker",
      "retired blocker",
      "contract drift",
      "feature seam",
      "missing UI wiring",
      "missing backend route",
      "missing verifier",
      "missing proof artifact",
      "stale docs or CI",
      "unsafe authority language",
      "deployment gap",
      "test coverage gap",
      "operator workflow gap"
    ]
  )

  if insights.is_empty and current_slice.done:
    return goal_doc

  goal_doc = weave_insights_into_goal(
    goal_doc=goal_doc,
    insights=insights,
    rules=[
      "update existing slices before adding new slices",
      "add new burndown rows only when no existing slice owns the work",
      "each new task names one state slice",
      "each feature seam maps UI -> API -> contract -> persistence -> proof -> docs",
      "keep proposal lanes non-authoritative",
      "keep blockers explicit instead of marking partial work done",
      "keep validation commands exact and pnpm-based",
      "preserve historical evidence as historical only"
    ]
  )

  next_tasks = decompose_insights(
    insights=insights,
    constraints=[
      "one state slice per task",
      "bounded write paths",
      "smallest falsifiable validation",
      "no secrets",
      "no vendored/source-input refactors unless explicitly assigned",
      "no broad production claims without target proof"
    ]
  )

  for task in next_tasks:
    worker_prompt = build_worker_prompt(
      repo="/Users/shaanp/Documents/venture/lusis-mesh",
      task=task,
      state_slice=task.state_slice,
      owned_write_paths=task.owned_write_paths,
      validation=task.validation_commands,
      suffix="MAKE NO MISTAKES."
    )

    result = run_or_assign_agentic_engineering_task(worker_prompt)

    goal_doc = recursive_production_ready_goal(
      goal_doc=goal_doc,
      current_slice=task,
      evidence_packet=result.evidence_packet,
      depth=depth + 1,
      max_depth=max_depth
    )

  return goal_doc
```

Recursion limits:

- Default `max_depth` is `3` inside one local engineering session.
- Stop early when a task needs live credentials, human provider-console work, target-environment access, merge authority, or no-mistakes/CI review.
- Stop early when two identical errors occur and the repeated-error research rule has not been executed.
- Stop early when new work would touch a dirty file outside the current state slice.
- Stop early when the next task is larger than one reviewable vertical slice; write it into the burndown instead.

Insight weaving rules:

- UI feature discovered without backend support becomes `UI -> API route -> contract -> persistence -> proof -> docs`.
- Backend route discovered without product visibility becomes `API route -> generated types -> product read model -> UI state -> e2e test`.
- Verifier gap discovered during validation becomes `proof schema -> verifier -> negative test -> docs -> release gate`.
- Deployment gap discovered during smoke becomes `env var -> secret boundary -> readiness blocker -> runbook -> target proof`.
- Auth/provider gap becomes `ignored env preflight -> stack smoke -> clean-browser proof -> runtime auth evidence -> checkpoint`.
- Proposal-lane capability becomes `proposal artifact -> Mesh certification -> approval path -> audit -> revocation`, never direct actuation.
- Historical proof discovered during research becomes a note under historical evidence, not current readiness.
- New production claim requires current code, current artifacts, current runtime binding, and an exact verifier.

Recursive closeout checklist:

- The goal doc changed only where the new evidence requires it.
- Every added task has one owning state slice and one validation path.
- Every retired blocker names the evidence that retired it.
- Every new blocker names the proof path, env var, endpoint, or command that can retire it.
- `git diff --check` passes after the goal-doc update.
- Production-readiness doc changes run `scripts/verify_release_cut_list.py --json`.
- Before merge, `pnpm run lint` passes on the exact committed head.

## Burndown

| ID | Status | State slice | Deliverable | Done criteria | Validation |
| --- | --- | --- | --- | --- | --- |
| P0 | complete | `production-readiness.truth-map.v1` | Current truth refresh | Docs, scripts, package gates, dirty tree, release blockers, and historical evidence are classified. | `git status --short --branch`, `corepack pnpm run lint:fast` |
| P1 | complete | `repo-gate-ladder.v1`, `validation-gate-surface.v1` | Gate discipline and CI convergence | Root scripts are documented and working: `lint:fast`, `test:focused`, `verify:contracts`, `verify:full`, `lint`. CI workflows and active docs use pnpm-aligned gates before CI is cited as authoritative. | `corepack pnpm run lint`, `python3 scripts/verify_release_cut_list.py --json`, `python3 scripts/verify_security_audit_readiness.py --json` |
| P2 | complete | `contracts-and-schemas` | Contract drift closure | Control-plane and product schemas, generated TS types, Python validators, and tests agree. | `corepack pnpm run verify:contracts`, `corepack pnpm run test:focused` |
| P3 | complete | `mesh-control-plane-runtime.v1` | Runtime hardening | Health, readiness, run admission, approvals, steering, watchers, evidence, Merkle, export, kill switch, and policy routes fail closed and carry operator identity. | `corepack pnpm run test:focused`, `python3 scripts/verify_release_cut_list.py --json` |
| P4 | complete | `ui-product-shell` | Product app completion | `meshapp/frontend` supports Home, runs, approvals, evidence, connectors, readiness, topology, memory, kill switch, policy, settings, keys, team, Praxis, and Agent Flow without legacy shortcuts. | `corepack pnpm run test:product:e2e`, `corepack pnpm --dir meshapp/frontend run test`, `corepack pnpm --dir meshapp/frontend run lint` |
| P5 | blocked | `auth-identity`, `team-tenancy`, `auth-provider-proof.v1` | Auth and provider proof | App-session and proxy-header modes are fail-closed. OAuth/captcha provider proof is captured in clean browser and matched to runtime auth evidence. Current blocker: `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` is missing, so runtime auth events remain incomplete. | `pnpm run auth-provider:live-preflight`, `pnpm run auth-provider:live-stack-smoke`, `pnpm run auth-provider:checkpoint`, `pnpm run test:auth-provider:live` |
| P6 | complete | `mesh.operator-preferences.v1`, `mesh-settings-control` | Operator setup and settings | UI and CLI settings share validation, audit reasons, scope, and redaction. Preferences cannot store secrets or bypass policy. | `python scripts/operator_config.py validate --scope global`, `pnpm run verify:operator-goal` |
| P7 | complete | `meshapp.run-preflight.v1`, `meshapp.run-workbench.v1` | Launch and proof workbench | Launch preflight shows identity, roles, topology, target locks, connector scopes, readiness, and blockers. Workbench shows events, evidence, decisions, tasks, timeline proof, and export. | `pnpm run test:product:e2e`, `pnpm run verify:contracts` |
| P8 | complete | `policy-evaluation-approval.v1` | Governance gates | Policy, evaluation, evidence sufficiency, approvals, forced approval gate, kill switches, and autonomy tier guard cannot be bypassed. | `pnpm run test:focused`, `python3 scripts/verify_release_cut_list.py --json` |
| P9 | complete | `connector-certification.v1` | Connector maturity | Every connector has state, authority posture, credential boundary, degraded behavior, scopes, blockers, and proof refs. Feature-flag, incident-provider, external-audit, and provider-write lanes remain scope-blocked until proof packets authorize exact actions. | `python3 -m unittest tests.test_contracts tests.test_provider_action_scope tests.test_provider_adapter_proof -v`, `python3 scripts/verify_release_cut_list.py --json` |
| P10 | complete | `live-signal-ingest.v1` | Real signal paths | Kubernetes watcher, webhook, OTel, manual replay, and simulator flows create or block runs with evidence and redaction. Target-live watch and incident packets remain separate P22/P23 requirements. | `python3 -m unittest tests.test_kubernetes_watcher tests.test_watch_daemon tests.test_webhook_ingest tests.test_otel_ingest tests.test_watch_mode_proof tests.test_incident_coverage tests.test_ai_sre_platform_slice -v`, `pnpm run test:focused` |
| P11 | complete | `run-export-proof.v1` | Postmortem export | Export packages include timeline, Markdown summary, artifacts, decision/evaluation/execution/feedback, approvals, Merkle, vault, redaction, retention/delete-after handling, independent review, and retrieval/upload proof. | `python3 -m unittest tests.test_run_export_retrieval tests.test_run_export_upload tests.test_run_export_retention tests.test_postmortem_review tests.test_override_review tests.test_production_cut_list.RunExportPackageTests -v`, `pnpm run test:focused` |
| P12 | complete | `postgres-state-production.v1` | Durable state | Production deployments default to Postgres, local compose migration rehearsal and restart proof pass, root gates cover backup/restore contracts, and a current-head pilot Postgres backup/restore packet verifies locally. Boundary: production/staging target claims still require rerunning the same restore proof against the target Postgres backend and durable backup storage before release provenance can bind it. | `PYTHONPATH=. uv run --with-editable . python -m unittest tests.test_backup_restore_rehearsal -v`, `PYTHONPATH=. uv run --with-editable . python scripts/run_backup_restore_rehearsal.py --database-url postgresql://mesh:mesh@127.0.0.1:5432/mesh --environment pilot --operator-id platform@example.com --output .mesh-runtime-state/backup-restore-rehearsal.json --artifact-dir .mesh-runtime-state/backup-restore-rehearsal --json`, `python3 scripts/verify_backup_restore_rehearsal.py --proof .mesh-runtime-state/backup-restore-rehearsal.json --expected-environment pilot --expected-state-backend postgres --json`, `corepack pnpm run lint:fast` |
| P13 | complete | `authenticated-ingress-deployment.v1` | TLS and identity ingress | App-level proxy-header role rehearsal passes, production compose requires a deployment proof path, and the current pilot authenticated-ingress deployment packet verifies TLS termination, SSO/proxy identity enforcement, header stripping, private upstream, role mapping, audit identity, and no raw secret material. Boundary: production or staging ingress claims still require rerunning the same proof packet for that target environment. | `python3 scripts/verify_authenticated_ingress.py --json`, `python3 scripts/verify_authenticated_ingress_deployment.py --proof .mesh-runtime-state/proofs/authenticated-ingress-deployment-proof.json --expected-environment pilot --json`, `pnpm run test:focused` |
| P14 | blocked | `release-provenance-current-head.v1` | Release assurance | Release provenance and runtime-binding tests pass locally, and the repo-local commit step retired the `clean_git_tree` blocker. The latest ignored local release rehearsal path `.mesh-runtime-state/release-provenance-p14-current-rehearsal.json` must be regenerated after each commit; when regenerated after the repo-local commit, it narrowed P14 to two blockers by binding image digest, base image digests, signed policy lifecycle packet, migration rehearsal, build command, and a real CycloneDX SBOM with 4827 components, but remained `status=incomplete` because `vulnerability_scan_path=false` and `ci_attestation=false`. Current blockers: the normalized Grype scan has 14 unaccepted high/critical findings in Python `3.13.13`, glibc, and ncurses packages; the exception policy expired on 2026-05-21; no valid GitHub Actions CI attestation exists for the current head; and `scripts/verify_release_runtime_binding.py --json` still lacks a complete `MESH_RELEASE_PROVENANCE_PATH`. | `scripts/generate_release_provenance.py --require-complete --json`, `scripts/verify_release_runtime_binding.py --json`, `pnpm run test:focused` |
| P15 | complete | `mesh-brain-controlled-canary.v1` | Mesh Brain MVP proof | Local E2E overlay config now supplies Mesh Brain artifact URI, artifact registry, upload proof, serving base URL, and serving model. The control plane observed model-kernel proof, one CROPS live canary lane, and rollback drill evidence in state-store runs; `/api/pilot/go-no-go` reports all Mesh Brain checks true. Boundary: this clears the local E2E canary proof, not a production release packet or external durable artifact store. | `MESH_E2E_BUILD_COMMIT="$(git rev-parse HEAD)" docker compose -f docker-compose.stack.yml -f docker-compose.e2estack.yml up -d --build mesh`, `POST /api/mesh-brain/model-kernel-probe`, `POST /api/mesh-brain/live-serving-smoke`, `POST /api/mesh-brain/rollback-drill`, `scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --expected-head "$(git rev-parse HEAD)" --json`, `pnpm run test:focused` |
| P16 | complete | `praxis.managed-dry-run-runtime.v1` | Praxis production boundary | Source intake, generated MCP contracts, Akto evidence, certification binding, dry-run MCP endpoint, revocation, and proof export work without granting production authority. | `uv run --with-editable . python scripts/verify_praxis_proof_packet.py`, `pnpm run verify:contracts`, `pnpm run test:focused` |
| P17 | complete | `mesh.agent_flow.*` | Harper-696 and Agent Flow | Chat stays read-only/draft-first, LiveKit token minting is short-lived and role-scoped, preview confirmation cannot execute Mesh mutations. | `pnpm run test:focused`, `pnpm --dir meshapp/frontend run test` |
| P18 | complete | `hardened-arena.*.v1` | Hardened arena target proof | Profile, catalog, packet, intent, API, UI, and proof runner produce target-specific observed proof without deployment-ready overclaims. | `python3 scripts/run_hardened_arena_proof.py --evidence <proof-input> --output <proof.json>`, `python3 scripts/verify_hardened_arena_proof.py --proof <proof.json> --json`, `pnpm run test:focused` |
| P19 | complete | `deployment-compatibility.v1` | Deployment packaging | Docker Compose and Kubernetes remain validated, ECS/Fargate remains the single next validated target, and target-specific promotion fails closed without health, readiness, ingress, persistence, feedback, audit, rollback, release provenance, and no-secret proof. | `scripts/verify_deployment_compatibility.py --json`, `scripts/verify_ecs_fargate_promotion.py --proof .mesh-runtime-state/ecs-fargate-promotion-proof.json --json`, `pnpm run test:focused` |
| P20 | complete | `load-concurrency-rehearsal.v1` | Load and concurrency | Load-concurrency proof contracts, runner, verifier, and expansion readiness gating pass. Current local pilot Postgres rehearsal packet `.mesh-runtime-state/load-concurrency-rehearsal.json` verifies multi-operator load, queue backpressure, rejected runs, tenant quota, target-lock conflict, cancellation, stuck-run recovery, admission latency, event persistence latency, evidence refs, and no raw secret material. Boundary: production expansion still requires rerunning the same proof runner against the target Postgres backend before claiming that target. | `python -m unittest tests.test_load_concurrency_rehearsal -v`, `scripts/run_load_concurrency_rehearsal.py --database-url <postgres-url> --environment pilot --output .mesh-runtime-state/load-concurrency-rehearsal.json --json`, `scripts/verify_load_concurrency_rehearsal.py --proof .mesh-runtime-state/load-concurrency-rehearsal.json --json`, `pnpm run test:focused` |
| P21 | complete | `production-target-proof.v1` | Production-like target proof | Production-target proof contracts pass locally, historical live proof `.mesh-runtime-state/live-proof-583/proofs/production-target-proof.json` verifies for `pilot`, and the older `.mesh-runtime-state/live-proof-current/proofs/production-target-proof.json` proof window verified for commit `cfd9f3b18d0d0bd87a59056faaa442ae73994573` with target run `run_20260523T072245_108d1468`. Boundary: this clears the target packet contract and that historical pilot proof window, not aggregate production autonomy or the current branch head; P24 remains blocked by strict repeatability and runtime binding. | `python3 -m unittest tests.test_production_live_proof_bundle tests.test_production_target_proof -v`, `scripts/capture_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --release-provenance <release-provenance.json> --release-runtime-binding <release-runtime-binding.json> --on-call-drill <on-call-drill.json> --allow-partial`, `scripts/verify_production_target_proof.py --proof .mesh-runtime-state/live-proof-current/proofs/production-target-proof.json --expected-environment pilot --require-live --json`, `pnpm run test:focused` |
| P22 | complete | `watch-mode-proof.v1` | Watch-mode proof | Watch-mode proof contracts pass locally, historical live proof `.mesh-runtime-state/live-proof-583/proofs/watch-mode-proof.json` verifies for `pilot`, and the older `.mesh-runtime-state/live-proof-current/proofs/watch-mode-proof.json` proof window verified target run `run_20260523T072245_108d1468` plus repeat run `run_20260523T072442_5925b9e0` with duplicate suppression, healthy suppression, provider-failure recovery, kill-switch pause, exports, and replay refs. Boundary: this clears watch-mode evidence for that historical proof window, not aggregate production autonomy or the current branch head; P24 remains blocked by strict repeatability and runtime binding. | `python3 -m unittest tests.test_production_live_proof_bundle tests.test_watch_mode_proof -v`, `scripts/generate_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --target-events <target-events.json> ...`, `scripts/verify_watch_mode_proof.py --proof .mesh-runtime-state/live-proof-current/proofs/watch-mode-proof.json --expected-environment pilot --require-live --json`, `pnpm run test:focused` |
| P23 | complete | `incident-coverage-proof.v1` | Incident coverage | Incident coverage proof contracts pass locally, historical live proof `.mesh-runtime-state/live-proof-583/proofs/incident-coverage-proof.json` verifies required classes with live evidence, and the older `.mesh-runtime-state/live-proof-current/proofs/incident-coverage-proof.json` proof window verified all required incident classes from the bounded live proof window. Boundary: this clears incident coverage evidence for that historical proof window, not aggregate production autonomy or the current branch head; P24 remains blocked by strict repeatability and runtime binding. | `python3 -m unittest tests.test_production_live_proof_bundle tests.test_incident_coverage -v`, `scripts/generate_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --target-export <target-export.json> --repeat-export <repeat-export.json> ...`, `scripts/verify_incident_coverage_proof.py --proof .mesh-runtime-state/live-proof-current/proofs/incident-coverage-proof.json --require-live --json`, `pnpm run test:focused` |
| P24 | blocked | `production-autonomy-clearance.v1` | Aggregate autonomy proof | Production autonomy clearance contracts pass locally, and historical proof bundles verify production target, provider action scopes, watch mode, incident coverage, and on-call drill for their own commits. The current workspace has no mounted current-branch `.mesh-runtime-state/live-proof-current/` bundle, so broad autonomy remains blocked for this branch. The latest known mounted repeatability packet was stale for later heads because it recorded repo head `cfd9f3b18d0d0bd87a59056faaa442ae73994573` and `working_tree_clean=false`; the generator now also requires a current-head `mesh.release_runtime_binding.v1` packet backed by `/api/health` or image-ref evidence before a bundle can report `pass`. Next action: generate a fresh current-head release provenance/runtime-binding packet, rerun `scripts/capture_production_live_proof_bundle.py` or `scripts/generate_production_live_proof_bundle.py` from observed current-head API artifacts with `--clean-env-recreated --fresh-image-built`, then rerun the aggregate verifier without dirty-env relaxation. Existing branch-tip replay-only proof generation also remains blocked by below-threshold compose-chaos summaries. | `python3 -m unittest tests.test_production_live_proof_bundle tests.test_production_autonomy_clearance tests.test_repeatability_proof tests.test_on_call_drill -v`, `scripts/capture_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --release-provenance <release-provenance.json> --release-runtime-binding <release-runtime-binding.json> --on-call-drill <on-call-drill.json> --clean-env-recreated --fresh-image-built`, `scripts/verify_production_autonomy_clearance.py --repeatability-proof .mesh-runtime-state/live-proof-current/proofs/repeatability-proof.json --production-target-proof .mesh-runtime-state/live-proof-current/proofs/production-target-proof.json --provider-action-scope-proof .mesh-runtime-state/live-proof-current/proofs/provider-action-scope-proof.json --watch-mode-proof .mesh-runtime-state/live-proof-current/proofs/watch-mode-proof.json --incident-coverage-proof .mesh-runtime-state/live-proof-current/proofs/incident-coverage-proof.json --on-call-drill-proof .mesh-runtime-state/live-proof-current/proofs/on-call-drill.json --expected-head "$(git rev-parse HEAD)" --expected-environment pilot --json`, `pnpm run test:focused` |
| P25 | complete | `pilot-go-no-go.v1` | Controlled pilot clearance | Local E2E overlay pilot clearance passed from observed endpoint evidence for historical head `cfd9f3b18d0d0bd87a59056faaa442ae73994573`: `/api/health` was commit/image bound, `/api/readiness` was `ready`, `/api/pilot/go-no-go` was `go` with empty missing evidence, and signed operator signoff verified against the captured go/no-go packet. Boundary: the E2E overlay release provenance uses `compose-e2e` CI attestation and the explicit E2E image digest; it does not clear the current branch head, and production release readiness remains blocked by P14 and P24 aggregate repeatability. | `docker exec -w /workspace/orbital-mesh orbital-mesh-stack python3 scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 45 --expected-head "$(git rev-parse HEAD)" --json`, `python3 scripts/verify_pilot_signoff.py --signoff .mesh-runtime-state/e2e/pilot-signoff.json --go-no-go .mesh-runtime-state/e2e/pilot-go-no-go.json --signing-key mesh-e2e-pilot-signoff-key --json`, `pnpm run test:focused` |
| P26 | complete | `docs-and-public-proof.v1` | Public and enterprise proof package | Public proof, procurement security, security-audit readiness, and design-partner packet verification pass locally. The design-partner packet is now bound to local E2E go/no-go packet SHA `80fa4823733582bca459fefe757053b2e1e6c48223f56623ef78d17d8c45b586` and E2E release provenance SHA `3027c613c9088247a1ae092df35a5606891896c4ccb52515000e86388f29ae20`. Boundary: this clears the local proof package; external publication, customer-specific benchmark outputs, and production-target partner evidence remain deployment-specific artifacts. | `python -m unittest tests.test_design_partner_packet tests.test_procurement_security_package tests.test_public_proof_package -v`, `scripts/verify_design_partner_packet.py --packet .mesh-runtime-state/proofs/design-partner-packet.json --expected-go-no-go-sha 80fa4823733582bca459fefe757053b2e1e6c48223f56623ef78d17d8c45b586 --expected-release-provenance-sha 3027c613c9088247a1ae092df35a5606891896c4ccb52515000e86388f29ae20 --json`, `scripts/verify_procurement_security_package.py --json`, `scripts/verify_security_audit_readiness.py --json`, `scripts/verify_public_proof_package.py --json`, `pnpm run test:focused` |

## Slice Definitions

### P0 Truth Refresh

State slice: `production-readiness.truth-map.v1`

Tasks:

- Re-run `git status --short --branch`.
- Record untracked or dirty paths and classify them as user-owned, generated, or target slice.
- Compare `docs/repo-truth-audit.md`, `docs/future-agent-operating-guide.md`, `docs/production-readiness-validation.md`, and `package.json`.
- Produce a blocker map with exact env vars, proof paths, endpoints, scripts, and docs.
- Remove stale wording only when it conflicts with current code or scripts.

Done: the orchestrator has an evidence map that separates implemented, locally validated, target-validated, historical, blocked, and proposal-only items.

### P1 Gate Discipline

State slices: `repo-gate-ladder.v1`, `validation-gate-surface.v1`

Tasks:

- Keep root `pnpm run lint` as the heavy gate.
- Keep `pnpm run lint:fast` fast enough for normal iteration.
- Keep `pnpm run test:focused`, `pnpm run verify:contracts`, and `pnpm run verify:full` explicit.
- Converge `.github/workflows/ci.yml`, `.github/workflows/release-image-handoff.yml`, and `.github/workflows/security.yml` onto pnpm-based install, cache, lint, test, build, audit, and release-image handoff commands before claiming CI as current authority.
- Remove stale command references in touched docs during the same slice. Historical benchmark records can keep old command transcripts when clearly historical.
- Do not rename scripts without updating docs, CI, and agent instructions.

Done: contributors, agents, no-mistakes, and CI all run the same gate ladder without guessing which package manager or validation command is canonical.

### P2 Contracts

State slice: `contracts-and-schemas`

Tasks:

- Treat `shared/mesh_runtime/schemas/` as source of truth.
- Keep Python dataclasses, validators, generated `web/src/types.ts`, generated `meshapp/frontend/src/types.ts`, and product types in sync.
- Add fail-closed validation before adding UI fields.
- Update tests when contracts change.

Done: `pnpm run verify:contracts` fails on drift before stale UI or runtime payloads ship.

### P3 Control Plane Runtime

State slice: `mesh-control-plane-runtime.v1`

Tasks:

- Harden `/api/health`, `/api/readiness`, `/api/runs`, `/api/runs/{id}/steer`, `/api/pilot/go-no-go`, `/api/kill-switch`, `/api/watchers`, `/api/connectors/certification`, `/api/operator/dashboard`, and proof endpoints.
- Verify every mutation route captures operator identity, role, reason, source, target, and audit record.
- Ensure proposal-only lanes cannot receive kubeconfig, repo write, or actuator credentials.
- Keep file-backed local state supported while proving Postgres for production reliance.

Done: runtime routes either complete with evidence or fail closed with operator-visible blockers.

### P4 Product App

State slice: `ui-product-shell`

Tasks:

- Make `meshapp/frontend` the product app for Home, Control Console bridge, Evaluations, approvals, evidence, readiness, connectors, topology, memory, kill switch, policy, team, members, keys, settings, Praxis, and Agent Flow.
- Retire reliance on `web/` as a product destination only in a dedicated cleanup slice.
- Keep product cards bound to real `/api/operator/dashboard` read models.
- Render empty, degraded, blocked, unauthorized, and backend-unavailable states distinctly.
- Verify mobile and desktop product flows if frontend layout changes.

Done: a new operator can use the protected app without understanding legacy surfaces.

### P5 Auth And Provider Proof

State slices: `auth-identity`, `team-tenancy`, `auth-provider-proof.v1`

Tasks:

- Keep `proxy_header` as default production ingress posture.
- Keep `app_session` allowed outside local only with secure deployment secret handling and provider evidence.
- Prove Google OAuth, GitHub OAuth, and captcha through clean-browser provider completion.
- Bind live provider proof to runtime auth evidence.
- Store only redacted presence, callback, event id, timestamp, and success/failure metadata.

Done: signup, login, OAuth, captcha, team, role mapping, logout, expired-session recovery, and dashboard access are fail-closed and proof-backed.

Current evidence:

- `corepack pnpm run auth-provider:live-preflight` passed on 2026-05-23 and wrote `.mesh-runtime-state/operator-auth-proof/live-preflight.json` with `state_slice=auth-provider-proof.v1`, `status=ready`, and no blockers.
- `corepack pnpm run auth-provider:live-stack-smoke` passed on 2026-05-23 and wrote `.mesh-runtime-state/operator-auth-proof/live-stack-smoke.json` with `state_slice=auth-provider-proof.v1`, `status=ready`, `stack_mode=managed_local_stack`, and `managed_processes_owned=true`.
- The non-secret local P5 artifact chain was refreshed on 2026-05-23: `corepack pnpm run auth-provider:live-preflight`, `corepack pnpm run auth-provider:live-stack-smoke`, `corepack pnpm run test:auth-provider:smoke`, and `corepack pnpm run auth-provider:checkpoint` all passed and wrote ignored `.mesh-runtime-state/operator-auth-proof/` artifacts. The refreshed checkpoint has `local_evidence_status=complete`, `status=blocked_external_provider_proof`, `live_provider_status=blocked`, `live_provider_blocker=live_provider_proof_missing`, and source artifact timestamps bound to preflight `2026-05-23T05:56:46Z`, stack smoke `2026-05-23T05:56:55Z`, and provider readiness `2026-05-23T05:57:12Z`.
- `python3 scripts/operator_auth_provider_smoke.py --require-live --no-write` fails closed on 2026-05-23 with `status=blocked_provider_console_unverified`, configured and ignored local env files, hCaptcha env ready, Google and GitHub local callback matches, no tracked secret material, and blockers limited to `live_provider_proof_missing` plus missing runtime auth events.
- `corepack pnpm run test:auth-provider:live` fails closed with `live_provider_proof_missing` until `.mesh-runtime-state/operator-auth-proof/live-provider-proof.json` records clean-browser Google OAuth, GitHub OAuth, and hCaptcha completion and matching runtime `auth_events`.

### P6 Operator Preferences And Settings

State slices: `mesh.operator-preferences.v1`, `mesh-settings-control`

Tasks:

- Keep preferences separate from deployment-owned runtime config.
- Require audit reasons for UI and CLI settings mutation.
- Validate settings schema before persistence.
- Keep secrets out of settings and preferences.
- Render CLI parity for every mutable UI setting.

Done: operator configuration is auditable, scoped, validated, and cannot bypass runtime policy.

Current evidence:

- `python scripts/operator_config.py validate --scope global` passed on 2026-05-23 with `valid=true`, `scope=global`, and no invalid settings.
- Focused settings/preference tests passed on 2026-05-23: `tests.test_operator_identity`, `tests.test_operator_auth_http.OperatorAuthHttpTests.test_operator_settings_requires_reason_and_writes_shared_audit`, `tests.test_operator_auth_http.OperatorAuthHttpTests.test_team_isolation_and_scoped_settings_are_forbidden_for_non_member`, and `tests.test_operator_product_contracts`.
- `corepack pnpm run verify:operator-goal` exited zero on 2026-05-23 after the auth-provider checkpoint refresh with local P1-P6 requirements complete, no stale local-evidence blockers, and only the P5 external blocker `live_provider_proof_missing` remaining.

### P7 Launch And Workbench

State slices: `meshapp.run-preflight.v1`, `meshapp.run-workbench.v1`

Tasks:

- Show identity, roles, team, topology, model binding, target lock, connector scope, readiness, and blockers before launch.
- Stamp preflight context into run creation without replacing Mesh admission.
- Show run events, evidence graph, RCA, decision, evaluation, agent tasks, timeline proof, Merkle proof, and export package in proof drill-ins.

Done: an operator can see why a run can start, why it is blocked, and what evidence supports its current state.

Current evidence:

- `corepack pnpm run test:product:e2e` passed on 2026-05-23 with 9 Playwright tests, including launch preflight assertions for `meshapp.run-preflight.v1`, operator identity, topology, target lock, connector scopes, and proof workbench assertions for `meshapp.run-workbench.v1`, timeline proof, export package, and agent mesh.
- `corepack pnpm --dir meshapp/frontend run test -- ProductApp.dashboard.test.tsx` passed on 2026-05-23 with model coverage for preflight identity, roles, team, topology, target, connector scopes, readiness blockers, workbench events, evidence, decision, tasks, timeline, and export posture.
- `corepack pnpm run verify:contracts` passed on 2026-05-23 and includes the product buildout verifier markers for preflight/workbench browser coverage.

### P8 Governance Gates

State slice: `policy-evaluation-approval.v1`

Tasks:

- Verify policy lifecycle, evidence sufficiency, evaluation, autonomy tier, approval queue, forced approval gate, and kill switch behavior.
- Include positive and negative tests.
- Prove denied action and allowed action against the same target class.
- Keep `approval_gate` default for pilot unless a specific action class earns a higher trust level.

Done: no production-impacting action can pass without the required policy, evidence, evaluation, approval, and rollback context.

Current evidence:

- `corepack pnpm run test:focused` passed on 2026-05-23 after adding the direct governance modules to the focused gate: `tests.test_autonomy_policy`, `tests.test_approval_queue`, `tests.test_contracts`, `tests.test_pipeline`, and `tests.test_darkharness_policy`.
- The focused gate now covers positive and negative paths for certified live rollback scope, approval-required blocking and approval-observed allow, denied/advisory tiers, force-approval evaluation blocking, approval queue pending/blocked states, signed policy lifecycle packets, evidence sufficiency pass/fail, and production-action policy allow/deny against the same pilot target class.
- `tests.test_production_cut_list.PolicySimulationAndKillSwitchTests` remains in `test:focused` and covers policy simulation as non-mutating plus kill switch disabling live execution and forcing `approval_gate`.
- `python3 scripts/verify_release_cut_list.py --json` passed on 2026-05-23 with policy lifecycle, evidence sufficiency, approval queue, policy simulation, approval endpoint, and kill-switch markers present.

### P9 Connectors And Providers

State slice: `connector-certification.v1`

Tasks:

- Maintain connector states: mock, read-only, staging-ready, pilot-ready, production-ready.
- Require credential policy, authority posture, degraded behavior, allowed scopes, blockers, evidence refs, and target proof.
- Keep incident, feature flag, external audit, and provider-write lanes blocked until real provider proof exists.
- Verify credential rotation and no-secret-leak behavior.

Done: "wired" never means "production-ready"; each connector exposes exact maturity and authority.

Current evidence: `config/connector-certification.registry.json` has 28 connector records with required state, authority, credential boundary, degraded behavior, allowed-scope, blocker, and evidence fields. `feature_flag_adapter` exposes only `dry-run` and `proposal`; `incident_adapter` exposes only `fixture-intake` and `proposal`; `audit_sink` exposes only `local-audit`. The provider action-scope and provider-adapter proof CLIs require explicit proof packets, so missing proof remains fail-closed instead of defaulting to readiness.

### P10 Live Signal Paths

State slice: `live-signal-ingest.v1`

Tasks:

- Prove Kubernetes watcher, webhook, OTel, manual replay, and simulator flows.
- Protect OTel with bearer token or private ingress.
- Verify HMAC or source registration for webhooks.
- Require kubeconfig reachability, context allowlists, namespace allowlists, and kill-switch compliance for Kubernetes.
- Record signal provenance and redaction.

Done: real signals create bounded runs or explicit blockers without hidden mutable side effects.

Current evidence: Kubernetes watcher tests cover unhealthy-run creation, healthy suppression, duplicate suppression, cooldown, active-run suppression, correlation, and per-target provider failure continuation. Webhook tests cover registered sources, HMAC rejection, unknown-source blocking, source deletion, secret redaction, and auto-run only on firing alerts. OTel tests cover OTLP parsing, signal normalization, Prometheus pull success/failure, and `/v1/metrics` bearer-token rejection/acceptance. Simulation tests cover sandbox context allowlists, scenario payload generation, deterministic signal randomization, manual override replay writing, and replay ingestion into rule learning. Watch-mode and incident-coverage proof tests cover fixture pass paths and `--require-live` fail-closed behavior. Live P22/P23 packets are still required before claiming target-live watch coverage.

### P11 Run Export

State slice: `run-export-proof.v1`

Tasks:

- Export timeline, Markdown summary, evidence artifacts, decisions, evaluations, execution records, feedback, approvals, handoffs, vault notes, Merkle proof, latest-event proof, and redaction metadata.
- Verify retrieval, upload, retention review, and delete-after behavior.
- Keep bulky fields compacted under configured size limits.

Done: postmortem packets are portable, redacted, replayable, and reviewable by operators who did not launch the run.

Current evidence: retrieval tests prove saved `mesh.run_export.v1` packages and `mesh.run_export_archive.v1` zip archives pass checksum, archive manifest, timeline, Markdown, Merkle, latest-event proof, vault document, retention, and redaction checks, and fail when secret fields remain unredacted. Upload tests prove `mesh.run_export_upload_proof.v1` manifests only pass when package/archive receipts are durable, hashes and byte counts match, provider identity matches, retention metadata is carried forward, and restore-test evidence is present. Retention tests prove dry-run-first purge behavior, expired JSON/archive deletion with `--apply`, and future `delete_after` preservation. Postmortem and override review tests enforce independent reviewers and exportable review records. `RunExportPackageTests` proves packages carry decision, evaluation, execution, feedback, approvals, lane/evidence artifacts, redacted timelines, Merkle/latest-event proof, vault Markdown, archive records, and size-cap compaction. The root `test:focused` gate now includes these P11 modules, and `lint:fast` compiles the run-export proof scripts and modules.

### P12 Persistence And Recovery

State slice: `postgres-state-production.v1`

Tasks:

- Prove Postgres default for production compose and target deployments.
- Rehearse migration, restart, backup, restore, corrupted-event handling, and state/vault/Merkle/integration restore.
- Prove RPO/RTO targets from observed rehearsal, not docs.
- Keep HelixDB memory projection optional until it becomes a canonical state backend with equivalent proof gates.

Done: production reliance does not depend on local JSON state, historical artifacts, or untested restore assumptions.

Current evidence: production compose requires `MESH_STATE_BACKEND=postgres`, `MESH_DATABASE_URL`, `MESH_BACKUP_RESTORE_REHEARSAL_PATH`, and `MESH_MIGRATION_REHEARSAL_PATH`; stack compose defaults the Mesh service to Postgres. P12 focused tests cover backup/restore proof validation and readiness blocking, migration proof generation/verification, real migration-runner behavior against a disposable schema, Postgres pool reuse/close/redaction/concurrency, and production compose evidence handoff requirements. Local compose Postgres was started and reached `healthy`; `scripts/run_postgres_migration_rehearsal.py` generated `.mesh-runtime-state/p12-postgres-proof/migration-rehearsal.json` for `local-compose`, applied `7` migrations through `005_relationship_infra_node_key`, and rolled back to the pre-migration schema. `scripts/verify_migration_rehearsal.py --proof .mesh-runtime-state/p12-postgres-proof/migration-rehearsal.json --expected-version 005_relationship_infra_node_key --expected-combined-sha256 79b1044064bc3a46ebf95ba591f772713fc8dc9ff91b89fad2f9277fb12501d5 --json` passed. `scripts/verify_postgres_restart_proof.py --database-url postgresql://mesh:mesh@127.0.0.1:5432/mesh --state-dir .mesh-runtime-state/p12-postgres-proof/restart --json` passed with run `run_20260523T024522_06a29b42` and stable Merkle root `51de1643ca48aebbc94dd11f60a610a54868d7f0a7fbad6c3f750b6be8c26054`. Current-head backup/restore proof now exists: `scripts/run_backup_restore_rehearsal.py --database-url postgresql://mesh:mesh@127.0.0.1:5432/mesh --environment pilot --operator-id platform@example.com --output .mesh-runtime-state/backup-restore-rehearsal.json --artifact-dir .mesh-runtime-state/backup-restore-rehearsal --json` generated rehearsal `backup_restore_20260523T044709Z` with RPO `2` seconds, RTO `900` seconds, measured restore `0.057` seconds, and restored `state_store`, `vault`, `merkle_proofs`, `integrations_config`, and `research_artifacts`; `python3 scripts/verify_backup_restore_rehearsal.py --proof .mesh-runtime-state/backup-restore-rehearsal.json --expected-environment pilot --expected-state-backend postgres --json` passed. Readiness clears `backup_restore_rehearsal_verified` when `MESH_READINESS_PROFILE=pilot`, `MESH_STATE_BACKEND=postgres`, `MESH_DATABASE_URL`, and `MESH_BACKUP_RESTORE_REHEARSAL_PATH=.mesh-runtime-state/backup-restore-rehearsal.json` are set. Boundary: production/staging target claims and release provenance still need this proof rerun against target Postgres and durable backup storage.

### P13 Ingress And Deployment

State slice: `authenticated-ingress-deployment.v1`

Tasks:

- Prove TLS, auth, role headers, header stripping, private upstream, audit identity, and no raw secrets.
- Keep `MESH_SERVER_HOST=127.0.0.1` or private bind behind the reverse proxy.
- Verify public landing and protected app/control-plane split.
- Rehearse rollback for the preview and target deployments.

Done: no unauthenticated public control-plane path exists and operator identity reaches Mesh audit records.

Current evidence: `scripts/verify_authenticated_ingress.py --json` passed locally with run `run_20260523T051415_acc2dca8`, proving anonymous run creation is denied, viewer run creation is denied, viewer policy simulation is accepted without mutation, launcher run creation stores proxy-header identity, launcher approval is denied, approver approval is accepted, launcher kill-switch access is denied, and admin kill-switch access is accepted. Deployment-proof tests cover `mesh.authenticated_ingress_deployment_proof.v1` schema validation, nonlocal environment matching, HTTPS ingress URL, TLS termination evidence, identity-provider enforcement, Mesh header sanitization, role mapping, private upstream boundary, app rehearsal reference, audit identity evidence, no raw secret material, readiness blocking, and CLI verification. Root `test:focused` now includes `tests.test_authenticated_ingress`, `tests.test_authenticated_ingress_deployment`, and `tests.test_operator_ingress`; `lint:fast` compiles the authenticated ingress module and proof scripts. The current pilot deployment packet also verifies: `python3 scripts/verify_authenticated_ingress_deployment.py --proof .mesh-runtime-state/proofs/authenticated-ingress-deployment-proof.json --expected-environment pilot --json` passes for proof `local_authenticated_ingress_rehearsal_20260507` with `environment=pilot`, HTTPS ingress URL `https://mesh.pilot.local`, TLS termination, OIDC enforcement, Mesh header sanitization, complete role mapping, private upstream network boundary, audit identity, passing app rehearsal, and no raw secret material. This clears the local pilot authenticated-ingress readiness blocker; production or staging targets still need their own environment-bound proof packet.

### P14 Release Assurance

State slice: `release-provenance-current-head.v1`

Tasks:

- Build from clean current `HEAD`.
- Generate SBOM, vulnerability scan, base image digest metadata, CI attestation, signed policy proof, migration proof, and release provenance.
- Bind deployed runtime `/api/health` commit and image digest to the release packet.
- Keep old packets historical.

Done: the release packet proves the exact code and image that the runtime is serving.

Current evidence: release provenance now uses the pnpm lockfile set (`pyproject.toml`, `uv.lock`, and `pnpm-lock.yaml`) instead of stale deleted npm lockfiles. Focused release tests pass for provenance generation, runtime binding, assurance artifact normalization, release image metadata, and image handoff. Root `test:focused` now includes these P14 modules, and `lint:fast` compiles the release provenance, runtime binding, assurance, metadata, CI attestation, image assurance, and handoff scripts. On 2026-05-23, `Dockerfile` was refreshed to Docker CLI `29.5.2` and kubectl `v1.36.1`; kubectl is now built from the Kubernetes `v1.36.1` source tarball in a checksum-pinned `golang:1.26.3-bookworm` builder stage instead of consuming the official kubectl binary built with Go `1.26.2`. `docker build --pull --build-arg MESH_BUILD_VERSION=p14-kubectl-go1263 --build-arg MESH_BUILD_COMMIT=$(git rev-parse HEAD) -t orbital-mesh-stack:p14-kubectl-go1263 .` passed; `docker run --rm orbital-mesh-stack:p14-kubectl-go1263 sh -lc 'docker --version && kubectl version --client=true -o yaml && python3 --version && hermes version'` reported Docker `29.5.2`, kubectl `v1.36.1` built with `go1.26.3`, Python `3.13.13`, and Hermes `0.9.0`. `scripts/collect_release_image_metadata.py --image-tag orbital-mesh-stack:p14-kubectl-go1263 --output .mesh-runtime-state/release-image-metadata-p14-kubectl-go1263.json --base-image-args .mesh-runtime-state/base-image-digest-p14-kubectl-go1263.args` passed and bound local image digest `sha256:af36481183033d5dd3aa0e7a9542068ebdbb71e3e87e4c0fb893f3bb34f1eef8` plus digests for `node:22-bookworm-slim`, `debian:12-slim`, `golang:1.26.3-bookworm`, `rust:1.92-slim-bookworm`, `python:3.13-slim-trixie`, and `python:3.11-slim-bookworm`. `scripts/generate_release_image_assurance.py` without the expired exception policy wrote digest-matched artifacts under `.mesh-runtime-state/release-assurance-local/normalized-p14-kubectl-go1263/` and failed closed with 14 unaccepted high/critical findings, down from 20 because the kubectl Go stdlib findings are gone. The remaining blockers are Python `3.13.13` and Debian trixie libc/ncurses packages. A local image-bound rehearsal packet at `.mesh-runtime-state/release-provenance-p14-kubectl-go1263-rehearsal.json` returned `status=incomplete`, packet SHA `9e6624d0fa3d6f20beecef1315da0118e950de3ad099d6e9c716f8f890812707`, and only `vulnerability_scan_path` plus `ci_attestation` missing after allowing the dirty tree and supplying local image, base image, migration, policy, SBOM, and build-command inputs. After the repo-local commit step and local image rebuild, strict `scripts/generate_release_provenance.py --require-complete --json` against `.mesh-runtime-state/release-provenance-p14-current-rehearsal.json` fails closed with `git.dirty=false` and only `vulnerability_scan_path` plus `ci_attestation` missing. Because docs commits advance `HEAD`, this ignored local rehearsal must be regenerated after the final commit before it can be cited as current-head evidence. The normalized current-head Grype scan still has 14 unaccepted high/critical findings. `scripts/verify_release_runtime_binding.py --json` fails with `release_provenance_path` missing until a complete release provenance packet is generated and supplied or exported through `MESH_RELEASE_PROVENANCE_PATH`.

2026-07-13 current-head correction: the vulnerability-exception policy is valid through 2026-08-06, and origin-main CI run `28631099377` recorded zero unaccepted findings for commit `97be17e`; that evidence does not apply to later local commits. The control-plane Dockerfile now removes Git after build-time use, so the local release-cut source gate passes. Repo-patch deployment uses three distinct images: the control plane has no Git, the authority alone retains Git, and the verifier is a minimal Python/cryptography runtime. `mesh.repo_patch_service_image_bundle.v1` additively requires exact commit, Dockerfile, immutable image, SBOM, normalized scan, GitHub Actions attestation, and verifier signer/sandbox bindings for all three roles. Local Docker builds and OS proofs pass, but same-database local normalized assurance reports 43 unaccepted findings for the control plane and three each for authority and verifier; the image IDs are also not registry manifest digests or GitHub attestations. P14 therefore remains blocked until reviewed VEX, fixed dependencies, or an authorized exception reduces every role to zero unaccepted findings, current-head CI builds, scans, attests, and publishes the three roles, and a deployed runtime binds the complete control-plane release packet plus the verified role bundle.

2026-07-13 superseding local remediation result: Docker CLI `v29.6.1` and kubectl `v1.36.2` are now built from pinned source with Go `1.26.5`, and the release-assurance generator applies a proof-bound, exact-predicate correction for Syft `1.44.0` issue 5057 while preserving the full raw SBOM. A current-database control-plane scan now has 30 blocking findings, 28 existing-policy acceptances, and two unaccepted findings: `CVE-2026-15308` on Python `3.13.14` and `CVE-2026-7017` on `perl-base` `5.40.1-6`. Authority and verifier retain one unaccepted `CVE-2026-15308` finding each. No new exception was added. The exact-commit GitHub workflow now builds, scans, publishes, attests, and verifies all three immutable role images only after every role reaches zero unaccepted findings. P14 remains blocked on the four role-level findings, live workflow evidence, and deployed-runtime binding; the dirty-tree local image is measurement evidence only and is not a current-head release artifact.

### P15 Mesh Brain

State slice: `mesh-brain-controlled-canary.v1`

Tasks:

- Configure durable artifact URI prefix, artifact registry, artifact upload proof, serving base URL, serving model, model-kernel gate, live canary smoke, single lane proof, rollback drill, and run export refs.
- Keep broad model-serving production blocked until the proof stack exists.
- Surface readiness blockers clearly in product UI and go/no-go packets.

Done: Mesh Brain can participate in a controlled pilot without overstating model-serving maturity.

Current evidence: `python -m mesh_brain.run_model_kernel_probe --output .mesh-runtime-state/p15-mesh-brain-proof/model-kernel --benchmark-iterations 20 --json` passed with release decision `pass`, deterministic digest `03f68ae7fd8c39521a3bc4a27486428278656a45268e5d3b4cb22295678d6a65`, max gradient relative error `5.2565e-08`, Q4.12 logit delta `1.212297e-05`, and local reference runtime execution. `run_mesh_brain_rollback_drill(output_directory=.mesh-runtime-state/p15-mesh-brain-proof/rollback-drill, tenant_id=tenant_a, task_type=crops)` passed with release decision `pass`, restored previous artifact `mb_artifact_030a6bb20dde`, retired candidate `mb_artifact_15897565dd02`, and wrote rollback manifest, metrics, before/after catalog, and audit-event artifacts. Focused P15 tests pass for durable artifact URI validation and upload-proof enforcement, model-kernel artifacts, live-serving smoke gate/eval/release decisions, model-management canary/promotion/rollback controls, control-plane run records, backend-matrix aggregation, readiness gap reporting, and pilot go/no-go Mesh Brain evidence binding. The root `test:focused` gate now includes these P15 modules, and `lint:fast` compiles the Mesh Brain proof modules and artifact-registry verifier. On 2026-05-23 the local E2E overlay also supplied `MESH_BRAIN_ARTIFACT_URI_PREFIX=s3://mesh-e2e/mesh-brain`, `/app/.mesh-runtime-state/e2e/mesh-brain-artifacts.json`, `/app/.mesh-runtime-state/e2e/mesh-brain-artifact-upload-proof.json`, `MESH_BRAIN_SERVING_BASE_URL=http://mesh-brain-serving:8000`, and `MESH_BRAIN_SERVING_MODEL=mesh-brain-e2e-local`. The control-plane go/no-go packet observed model-kernel run `run_20260523T052801_58d01fb1`, live canary smoke run `run_20260523T053440_0bfaa6dd`, one CROPS canary lane for `tenant_a`, and rollback drill run `run_20260523T052801_12a88f6f`; all Mesh Brain checks passed. Boundary: this is local E2E overlay canary evidence, not production durable artifact-store evidence for an external target.

### P16 Praxis

State slice: `praxis.managed-dry-run-runtime.v1`

Tasks:

- Keep Praxis as a Mesh-governed MCP connector factory.
- Bind source bundle, generated MCP contract, Akto evidence, Mesh certification binding, dry-run endpoint, revocation, and proof export.
- Keep Docker Dynamic MCP session-only and dry-run unless Mesh certification and target proof admit exact scopes.
- Block code-mode and managed pilot runtime deployment until production-like proof, live ownership, and credential rotation evidence exist.

Done: Praxis generates candidate tools while Mesh owns certification, policy, approval, audit, runtime posture, and revocation.

Current evidence: `python3 scripts/verify_praxis_contracts.py` passed and validates the P1 Praxis contract fixture against generation request, source bundle, generated MCP contract, Akto evidence, ACP session, and certification-binding schemas. `python3 scripts/verify_praxis_proof_packet.py` passed against `fixtures/praxis/p8_proof_packet.json`. Focused Praxis tests pass for redacted source intake, raw-secret rejection, fail-closed MCP tool generation, Akto evidence as advisory-only, certification binding that admits only read-only tools and denies unsafe mutation, proof packet blocking on broken source binding, managed dry-run runtime persistence, Docker Dynamic MCP safety policy, MCP JSON-RPC listing/calling only certified read-only tools, revocation, P10 proof export, team-scoped HTTP API persistence, and product dashboard exposure. The proof packet keeps `managed_runtime_deployed=false`, `dry_run_only=true`, Akto non-authoritative, and Mesh-owned revocation, so P16 is complete as a bounded dry-run lane, not as production actuator authority.

### P17 Agent Flow And Harper-696

State slices: `mesh.agent_flow.chat_response.v1`, `mesh.agent_flow.livekit_session.v1`, `mesh.agent_flow.mutation_preview.v1`

Tasks:

- Keep chat grounded in `/api/operator/dashboard` read-only state.
- Mint short-lived LiveKit browser tokens only for allowed operator roles.
- Scope room and participant identity to operator/team context.
- Validate mutation previews by schema, id, draft status, endpoint, resource type, state slice, proof slice, issued scope, issued operator, and HMAC proof.
- Require Mesh-owned endpoints for any real mutation.

Done: Harper-696 assists, explains, and drafts. It does not execute production actions.

Current evidence: `tests.test_operator_auth_http.OperatorAuthHttpTests.test_agent_flow_chat_livekit_and_confirmation_are_session_scoped` passed and covers unconfigured LiveKit fallback, pre-minted token handling, expired-token rejection, server-side LiveKit token minting without leaking the API secret, microphone-only browser publish grants, dashboard-grounded Harper chat response, signed `mesh.agent_flow.mutation_preview.v1` drafts, same-scope confirmation, tampered preview rejection, proof-slice rejection, cross-session confirmation rejection, and confirmation records with `side_effects_executed=false`. `tests.test_operator_product_contracts.OperatorProductContractTests.test_product_auth_dashboard_and_settings_responses_match_schema` passed and validates the dashboard `mesh.agent_flow.dashboard.v1` read model. `corepack pnpm --dir meshapp/frontend run test -- ProductApp.dashboard.test.tsx` passed with frontend helper coverage for fresh LiveKit sessions, unavailable voice states, and `mesh.agent_flow.livekit_session.v1` failure messaging. P17 is complete as an assistant and draft-preview lane; real mutations still require Mesh-owned routes.

### P18 Hardened Arena

State slice: `hardened-arena.*.v1`

Tasks:

- Keep profile registry, catalog ingest, packet generator, intent generator, proof runner, API, UI, and release-readiness wiring.
- Do not turn image selection or chart selection into a readiness claim.
- Validate each target with observed health, readiness, identity, persistence, feedback, audit, rollback, run export, kill switch, cleanup, and release-packet binding.

Done: the arena can produce proof packets for exact targets and can be sold or used internally without pretending every target is validated.

Current evidence: `python3 scripts/verify_hardened_arena_profiles.py --json` passed with `3` profiles and registry SHA `a8573b4de973688a6e865c8702c23f8d441c71b1e35bade1bd5e292f86d35229`. `python3 scripts/verify_hardened_arena_catalog.py --json` passed with `523` catalog entries, `445` images, `78` charts, and catalog SHA `7a130b758f55b34b3ec80acfbf4343b302b9c3d8503a52681a7fd488df1e2b10`. Focused hardened-arena tests pass for profile validation, catalog import, packet generation/verification, intent generation/verification, proof runner/verifier, API surfaces, and release-readiness integration. The API surface includes review-only packet creation and review-only intent creation; both require operator identity and return no-deploy/no-secret/no-kubeconfig posture. The proof runner requires observed health, readiness, identity, persistence, feedback, audit, rollback, run export, kill switch, cleanup, and release-packet binding evidence; `target_validated` additionally requires a verified packet ref for the same profile and rejects profile mismatch, missing packet refs, unresolved blockers, raw secrets, and readiness overclaims. `lint:fast` now compiles the hardened-arena modules and CLIs. P18 is complete as a target-proof capability; no specific external target is promoted without its own proof packet.

### P19 Deployment Compatibility

State slice: `deployment-compatibility.v1`

Tasks:

- Keep Docker Compose and Kubernetes as validated paths.
- Promote ECS/Fargate or other targets only through target-specific proof.
- Add Helm, Terraform, marketplace, and ingress-controller-specific packages only after the runtime proof shape is stable.
- Keep recipe, backlog, and not-planned targets distinct.

Done: deployment claims are machine-checkable and cannot drift into unsupported platform claims.

Current evidence: `python3 scripts/verify_deployment_compatibility.py --json` passed with registry SHA `3faabefdfb61625b32b3d4d43a16faf817f878ee33e8fda7894f566f21d5a7e4`, `7` targets, validated targets `docker_compose` and `kubernetes`, and next validated target `ecs_fargate`. Focused deployment tests pass for the default registry, release-packet enforcement on validated targets, ECS/Fargate next-target blocking, valid ECS/Fargate promotion proof, local-environment rejection, missing-feedback rejection, raw-secret rejection, and CLI verification. The root `test:focused` gate now includes `tests.test_deployment_compatibility` and `tests.test_ecs_fargate_promotion`, and `lint:fast` compiles the deployment compatibility and ECS/Fargate modules and CLIs. ECS/Fargate is not promoted: `python3 scripts/verify_ecs_fargate_promotion.py --proof .mesh-runtime-state/ecs-fargate-promotion-proof.json --json` fails closed because the proof packet is missing, leaving all target-specific checks false.

### P20 Load And Concurrency

State slice: `load-concurrency-rehearsal.v1`

Tasks:

- Prove multi-operator load, tenant active-run quotas, target locks, cancellation, recovery, event persistence latency, queue backpressure, and stuck-run recovery.
- Run under the same state backend and ingress pattern intended for production.

Done: the product can handle concurrent operator use without losing admission, event, approval, or export correctness.

Current evidence: `python -m unittest tests.test_load_concurrency_rehearsal -v` passed, proving the `mesh.load_concurrency_rehearsal.v1` proof schema, runner packet builder, CLI verifier, local-file-backend rejection, expansion readiness blocker when the proof is missing, and runner skip behavior when `MESH_DATABASE_URL` is absent. The root `test:focused` gate includes `tests.test_load_concurrency_rehearsal`, and `lint:fast` compiles `shared/mesh_runtime/load_concurrency.py`, `scripts/run_load_concurrency_rehearsal.py`, and `scripts/verify_load_concurrency_rehearsal.py`. `scripts/run_load_concurrency_rehearsal.py --database-url postgresql://mesh:mesh@127.0.0.1:5432/mesh --environment pilot --operator-id platform@example.com --output .mesh-runtime-state/load-concurrency-rehearsal.json --json` passed against local compose Postgres and wrote rehearsal `load_concurrency_20260523T043850Z` with `24` runs, `3` concurrent operators, `4` workers, queue size `8`, max queue depth `8`, `25` rejected runs, tenant quota enforcement, target-lock conflict, cancellation, stuck-run recovery, backpressure, p95 admission latency `1.025` ms, p95 event persistence latency `1.025` ms, and no raw secret material. `python3 scripts/verify_load_concurrency_rehearsal.py --proof .mesh-runtime-state/load-concurrency-rehearsal.json --json` passes all checks, and `MESH_READINESS_PROFILE=expansion MESH_LOAD_CONCURRENCY_REHEARSAL_PATH=.mesh-runtime-state/load-concurrency-rehearsal.json` leaves `load_concurrency_rehearsal_verified` out of the readiness blockers. This clears the current local pilot Postgres P20 packet; a separate target run is still required before making production-expansion capacity claims for another deployed environment.

### P21 Production Target Proof

State slice: `production-target-proof.v1`

Tasks:

- Capture target proof for one bounded production-like environment.
- Bind authenticated ingress, identity, telemetry, feedback, secret references, credential rotation, rollback, approval, postmortem export, governance refs, recovery refs, and replay refs.
- Reject fixture-only or dirty-env proof.

Done: the target environment has live evidence for the same bounded path the pilot will use.

Current evidence: `python3 -m unittest tests.test_production_live_proof_bundle tests.test_production_target_proof -v` passed, proving the `mesh.production_target_proof.v1` schema, CLI verifier, required-live fail-closed behavior, `mesh.production_live_proof_capture.v1` capture path, and `mesh.production_live_proof_bundle.v1` generator path for target packets. The capture script calls the live API run, event, export, timeline, Merkle, health, readiness, and kill-switch endpoints, then the generator copies observed API artifacts into a bundle, binds the target run to release/runtime/on-call evidence, and runs the target verifier as part of bundle generation. Historical live target proof exists: `python3 scripts/verify_production_target_proof.py --proof .mesh-runtime-state/live-proof-583/proofs/production-target-proof.json --expected-environment pilot --require-live --json` passes for run `run_20260510T204446_330aa693` and target `kubernetes://pilot/edge/api-gateway`. The older `.mesh-runtime-state/live-proof-current/proofs/production-target-proof.json` proof window passed for commit `cfd9f3b18d0d0bd87a59056faaa442ae73994573` and run `run_20260523T072245_108d1468`, but no mounted proof bundle in this workspace clears the current branch head. P21 is complete for the target-proof contract and historical pilot packet; P24 still blocks the current aggregate autonomy claim.

### P22 Watch Mode

State slice: `watch-mode-proof.v1`

Tasks:

- Capture live watch proof with multiple ticks, unique run IDs, duplicate suppression, provider failure, recovered provider failure, kill-switch pause, exports, and replay refs.
- Keep fixture packets out of live production claims.

Done: watch mode can run under bounded production posture without duplicate spam, hidden failure, or unreviewed actuation.

Current evidence: `python3 -m unittest tests.test_production_live_proof_bundle tests.test_watch_mode_proof -v` passed, proving the `mesh.watch_mode_proof.v1` verifier, required-live fail-closed behavior, and the bundle generator path for watch-mode packets. The generated packet includes multiple live-shaped ticks, duplicate suppression, healthy suppression, provider failure recovery, kill-switch pause, run exports, postmortem refs, redaction, and third-party replay refs from supplied observed artifacts. Historical live watch proof exists: `python3 scripts/verify_watch_mode_proof.py --proof .mesh-runtime-state/live-proof-583/proofs/watch-mode-proof.json --expected-environment pilot --require-live --json` passes for runs `run_20260510T204446_330aa693` and `run_20260510T204458_06e0ab59`. The older `.mesh-runtime-state/live-proof-current/proofs/watch-mode-proof.json` proof window passed for target run `run_20260523T072245_108d1468` and repeat run `run_20260523T072442_5925b9e0`, but no mounted proof bundle in this workspace clears the current branch head. P22 is complete for the watch-mode contract and historical pilot proof window; P24 still blocks the current aggregate autonomy claim.

### P23 Incident Coverage

State slice: `incident-coverage-proof.v1`

Tasks:

- Cover crash loops, bad deploy/image, readiness degradation, config drift, feature-flag regression, telemetry degradation, queue/resource pressure, external provider failure, partial outage, and false positives.
- Require live run IDs and artifact refs from the same proof window.

Done: production incident claims are based on broad enough live coverage to be credible.

Current evidence: `python3 -m unittest tests.test_production_live_proof_bundle tests.test_incident_coverage -v` passed, proving the `mesh.incident_coverage_proof.v1` verifier, required incident class set, fixture/live separation, and the bundle generator path for live-shaped coverage. The generated packet covers `crash_loop`, `bad_deploy_image`, `readiness_degradation`, `config_drift`, `feature_flag_regression`, `telemetry_degradation`, `queue_resource_pressure`, `external_provider_failure`, `partial_outage`, and `false_positive_controls` with run IDs and artifact refs from the supplied proof window. Historical live incident coverage exists: `python3 scripts/verify_incident_coverage_proof.py --proof .mesh-runtime-state/live-proof-583/proofs/incident-coverage-proof.json --require-live --json` passes for all required classes. The older `.mesh-runtime-state/live-proof-current/proofs/incident-coverage-proof.json` proof window passed for all required incident classes, but no mounted proof bundle in this workspace clears the current branch head. P23 is complete for the incident-coverage contract and historical pilot proof window; P24 still blocks the current aggregate autonomy claim.

### P24 Autonomy Clearance

State slice: `production-autonomy-clearance.v1`

Tasks:

- Bind repeatability, production target, provider action scope, watch mode, incident coverage, and on-call drill packets.
- Require same target refs and same bounded run set.
- Keep broad production autonomy blocked until aggregate verifier passes without fixture or dirty-env relaxations.

Done: production autonomy is an earned per-action-class clearance, not a global switch.

Current evidence: `python3 -m unittest tests.test_production_live_proof_bundle tests.test_production_autonomy_clearance tests.test_repeatability_proof tests.test_on_call_drill -v` passed, proving repeatability, on-call drill, aggregate production-autonomy clearance, the `mesh.production_live_proof_capture.v1` capture path, and the `mesh.production_live_proof_bundle.v1` generator path. The capture script records live API artifacts and the generator writes repeatability, production-target, provider action-scope, watch-mode, incident-coverage, release runtime-binding, and aggregate verification artifacts from one observed live evidence set. It only returns `pass` when the aggregate verifier passes and the supplied `mesh.release_runtime_binding.v1` packet is current-head, image-digest matched, runtime-env populated, and backed by `/api/health` or image-ref evidence. `--allow-partial` records missing evidence such as dirty or unrecreated repeatability or missing runtime-binding evidence without clearing readiness. Historical live aggregate evidence exists under `.mesh-runtime-state/live-proof-583/proofs/`. The older `.mesh-runtime-state/live-proof-current/proofs/` proof window passed production-target, provider action-scope, watch-mode, and incident-coverage verifiers for commit `cfd9f3b18d0d0bd87a59056faaa442ae73994573`, target run `run_20260523T072245_108d1468`, and repeat run `run_20260523T072442_5925b9e0`, but no mounted proof bundle in this workspace clears the current branch head. P24 remains blocked until a fresh current-head proof capture/generation is produced after release provenance/runtime binding is supplied. Current-head replay-only proof generation is also blocked by below-threshold compose-chaos summaries.

### P25 Controlled Pilot

State slice: `pilot-go-no-go.v1`

Tasks:

- Deploy one production environment, one or two low-blast-radius services, one namespace allowlist, approval gate default, and clear customer/user consent.
- Generate readiness, go/no-go, signoff, on-call drill, release provenance, backup/restore, ingress, provider proof, and design-partner packets.
- Execute one approved action that succeeds or cleanly rejects with human review.
- Prove kill switch, watcher pause, bad target revocation, key rotation, rollback, restore, and blocked missing evidence.

Done: pilot clearance is generated from observed evidence and signed by the required operator role.

Current evidence: `python -m unittest tests.test_verify_pilot_clearance tests.test_pilot_clearance_audit tests.test_pilot_signoff -v` passed with 19 tests, proving clearance-mode success/failure, expected-blocked auditing, runtime commit/image binding, endpoint failure handling, signed signoff schema validation, authorized-role enforcement, HMAC signature validation, go/no-go packet hash matching, release provenance SHA matching, and refusal to build signoff for a blocked go/no-go packet. The root `test:focused` gate now includes these P25 tests, and `lint:fast` compiles `shared/mesh_runtime/pilot_signoff.py`, `scripts/verify_pilot_clearance.py`, and `scripts/verify_pilot_signoff.py`. The first documented stack smoke run failed because the runtime image installed `psycopg[binary]` without the separate pool extra required by the Postgres state backend. `Dockerfile` now installs `psycopg[binary,pool]>=3.2,<4`, matching `pyproject.toml`; after `docker compose -f docker-compose.stack.yml down`, `docker compose -f docker-compose.stack.yml up --build --abort-on-container-exit --exit-code-from mesh-smoke mesh-smoke` rebuilt the image, installed `psycopg-pool-3.3.1`, reached `orbital-mesh-stack` healthy, and exited `0` with smoke run `run_20260523T043031_f55fbea8` and `execution_status=succeeded`. The denied-action proof is observed from live local run `run_20260523T050025_ed9817d1`, launched through `/api/runs` with `scenario_key=kubernetes_crashloop_patch`; it stopped at `awaiting_operator`, `pending_pause_stage=evaluation_ready`, `evaluation.passed=false`, and `final_recommendation=human_review` with blocking reasons `approval required before execution`, `confidence below minimum threshold`, `approval_required_before_execution`, and `remediation safety case has hard stops`. On 2026-05-23 the E2E overlay cleared the local pilot packet: `docker exec -w /workspace/orbital-mesh orbital-mesh-stack python3 scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 45 --expected-head cfd9f3b18d0d0bd87a59056faaa442ae73994573 --json` returned `status=pass`, `mode=clearance`, `/api/readiness status=ready`, `/api/pilot/go-no-go status=go`, `missing=[]`, release provenance packet SHA `3027c613c9088247a1ae092df35a5606891896c4ccb52515000e86388f29ae20`, runtime image digest `sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`, and runtime commit matching current head. Captured `.mesh-runtime-state/e2e/pilot-go-no-go.json` signed into `.mesh-runtime-state/e2e/pilot-signoff.json`; `python3 scripts/verify_pilot_signoff.py --signoff .mesh-runtime-state/e2e/pilot-signoff.json --go-no-go .mesh-runtime-state/e2e/pilot-go-no-go.json --signing-key mesh-e2e-pilot-signoff-key --json` returned `status=pass`, `go_no_go_packet_sha256=80fa4823733582bca459fefe757053b2e1e6c48223f56623ef78d17d8c45b586`, and `release_provenance_packet_sha256=3027c613c9088247a1ae092df35a5606891896c4ccb52515000e86388f29ae20`. Boundary: this clears the local E2E overlay pilot and signoff packet, not a clean release cut; P14 and P24 still block a production-ready claim.

### P26 Public And Enterprise Proof

State slice: `docs-and-public-proof.v1`

Tasks:

- Produce architecture brief, benchmark report, limitations statement, design-partner packet, security packet, API contract bundle, reference deployment packet, and procurement/security package.
- Keep market, certification, "best", "only", and broad production claims out unless independently evidenced.
- Make every public proof reproducible from commands and artifacts.

Done: external readers can verify what is real, what is blocked, and what is proposal-only.

Current evidence: `python -m unittest tests.test_design_partner_packet tests.test_procurement_security_package tests.test_public_proof_package -v` passed with 14 tests, proving design-partner packet validation/failure behavior, procurement package coverage, public proof package coverage, artifact-ref checks, limitations-ref checks, and readiness blockers for missing expansion packets. `python3 scripts/verify_procurement_security_package.py --json`, `python3 scripts/verify_public_proof_package.py --json`, and `python3 scripts/verify_security_audit_readiness.py --json` pass. The root `test:focused` gate now includes the P26 tests, and `lint:fast` compiles `shared/mesh_runtime/design_partner.py`, `shared/mesh_runtime/procurement_security.py`, `shared/mesh_runtime/public_proof.py`, `scripts/verify_design_partner_packet.py`, `scripts/verify_procurement_security_package.py`, `scripts/verify_public_proof_package.py`, and `scripts/verify_security_audit_readiness.py`. On 2026-05-23 `.mesh-runtime-state/proofs/design-partner-packet.json` was rebound to the local E2E pilot packet; `python3 scripts/verify_design_partner_packet.py --packet .mesh-runtime-state/proofs/design-partner-packet.json --expected-go-no-go-sha 80fa4823733582bca459fefe757053b2e1e6c48223f56623ef78d17d8c45b586 --expected-release-provenance-sha 3027c613c9088247a1ae092df35a5606891896c4ccb52515000e86388f29ae20 --json` returned `status=pass`, with `evidence_summary_go`, expected go/no-go SHA match, expected release-provenance SHA match, schema, partner, bounded scope, metrics, data handling, support, rollback, consent, and no-raw-secret checks all true. Boundary: this is a local E2E design-partner packet for `local-pilot-rehearsal`; real customer/public claims still require target-specific publication, benchmark, support, and partner evidence.

## Validation Ladder

Fast preflight:

```bash
git status --short --branch
pnpm run lint:fast
git diff --check
```

Contract gate:

```bash
pnpm run verify:contracts
```

Focused behavior gate:

```bash
pnpm run test:focused
```

Product gate:

```bash
pnpm run test:product:e2e
pnpm --dir meshapp/frontend run test
pnpm --dir meshapp/frontend run lint
```

Auth provider gate:

```bash
pnpm run test:auth-provider:smoke
pnpm run auth-provider:live-preflight
pnpm run auth-provider:live-stack-smoke
pnpm run auth-provider:checkpoint
pnpm run auth-provider:live-attempt
pnpm run test:auth-provider:live
```

Release and readiness gate:

```bash
scripts/verify_release_cut_list.py --json
scripts/generate_release_provenance.py --require-complete --json
scripts/verify_pilot_clearance.py --base-url <mesh-host> --timeout-seconds 30 --expected-head "$(git rev-parse HEAD)" --json
```

Blocked pilot audit:

```bash
scripts/verify_pilot_clearance.py \
  --base-url <mesh-host> \
  --timeout-seconds 30 \
  --expect-blocked \
  --json
```

Full local gate:

```bash
pnpm run verify:full
pnpm run lint
git diff --check
git status --short --branch
```

Compose config gate:

```bash
docker compose -f docker-compose.stack.yml -f docker-compose.e2estack.yml config --quiet
docker compose -f docker-compose.prod.yml config --quiet
```

Live target proof gates, as applicable:

```bash
scripts/verify_authenticated_ingress_deployment.py --proof "$MESH_AUTHENTICATED_INGRESS_PROOF_PATH" --json
scripts/verify_backup_restore_rehearsal.py --proof "$MESH_BACKUP_RESTORE_REHEARSAL_PATH" --json
scripts/verify_credential_rotation.py --proof <credential-rotation-proof.json> --json
scripts/verify_provider_action_scopes.py --proof <provider-action-scope-proof.json> --require-live --json
scripts/capture_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --release-provenance <release-provenance.json> --release-runtime-binding <release-runtime-binding.json> --on-call-drill <on-call-drill.json> --allow-partial
scripts/generate_production_live_proof_bundle.py --output-dir .mesh-runtime-state/live-proof-current --clean-env-recreated --fresh-image-built ...
scripts/verify_watch_mode_proof.py --proof <watch-mode-proof.json> --require-live --json
scripts/verify_incident_coverage_proof.py --proof <incident-coverage-proof.json> --require-live --json
scripts/verify_repeatability_proof.py --proof <repeatability-proof.json> --expected-head "$(git rev-parse HEAD)" --json
scripts/verify_production_target_proof.py --proof <production-target-proof.json> --expected-environment <target-env> --require-live --json
scripts/verify_load_concurrency_rehearsal.py --proof <load-concurrency-proof.json> --json
scripts/verify_production_autonomy_clearance.py --json
```

## Evidence Binder

Each slice report must include:

- state slice touched;
- files changed;
- commands run;
- exact pass/fail status;
- artifact paths generated;
- endpoint URLs queried;
- current `git rev-parse HEAD`;
- whether the tree was clean or dirty;
- release image digest, if relevant;
- runtime `/api/health` commit and image digest, if relevant;
- blockers and their env vars or proof paths;
- remaining non-claims.

Use committed docs for durable proof summaries. Use ignored `.mesh-runtime-state/` only for generated runtime evidence. Never commit raw generated state unless a deterministic fixture is explicitly required by a test or doc.

## Publishing Workflow

Use normal local git only after focused validation is clean.

1. Inspect:

```bash
git status --short --branch
git diff --check
```

2. Stage only the slice-owned files.
3. Commit with a message naming the state slice.
4. Push through the configured `no-mistakes` remote instead of `origin`:

```bash
git push no-mistakes
```

5. Attach to the gate when interactive monitoring is needed:

```bash
no-mistakes
```

6. Review no-mistakes findings, CI, and the created PR.
7. Merge only after local validation, no-mistakes gate, PR review, and CI agree.

The no-mistakes gate runs in a disposable worktree and can rebase, review, test, document, lint, push upstream, open or update a PR, watch CI, and apply approved fixes. It does not replace local slice discipline.

## Stop Conditions

Stop and report instead of continuing when:

- a required edit overlaps unrelated user changes;
- live proof would require secrets that are not already configured through ignored local env or platform secret stores;
- a command would expose tokens, cookies, OAuth codes, kubeconfigs, or provider credentials;
- two identical errors happen and the repeated-error research step has not been done;
- a target proof is fixture-only but the task asks for production or live clearance;
- release provenance references a different commit or image than the deployed runtime;
- `/api/health` reports `commit=unknown` or `image_digest=null` during a release-bound claim;
- no-mistakes or CI rewrites the branch in a way that changes slice ownership.

## Definition Of Done

This goal is done when:

- `pnpm run lint` passes on the exact committed head.
- `pnpm run verify:full` passes on the exact committed head.
- Current-head release provenance is complete.
- Runtime health metadata matches the release provenance commit and image digest.
- `/api/readiness` is ready for the intended profile.
- `/api/pilot/go-no-go` is `go` with empty missing evidence for the intended target.
- Authenticated ingress, provider auth, backup/restore, credential rotation, run export, on-call drill, watch mode, incident coverage, production target, provider action scopes, repeatability, and load/concurrency have target proof packets.
- Broad production autonomy is either verified by aggregate clearance or explicitly remains disabled and non-claimed.
- Product app workflows are tested end to end.
- Public/protected deployment boundaries are verified.
- Docs name exact limitations and do not rely on historical packets for current release claims.
- PR is opened through `no-mistakes`, CI is clean, review is complete, and merge uses the validated PR path.
