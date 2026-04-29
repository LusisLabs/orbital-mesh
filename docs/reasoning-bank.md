# ReasoningBank Memory

Mesh implements a ReasoningBank-style loop on top of its existing memory
substrate. It does not vendor the upstream WebArena or SWE-Bench harness. The
runtime follows the core ReasoningBank pattern: retrieve relevant lessons before
a run, execute the task, score the trajectory, distill success or failure into a
structured memory item, and retrieve that lesson for similar future runs.

ReasoningBank is disabled by default:

```bash
MESH_REASONING_BANK_ENABLED=false
MESH_REASONING_BANK_DISTILLER=deterministic
MESH_REASONING_BANK_MAX_STRATEGIES=5
MESH_REASONING_BANK_SCALING_MODE=off
```

When enabled, Mesh retrieves procedural and semantic strategy memories before
scenario analysis. The retrieved packet is stored as the run artifact
`reasoning_bank_packet` and is advisory only. Evaluation, approval gates,
remediation safety checks, and live evidence remain authoritative.

After a run completes, Mesh distills one deterministic lesson:

- successful evaluated action: a procedural strategy claim
- failed, blocked, escalated, or unevaluated action: a semantic guardrail claim

The lesson is written as a normal `ObservationRecord` plus `ClaimRecord` with
citations back to the source run events. Observation metadata marks the row with
`reasoning_bank=true`, `lesson_type`, `outcome`, `source_stage`,
`failure_mode`, `title`, `description`, `content`, and `scorer_impact`.

Trajectory evaluation writes these artifacts:

- `task_trace`: input, context, memory retrieval, evidence probes, decisions,
  evaluation, execution, feedback, ordered events, tool calls, and failure cause.
- `trajectory_score`: aggregate behavioral score plus per-scorer evidence refs.
- `verifier_output`: deterministic execution and feedback facts.
- `phoenix_spans`: Phoenix/OpenTelemetry-style spans for trace inspection.

Memory-aware scaling mode is controlled by `MESH_REASONING_BANK_SCALING_MODE`:

- `off`: retrieve and distill one trajectory.
- `sequential`: preserve intermediate improvement signals in the run trace.
- `parallel`: preserve contrastive trajectory signals when multiple attempts are
  available.

When `MESH_CORPUS_MEMORY_ENABLED=1`, the incident corpus database is projected
into the same memory substrate at control-plane startup. Internal successful
corpus rows can become procedural strategy claims only when promotion gates pass.
Public dataset and public tooling rows become semantic advisory claims only.
Those public claims give agents retrieval grounding for parsers, OTLP pipeline
tests, benchmark RCA, and dataset limitations, but they do not bypass live
evidence, evaluation, approval gates, or remediation safety.

The API endpoint `GET /api/runs/{run_id}/reasoning-bank` returns the retrieved
packet and any lessons produced for the run.
