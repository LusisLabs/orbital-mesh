# Evaluation Kits

This document packages evaluation paths from active `orbital-mesh` files. It does not describe hypothetical demos.

## Enterprise Evaluation Kit

Use this packet for platform, SRE, security, and infrastructure buyers who need production-style evidence before a pilot.

Required artifacts:

- architecture brief: `README.md`, `docs/production-deployment-roadmap.md`, and `docs/integrations.md`;
- safety boundary brief: `docs/production-hardening-records.md`, `docs/production-live-runbook.md`, and `docs/production-readiness-validation.md`;
- one-command whole-system environment: `docker-compose.stack.yml`;
- production-like deployment template: `docker-compose.prod.yml`;
- whole-system smoke command: `scripts/compose_stack_smoke.sh`;
- production endpoint smoke command: `scripts/prod_smoke.sh`;
- Postgres restart proof harness: `scripts/verify_postgres_restart_proof.py`;
- generated API contract: `shared/mesh_runtime/schemas/control-plane.schema.json`;
- UI contract types: `web/src/types.ts`;
- benchmark harness entrypoint: `services/benchmark/__main__.py`.

Evaluation sequence:

1. Run unit and contract gates from `AGENTS.md`.
2. Run `docker compose -f docker-compose.stack.yml up --build`.
3. Rerun `docker compose -f docker-compose.stack.yml run --rm mesh-smoke` for a CI-style exit code.
4. Deploy `docker-compose.prod.yml` in a private environment with authenticated ingress, required operator identity headers, Kubernetes allowlists, and platform secret injection.
5. Run `scripts/prod_smoke.sh` against the private endpoint.
6. Run `scripts/verify_postgres_restart_proof.py --database-url "$MESH_DATABASE_URL" --json` against the pilot database.
7. Export the observed `/api/pilot/go-no-go` packet only after the above gates produce evidence.

Reference architectures:

- local full-stack proof: `docker-compose.stack.yml`;
- production-like single service: `docker-compose.prod.yml`;
- live Kubernetes recovery proof: `scripts/e2e_seed_failure.sh` plus `scripts/e2e_run_mesh.sh`;
- browser operator proof: `scripts/e2e_ui_operator.sh`;
- long-running evidence sweep: `scripts/run_breakthrough_proof.sh` and `scripts/run_overnight_mesh_breakthrough_cron.py`.

Enterprise pass criteria:

- readiness profile is `pilot` or `expansion` and `GET /api/readiness` returns `status: ready`;
- proposal lanes remain advisory and have no production kubeconfig or repository write authority;
- kill switch can force approval gates and disable live execution;
- Postgres restart proof passes for run events, memory, and Merkle roots;
- at least one allowed action and one denied action are captured in the pilot go/no-go packet;
- rollback metadata exists for every live action class admitted to the pilot.

## Startup And Developer Evaluation Path

Use this path for small teams validating the core loop without procurement.

Five-minute local demo:

1. Run `python3 setup_integrations.py`.
2. Run `npm --prefix web install` once, then `npm --prefix web run build`.
3. Run `python3 run_server.py`.
4. Open `http://127.0.0.1:8787`.
5. Launch the `search_latency_regression` fixture in approval-gate mode and inspect the evidence graph.

Thirty-minute staging guide:

1. Set `MESH_READINESS_PROFILE=staging`.
2. Set `MESH_OPERATOR_IDENTITY_REQUIRED=1` behind a local authenticated proxy or staging ingress that forwards `X-Mesh-Operator` and `X-Mesh-Roles`.
3. Configure `MESH_OTEL_RECEIVER_TOKEN` if OTel ingest is enabled.
4. Keep `MESH_KUBERNETES_LIVE_EXECUTION_ENABLED=0` until Kubernetes context and namespace allowlists are reviewed.
5. Run `PYTHONPATH=. python3 -m unittest tests.test_production_cut_list`.
6. Run `npm --prefix web run lint`.

Sample exported run:

- launch `search_latency_regression`;
- approve only after evaluation passes;
- inspect `/api/runs/<run_id>`, `/api/runs/<run_id>/events`, `/api/runs/<run_id>/evidence-graph`, and `/api/runs/<run_id>/merkle`;
- include the Merkle root, decision artifact, evaluation artifact, feedback artifact, and operator command event in the sample packet.

Developer pass criteria:

- local readiness loads without requiring optional proposal CLIs;
- every mutating API is exercised through operator headers when identity is required;
- policy simulation returns `mutates: false`;
- evidence graph is the first run-inspection surface;
- no production kubeconfig is present in proposal-lane sandboxes.
