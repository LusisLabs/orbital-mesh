# Repo Reference

## Why This Skill Fits Here

This repo already has a Goose integration boundary plus a vault-oriented habit for preserving structured outputs.

- `shared/mesh_runtime/integrations.py` resolves the active Goose command, provider, model, and fallback profile.
- `services/orchestrator/goose_bridge.py` shows the repo's preferred Goose invocation style: explicit prompts, `--no-session`, `--quiet`, and JSON output.
- `shared/mesh_runtime/postprocessing.py` demonstrates a second Goose usage pattern: generate polished markdown artifacts from structured run state.
- `shared/mesh_runtime/vault.py` shows the repo's expectation that intermediate and final artifacts should be written into explicit notes rather than left implicit.

## Session Layout

The bootstrap script creates a session under:

```text
.mesh-runtime-state/research/<timestamp>-<slug>/
```

Default directories:

- `prompts/` for lead, worker, and synthesis prompt files
- `results/` for raw worker outputs and scorecards
- `notes/` for operator notes, open questions, and follow-up ideas
- `synthesis/` for the final converged write-up

## Recommended Session Cadence

1. Define the research question and explicit success rubric.
2. Launch a first wave of 3-4 differentiated workers.
3. Save each worker response as its own artifact.
4. Score outputs against the same rubric.
5. Run a second wave only to resolve gaps, contradictions, or weak evidence.
6. Produce one synthesis that names consensus, dissent, and recommended next action.

## Good Worker Mix

Use a small but intentionally diverse cluster:

- `baseline`: answer the question directly with default settings
- `skeptic`: attack assumptions, edge cases, and weak evidence
- `deep-dive`: focus on the hardest unresolved sub-question
- `editor`: consolidate, compare, and point out missing support

## Result Hygiene

- Keep worker prompts short and role-specific.
- Keep output schemas consistent so scorecards stay comparable.
- Capture exact source paths, URLs, or commands when a worker makes a claim.
- Preserve rejected or low-scoring runs if they explain why a better answer won.

## Goose Command Guidance

When running Goose for this skill:

- prefer the resolved repo profile instead of hard-coding provider/model flags
- use direct Goose execution for open-ended research prompts
- reserve the repo's `goose_bridge` flow for bounded orchestration/review paths that expect a strict JSON contract

The bootstrap script extracts the direct Goose binary and profile hints from the repo's resolved integration config so the session manifest can record them for reuse.
