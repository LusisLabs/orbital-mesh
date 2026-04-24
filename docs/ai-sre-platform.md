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
- writes `summary.json`, `runs.json`, `dataset.jsonl`, and `stress-report.md`.

The expanded catalog covers CrashLoop, ImagePullBackOff, OOMKilled, probe failure, CPU saturation, queue lag, memory pressure, request spikes, weak-signal no-action controls, missing credentials, high-impact escalation, dependency latency, cascading namespace impact, and adversarial OTel no-rule escalation. Operator-awaiting simulation runs are benchmarked as learning outcomes instead of being hidden as harness timeouts.

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

The loop writes each cycle under `.mesh-runtime-state/simulation-stress/continuous/` and maintains `rollup.json` plus `rollup-report.md` across cycles. `--cycles 0` runs until interrupted and should be used only under a supervisor that owns stop policy, artifact retention, and resource limits. The loop remains sandbox-only because it delegates to the same simulation matrix harness and allowlisted scenario catalog.

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
