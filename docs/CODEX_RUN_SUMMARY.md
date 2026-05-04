# CODEX Run Summary

This file is a chronological run log. Older entries preserve the state that
existed when they were written, including scaffold-era mock and placeholder
language. Current integration boundaries, fallback classification, and release
validation status live in [`docs/integrations.md`](./integrations.md) and
[`docs/production-readiness-validation.md`](./production-readiness-validation.md).

## Run: 2026-04-06 00:00 (local)

### Scope
- Delivered the first Python multi-service scaffold for the closed-loop platform, including shared contract models, stage services, Promptfoo/Goose integration seams, a runnable first infrastructure-healing slice, and updated architecture documentation that now distinguishes implemented pieces from remaining work.

### Changes
- Added Python project setup in `pyproject.toml`.
- Added shared runtime package in `shared/mesh_runtime/` for contract models, schema validation, event envelopes, config, fixture loading, and policy loading.
- Added service implementations in `services/ingest/`, `services/trigger/`, `services/diagnosis/`, `services/planner/`, `services/evaluation/`, `services/orchestrator/`, `services/feedback/`, and `services/actuators/`.
- Added `services/evaluation/promptfoo_adapter.py` with mock and CLI-placeholder Promptfoo modes.
- Added `services/orchestrator/goose_adapter.py` with mock and CLI-placeholder Goose modes.
- Added first-slice runner in `run_first_slice.py` and wiring in `services/pipeline.py`.
- Added runtime policy files in `policies/`.
- Added deterministic fixtures in `fixtures/`.
- Added tests in `tests/test_contracts.py` and `tests/test_pipeline.py`.
- Rewrote `architecture.md` to reflect the current scaffolded architecture, implemented components, and remaining TODOs.

### How It Works Now
- A raw infrastructure-healing signal is normalized by ingest into an event envelope.
- Trigger detection emits a `Trigger` when the regression is material and persistent.
- Diagnosis and planning produce deterministic first-slice outputs.
- Evaluation validates policy and routes through the Promptfoo adapter boundary.
- Orchestration routes approved plans through the Goose adapter boundary and local mock actuators.
- Feedback records a deterministic recovery outcome and learning summary.

### Files Touched
- `pyproject.toml` with Python package setup.
- `shared/mesh_runtime/*` with shared runtime primitives.
- `services/*` with stage services, pipeline wiring, and integration seams.
- `policies/*.json` with autonomy, protected-scope, and rollback rules.
- `fixtures/*` with deterministic first-slice inputs.
- `tests/test_contracts.py` and `tests/test_pipeline.py` with scaffold validation.
- `architecture.md` with updated current-state architecture documentation.

### Validation
- Ran `python3 -m unittest discover -s tests -v`: passed.
- Read lints for changed Python files and docs: no issues reported.

### Risks / Follow-ups
- Promptfoo and Goose real production integrations are not implemented yet; only mock mode plus CLI-placeholder seams exist. Updated on 2026-04-08: superseded by the later real bridge foundation entry below.
- Persistence, async messaging, world-model storage, and production observability remain TODOs.
- Diagnosis, planning, and feedback logic are deterministic placeholders rather than learned or evidence-rich implementations.

## Run: 2026-04-08 05:55 (UTC)

### Scope
- Upgraded the `stable-mesh` runtime from placeholder integration seams into richer real-integration foundations: Promptfoo now drives evaluation artifacts from parsed CLI results, Goose returns structured review metadata and failure context, the control plane persists typed integration events and readiness snapshots, and the deterministic trigger/decision/feedback path now carries more evidence-aware runtime state.

