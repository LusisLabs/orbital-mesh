# AI SRE Platform Spine

Mesh now has an implementation spine for the AI SRE roadmap: sandboxed simulation catalog, benchmark records, service-agent routing, lane-routing artifacts, and agent reconciliation.

## Interfaces

- `GET /api/simulations` lists built-in sandbox scenarios.
- `POST /api/simulations/{scenario_id}/run` starts a simulation-backed Mesh run when `MESH_SIMULATION_ENABLED=1`.
- `GET /api/benchmarks` and `GET /api/benchmarks/{benchmark_id}` expose benchmark results.
- `GET /api/service-agents` lists configured service agents.
- `GET /api/reconciliation/{run_id}` returns the agent reconciliation artifact for a run.

## Safety Defaults

Simulation execution is disabled by default. A simulation run requires:

- `MESH_SIMULATION_ENABLED=1`
- `MESH_SIMULATION_CONTEXT_ALLOWLIST` containing the scenario kube context
- a non-production namespace in the scenario sandbox metadata

Simulation runs still use normal Mesh policy, evaluation, operator steering, audit events, Merkle roots, and bounded actuators. The simulation plane does not bypass Kubernetes allowlists or production execution guards.

## Dataset Export

When a run carries `simulation_context`, Mesh records:

- `benchmark_score`
- `dataset_export_ref`
- JSONL row at `MESH_BENCHMARK_EXPORT_PATH`

Rows include scenario metadata, input signal, decision, evaluation, agent tasks, service-agent route, lane route, reconciliation, execution, feedback, events, and Merkle snapshot.

## Parallel Stress Harness

Use the local coordinator stress harness to run simulation-backed control-plane runs in parallel:

```bash
python3 scripts/run_simulation_matrix.py --iterations 32 --workers 8 --output .mesh-runtime-state/simulation-stress/run-32x8
```

The harness:

- uses isolated temp state per worker;
- enables simulation and benchmark export;
- installs a scoped service-agent config for the built-in search and API scenarios;
- waits for terminal or operator-awaiting state plus benchmark export before cleanup;
- writes `summary.json`, `runs.json`, `dataset.jsonl`, `override-replay.jsonl`, and `stress-report.md`.

The expanded catalog covers CrashLoop, ImagePullBackOff, OOMKilled, probe failure, CPU saturation, queue lag, memory pressure, request spikes, weak-signal no-action controls, missing credentials, high-impact escalation, dependency latency, cascading namespace impact, and adversarial OTel no-rule escalation. Operator-awaiting simulation runs are benchmarked as learning outcomes instead of being hidden as harness timeouts.

Pass/fail dimensions are split into `safe_autonomy_pass` and `correct_pause_pass`. A scenario that correctly pauses for high risk, missing authority, or human review can pass as a bounded SRE outcome even when it does not execute autonomously. Benchmark rows also include normalized blocker classes so evaluator quality, confidence, approval, risk, and human-review failures can be tracked independently.

## Nightly Benchmark Trends

Use the nightly wrapper when a trend report and regression exit code are required:

```bash
python3 scripts/run_nightly_benchmarks.py --iterations 32 --workers 8
```

The wrapper creates a dated output directory under `.mesh-runtime-state/simulation-stress/nightly/`, runs the matrix, compares pass rate, average score, average elapsed time, and reconciliation disagreements against the previous run, then writes `trend.json` and `trend-report.md`. Use `--allow-regression` for exploratory local runs that should record the trend without failing the command.

The first stress runs exposed two lifecycle issues: run stage `completed` can precede post-completion memory and benchmark artifacts, and approval-gated simulations can pause before completion. The harness now waits for `benchmark_score`, and the coordinator records benchmark artifacts for simulation runs that pause or spawn recovery children. This preserves benchmark reproducibility under parallel execution.

## Continuous Simulation Loop

Use the continuous loop for repeated benchmark cycles with rollup artifacts:

```bash
python3 scripts/run_continuous_simulations.py --cycles 3 --iterations 32 --workers 8 --sleep-seconds 60
```

