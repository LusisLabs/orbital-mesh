# HALO Outer Loop

HALO is integrated as an optimizer above Mesh, not as a remediation worker inside a run. Mesh keeps ownership of evidence, policy, approval, execution, and audit. HALO consumes Mesh run traces and produces harness-improvement reports.

## Flow

1. Export Mesh run history to HALO-compatible JSONL.
2. Run the HALO engine against those traces.
3. Convert the HALO report into a bounded agent patch task.
4. Validate proposed harness changes with the Mesh Python, lint, typecheck, web lint, and web build gates.
5. Record the optimization cycle as a Mesh artifact with `artifact_key=halo_optimization_cycle`.

## Commands

Export recent runs:

```bash
python3 scripts/halo_outer_loop.py export \
  --output .mesh-runtime-state/halo/traces.jsonl \
  --limit 100
```

Run HALO if the `halo` CLI is installed:

```bash
OPENAI_API_KEY=... python3 scripts/halo_outer_loop.py run \
  --output .mesh-runtime-state/halo/traces.jsonl \
  --report-path .mesh-runtime-state/halo/report.md \
  --prompt "Diagnose recurring Mesh harness failure modes and suggest bounded fixes."
```

Record a HALO report as a bounded Mesh patch task:

```bash
python3 scripts/halo_outer_loop.py task \
  --trace-jsonl .mesh-runtime-state/halo/traces.jsonl \
  --report .mesh-runtime-state/halo/report.md \
  --print-json
```

Use `--state-directory` for isolated simulation or e2e state directories.

## Trace Shape

Each JSONL row uses `trace_format=mesh.halo.trace.v1` and includes:

- run summary: status, stage, scenario, timestamps, Merkle root
- harness configuration: evaluation mode, orchestration mode, steering mode, pause points
- OpenTelemetry-style spans derived from Mesh run events
- event summaries with payloads and summaries redacted
- core artifacts: input signal, trigger, evidence pack, scenario analysis, decision, evaluation, agent tasks, reconciliation, execution, feedback, benchmark score
- failure context: blocking reasons, benchmark score, agent risk flags, run error

Secret-shaped keys such as `token`, `secret`, `password`, `credential`, `api_key`, `kubeconfig`, and private keys are redacted before export.

## Patch Task Boundary

HALO patch tasks are proposal-only and constrained to harness paths:

- `services/`
- `shared/mesh_runtime/`
- `control_plane_server.py`
- `scripts/`
- `tests/`
- `web/src/`
- `docs/`

Default verification commands:

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest
RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'
npm --prefix web run lint
npm --prefix web run build
```