### Changes
- Reworked `services/evaluation/promptfoo_bridge.py` to generate real Promptfoo assertion configs, export JSON results, parse pass/fail plus assertion details, and return structured artifacts instead of a smoke-check-only success bit.
- Extended `services/evaluation/promptfoo_adapter.py`, `services/evaluation/service.py`, and `services/evaluation/cli_gate.py` so Promptfoo artifacts flow into `stage_results["promptfoo_quality"]` with mode, notes, and assertion summaries.
- Reworked `services/orchestrator/goose_bridge.py`, `services/orchestrator/goose_adapter.py`, `services/orchestrator/service.py`, and `services/orchestrator/cli_executor.py` so Goose review/execution returns structured review JSON, richer failure context, and review-backed execution artifacts rather than only ACK text.
- Added typed run-event metadata in `shared/mesh_runtime/control_plane_models.py`, `shared/mesh_runtime/control_plane_state.py`, and `shared/mesh_runtime/run_events.py` for artifact keys, integration names, and status tracking.
- Expanded persistence in `services/control_plane.py` and `services/runtime.py` so runs record readiness snapshots, Promptfoo/Goose integration artifacts, replay-friendly stage events, and richer run-history counters through the existing `.mesh-runtime-state` model.
- Deepened deterministic runtime logic in `services/trigger/service.py`, `services/decision/service.py`, and `services/feedback/service.py` with trigger-signal evidence, confidence adjustments, credential-aware escalation, and feedback-side integration observations.
- Added lightweight structured logging support in `shared/mesh_runtime/logging.py` and instrumented evaluation/orchestration bridge/service flows.
- Updated `scaffold/contracts/schemas/decision.schema.json`, `web/src/types.ts`, and integration/runtime tests to match the richer contract and event shapes.

### How It Works Now
- Run creation captures an integration readiness snapshot, stores it in the run session, and records a typed readiness event before execution begins.
- During evaluation in `promptfoo` mode, the bridge writes a generated Promptfoo config with contract assertions, runs `promptfoo eval --output ...`, parses the result JSON, and feeds pass/fail, score, notes, and assertion artifacts into the mesh evaluation contract.
- During orchestration in `goose` mode, Goose is asked for compact JSON review output; the runtime stores approval/rejection metadata, routes retryable failures to incident creation, and keeps review artifacts attached to the execution record.
- Both the synchronous runtime and the control plane now emit replay-friendly stage events with `artifact_key`, `integration_name`, and `status` fields so the same event log can later back a real bus or projection layer.
- Trigger, decision, and feedback stages now preserve richer evidence in the existing contract shapes without replacing the current bounded deterministic control loop.

### Files Touched
- `services/evaluation/promptfoo_bridge.py` with real Promptfoo eval/export/parse flow.
- `services/evaluation/promptfoo_adapter.py`, `services/evaluation/service.py`, and `services/evaluation/cli_gate.py` with richer evaluation artifacts.
- `services/orchestrator/goose_bridge.py`, `services/orchestrator/goose_adapter.py`, `services/orchestrator/service.py`, and `services/orchestrator/cli_executor.py` with structured Goose review and failure handling.
- `services/control_plane.py` and `services/runtime.py` with readiness snapshots, typed run events, and persisted integration artifacts.
- `services/trigger/service.py`, `services/decision/service.py`, and `services/feedback/service.py` with deeper deterministic evidence logic.
- `shared/mesh_runtime/control_plane_models.py`, `shared/mesh_runtime/control_plane_state.py`, `shared/mesh_runtime/state.py`, `shared/mesh_runtime/run_events.py`, `shared/mesh_runtime/logging.py`, and `shared/mesh_runtime/__init__.py` with event, persistence, and logging support.
- `scaffold/contracts/schemas/decision.schema.json` and `web/src/types.ts` with updated contract/UI compatibility.
- `tests/test_integrations.py` and `tests/test_loop_behaviors.py` with artifact and typed-event coverage.

### Validation
- Ran `python3 -m unittest discover -s tests -v`: passed.
- Ran targeted regressions for `tests.test_loop_behaviors`, `tests.test_pipeline`, `tests.test_tui_controller`, and `tests.test_control_plane`: passed.
- Read lints for changed runtime, service, test, and UI type files: no issues reported.

