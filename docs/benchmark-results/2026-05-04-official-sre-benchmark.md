Official SRE Benchmark Run - 2026-05-04
======================================

Status
------
This is a completed local reproducibility and gap report for the benchmark
harness. It is not a leaderboard submission and it is not evidence that Mesh
beats another SRE agent.

Publication boundary:

  - Cloud-OpsBench: official case assets were used for a full 656-case hidden
    Mesh run with repeat=3.
  - SREGym: no official score yet because local-kind execution is still blocked
    by local Docker/Helm prerequisites.
  - OpenSRE: no clean full baseline yet because the configured Anthropic key
    failed during the one-case smoke with a low-credit API error.
  - The headline result is not the weighted score. For Cloud-OpsBench-style RCA,
    the meaningful metrics are root-cause accuracy, tool coverage, trajectory
    match, invalid action count, and zero-tool diagnosis.

The useful finding is clear: Mesh is strong at safe bounded escalation, but it
does not yet perform Cloud-OpsBench RCA in hidden mode.


Source Versions
---------------
Mesh:

  - Repository: /Users/madhavgoyal/ai/mesh
  - Base commit before this patch: 4e57a331aaea7827c3c3f63ce15896cbb158691f
  - Additional local patch: compact benchmark artifact controls.

SREGym:

  - Repository: https://github.com/SREGym/SREGym
  - Local sparse/code clone: .mesh-runtime-state/external-benchmarks/SREGym-code
  - Commit: 1c96acfd6a4ef624c0ece78d70cfd852e6c5104a

Cloud-OpsBench:

  - Repository: https://github.com/LLM4Ops/Cloud-OpsBench
  - Local sparse clone:
    .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse
  - Commit: b4454420d8d713eac935050be9dc2b799b534782
  - Sparse checkout expanded to all metadata/tool_cache case assets:
      656 metadata.json files
      656 tool_cache.json files
      about 694 MB on disk


Environment Disclosure
----------------------
Machine/runtime:

  - OS/arch: macOS Darwin arm64
  - Python: 3.13.5
  - uv: 0.6.8
  - kind: v0.31.0 go1.25.5 darwin/arm64
  - kubectl client: v1.24.0
  - Helm: not installed
  - Docker client: Docker 20.10.16 darwin/arm64
  - Disk after compact run: about 1.8 GiB available on a 460 GiB volume

Docker/SREGym blocker:

  - Sandbox docker version fails with permission denied on /var/run/docker.sock.
  - Outside-sandbox docker version hung for more than 90 seconds and was killed.
  - Helm is not installed.
  - SREGym local-kind requires Docker, kind, Helm, and its local benchmark
    services.
  - Result: official SREGym local-kind task execution was not run.

Model/API:

  - .env.benchmark contains LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY.
  - OpenSRE used the Anthropic-backed CLI path.
  - OpenSRE one-case smoke failed during the planning step because Anthropic
    returned "Your credit balance is too low to access the Anthropic API."
  - Mesh Cloud-OpsBench hidden runs did not produce useful external model/tool
    calls; latency was sub-100 ms per case.
  - Exact token and dollar costs were not emitted by the benchmark harness.


Methodology
-----------
Ground-truth handling:

  - Cloud-OpsBench hidden mode does not replay expert trajectories and does not
    inject official root-cause labels into raw signals or investigation
    reports.
  - Cloud-OpsBench oracle mode remains available only for adapter plumbing
    tests.
  - The reported full Mesh run used hidden mode.

Split:

  - Full suite: 656 official cases.
  - Deterministic dev split: 135 cases.
  - Deterministic eval split: 521 cases.
  - Split rule: MD5(scenario_id) modulo 5; bucket 0 is dev, buckets 1-4 are
    eval. The scenario id shape is cloudops_<system>_<fault_category>_<case_id>.

