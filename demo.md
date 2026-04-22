# Demo Environment And Recording Plan

## Summary
Use the all-in-one local stack in `docker-compose.stack.yml` as the recording environment. Record one primary end-to-end story and one secondary capability story.

Primary story:
- deterministic live Kubernetes remediation
- promptfoo evaluation
- execution handoff
- feedback loop completion

Secondary story:
- Hermes orchestration
- agent-mesh proposal lanes enabled
- Deep Agents, LatentMAS, and Evo shown as available advisory/execution fabric components without making them the critical path

This keeps the demo stable while still showcasing the full system surface.

## Environment Setup
Build a dedicated local demo stack on a private machine. Do not expose it to the public Internet.

Environment defaults:
- host: one laptop or workstation with Docker Desktop and Compose v2
- access: localhost only
- UI/API: `http://127.0.0.1:8787`
- cluster: embedded k3s from the stack
- database/state: stack-local only
- recording target: local screen capture, not live public hosting

Configuration for the recording environment:
1. Start from the current fixed branch/worktree that includes:
   - Hermes artifact naming fix
   - evaluation-to-execution handoff fix
   - bounded agent-task timeout
   - LatentMAS health/readiness fix
   - Deep Agents auth/readiness fix
   - Evo `uv` availability fix
2. Use `docker-compose.stack.yml` as the canonical runtime.
3. Enable all optional lanes for the demo environment:
   - Deep Agents enabled
   - LatentMAS enabled
   - Evo enabled
4. On Apple Silicon or any host where GPU/container acceleration is uncertain, force LatentMAS to CPU using `Dockerfile.latentmas.cpu` and `MESH_LATENTMAS_DEVICE=cpu`. Do not attempt GPU during the recording.
5. Keep `MESH_AGENT_TASK_TIMEOUT_SECONDS` set to a bounded value suitable for demo stability. Default to `15`. This preserves the fix that prevents proposal lanes from blocking execution.
6. Keep the network private. If another person must watch live, use screen share only.

## Pre-Recording Validation
Do one dry run before recording. The environment is recordable only if all checks below pass.

Readiness gate:
1. `mesh`, `hermes`, `k3s`, `postgres`, and `latentmas` containers are healthy.
2. `/api/health` returns `status=ok`.
3. `/api/readiness` shows:
   - `promptfoo.ready=true`
   - `hermes.ready=true`
   - `goose.ready=true`
   - `deepagents.ready=true`
   - `latentmas.ready=true`
   - `evo.ready=true`
4. The UI loads cleanly at `http://127.0.0.1:8787`.

Code and regression gate:
1. `python3 -m unittest discover -s tests` passes.
2. `npm run lint` passes.
3. `npm test` and `npm run build` pass if the web UI is part of the recording.
4. One fresh smoke run completes without hanging at `evaluation_ready`.

Acceptance proof for the handoff fix:
- run a Hermes scenario and confirm the event chain includes:
  - `agent_task_recorded`
  - `execution_recorded`
  - `feedback_recorded`
  - `run_completed`
- confirm Hermes review artifacts are stored as `hermes_review`, not `goose_review`

## Recording Script
Record in this order. Do not improvise the sequence.

### Segment 1: Environment credibility
1. Show Docker containers healthy.
2. Show `/api/health`.
3. Show `/api/readiness` with Deep Agents, LatentMAS, Evo, Hermes, Goose, and Promptfoo all green.
4. Open the UI at `http://127.0.0.1:8787`.

Narration focus:
- this is a private, reproducible stack
- the environment includes control plane, orchestration, evaluation, feedback, and an embedded Kubernetes target
- optional agent lanes are enabled, but the system remains bounded and auditable

### Segment 2: Primary end-to-end story
Use `live_kubernetes:search/semantic-search` as the hero scenario.

Flow:
1. Start the run from the UI if possible. If the UI path is slower, start it by API and then pivot immediately to the UI.
2. Show the input signal:
   - degraded rollout
   - pod failures
   - search service context
3. Show promptfoo evaluation recommending action.
4. Show the run crossing from evaluation into execution.
5. Show execution completion.
6. Show feedback/post-action observations proving the rollout recovered.

Narration focus:
- Mesh receives a real operational signal
- evaluation chooses a bounded action
- execution happens under policy
- post-action feedback closes the loop

Success criteria for this segment:
- run reaches `stage=completed`
- execution succeeds
- feedback is recorded
- no stall at `evaluation_ready`

### Segment 3: Secondary orchestration story
Use `kubernetes_crashloop_patch` as the artifact-heavy showcase.

Flow:
1. Launch the scenario with:
   - `evaluation_mode=promptfoo`
   - `orchestration_mode=hermes`
   - `steering_mode=interruptible_auto`
2. Show the signal contents:
   - CrashLoopBackOff
   - logs
   - bounded allowed path
   - test command
3. Show readiness and agent-task collection with optional lanes enabled.
4. Show the run moving through:
   - evaluation
   - `agent_task_recorded`
   - `execution_recorded`
   - `integration_artifact_recorded`
   - `feedback_recorded`
   - `run_completed`
5. Open the recorded review artifact and confirm it is `hermes_review`.

Narration focus:
- Hermes is the orchestrator
- Deep Agents, LatentMAS, and Evo are available in the mesh
- proposal lanes are bounded and cannot deadlock the control plane
- audit artifacts are stored under the correct integration identity

Do not rely on this segment to prove successful remediation. Its purpose is to prove orchestration, artifact integrity, and the control-plane fix.

## Showcase Framing
Use these product claims and nothing broader:
- Mesh can ingest an operational signal, evaluate it, execute a bounded response, and record post-action feedback end to end.
- The control plane no longer stalls when optional proposal lanes are slow or unavailable.
- Hermes executions now produce correctly attributed Hermes review artifacts.
- Deep Agents, LatentMAS, and Evo can be enabled in the mesh without breaking the main remediation loop.

Do not claim:
- public Internet readiness
- production multi-tenant hardening
- autonomous public-safe deployment without operator controls

## Test Cases To Run Before The Final Take
1. Native live Kubernetes scenario completes successfully.
2. Hermes crashloop scenario completes end to end and records `hermes_review`.
3. Readiness remains green after stack restart.
4. Disabling one optional lane does not block the primary scenario.
5. A slow advisory lane times out into a recorded failed attempt instead of hanging the run.

## Assumptions And Defaults
- Recording happens on a private local machine.
- The current fixed codebase is the demo candidate.
- LatentMAS runs on CPU unless hardware acceleration is already proven stable.
- The core story is deterministic remediation first, optional agent fabrics second.
- The demo is judged successful only if the primary story completes cleanly on the first recorded take.
