---
name: goose-autoresearch
description: Run long-form Goose research orchestration modeled on clustered autoresearch loops: one lead agent defines the brief, fans out heterogeneous worker runs, scores results, iterates, and synthesizes a final answer. Use when the user mentions Goose research, autoresearch, long-running research sessions, cluster fan-out, multi-pass synthesis, or comparing several Goose runs before converging.
---

# Goose Autoresearch

Use this skill when the task is not a single prompt/response, but a research campaign that benefits from multiple Goose runs exploring different angles before a lead synthesis pass.

## Mesh-native empirical digest (before LLM waves)

To collect **ground-truth pipeline metrics** from real `FirstSlicePipeline` runs (feature-flag, Kubernetes, no-trigger) and write `run_summaries.json` + `showcase-insights.md` under `.mesh-runtime-state/research/`:

```bash
python3 scripts/mesh_showcase_research.py
python3 scripts/mesh_showcase_research.py --minimax   # optional: chain MiniMax synthesis on the same session
```

Use that output as the factual base for research narratives or paste summaries into worker prompts.

## Quick Start

1. Bootstrap a session workspace:

```bash
python3 services/skills/goose-autoresearch/scripts/init_session.py --slug "<short-session-name>" --question "<research question>"
```

2. Read the generated `manifest.json` and prompt files in the created session directory.

3. Run the session as a lead-agent loop:
- clarify the question, scope, and success rubric
- define a small worker matrix with intentionally different angles
- collect each worker result into the session `results/` directory
- score the worker outputs against the rubric
- launch another wave only if gaps remain
- write the final synthesis into `synthesis/final-report.md`

## MiniMax API — multi-wave research (end-to-end)

Use this when you want **long-form research driven entirely by MiniMax’s OpenAI-compatible HTTP API** (no Goose CLI), with **three waves**: four parallel workers → lead merge (scorecard + gaps) → final report.

**Environment** (same variables as the rest of the repo’s MiniMax integration):

OpenAI-compatible (preferred if `OPENAI_API_KEY` is set):

```bash
export OPENAI_API_KEY="<MINIMAX_OPENAI_API_KEY>"
export OPENAI_BASE_URL="https://api.minimax.io/v1"
# Set a MiniMax model id here; do not rely on GOOSE_MODEL/HERMES_MODEL (often Ollama) — the MiniMax API will 400.
export MINIMAX_MODEL="MiniMax-M2.7"
```

Anthropic-compatible fallback (used when OpenAI keys are unset—matches typical Mesh `.env`):

```bash
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"
export ANTHROPIC_API_KEY="<MINIMAX_ANTHROPIC_API_KEY>"
# Optional: stronger model for research quality
export MINIMAX_MODEL="MiniMax-M2.7"
```

The runner also loads the repo **`.env`** automatically (without overriding variables you already exported).

**Control plane UI:** MiniMax research does **not** create a Mesh pipeline run, so it will not appear under **Run Queue**. After the script finishes, open the browser control plane and use the left-rail **Research (MiniMax)** list (or reload the page), then open the **Research** inspector tab to read `synthesis/final-report.md`. The server must use the same `state_directory` as the machine where you ran the script (e.g. shared repo volume when using Docker).

**New session + full run** (six model calls: 4 + 1 + 1):

```bash
python3 services/skills/goose-autoresearch/scripts/run_minimax_research.py \
  --slug "my-research" \
  --question "Your research question here?"
```

**Existing session directory**:

```bash
python3 services/skills/goose-autoresearch/scripts/run_minimax_research.py \
  --session-dir ".mesh-runtime-state/research/<timestamp>-<slug>"
```

**Outputs**: `results/wave1-worker-*-minimax.md`, `results/wave2-lead-scorecard-minimax.md`, `synthesis/final-report.md`, and `manifest.json` status `minimax_multiwave_complete`.

Implementation: `services/skills/goose-autoresearch/scripts/minimax_client.py` (stdlib only) + `run_minimax_research.py`.

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
