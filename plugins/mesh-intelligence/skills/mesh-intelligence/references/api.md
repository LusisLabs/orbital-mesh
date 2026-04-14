# Mesh Intelligence API Reference

Default base URL: `http://127.0.0.1:8787`.

Use `MESH_BASE_URL` when a specific Mesh instance is supplied.

## Read Endpoints

- `GET /api/health` returns server status, environment, version, and commit when supported.
- `GET /api/readiness` returns integration readiness for Promptfoo, Goose, Hermes, Evo, LatentMAS, and GitNexus when supported. This may probe CLIs and can be slower than health.
- `GET /api/runs` returns run records. Payloads can be large because artifacts are included.
- `GET /api/runs/:id` returns one run with artifacts, events, and Merkle metadata.
- `GET /api/runs/:id/events` returns the run event stream.
- `GET /api/runs/:id/agent-tasks` returns `{"tasks": [...]}` on servers with the agent mesh route.
- `GET /api/research-sessions` returns filesystem research sessions.
- `GET /api/research-sessions/:id` returns one research session and synthesis when present.
- `GET /api/research-corpus` returns corpus-level research grounding and drift analysis.
- `GET /api/vault/tree` returns the vault document tree.
- `GET /api/vault/document?path=...` returns one vault document.

## Write Endpoints

- `POST /api/goals` creates a goal.
- `POST /api/runs` creates a run.
- `POST /api/runs/:id/steer` updates steering for a run.

Codex workers should default to read endpoints. Use write endpoints only when the user explicitly asks and the request is within Mesh policy.

## Agent Task Shape

Expected response:

```json
{
  "tasks": [
    {
      "task_id": "task_run_...",
      "run_id": "run_...",
      "kind": "rollback_plan",
      "status": "completed",
      "allowed_paths": [],
      "test_commands": [],
      "kubernetes_scope": {
        "context": "k3d-mesh-e2e",
        "namespace": "search",
        "deployment_name": "semantic-search"
      },
      "attempts": [
        {
          "agent": "goose",
          "adapter": "native_contract",
          "status": "completed",
          "summary": "Operational plan...",
          "risk_flags": [],
          "recommended_action": "execute"
        },
        {
          "agent": "evo",
          "adapter": "native_contract",
          "status": "completed",
          "summary": "Evo proposal lane is gated until evo-hq-cli is configured.",
          "risk_flags": ["evo_cli_missing"],
          "recommended_action": "human_review"
        }
      ],
      "selected_attempt_id": "attempt_..."
    }
  ]
}
```

If this endpoint returns a full run payload instead, the running Mesh process predates the agent-task route. Restart Mesh from the current tree.
