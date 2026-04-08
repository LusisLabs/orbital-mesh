---
name: goose-autoresearch
description: Run long-form Goose research orchestration modeled on clustered autoresearch loops: one lead agent defines the brief, fans out heterogeneous worker runs, scores results, iterates, and synthesizes a final answer. Use when the user mentions Goose research, autoresearch, long-running research sessions, cluster fan-out, multi-pass synthesis, or comparing several Goose runs before converging.
---

# Goose Autoresearch

Use this skill when the task is not a single prompt/response, but a research campaign that benefits from multiple Goose runs exploring different angles before a lead synthesis pass.

## Quick Start

1. Bootstrap a session workspace:

```bash
python3 .cursor/skills/goose-autoresearch/scripts/init_session.py --slug "<short-session-name>" --question "<research question>"
```

2. Read the generated `manifest.json` and prompt files in the created session directory.

3. Run the session as a lead-agent loop:
- clarify the question, scope, and success rubric
- define a small worker matrix with intentionally different angles
- collect each worker result into the session `results/` directory
- score the worker outputs against the rubric
- launch another wave only if gaps remain
- write the final synthesis into `synthesis/final-report.md`

## Default Topology

Model the session after a clustered autoresearch loop:

- `lead`: owns the brief, worker assignment, scorecard, and convergence checks
- `worker-01`: baseline answer with the default Goose profile
- `worker-02`: contrarian or skeptical pass
- `worker-03`: tool-heavy or source-heavy pass
- `worker-04`: synthesis-ready editor that looks for gaps, conflicts, and missing evidence

Keep the first wave small. Add more workers only when they buy diversity, not just more tokens.

## Repo-Specific Rules

- Prefer the Goose profile resolved by this repo instead of guessing flags. The bootstrap script captures the active Goose bridge settings from `shared.mesh_runtime.integrations`.
- Store session artifacts under `.mesh-runtime-state/research/`. That matches this repo's generated-runtime convention and avoids mixing ephemeral research output with source docs.
- If the session produces durable conclusions worth keeping, distill them into `docs/` or another user-requested destination after the research loop converges.
- Use the vault-style habit from this repo: keep operator notes, intermediate findings, and final synthesis explicit rather than burying them in a terminal transcript.

## Worker Design

Vary workers by angle, not by cosmetic prompt wording. Good axes:

- baseline vs contrarian
- short-horizon answer vs exhaustive answer
- architecture-first vs implementation-first
- local-repo evidence vs external-source evidence
- optimistic plan vs risk-first critique

Each worker should have:

- a clear role
- a bounded sub-question
- an output format
- a stop condition

## Scoring Loop

Score every worker output on:

- correctness
- evidence quality
- novelty
- actionability
- consistency with repo reality

Use simple `1-5` scoring plus short notes. Favor the best-supported answer, not the most verbose one.

## Convergence Rules

Stop iterating when one of these is true:

- two or more strong worker answers converge on the same conclusion
- the remaining disagreement is explicitly documented and narrow
- the next wave would mostly repeat prior work
- the user asked for a time-boxed result and the current evidence is good enough

Escalate to another wave when:

- the best answer is still missing concrete evidence
- workers disagree on key facts
- repo-local evidence and external evidence conflict
- the final recommendation still feels under-specified

## Deliverables

By default, produce:

- a filled-in `manifest.json`
- worker result files under `results/`
- a scored summary in `results/scorecard.md`
- a final synthesis in `synthesis/final-report.md`

## Additional Resources

- Repo-specific orchestration notes: [reference.md](reference.md)
- Prompt and scorecard templates: [templates.md](templates.md)
