Official SRE Benchmark Attempt - 2026-05-04
==========================================

Status
------
This is a real local benchmark attempt, not a leaderboard claim.

Publication status:

  - Shareable as a reproducibility and gap report.
  - Not publishable as a claim that Mesh beats other SRE agents.
  - Not an official SREGym score, because local-kind execution was blocked by
    the local environment.
  - Not a full Cloud-OpsBench score, because only a sparse 22-case official
    subset was downloaded and Mesh does not yet use Cloud-OpsBench's
    interactive tool API.

The useful finding is clear: Mesh is strong at safe bounded escalation, but it
currently fails Cloud-OpsBench's RCA process metrics in hidden mode.


Source Versions
---------------
Mesh:

  - Repository: /Users/madhavgoyal/ai/mesh
  - Base commit during the run: c3d551868442d41cd2a2a0076735c0ad022c3729
  - Additional local patch: Cloud-OpsBench hidden/oracle ground-truth mode.

SREGym:

  - Repository: https://github.com/SREGym/SREGym
  - Local sparse/code clone: .mesh-runtime-state/external-benchmarks/SREGym-code
  - Commit: 1c96acfd6a4ef624c0ece78d70cfd852e6c5104a

Cloud-OpsBench:

  - Repository: https://github.com/LLM4Ops/Cloud-OpsBench
  - Local sparse clone: .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse
  - Commit: b4454420d8d713eac935050be9dc2b799b534782
  - Sparse checkout size after expansion: about 130 MB


Environment Disclosure
----------------------
Machine/runtime:

  - OS/arch: macOS Darwin arm64
  - Python: 3.13.5
  - uv: 0.6.8
  - kind: v0.31.0 go1.25.5 darwin/arm64
  - kubectl client: v1.24.0
  - Helm: not installed
  - Disk after sparse fetch: about 1.1 GiB available on a 460 GiB volume

Docker/SREGym blocker:

  - Docker client is present: Docker 20.10.16 darwin/arm64.
  - Sandbox docker info fails with permission denied on /var/run/docker.sock.
  - Outside-sandbox docker info timed out after 8 seconds.
  - SREGym local-kind requires Docker, kind, Helm, and its local services.
  - Result: official SREGym local-kind task execution was not run.

Model/API:

  - .env.benchmark set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY was present.
  - Mesh Cloud-OpsBench hidden runs did not make useful external model/tool
    calls; runtime was deterministic and sub-100 ms per case.
  - OpenSRE used the Anthropic-backed CLI path.
  - The OpenSRE repeat=3 baseline became invalid on the third repeat because
    Anthropic returned "credit balance is too low".
  - Exact token and dollar costs were not emitted by the benchmark harness.


Methodology
-----------
Ground-truth handling:

  - Added explicit Cloud-OpsBench ground-truth modes:
      hidden: do not replay expert trajectory and do not inject root cause.
      oracle: preserve old adapter behavior for plumbing sanity tests only.
  - Official benchmark runs used hidden mode.
  - Oracle mode was not used for the reported Mesh Cloud-OpsBench scores.

Split:

  - Dev split: 6 official Cloud-OpsBench cases.
  - Eval split: 16 official Cloud-OpsBench cases.
  - No code or scoring changes were made after observing the eval results.

Eval cases:

  - Systems: boutique, trainticket.
  - Fault groups represented in eval:
      boutique/admission, boutique/infrastructure, boutique/performance,
      boutique/runtime, boutique/scheduling, boutique/service,
      boutique/startup, trainticket/performance, trainticket/runtime,
      trainticket/service, trainticket/startup.
  - Root-cause labels represented in eval:
      containerd_unavailable, db_connection_exhaustion, gateway_misrouted,
      image_registry_dns_failure, incorrect_image_reference,
      liveness_probe_incorrect_protocol, missing_secret_binding,
      missing_service_account, node_cordon_mismatch, pod_cpu_overload,
      pod_network_delay, service_env_var_address_mismatch.

Repetition:

  - Mesh dev: repeat=3, 18 total attempts.
  - Mesh eval: repeat=3, 48 total attempts.
  - OpenSRE baseline: attempted repeat=3 on an earlier 4-case eval subset; 8
    attempts completed, 4 failed after Anthropic credit exhaustion.

Scoring interpretation:

  - Mesh operational score measures safe bounded behavior: escalation, safety,
    recovery routing, latency, and learning artifact presence.
  - Agentic RCA score and process metrics are the Cloud-OpsBench-relevant
    indicators: root-cause accuracy, trajectory order match, tool coverage,
    invalid action count, and related process metrics.
  - The weighted score is not the headline for Cloud-OpsBench because safe
    escalation can score highly while RCA remains unsolved.


