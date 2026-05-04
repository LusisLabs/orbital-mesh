# PR B Comparison

Date: 2026-05-04

Scope:

- Branch A baseline: `codex/mesh-rca-tool-loop` at `421e0dd Add native investigation probe selector`.
- Candidate branch: `codex/mesh-rca-hypothesis-wiring`.
- Candidate changes: conservative CloudOps ontology expansion plus `HypothesisEngine.generate(..., investigation_report=...)` RCA evidence wiring.

Dev-Only Benchmark Status:

- No eval split was used.
- The official Cloud-OpsBench sparse checkout documented at `.mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse` is not present in the current worktree.
- Because the dev split assets are absent, the Cloud-OpsBench dev A@1/A@3 delta was not run in this workspace.
- Required command once assets are restored:

```bash
python3 -m services.benchmark run \
  --suite cloudopsbench_official_dev_full \
  --provider cloudopsbench \
  --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
  --output .mesh-runtime-state/benchmarks/pr-b-dev-candidate
```

Validation Completed:

- `python3 -m unittest tests.test_hypothesis_engine -v`: passed, 22 tests.
- `python3 -m unittest tests.test_hypothesis_engine_reth -v`: passed, 8 tests.
- `python3 -m unittest tests.test_investigation_service -v`: passed, 14 tests.
- Targeted pytest over hypothesis, investigation, and benchmark tests: passed, 80 tests.
- `uvx ruff check` on touched files: passed.
- Repo strict mypy command: passed.

Observed Unit-Level RCA Effects:

- RCA candidate at rank 1 becomes the top ranked hypothesis.
- RCA candidate at rank 3 is preserved in the top-three hypothesis list.
- Investigation report and evidence pack are read additively and not mutated.
- RCA-driven Kubernetes action upgrade is forced to `approval_required`, preserving the policy safety floor.