Full-suite case coverage:

  - Systems: boutique 452, trainticket 204.
  - Fault groups: 11.
  - Distinct root-cause labels: 49.
  - Category counts:
      boutique/admission 58
      boutique/infrastructure 48
      boutique/performance 21
      boutique/runtime 45
      boutique/scheduling 164
      boutique/service 54
      boutique/startup 62
      trainticket/performance 47
      trainticket/runtime 96
      trainticket/service 37
      trainticket/startup 24

Repetition:

  - Mesh full run: repeat=3, 1,968 total attempts.
  - Score stddev: 0.0000.
  - OpenSRE was not run full because the smoke failed on provider credit.

Scoring interpretation:

  - Mesh operational score measures safe bounded behavior: escalation, safety,
    recovery routing, latency, and learning artifact presence.
  - Agentic RCA score and process metrics are the Cloud-OpsBench-relevant
    indicators: root-cause accuracy, trajectory order match, tool coverage,
    invalid action count, and related process metrics.
  - The weighted score is not a suitable headline for Cloud-OpsBench because
    safe escalation can score highly while RCA remains unsolved.


Commands
--------
Generate/import the full official Cloud-OpsBench scenarios:

  git -C .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
    sparse-checkout set --no-cone README.md interact.py \
    '/benchmark/*/*/*/metadata.json' \
    '/benchmark/*/*/*/tool_cache.json' \
    '/golden-trajectory/*/*/*/path1.json'

  python3 -m services.benchmark.cloudopsbench_import \
    --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
    --output .mesh-runtime-state/official-benchmark/scenarios

Mesh full hidden Cloud-OpsBench run:

  set -a; source .env.benchmark; set +a
  python3 -m services.benchmark run \
    --suite cloudopsbench_official_full \
    --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
    --provider cloudopsbench \
    --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
    --cloudopsbench-ground-truth-mode hidden \
    --repeat 3 \
    --attempt-artifact-mode errors \
    --runtime-state-mode none \
    --agent-fabric-mode deepagents \
    --agent-tasks-mode blocking \
    --agent-lane investigator \
    --agent-task-timeout-seconds 60 \
    --deepagents-model claude-haiku-4-5-20251001 \
    --backend-timeout-seconds 300 \
    --output .mesh-runtime-state/benchmarks/cloudopsbench-official-full-hidden-mesh-compact

Mesh full hidden Cloud-OpsBench gap report:

  python3 -m services.benchmark gaps \
    --provider cloudopsbench \
    --run .mesh-runtime-state/benchmarks/cloudopsbench-official-full-hidden-mesh-compact/bench_20260504T092637813921Z

OpenSRE one-case smoke:

  set -a; source .env.benchmark; set +a
  python3 -m services.benchmark run \
    --suite cloudopsbench_official_full \
    --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
    --backend opensre-cli \
    --scenario-id cloudops_boutique_admission_1 \
    --repeat 1 \
    --attempt-artifact-mode full \
    --backend-timeout-seconds 300 \
    --output .mesh-runtime-state/benchmarks/cloudopsbench-official-opensre-smoke


Results
-------
Mesh Cloud-OpsBench official full hidden:

  - Run: bench_20260504T092637813921Z
  - Report:
    .mesh-runtime-state/benchmarks/cloudopsbench-official-full-hidden-mesh-compact/bench_20260504T092637813921Z/report.md
  - Gap report:
    .mesh-runtime-state/benchmarks/cloudopsbench-official-full-hidden-mesh-compact/bench_20260504T092637813921Z/gap_report.md
  - Scenarios: 656
  - Attempts: 1,968
  - Repeat count: 3
  - Weighted score: 93.50 / 100
  - Mesh operational score: 100.00 / 100
  - Agentic RCA score: 30.00 / 100
  - Weighted score stddev: 0.0000
  - Pass rate: 100.00%
  - Unsafe action rate: 0.00%
  - Decision match rate: 100.00%
  - Investigation coverage: 100.00%
  - P95 latency: 72.62 ms
  - Root-cause accuracy: 0.0000
  - Trajectory in-order match: 0.0000
  - Tool relevance: 0.0000
  - Tool coverage: 0.0000
  - Invalid action count average: 0.0000
  - Redundant action rate: 0.0000
  - Zero-tool diagnosis rate: 0.0000
  - MTTRI: 0.0000 ms
  - Gap count: 5,904

