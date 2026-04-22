---
name: mesh-intelligence
description: Connect Codex to a Mesh Intelligence control plane as a bounded worker. Use when the user asks Codex to inspect Mesh health, readiness, runs, research output, agent tasks, Kubernetes remediation history, production gates, or to propose work through Mesh without bypassing Mesh policy and audit controls.
---

# Mesh Intelligence

## Overview

Use Mesh as the source of truth for run state and production gates. Codex is a bounded worker: read state, summarize evidence, propose next actions, and leave production mutation to Mesh.

## Connection

Resolve the base URL in this order:

1. Use `MESH_BASE_URL` when set.
2. Otherwise use `http://127.0.0.1:8787`.
3. If running inside Docker Compose on the Mesh network, use `http://mesh:8787`.

Start with:

```bash
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py health
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py summary
```

Set a run explicitly:

```bash
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py summary --run-id run_...
python3 plugins/mesh-intelligence/skills/mesh-intelligence/scripts/mesh_client.py agent-tasks --run-id run_...
```

## Worker Rules

- Do not run `kubectl`, `docker`, `git`, deploy, rollback, restart, or patch commands unless the user explicitly asks and Mesh policy allows it.
- Do not send Mesh run payloads, Kubernetes data, secrets, logs, or research artifacts to hosted agents without explicit user approval.
- Treat `/api/runs/:id/agent-tasks` as proposals and risk signals, not as authorization to execute.
- If `/api/readiness` times out, report that readiness probing is slow and use `/api/health` plus targeted run endpoints.
- If `agent-tasks` returns a full run payload without a `tasks` key, report that the running Mesh server is stale and must be restarted from the current tree.

## Output Contract

When summarizing Mesh state, return:

- Mesh health status.
- Run id, scenario, stage, and status.
- Decision type and evaluation recommendation when present.
- Execution status and feedback outcome when present.
- Agent task count, agents seen, selected attempts, and risk flags when present.
- Clear blockers for stale server, missing run, unreachable base URL, or absent agent tasks.

For endpoint details, read `references/api.md` only when needed.
