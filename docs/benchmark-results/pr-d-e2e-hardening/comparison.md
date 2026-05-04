# PR D E2E Hardening Comparison

Date: 2026-05-04

Scope:

- Baseline branch: `mesh-brain` at `4a52d53`.
- Candidate branch: `codex/mesh-rca-e2e-hardening`, stacked on PR C at `1961d04`.
- Candidate stack: PR A report contract/native selector, PR B dev-only RCA ontology plus HypothesisEngine wiring, PR C planner telemetry and shadow LLM selector swap point.
- PR D adds E2E hardening evidence only. No broad new planner work was added.

Benchmark Commands:

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents python -m services.benchmark run \
  --suite golden \
  --agent-tasks-mode off \
  --runtime-state-mode none
```

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents python -m services.benchmark compare \
  .mesh-runtime-state/benchmarks/pr-d-mesh-brain-golden/bench_20260504T165209329998Z \
  .mesh-runtime-state/benchmarks/pr-d-current-golden/bench_20260504T165144042062Z
```

Golden Suite Against `mesh-brain`:

| Run | Branch | Run ID | Cases | Weighted | Mesh Ops | Agentic RCA | A@1 | A@3 | Unsafe |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | `mesh-brain` / `4a52d53` | `bench_20260504T165209329998Z` | 3 | 91.00 | 96.67 | 61.67 | n/a | n/a | 0.00 |
| Candidate | `codex/mesh-rca-e2e-hardening` / `1961d04` | `bench_20260504T165144042062Z` | 3 | 95.00 | 96.67 | 66.67 | 0.6667 | 0.6667 | 0.00 |

Golden Delta:

- Weighted score: +4.00.
- Mesh operational score: +0.00.
- Agentic RCA score: +5.00.
- Investigation dimension: +20.00%.
- Pass rate: +0.00%.
- Decision match rate: +0.00%.
- Unsafe action rate: +0.00%.
- P95 latency: +0.86 ms.

Small Cloud-OpsBench Dev Subset:

Command:

```bash
PYTHONPATH=. uvx --with-editable . --with deepagents python -m services.benchmark run \
  --suite cloudopsbench_official_dev_full \
  --scenario-root .mesh-runtime-state/external-benchmarks/cloudopsbench-scenarios \
  --provider cloudopsbench \
  --backend cloudopsbench \
  --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
  --cloudopsbench-ground-truth-mode hidden \
  --agent-tasks-mode off \
  --runtime-state-mode none
```

Result:

- Run ID: `bench_20260504T165154016491Z`.
- Cases: 5 dev cases only.
- Weighted score: 97.50.
- Mesh operational score: 100.00.
- Agentic RCA score: 89.00.
- Decision match rate: 100.00%.
- Investigation coverage: 100.00%.
- Unsafe action rate: 0.00%.
- `root_cause_accuracy`: 0.8000.
- `root_cause_at_1`: 0.8000.
- `root_cause_at_3`: 0.8000.

Dev subset case IDs:

- `cloudops_boutique_runtime_41`.
- `cloudops_boutique_scheduling_102`.
- `cloudops_boutique_scheduling_25`.
- `cloudops_boutique_startup_52`.
- `cloudops_trainticket_startup_11`.

Integration Hardening Checks:

- UI consumes `root_cause_candidates`: `web/src/App.tsx` builds the RCA graph from `artifacts.investigation_report` and reads `report.root_cause_candidates` before legacy candidate shapes.
- Control-plane persistence stores investigation output: `services/control_plane.py` records `evidence_pack` and `investigation_report` as separate run artifacts and emits separate artifact-keyed run events.
- Benchmark gates consume threshold config: `services/benchmark/gates.py` loads `benchmarks/benchmark_gates.json`, applies CLI threshold overrides, and evaluates configured scorecard/process/regression thresholds.
- Benchmark scoring consumes stable RCA output: `services/benchmark/scoring.py` extracts `root_cause_candidates` before falling back to ranked findings.
- Audit trail distinguishes frozen evidence from investigation findings: `evidence_pack` remains the frozen evidence artifact; `investigation_report` remains the additive investigation artifact with findings and RCA candidates.

Validation Status:

- Golden suite against current branch: passed.
- Golden comparison against `mesh-brain`: passed, candidate +4.00 weighted score.
- Small Cloud-OpsBench dev subset: passed, 5 dev cases.
- `python3 -m unittest tests.test_investigation_service -v`: passed, 17 tests.
- Targeted pytest over hypothesis, investigation, and benchmark tests: passed, 84 tests.
- Benchmark harness unittest under the repo `uvx` Python environment: passed, 19 tests.
- `uvx ruff check .`: passed.
- Repo strict mypy command: passed.
- `npm --prefix web run lint`: passed.