OpenSRE smoke:

  - Run: bench_20260504T092421685247Z
  - Report:
    .mesh-runtime-state/benchmarks/cloudopsbench-official-opensre-smoke/bench_20260504T092421685247Z/report.md
  - Scenarios: 1
  - Attempts: 1
  - Weighted score: 8.00 / 100
  - Mesh operational score: 0.00 / 100
  - Agentic RCA score: 25.00 / 100
  - Failure: Anthropic API low credit during OpenSRE planning.
  - Interpretation: environment/provider failure; not a valid OpenSRE
    capability score.


Interpretation
--------------
Mesh did the safe thing on every full hidden Cloud-OpsBench case: it escalated
unknown incidents without unsafe mutation. That is good control-plane behavior.

Mesh did not solve Cloud-OpsBench RCA. It did not produce the official root
cause labels, did not follow expert diagnostic trajectories, and did not use
the Cloud-OpsBench tool families in hidden mode. The current agentic RCA score
of 30/100 is mostly base investigation/artifact credit, not real RCA success.

OpenSRE cannot be compared yet. The one-case smoke confirms the adapter can
launch the CLI, but the configured provider key fails before planning finishes.
A full OpenSRE run with the same suite should wait until a funded provider key
is available.

The next architecture improvement is therefore not another deterministic
decision rule. Mesh needs an interactive Cloud-OpsBench/SREGym investigation
tool loop:

  - expose snapshot/live benchmark tools to InvestigationService;
  - let the agent choose read-only probes;
  - record actual tool calls rather than expert replay;
  - emit ranked root-cause candidates;
  - score A@1/A@3 and trajectory coverage;
  - keep all mitigation routes policy-gated and benchmark-scoped.


Validation
----------
Patch-level validation:

  - PASS: PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest
    pytest tests/test_benchmark_harness.py -q, 18 tests.
  - PASS: RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark
    tests/test_benchmark_harness.py.
  - PASS: python3 -m services.benchmark.cloudopsbench_import
    --cloudopsbench-root
    .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse --output
    /tmp/mesh-cloudopsbench-import-check produced full=656, dev=135, eval=521,
    root_causes=49, fault_groups=11.

Full-suite validation from the prior official-benchmark patch:

  - PASS: TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable .
    --with deepagents --with mypy mypy --strict --exclude
    'deepagents/|latent-mesh/LatentMAS/|services/skills/'.
  - PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest
    finished with 762 passed, 1 skipped, 9 failed.
  - Failing areas: control-plane agent task indexing/recovery timing,
    Deep Agents model resolver test signature drift, LatentMAS tokenizer probe,
    and FileStateStore vault materialization debounce.
  - Full ruff check failed because it traversed unrelated untracked
    .claude/worktrees copies of deepagents and latent-mesh. Targeted first-party
    benchmark lint passed.


Conclusion
----------
These results are shareable as an honest engineering benchmark packet, but not
as a comparative superiority claim:

  - SREGym: no official score; environment blocked.
  - Cloud-OpsBench: official full hidden Mesh run completed, repeat=3, 656
    cases, 1,968 attempts.
  - Mesh result: operationally safe, RCA/process score currently poor.
  - OpenSRE result: smoke blocked by provider credit, no clean baseline.

The measurable next target is to move Mesh Cloud-OpsBench hidden full-suite
process metrics from:

  root_cause_accuracy=0.0, tool_coverage=0.0

to:

  root_cause_accuracy >= 0.25 and tool_coverage >= 0.50 on the held-out eval
  split without using oracle mode or tuning on eval cases.