### Risks / Follow-ups
- Promptfoo parsing is robust against current documented JSON exports, but the bridge still depends on CLI output shape staying compatible across Promptfoo versions.
- Goose review is now structured, but it still relies on prompt discipline rather than a hard schema-enforced recipe path.
- The event model is now bus-friendly, but there is still no external broker/database projection or durable world-model store yet.
- Structured logs are opt-in through `MESH_STRUCTURED_LOGS`; centralized log shipping, metrics, and deployment manifests remain future work.

## Run: 2026-04-08 06:10 (UTC)

### Scope
- Rewrote `architecture.md` so it matches the current bounded control-plane runtime instead of the older simplified MVP sketch, then performed conservative repository housekeeping by removing stale aspirational docs and clearing generated local runtime state from the tree.

### Changes
- Replaced `architecture.md` with a current-state architecture document covering the core loop, control plane, integration bridges, run lifecycle, persistence model, execution boundary, and what is or is not real today.
- Updated `README.md` supporting-doc links to point at active docs instead of the removed early-vision flow document.
- Removed stale aspirational docs: `data-flows.md` and `mesh-intelligence-context.md`.
- Cleared generated local runtime artifacts under `.mesh-runtime-state/` so the repository reflects source instead of checked-in run output.
- Marked the outdated 2026-04-06 Promptfoo/Goose risk note as superseded by the newer 2026-04-08 integration entry.

### How It Works Now
- `architecture.md` now documents the actual current shape: bounded remediation services feed into the control plane, Promptfoo/Goose bridges enrich evaluation and orchestration, and run state persists to the local event log plus vault/Merkle outputs.
- The repo docs now center on active sources of truth: `README.md`, `architecture.md`, `first-closed-loop-contract.md`, and this run summary.
- Generated local state is treated as disposable runtime output rather than repository content.

### Files Touched
- `architecture.md` with current runtime/control-plane architecture.
- `README.md` with cleaned supporting-doc references.
- `docs/CODEX_RUN_SUMMARY.md` with supersession note and this housekeeping entry.
- Deleted `data-flows.md` and `mesh-intelligence-context.md` as stale aspirational docs.
- Deleted generated files under `.mesh-runtime-state/`.

### Validation
- Ran `python3 -m unittest discover -s tests -v`: passed.
- Searched for stale references to removed docs: none found.
- Read lints for changed docs: no issues reported.

### Risks / Follow-ups
- `architecture.md` is now aligned with the current runtime, but future large behavior changes should update it in the same run to avoid drift.
- Empty directories may still remain under `.mesh-runtime-state/`, which is acceptable because the path is ignored and repopulated at runtime.
- Additional housekeeping could later remove or archive older scaffold-era documents, but those were intentionally kept because they still provide useful historical contract context.

## Run: 2026-05-02 14:47 (+08)

### Scope
- Added the first agentic-SRE implementation slice: a living work harness plus a conservative read-only investigation stage that runs after evidence assembly and before scenario analysis while preserving bounded execution and policy gates.

### Changes
- Added `docs/AGENTIC_SRE_HARNESS.txt` as the detailed living harness for the agentic-SRE roadmap, active checkpoint, validation matrix, file map, and safety invariants.
- Added `InvestigationPlan`, `InvestigationProbeResult`, and `InvestigationReport` contracts with JSON Schemas.
- Added `services/investigation/` with deterministic built-in read-only probes for evidence sufficiency, trigger signatures, memory context, and topology context.
- Wired `investigation_ready` into the synchronous runtime and control-plane run coordinator with an `investigation_report` artifact and non-fatal failure handling.
- Made scenario analysis consume investigation reports as advisory evidence and made decisions attach investigation metadata without bypassing policy.
- Updated the web run graph stage ordering/icons and added focused investigation tests.