The loop writes each cycle under `.mesh-runtime-state/simulation-stress/continuous/` and maintains `rollup.json` plus `rollup-report.md` across cycles. It enables seeded scenario randomization by default, perturbing telemetry values and context while keeping the expected decision contract stable. Use `--no-randomize` for deterministic catalog sweeps. `--cycles 0` runs until interrupted and should be used only under a supervisor that owns stop policy, artifact retention, and resource limits. The loop remains sandbox-only because it delegates to the same simulation matrix harness and allowlisted scenario catalog.

## Learning Results

Recent benchmark runs established the current baseline:

| Run | Scope | Runs | Failures | Pass rate | Avg score | Main signal |
|-----|-------|------|----------|-----------|-----------|-------------|
| `continuous-hour` | deterministic one-hour loop | 1808 | 0 | 0.4375 | 0.775 | The runtime and export loop are stable; old scoring treated correct pauses as generic failures. |
| `post-merge-randomized` | 3 randomized cycles, 64 runs each | 192 | 0 | 0.8125 | 0.8167 | Pause-aware scoring and seeded variants produce a more accurate bounded-autonomy benchmark. |

The deterministic one-hour run produced 113 cycles and no harness failures. That proves the coordinator, benchmark export, reconciliation artifacts, and dataset writes are stable under repeated sandbox load. It also showed that repetition alone does not create new learning once the catalog order is deterministic.

The randomized post-merge run produced 133 override replay rows and no harness failures. The pass-rate increase from 0.4375 to 0.8125 came from scoring correctness: high-risk or missing-authority cases now pass when Mesh pauses or escalates correctly. That is the intended product posture. Bounded SRE assistance should be rewarded for refusing unsafe autonomy.

Current blocker classes from the randomized run:

| Blocker class | Count | Interpretation |
|---------------|-------|----------------|
| `evaluator_quality` | 133 | The evaluator/promptfoo gate is the largest calibration target. |
| `confidence` | 122 | Confidence thresholds are conservative; tune per scenario family, not globally. |
| `human_review` | 68 | Human review routes are expected for escalation scenarios and should feed override replay. |
| `approval_gate` | 61 | Approval gates are functioning as safety controls. |
| `risk` | 53 | High-risk routes are correctly resisting autonomous execution. |

Decision mix from the randomized run:

| Decision | Count |
|----------|-------|
| `escalate` | 68 |
| `restart_deployment` | 36 |
| `scale_deployment` | 31 |
| `disable_flag` | 15 |
| `investigate_and_patch` | 15 |
| `none` | 13 |
| `rollback_deployment` | 12 |
| `no_action` | 2 |

## Next Work

1. Convert `override-replay.jsonl` rows into rule-learning fixtures so blocked runs can be replayed as operator approvals, rejections, or escalations.
2. Add scenario-family reports for Kubernetes, OTel, feature flags, adversarial telemetry, and no-action controls.
3. Tune evaluator gates by blocker class. `evaluator_quality` and `confidence` should be calibrated first because they dominate the current benchmark loss.
4. Add model/profile comparison over the same matrix, capturing `evaluation_mode`, `orchestration_mode`, agent fabric, model IDs, latency, schema validity, disagreement rate, and correct-pause rate.
5. Add PR-blocking CI for focused Python tests, `ruff`, web lint, and a small randomized matrix.
6. Expand remediation coverage to node pressure, PVC/storage pressure, DNS failures, ingress/TLS failures, database latency, queue poison messages, ArgoCD drift, and feature-flag rollback conflicts.

## Service Agents

Set `MESH_SERVICE_AGENTS_CONFIG_PATH` to a JSON file:

```json
{
  "agents": [
    {
      "service": "search",
      "scope": {
        "deployments": ["semantic-*"],
        "namespaces": ["search"],
        "flags": ["search-*"],
        "repos": ["*/search"]
      },
      "runbook_path": "runbooks/search.md",
      "preferred_lanes": ["hermes", "goose"],
      "autonomy_overrides": {
        "rollback_deployment": "approval_required"
      }
    }
  ]
}
```

When no service agent matches, Mesh records the default route and preserves existing global behavior.

## Standards Anchors

- OpenTelemetry semantic conventions for telemetry field naming.
- Kubernetes release/skew policy for supported cluster expectations.
- NIST AI RMF and NIST Generative AI Profile for AI governance controls.
- OWASP LLM Top 10 for agent threat modeling.
- CycloneDX and SLSA-aligned provenance goals for release hardening.