Commands
--------
Mesh eval, larger hidden split:

  set -a; source .env.benchmark; set +a
  python3 -m services.benchmark run \
    --suite cloudopsbench_official_eval \
    --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
    --provider cloudopsbench \
    --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
    --cloudopsbench-ground-truth-mode hidden \
    --repeat 3 \
    --agent-fabric-mode deepagents \
    --agent-tasks-mode blocking \
    --agent-lane investigator \
    --agent-task-timeout-seconds 60 \
    --deepagents-model claude-haiku-4-5-20251001 \
    --backend-timeout-seconds 300 \
    --output .mesh-runtime-state/benchmarks/cloudopsbench-official-hidden-mesh-16eval

Mesh dev:

  python3 -m services.benchmark run \
    --suite cloudopsbench_official_dev \
    --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
    --provider cloudopsbench \
    --cloudopsbench-root .mesh-runtime-state/external-benchmarks/Cloud-OpsBench-sparse \
    --cloudopsbench-ground-truth-mode hidden \
    --repeat 3 \
    --output .mesh-runtime-state/benchmarks/cloudopsbench-official-hidden-mesh-6dev

OpenSRE baseline attempt:

  set -a; source .env.benchmark; set +a
  python3 -m services.benchmark run \
    --suite cloudopsbench_official_eval \
    --scenario-root .mesh-runtime-state/official-benchmark/scenarios \
    --backend opensre-cli \
    --repeat 3 \
    --backend-timeout-seconds 300 \
    --output .mesh-runtime-state/benchmarks/cloudopsbench-official-hidden-opensre-alert-only-escalated


Results
-------
Mesh Cloud-OpsBench hidden eval:

  - Run: bench_20260504T083705604096Z
  - Report: .mesh-runtime-state/benchmarks/cloudopsbench-official-hidden-mesh-16eval/bench_20260504T083705604096Z/report.md
  - Scenarios: 16
  - Attempts: 48
  - Repeat count: 3
  - Weighted score: 93.50 / 100
  - Mesh operational score: 100.00 / 100
  - Agentic RCA score: 30.00 / 100
  - Weighted score stddev: 0.0000
  - Pass rate: 100.00%
  - Unsafe action rate: 0.00%
  - P95 latency: 69.92 ms
  - Root-cause accuracy: 0.0000
  - Trajectory in-order match: 0.0000
  - Tool coverage: 0.0000
  - Invalid action count average: 0.0000

Mesh Cloud-OpsBench hidden dev:

  - Run: bench_20260504T083715534015Z
  - Scenarios: 6
  - Attempts: 18
  - Weighted score: 93.50 / 100
  - Mesh operational score: 100.00 / 100
  - Agentic RCA score: 30.00 / 100
  - Root-cause accuracy: 0.0000
  - Tool coverage: 0.0000

OpenSRE alert-only baseline, partial:

  - Run: bench_20260504T082745744637Z
  - Report: .mesh-runtime-state/benchmarks/cloudopsbench-official-hidden-opensre-alert-only-escalated/bench_20260504T082745744637Z/report.md
  - Scenarios: 4
  - Attempts: 12
  - Successful attempts: 8
  - Failed attempts: 4, all due to Anthropic credit exhaustion.
  - All-attempt weighted score: 62.33 / 100
  - All-attempt agentic RCA score: 35.00 / 100
  - Successful-only weighted mean: 89.50 / 100
  - Successful-only agentic RCA mean: 40.00 / 100
  - Root-cause accuracy: 0.0000
  - Tool coverage: 0.0000
  - Trajectory in-order match: 0.0000


Interpretation
--------------
Mesh did the safe thing on every hidden Cloud-OpsBench eval case: it escalated
unknown production-like incidents without unsafe mutation. That is good
control-plane behavior.

Mesh did not solve Cloud-OpsBench RCA. It did not produce the official root
cause labels, did not follow expert diagnostic trajectories, and did not use
the Cloud-OpsBench tool families in hidden mode. The current agentic RCA score
of 30/100 is mostly base investigation/artifact credit, not real RCA success.

OpenSRE was better as an LLM investigation shell on completed attempts, but it
also did not recover any official root cause labels or tool trajectories from
the alert-only input. Its repeat=3 run cannot be treated as a clean baseline
because the third repeat failed from Anthropic account credit exhaustion.

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
    pytest tests/test_benchmark_harness.py -q
  - PASS: RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark
    tests/test_benchmark_harness.py
  - PASS: TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable .
    --with deepagents --with mypy mypy --strict --exclude
    'deepagents/|latent-mesh/LatentMAS/|services/skills/'

Full-suite validation:

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
These results are shareable as an honest engineering benchmark packet:

  - SREGym: no official score; environment blocked.
  - Cloud-OpsBench: official sparse hidden eval ran, repeat=3, 16 cases.
  - Mesh result: operationally safe, RCA/process score currently poor.
  - Baseline result: OpenSRE partial alert-only run, not clean due API credits.

The measurable next target is to move Mesh Cloud-OpsBench hidden eval from:

  root_cause_accuracy=0.0, tool_coverage=0.0

to:

  root_cause_accuracy >= 0.25 and tool_coverage >= 0.50 on the 16-case eval
  split without using oracle mode or tuning on eval cases.
