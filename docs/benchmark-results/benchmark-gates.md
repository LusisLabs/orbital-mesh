Benchmark Gates
===============

Purpose
-------
The benchmark harness now has explicit gate profiles for development,
evaluation, CI, and nightly runs. Profiles live in
`benchmarks/benchmark_gates.json` so thresholds can be reviewed without
changing harness code.

Profiles
--------
- `dev`: fast deterministic development gate. When the requested suite is an
  official full suite, it runs the deterministic dev split.
- `eval`: held-out evaluation gate. When the requested suite is an official
  full suite, it runs the deterministic eval split.
- `ci`: pull-request gate with compact artifacts and single-repeat execution.
- `nightly`: held-out repeated gate with stricter regression thresholds.

For Cloud-OpsBench official suites, the split mapping is deterministic:

- `cloudopsbench_official_full` + `dev` or `ci` becomes
  `cloudopsbench_official_dev_full`.
- `cloudopsbench_official_full` + `eval` or `nightly` becomes
  `cloudopsbench_official_eval_full`.
- Explicit dev/eval suite names are rewritten to the profile split.

Commands
--------
Fast local gate:

```bash
python3 -m services.benchmark gate \
  --profile ci \
  --suite golden \
  --output .mesh-runtime-state/benchmarks/ci
```

Cloud-OpsBench dev gate:

```bash
python3 -m services.benchmark gate \
  --profile dev \
  --suite cloudopsbench_official_full \
  --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
  --provider cloudopsbench \
  --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
  --output .mesh-runtime-state/benchmarks/cloudopsbench-dev
```

Nightly eval gate with regression comparison:

```bash
python3 -m services.benchmark gate \
  --profile nightly \
  --suite cloudopsbench_official_full \
  --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
  --provider cloudopsbench \
  --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
  --baseline .mesh-runtime-state/benchmarks/baseline/bench_YYYYMMDDTHHMMSSZ \
  --output .mesh-runtime-state/benchmarks/cloudopsbench-nightly
```

Artifacts
---------
Gate runs write:

- `gate.json`: machine-readable pass/fail checks and threshold values.
- `gate.md`: human-readable gate report.
- `comparison.json` and `comparison.md`: written when `--baseline` is set.
- `benchmark-compact.json`: scorecard plus capped failure rows.
- `scenario-results-compact.jsonl`: compact per-attempt rows for trend
  ingestion.

Gate profiles default to `--attempt-artifact-mode errors`,
`--runtime-state-mode none`, and compact artifacts. Full attempt payloads remain
available through the regular `run` command or by overriding gate artifact
options.

Threshold Rules
---------------
Absolute thresholds use scorecard and process metrics:

- minimum score checks: weighted score, Mesh operational score, Agentic RCA
  score, pass rate, decision-match rate, investigation coverage, root-cause
  accuracy, tool coverage, trajectory order match;
- maximum checks: unsafe-action rate, p95 latency, invalid action count, and
  zero-tool-diagnosis rate.

Regression thresholds apply only when `--baseline` is set. Drops beyond the
configured max regression fail the gate; unsafe-action-rate increases beyond
the configured max increase also fail the gate. If no baseline is provided, the
gate records a warning and evaluates only absolute thresholds.
