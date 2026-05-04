# PR B Comparison

Date: 2026-05-04

Scope:

- Branch A baseline: `codex/mesh-rca-tool-loop` at `421e0dd Add native investigation probe selector`.
- Candidate branch: `codex/mesh-rca-hypothesis-wiring`.
- Candidate changes: conservative CloudOps ontology expansion plus `HypothesisEngine.generate(..., investigation_report=...)` RCA evidence wiring.

Dev-Only Benchmark Status:

- No eval split was used.
- Official Cloud-OpsBench sparse checkout: `.mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse`.
- Imported official suites: `.mesh-runtime-state/external-benchmarks/cloudopsbench-scenarios`.
- Import counts: 656 total cases, 135 dev cases, 521 eval cases, 49 root-cause labels.
- Dev split high-frequency labels included `node_selector_mismatch`, `missing_secret_binding`, `pod_network_delay`,
  `deployment_zero_replicas`, `taint_toleration_mismatch`, `mysql_invalid_credentials`,
  `memory_capacity_mismatch`, `pod_anti_affinity_conflict`, `cpu_capacity_mismatch`,
  `missing_image_pull_secret`, and `gateway_misrouted`.
- Conservative additions came from dev-observed signals only: capacity scheduling text, pod anti-affinity text,
  image-pull-secret events, and explicit readiness/liveness probe port/protocol failures.
- False-positive rules were tightened for normal `Service Account:` pod fields and generic `0/1` READY counts.

Benchmark Command:

```bash
uvx --with-editable . python -m services.benchmark run \
  --suite cloudopsbench_official_dev_full \
  --scenario-root .mesh-runtime-state/external-benchmarks/cloudopsbench-scenarios \
  --provider cloudopsbench \
  --backend cloudopsbench \
  --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
  --cloudopsbench-ground-truth-mode hidden \
  --agent-tasks-mode off \
  --runtime-state-mode none
```

Dev-Only Delta Against Branch A:

| Run | Branch | Run ID | Cases | A@1 | A@3 | Agentic RCA |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Baseline | `codex/mesh-rca-tool-loop` / `421e0dd` | `bench_20260504T163935743588Z` | 135 | 0.0000 | 0.0296 | 66.45 |
| Candidate | `codex/mesh-rca-hypothesis-wiring` | `bench_20260504T164220673085Z` | 135 | 0.2889 | 0.3481 | 73.62 |

Delta:

- A@1: +0.2889
- A@3: +0.3185
- Agentic RCA score: +7.17

Validation Completed:

- `python3 -m unittest tests.test_hypothesis_engine -v`: passed, 22 tests.
- `python3 -m unittest tests.test_hypothesis_engine_reth -v`: passed, 8 tests.
- `python3 -m unittest tests.test_investigation_service -v`: passed, 17 tests.
- Targeted pytest over hypothesis, investigation, and benchmark tests: passed, 83 tests.
- `uvx ruff check .`: passed.
- Repo strict mypy command: passed.
- `npm --prefix web run lint`: passed.

Observed Unit-Level RCA Effects:

- RCA candidate at rank 1 becomes the top ranked hypothesis.
- RCA candidate at rank 3 is preserved in the top-three hypothesis list.
- Investigation report and evidence pack are read additively and not mutated.
- RCA-driven Kubernetes action upgrade is forced to `approval_required`, preserving the policy safety floor.
