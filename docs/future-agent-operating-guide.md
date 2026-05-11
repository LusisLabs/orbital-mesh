# Future Agent Operating Guide

Use this guide before changing `orbital-mesh`. It ranks source material, names active surfaces, and defines validation by change type. It does not grant authority to change runtime behavior.

## Source-Of-Truth Hierarchy

1. Current code and config win over prose: `control_plane_server.py`, `services/`, `shared/mesh_runtime/`, `mesh_brain/`, `meshapp/`, `web/`, `scripts/`, `config/`, `policies/`, and `docker-compose*.yml`.
2. Contracts win over inferred shapes: JSON Schemas in `shared/mesh_runtime/schemas/` plus Python dataclasses and validators in `shared/mesh_runtime/contracts.py` and related modules.
3. Generated UI contracts must match backend contracts in both `web/src/types.ts` and `meshapp/frontend/src/types.ts`. Use `npm run lint`, `npm --prefix web run contracts:check`, or `npm --prefix meshapp/frontend run contracts:check`; use `scripts/generate_control_plane_contracts.py --types-path <path>` only when intentionally checking or updating one UI surface.
4. Roadmap and evidence docs are evidence indexes, not truth by themselves: `docs/production-deployment-roadmap.md`, `docs/production-hardening-records.md`, and `docs/production-readiness-validation.md`.
5. Historical docs and archived trees are provenance only unless the task explicitly revives them.
6. External product, competitor, market, or certification claims require independent verification and explicit evidence.

## Active Runtime Map

- Control-plane server: `run_server.py` -> `control_plane_server.py` -> `services/control_plane.py`.
- Runtime loop and services: `services/runtime.py`, `services/pipeline.py`, `services/ingest/`, `services/trigger/`, `services/evidence/`, `services/investigation/`, `services/decision/`, `services/evaluation/`, `services/orchestrator/`, `services/actuators/`, `services/feedback/`, `services/observer/`, and watchers.
- Runtime contracts and persistence: `shared/mesh_runtime/`, with `shared/mesh_runtime/schemas/` as schema source.
- Model lifecycle plane: `mesh_brain/`.
- Operator UI: `meshapp/` for the production pilot-serving app and zero-native shell, especially `meshapp/frontend/src/App.tsx`, `meshapp/frontend/src/api.ts`, `meshapp/frontend/src/types.ts`, `meshapp/frontend/src/lib/`, and `meshapp/src/`. `web/` remains the Vite reference surface during migration.
- Deployment and validation: `docker-compose.stack.yml`, `docker-compose.prod.yml`, `scripts/`, `config/`, and `policies/`.
- Vendored/source-input by default: `deepagents/`, `latent-mesh/LatentMAS/`, and `agentic-operator-core-main/`.
- Archived UI: `docs/history/gpui/`.

## Product And Authority Invariants

- Mesh owns policy, evaluation, approval, audit, execution, promotion, run events, and proof continuity.
- External agents, orchestrators, evaluators, model runtimes, and imported source trees are advisory, proposal, review, or source-input lanes unless current code, connector certification, credentials boundary, and tests prove bounded authority.
- `agentic-operator-core-main/` is source input only until forked through provenance, license, renamed contracts, authority gates, and tests.
- Promptfoo is a compatibility mode name and advisory integration lane. Mesh-native evaluation decides pass/fail.
- Hermes is first-class for explanation and interaction. In `auto` orchestration mode the adapter prefers Hermes when ready, then Goose, then native fallback. Hermes does not replace Mesh authority.
- Postgres is the compose production default and required for multi-operator production reliance. File-backed state remains supported and is the library default.
- HelixDB memory projection is an optional graph-vector overlay for verified memory records. Do not treat `MESH_MEMORY_GRAPH_BACKEND=helix` as a replacement for `MESH_STATE_BACKEND=postgres` pilot persistence or release proof.
- Local smoke evidence is not production proof.
- Synthetic, fixture, local-only, or `--allow-dirty` release evidence is not pilot-signing proof.
- Raw secrets, kubeconfigs, tokens, API keys, SSH keys, and service account credentials must not enter run artifacts, docs examples, or committed fixtures.
- `meshapp/` is the active production pilot-serving operator surface. `web/` is the browser/Vite reference surface during migration. GPUI is archived unless explicitly revived.

