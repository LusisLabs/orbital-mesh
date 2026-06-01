# Recursive Chaos Automation

State slice: `mesh.recursive_chaos.automation.v1`.

The recursive chaos automation runner is source-controlled at `scripts/run_recursive_chaos_automation.py`.
It calls the live Mesh API, discovers the arena profile registry at runtime, creates an advisory-only recursive chaos session, and writes a compact automation summary with an intelligence score.

## Runtime Contract

- Default API: `http://127.0.0.1:8788/api/recursive-chaos/sessions`
- Default profile registry: `http://127.0.0.1:8788/api/recursive-chaos/profiles`
- Default mode: `MESH_RECURSIVE_CHAOS_PROFILE_MODE=registry_all`
- Default mutation authority: `MESH_RECURSIVE_CHAOS_EXECUTE=false`
- Summary artifact: `/opt/lusis-mesh-webapp/shared/state/recursive-chaos/automation/last-run.json`
- History artifacts: `/opt/lusis-mesh-webapp/shared/state/recursive-chaos/automation/runs/*.json`

The runner stamps operator identity through `X-Auth-Request-Email` and `X-Mesh-Role`. Hetzner keeps the account-specific value in `/etc/lusis-mesh-recursive-chaos.env`; the repo template uses a generic local operator.

## Intelligence Score

State slice: `mesh.recursive_chaos.intelligence_score.v1`.

Each run records:

- profile coverage across the live registry
- P0 profile coverage
- learning packet density
- novelty score from repeated advisory hashes
- scheduler weights for the next profile selection pass

The score is advisory. It does not grant training authority, serving authority, or production mutation authority.

## Sandbox Execution Lane

State slice: `mesh.recursive_chaos.sandbox_execution.v1`.

`scripts/run_recursive_chaos_sandbox_execution.py` runs one opt-in `execute=true` session against a disposable Compose target:

- substrate: `compose_sandbox`
- environment: `local_disposable`
- default image: `python:3.13-slim-trixie`
- fault: stop the isolated `target` service
- recovery: start the same service and prove it is running again
- cleanup: `docker compose down --volumes --remove-orphans`

The control plane records the run as recursive chaos evidence, but production authority remains false. This lane is not scheduled by the hourly timer; it is a deliberate proof lane.

Run manually on Hetzner:

```bash
python3 scripts/run_recursive_chaos_sandbox_execution.py --env-file /etc/lusis-mesh-recursive-chaos.env --json
```

## Feedback Gate

State slice: `mesh.recursive_chaos.feedback_gate.v1`.

Every recursive chaos API run records `mesh_brain_recursive_chaos_feedback_gate` as a first-class run artifact. The gate lets MeshBrain recommend scheduler weights from sealed packets while MeshModel stays blocked:

- `mesh_brain_mode=recommend_only`
- `mesh_model_mode=recommend_only`
- `mesh_model_training_allowed=false`
- `training_allowed=false`
- `production_authority=false`
- `promotion_authority=false`

## Deployment

`scripts/deploy_lusislabs_preview.sh` installs or refreshes:

- `lusis-mesh-recursive-chaos.service`
- `lusis-mesh-recursive-chaos.timer`

The deploy hook preserves an existing `/etc/lusis-mesh-recursive-chaos.env`. If the env file is absent, it installs `config/recursive-chaos-automation.env.example`.

Disable installation with:

```bash
LUSIS_RECURSIVE_CHAOS_AUTOMATION_ENABLED=0 scripts/deploy_lusislabs_preview.sh
```

Run manually:

```bash
python3 scripts/run_recursive_chaos_automation.py --env-file /etc/lusis-mesh-recursive-chaos.env --json
```