### How It Works Now
- Runs assemble an evidence pack, then create an investigation report before scenario analysis.
- The investigation report records a read-only probe plan, probe results, citations, uncertainty, stop reason, safety notes, and a recommendation to continue through the existing Mesh pipeline.
- Scenario analysis can record the investigation report as advisory evidence; `DecisionService` attaches report metadata to reasoning, but evaluation and actuation remain authoritative.
- If investigation raises, Mesh records a contract-valid failed report and continues the existing deterministic path.

### Files Touched
- `docs/AGENTIC_SRE_HARNESS.txt` with the living work harness.
- `services/investigation/service.py` with the read-only investigation service.
- `shared/mesh_runtime/contracts.py` and `shared/mesh_runtime/schemas/investigation-*.schema.json` with new contracts.
- `services/runtime.py`, `services/control_plane.py`, `services/scenario_analysis/service.py`, and `services/decision/service.py` with pipeline wiring.
- `web/src/lib/runGraph.ts`, `web/src/lib/format.ts`, and `web/src/App.tsx` with stage display support.
- `tests/test_investigation_service.py` with first-slice coverage.

### Validation
- `python3 -m unittest tests.test_investigation_service -v`: passed.
- `python3 -m py_compile services/investigation/service.py services/runtime.py services/control_plane.py services/scenario_analysis/service.py services/decision/service.py shared/mesh_runtime/contracts.py`: passed.
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check ...`: passed after rerunning with `/tmp` uv caches and network approval.
- `python3 -m unittest tests.test_loop_behaviors tests.test_pipeline -v`: passed except `test_kubernetes_probe_failure_alone_escalates`, where current code returns `defer_until` while the existing test expects `escalate`.
- `python3 -m unittest tests.test_control_plane -v`: local-server binding required elevated permission; after rerun, most tests passed but the suite still reported a missing recovery artifact and temp-dir cleanup races from background work.
- `npm --prefix web run build`: TypeScript reached Vite, then failed with `crypto.getRandomValues is not a function` in the active Node/Vite runtime.
- Targeted strict mypy still reports broad pre-existing export/type issues across imported modules, not isolated to the investigation slice.

### Risks / Follow-ups
- The investigation planner is deterministic only; LLM-driven probe planning is intentionally deferred.
- Live observability probes are not implemented yet.
- Bayesian priors and agent-lane arbitration remain future workstreams.
- Control-plane background cleanup/race behavior should be stabilized before treating the full HTTP suite as green.

## Run: 2026-05-02 15:15 (+08)

### Scope
- Added the first measurable architecture benchmark harness for agentic-SRE iterations, including a golden scenario suite, weighted scorecard output, Markdown reporting, and a Loghub corpus extraction adapter for broader offline log-anomaly scenarios.

### Changes
- Added `services/benchmark/` with benchmark models, scenario loading, scoring, report rendering, CLI execution, and Loghub extraction.
- Added `benchmarks/scenarios/golden/` with three initial architecture benchmark scenarios: feature-flag latency disable, Kubernetes crash-loop patch, and unknown OTel metric escalation.
- Added `benchmarks/corpora/loghub_manifest.json` to document public Loghub provenance and the local extraction workflow.
- Added `tests/test_benchmark_harness.py` covering suite loading, score weights, benchmark artifact writing, unsafe-action scoring, and Loghub scenario extraction.
- Updated `docs/AGENTIC_SRE_HARNESS.txt` with external agentic-SRE benchmark patterns, W5 checkpoint results, validation status, and the first measured score.

### How It Works Now
- `python -m services.benchmark run --suite golden` runs Mesh in native evaluation/orchestration mode against scenario fixtures and writes `benchmark.json`, `scorecard.json`, `scenario-results.jsonl`, and `report.md`.
- The scorecard measures safety, decision correctness, investigation grounding, recovery, latency, and learning hooks with explicit weights.
- `python -m services.benchmark extract-loghub --dataset DATASET --input /path/to/loghub/DATASET --output benchmarks/scenarios/loghub` turns local Loghub files into provenance-rich OTel-style benchmark scenarios without network access.
- The first golden baseline is 69.00 / 100 with 0.00% unsafe-action rate; the long-tail OTel scenario currently exposes an unknown-metric pipeline error instead of clean escalation.

### Files Touched
- `services/benchmark/*.py` with the benchmark harness implementation.
- `benchmarks/scenarios/golden/*.json` with the initial scenario corpus.
- `benchmarks/corpora/loghub_manifest.json` with external corpus metadata.
- `tests/test_benchmark_harness.py` with focused validation.
- `docs/AGENTIC_SRE_HARNESS.txt` and `docs/CODEX_RUN_SUMMARY.md` with work log updates.

### Validation
- `python3 -m unittest tests.test_benchmark_harness -v`: passed.
- `python3 -m services.benchmark run --suite golden --output /tmp/mesh-benchmark-smoke`: passed, score 69.00 / 100.
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py tests/test_investigation_service.py`: passed, 8 tests.
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark tests/test_benchmark_harness.py`: passed.
- `python3 -m py_compile services/benchmark/*.py tests/test_benchmark_harness.py`: passed.
- Targeted strict mypy still reports existing broader runtime/import strictness issues when importing `services.runtime`; local benchmark typing issues found in that run were cleaned up.

### Risks / Follow-ups
- Add an architecture comparison command so scorecards can be diffed run-to-run.
- Fix unknown OTel metric handling so the benchmarked long-tail scenario cleanly escalates.
- Add larger generated Loghub suites once a local corpus is available, keeping corpus-derived scenarios separate from full incident/recovery fixtures.

## Run: 2026-05-03 22:18 (+08)

### Scope
- Upgraded the benchmark harness toward industry-style methodology by adding repeated-run statistics and artifact-to-artifact comparison, so architecture iterations can be evaluated by deltas and variance rather than one-off scores.

### Changes
- Extended `BenchmarkRunConfig` with `repeat` and recorded an `iteration` on every scenario result.
- Extended `BenchmarkScorecard` with `scenario_attempt_count`, `iteration_count`, `weighted_score_stddev`, `weighted_score_min`, and `weighted_score_max`.
- Updated Markdown reports to include attempts, iterations, score standard deviation, and per-row iteration numbers.
- Added `services/benchmark/compare.py` for benchmark directory comparison across weighted score, dimension scores, pass rate, unsafe-action rate, p95 latency, and per-scenario score.
- Added `python -m services.benchmark compare BASELINE_DIR CANDIDATE_DIR`, writing `comparison.json` and `comparison.md` into the candidate run directory by default.
- Expanded `tests/test_benchmark_harness.py` with repeated-run and comparison artifact coverage.

### How It Works Now
- `python -m services.benchmark run --suite golden --repeat 3` executes each selected scenario three times, writes each attempt to `scenario-results.jsonl`, and aggregates stability metrics into `scorecard.json`.
- `python -m services.benchmark compare old_run_dir new_run_dir` reads the existing `benchmark.json` artifacts and produces a compact delta report.
- The compare report explicitly marks added, removed, changed, and unchanged scenarios so different scenario sets are visible instead of hidden inside aggregate means.

### Files Touched
- `services/benchmark/models.py`, `services/benchmark/runner.py`, `services/benchmark/scoring.py`, and `services/benchmark/report.py` with repeat-aware scorecards.
- `services/benchmark/compare.py` and `services/benchmark/__main__.py` with comparison support.
- `services/benchmark/__init__.py` with exported comparison entry point.
- `tests/test_benchmark_harness.py` with new regression coverage.
- `docs/AGENTIC_SRE_HARNESS.txt` and `docs/CODEX_RUN_SUMMARY.md` with work log updates.

### Validation
- `python3 -m unittest tests.test_benchmark_harness -v`: passed, 6 tests.
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py tests/test_investigation_service.py`: passed, 10 tests.
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark tests/test_benchmark_harness.py`: passed.
- `python3 -m py_compile services/benchmark/*.py tests/test_benchmark_harness.py`: passed.
- CLI smoke: repeated feature-flag benchmark with `--repeat 2` passed with score 93.50 and stddev 0.0000.
- CLI smoke: compare command wrote `comparison.json` and `comparison.md`, surfacing an added Kubernetes scenario.

### Risks / Follow-ups
- Add CI threshold gates once the golden suite is less tiny.
- Add confidence intervals across larger stochastic suites.
- Add containerized benchmark execution and a locked/hidden evaluation set before claiming public benchmark comparability.

## Run: 2026-05-04 14:45 (+08)

### Scope
- Tightened the SREGym and Cloud-OpsBench parity slice from benchmark-shaped scaffolding into adapters that match the real external contracts.

### Changes
- Updated `services.benchmark.sregym_agent` to use SREGym’s actual MCP tool arguments: `submit(ans=...)`, kubectl `cmd`, and Prometheus `query`.
- Added an SSE MCP client for SREGym mounts at `/kubectl/sse`, `/prometheus/sse`, `/loki/sse`, `/jaeger/sse`, and `/submit/sse`, with client-side read-only kubectl validation.
- Added SREGym agent registry rendering via `python -m services.benchmark.sregym_agent --print-agent-yaml`.
- Added trigger bootstrapping from SREGym read-only observations for real launches that do not pass a Mesh trigger JSON.
- Extended Cloud-OpsBench loading to understand official case directories such as `benchmark/boutique/startup/25/metadata.json` plus `tool_cache.json`.
- Converted Cloud-OpsBench metadata root cause and process paths into benchmark evidence and deterministic tool trajectories while keeping the runtime signal mapped to Mesh’s existing metric-regression contract.

### Validation
- `python3 -m py_compile services/benchmark/sregym_agent.py services/benchmark/cloudopsbench.py services/benchmark/backends.py tests/test_benchmark_harness.py`: passed.
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark tests/test_benchmark_harness.py`: passed.
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py tests/test_investigation_service.py`: passed, 17 tests.
- `python3 -m services.benchmark.sregym_agent --print-agent-yaml --server-url http://localhost:8000 --workdir /Users/madhavgoyal/ai/mesh`: produced a valid SREGym `agents.yaml`-shaped entry.
- Full `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest`: attempted; 763 passed, 1 skipped, 6 failed in existing control-plane/deepagents/LatentMAS/state-store tests.
- Full `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .`: attempted; failed on pre-existing/unrelated `.claude/worktrees` and vendored LatentMAS/deepagents files.
- `TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict --exclude 'deepagents/|latent-mesh/LatentMAS/|services/skills/'`: passed for the configured source scope.

### Risks / Follow-ups
- Live SREGym still needs the local kind benchmark services running before the SSE MCP client can produce a real trajectory.
- Cloud-OpsBench now loads official case shape; the next step is generating a broad suite manifest across systems and fault categories.

## Run: 2026-05-04 13:30 (+08)

### Scope
- Added the first benchmark-parity slice for SREGym and Cloud-OpsBench so Mesh can measure live-environment SRE workflow compatibility and deterministic snapshot RCA gaps through the existing benchmark harness.

### Changes
- Extended benchmark scenarios/results with process-centric RCA fields: expert trajectories, required tool families, root-cause accuracy, trajectory order match, tool relevance/coverage, invalid action count, redundant action rate, zero-tool diagnosis, and MTTI.
- Added separate scorecard views for `mesh_operational_score` and `agentic_rca_score` while preserving the existing weighted score and dimension scores.
- Added SREGym provider/backend support plus `services.benchmark.sregym_agent`, a registerable local-kind scoped Mesh agent wrapper that submits diagnosis before mitigation and refuses non-local benchmark targets.
- Added Cloud-OpsBench provider/backend support with deterministic snapshot tool replay and Mesh runtime execution against snapshot-derived signals.
- Added `services.benchmark.gaps` and `python -m services.benchmark gaps --provider ... --run ...` for capability gap reports grouped by setup, trigger normalization, evidence, tool syntax, RCA, decision mapping, mitigation safety, recovery, and learning.

### How It Works Now
- `python -m services.benchmark run --suite golden --provider sregym` produces SREGym-normalized benchmark artifacts with tool trajectories and process metrics.
- `python -m services.benchmark run --suite cloudopsbench --provider cloudopsbench --scenario-root ...` can run inline Cloud-OpsBench-style snapshots without live cluster access.
- Reports now show weighted score, operational score, RCA score, process metrics, and per-scenario Ops/RCA columns.
- Gap reports write `gap_report.json` and `gap_report.md` into a benchmark run directory.

### Validation
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py tests/test_investigation_service.py`: passed, 15 tests.

### Risks / Follow-ups
- This is parity scaffolding, not an official SREGym or Cloud-OpsBench leaderboard submission path yet.
- SREGym live MCP transport should be exercised after the local kind benchmark infra is installed.
- Cloud-OpsBench official repo/data import needs a larger suite mapping once local assets are available.

## Run: 2026-05-03 22:23 (+08)

### Scope
- Added an external-agent benchmark backend for OpenSRE-style systems so Mesh can score OpenSRE CLI investigations against the same golden scenarios and compare those results with native Mesh runs.

### Changes
- Added `services/benchmark/backends.py` with a default Mesh backend and an `opensre-cli` backend.
- Extended `BenchmarkRunConfig` and the CLI with `--backend`, `--opensre-command`, and `--backend-timeout-seconds`.
- Added backend labels to scenario result rows and benchmark Markdown reports.
- Converted Mesh benchmark scenarios into neutral OpenSRE alert JSON without leaking expected decisions.
- Normalized OpenSRE CLI text output into the existing benchmark outcome shape with inferred decision, investigation report, citations, and feedback stub.
- Added fake OpenSRE CLI test coverage in `tests/test_benchmark_harness.py`.
- Updated `docs/AGENTIC_SRE_HARNESS.txt` with OpenSRE backend status and setup caveats.

### How It Works Now
- Native Mesh benchmark:
  `python -m services.benchmark run --suite golden --backend mesh`
- OpenSRE CLI benchmark:
  `python -m services.benchmark run --suite golden --backend opensre-cli`
- The OpenSRE backend runs `uvx opensre --json investigate -i INPUT -o OUTPUT`, with `OPENSRE_NO_TELEMETRY=1` and `OPENSRE_ANALYTICS_DISABLED=1` set by default for benchmark runs.
- If OpenSRE emits JSON/report text, the harness infers a bounded action such as `disable_flag`, `rollback_deployment`, `investigate_and_patch`, `restart_deployment`, `no_action`, or `escalate`, then scores it with the same benchmark rubric.
- Setup/backend failures now receive zero safety, latency, and learning credit so fast failures do not look like fast investigations.

### Files Touched
- `services/benchmark/backends.py` with external backend support.
- `services/benchmark/runner.py`, `services/benchmark/models.py`, `services/benchmark/scoring.py`, `services/benchmark/report.py`, and `services/benchmark/__main__.py` with backend-aware execution and reporting.
- `tests/test_benchmark_harness.py` with fake OpenSRE CLI coverage.
- `docs/AGENTIC_SRE_HARNESS.txt` and `docs/CODEX_RUN_SUMMARY.md` with implementation notes.

### Validation
- `python3 -m unittest tests.test_benchmark_harness -v`: passed, 7 tests.
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py tests/test_investigation_service.py`: passed, 11 tests.
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/benchmark tests/test_benchmark_harness.py`: passed.
- `python3 -m py_compile services/benchmark/*.py tests/test_benchmark_harness.py`: passed.
- Real OpenSRE CLI smoke completed through the harness via `uvx opensre`, but scored only the missing provider-key setup error because no `LLM_PROVIDER`/matching API key was present in the environment.

### Risks / Follow-ups
- Set `LLM_PROVIDER` and the matching provider API key in the shell environment before real OpenSRE runs.
- Replace text-output inference with structured OpenSRE JSON output if/when a stable machine-readable report flag is available.

## Run: 2026-05-04 16:06 (+08)

### Scope
- Added a full control-plane benchmark mode so Mesh can be measured with investigation, scenario analysis, decision/evaluation, execution feedback, and agent-mesh proposal lanes rather than only the fast deterministic runtime path.

### Changes
- Added `mesh-control-plane` / `mesh-agentic` benchmark backend aliases that drive `RunCoordinator` and persist raw attempt artifacts.
- Benchmark runs now write `attempt-artifacts/iteration-N/SCENARIO.json` with `control_plane_run`, `run_events`, `agent_tasks`, `reconciliation`, and `tool_trajectory`.
- Added benchmark CLI controls for agent fabric, lane selection, blocking/async agent tasks, Deep Agents model, context budget, output token budget, and control-plane timeout.
- Added `agent_mesh_agents` / `MESH_AGENT_MESH_AGENTS` so benchmark runs can restrict lanes, e.g. `--agent-lane hermes`.
- Improved Deep Agents adapter setup by resolving the vendored SDK path, compacting context fragments, bounding Anthropic output tokens, and avoiding executor waits after timeouts.
- Kept `deepagents_output_unparseable` as an output-quality risk without counting it as an invalid tool/action call.

### How It Works Now
- Fast deterministic benchmark remains: `python -m services.benchmark run --suite golden --backend mesh`.
- Full native control-plane benchmark: `python -m services.benchmark run --suite golden --backend mesh-control-plane --agent-fabric-mode native --agent-tasks-mode blocking`.
- Low-quota live LLM lane smoke: run `mesh-control-plane` with `--agent-fabric-mode deepagents --agent-lane hermes --deepagents-max-artifact-chars 2000 --deepagents-max-output-tokens 512`.

### Files Touched
- `services/benchmark/backends.py`, `runner.py`, and `__main__.py` with full-control-plane backend, raw artifact persistence, and CLI controls.
- `services/orchestrator/agent_mesh.py` with lane filtering.
- `services/orchestrator/deepagents_adapter.py` with SDK resolution, context/output budget handling, and bounded timeout behavior.
- `shared/mesh_runtime/config.py` with new agent-lane and Deep Agents budget config.
- `tests/test_benchmark_harness.py` with control-plane artifact/lane coverage.
- `docs/AGENTIC_SRE_HARNESS.txt` with detailed benchmark run notes and gaps.

### Validation
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check services/orchestrator/agent_mesh.py services/orchestrator/deepagents_adapter.py services/benchmark shared/mesh_runtime/config.py tests/test_benchmark_harness.py`: passed.
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest tests/test_benchmark_harness.py -q`: passed, 14 tests.
- Native full-control-plane golden run `bench_20260504T074259470997Z`: score 84.33, operational 100.00, agentic RCA 55.00.
- Compact live Deep Agents Hermes scenario `bench_20260504T080650045071Z`: score 83.50, operational 100.00, agentic RCA 90.00; Hermes completed with useful RCA text but missed the strict JSON envelope.

### Risks / Follow-ups
- Add constrained-output retry/schema repair for Deep Agents lane responses.
- Add rate-limit aware lane scheduling before running all six Deep Agents lanes on low TPM keys.
- Add a separate output-schema-compliance metric so RCA quality and JSON discipline are visible independently.