## Validation Commands By Change Type

Always run:

```bash
git status --short --branch
git diff --check
npm run lint
```

Documentation-only changes:

```bash
rg -n "<stale-name-or-path>" <files-you-touched>
git diff --check
npm run lint
```

Docs touching production readiness, release, schemas, config, API contracts, or deployment claims:

```bash
./scripts/verify_release_cut_list.py
git diff --check
npm run lint
```

Python runtime or contract changes:

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest
RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'
```

Web UI or generated contract changes:

```bash
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build
npm --prefix meshapp/frontend run lint
npm --prefix meshapp/frontend run test
npm --prefix meshapp/frontend run build
```

Live UI e2e, when browser and localhost bind are available:

```bash
npm --prefix web run test:e2e
```

Compose or deployment config changes:

```bash
docker compose -f docker-compose.stack.yml config --quiet
docker compose -f docker-compose.prod.yml config --quiet
./scripts/verify_release_cut_list.py
```

LatentMAS changes only:

```bash
cd latent-mesh/LatentMAS
cargo test
cargo clippy
```

Run focused Python tests only when the change touches executable behavior, generated contracts, or a doc claim that depends on test-covered behavior. Do not run broad live tests merely to justify docs that are explicitly classified as unknown.

## Docs Update Rules

- Update docs in the same change when behavior, contracts, commands, paths, readiness gates, or deployment evidence changes.
- Prefer updating existing docs over creating new docs unless the task asks for a new operating record.
- Use exact file, command, endpoint, schema, and config names.
- Separate `implemented`, `validated locally`, `validated in target environment`, `historical`, `proposal`, and `not implemented`.
- Do not convert roadmap items into current facts without code and validation evidence.
- Do not describe a connector as production-ready unless the registry state, proof packet, degraded behavior, and target validation support that exact deployment.
- Do not use competitor, market, certification, "best", "only", "moat", or production-readiness claims without evidence and scope.
- When docs cite live evidence, include date, command, environment, run id or artifact path, and whether the tree was clean.

## Forbidden Assumptions

- Do not assume `production` means a distinct readiness profile; code maps it to `pilot`.
- Do not assume Postgres is always active; check `MESH_STATE_BACKEND` and the launch path.
- Do not assume file-backed state is obsolete.
- Do not assume the all-in-one compose stack proves external TLS, SSO, cloud IAM, audit sink, target backup/restore, or production network isolation.
- Do not assume local Grype/SBOM artifacts are current release proof.
- Do not assume historical `.mesh-runtime-state/` files clear current gates.
- Do not assume `agentic-operator-core-main/` code is active runtime because the directory exists.
- Do not assume `deepagents/` or `latent-mesh/LatentMAS/` are safe refactor targets.
- Do not assume user dirty changes are yours to stage, format, or rewrite.
- Do not assume generated contracts are current after backend model changes; run the contract check.

## Dirty Worktree Handling

- Start and finish with `git status --short --branch`.
- Identify unrelated modified and untracked files before editing.
- Do not stage, format, delete, rename, or rewrite unrelated dirty files.
- If a required edit overlaps with an existing user change, inspect the file and preserve the user change while making the narrowest possible edit.
- If the overlap makes the task ambiguous, stop and report the conflict instead of overwriting.
- For docs-only tasks, keep changes to docs unless a broken doc link or generated reference must be fixed.

## Vendored And Source-Input Handling

- `deepagents/`: vendored dependency path used by `pyproject.toml`; do not refactor or modernize it during first-party cleanup.
- `latent-mesh/LatentMAS/`: vendored Rust/Python source input; run Rust validation only when touching it.
- `agentic-operator-core-main/`: source input only. Use `config/agentic-operator-source.provenance.json` and `scripts/verify_agentic_operator_source_provenance.py --json` before any fork work.
- Archived `docs/history/gpui/`: provenance only. Do not treat it as active UI code.
