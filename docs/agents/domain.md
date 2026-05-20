# Domain Docs

How engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This repo is currently single-context for skill consumption.

No root `CONTEXT.md`, root `CONTEXT-MAP.md`, or `docs/adr/` directory exists in this checkout. Proceed silently when those files are absent; do not create them unless a task explicitly asks for domain glossary or ADR work.

## Before Exploring

Read these first for non-trivial repo work:

- `AGENTS.md` for operating rules, state-slice discipline, validation gates, and scope boundaries.
- `docs/repo-truth-audit.md` for current, stale, conflicting, and historical repo claims.
- `docs/future-agent-operating-guide.md` for source-of-truth order, active runtime boundaries, validation gates, and dirty-worktree handling.
- `architecture.md` for system architecture.

Then read area-specific docs under `docs/` that match the task. Prefer first-party runtime docs over historical scaffold files under `docs/history/`.

## Domain Vocabulary

When output names a domain concept, use the repository's terms from the current docs. Do not replace established terms with synonyms unless the task is explicitly about renaming.

If a needed term is missing from the docs, note the gap in the work product. Do not invent permanent vocabulary in code comments, issue titles, or public docs without grounding it in the existing architecture language.

## Architectural Decisions

If formal ADRs are added later, skills should read the relevant ADRs before proposing architecture changes. If an output contradicts an ADR or a root operating guide, surface that conflict explicitly instead of silently overriding it.
