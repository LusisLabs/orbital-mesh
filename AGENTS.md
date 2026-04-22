# Agent & contributor guide (mesh-intelligence)

This file captures **how we build and change this repo** so humans and coding agents stay aligned. It is not a product spec; see `architecture.md` and `docs/` for architecture.

## Stack

| Area | Stack |
|------|--------|
| Core services & runtime | Python 3.x, `uv` |
| Web UI | TypeScript, Vite, `npm` |
| LatentMAS (vendored path) | Rust, `cargo` under `latent-mesh/LatentMAS/` |

## Commands (validation gates)

Run these after non-trivial Python changes (or before opening a PR):

```bash
# Python tests (repo root; editable install + deps)
PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest

# Lint / typecheck (cache in /tmp if default cache dirs are not writable)
RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict \
  --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'
```

Web build (from repo root):

```bash
npm --prefix web ci
npm --prefix web run build
```

Rust (when touching LatentMAS):

```bash
(cd latent-mesh/LatentMAS && cargo test && cargo clippy)
```

**Note:** `PYTHONPATH=.` is required for tests that import top-level modules (e.g. `control_plane_server`).

## Scope & refactors

- **In scope for first-party cleanup:** `services/`, `shared/mesh_runtime/`, `control_plane_server.py`, `web/`, scaffold moves under `docs/history/`, and orchestration scripts that reference those paths.
- **Treat as vendored / upstream (avoid drive-by refactors):** `deepagents/`, `latent-mesh/LatentMAS/` (still run `cargo` when you change Rust there). Evo is no longer vendored in-tree; the `evo` CLI must be installed separately (see `MESH_EVO_COMMAND` / `evo-hq-cli`).
- **Critical paths** (extra care; prefer small, reviewed diffs): `services/control_plane.py`, `shared/mesh_runtime/contracts.py`, `shared/mesh_runtime/schemas/`, `control_plane_server.py`.

## Contracts & schemas

- **Source of truth:** JSON Schema files in `shared/mesh_runtime/schemas/`.
- **Python:** Dataclasses and validators in `shared/mesh_runtime/contracts.py` (and related) must stay consistent with those schemas; prefer schema-driven nullability and field shapes.

## Git workflow (stacked changes)

When landing a multi-step cleanup, **stack branches** so each step builds on the previous one (avoid branching every step from the same old base, which drops prior commits):

```bash
git checkout -B cleanup/phase-2-stepN cleanup/phase-2-stepN-minus-1
```

Merge the **tip** branch (e.g. `cleanup/phase-2-comment-cleanup`) into `master` once the stack is validated.

## Comment hygiene

- Remove **decorative** section banners and **numbered narration** that duplicates the code.
- Keep comments that explain **non-obvious intent** (especially broad `except` blocks, security/CORS choices, and contract invariants).
- Do not add new standalone doc files for routine tasks unless the team asks for them.

## Orchestration / skills paths

- Goose autoresearch scripts live under `services/skills/goose-autoresearch/scripts/` (not under `.cursor/skills/` in-repo).
