# Evaluation Kits

This document packages evaluation paths from active `orbital-mesh` files. It does not describe hypothetical demos.

## Enterprise Evaluation Kit

Use this packet for platform, SRE, security, and infrastructure buyers who need production-style evidence before a pilot.

Required artifacts:

- architecture brief: `README.md`, `docs/production-deployment-roadmap.md`, and `docs/integrations.md`;
- safety boundary brief: `docs/production-hardening-records.md`, `docs/production-live-runbook.md`, and `docs/production-readiness-validation.md`;
- deployment compatibility brief: `docs/deployment-compatibility.md`;
- agentic operator fork-in brief: `docs/agentic-operator-core-import-plan.md`;
- one-command whole-system environment: `docker-compose.stack.yml`;
- production-like deployment template: `docker-compose.prod.yml`;
- ownership registry: `config/ownership.registry.json`;
- policy lifecycle manifest: `config/policy-lifecycle.manifest.json`;
- data-classification policy: `config/data-classification.policy.json`;
- agentic-operator source provenance: `config/agentic-operator-source.provenance.json`;
- trigger-web-source provenance: `config/trigger-web-source.provenance.json`;
- sample export and benchmark packet generator: `scripts/generate_evaluation_kit_packet.py`;
- evaluation-kit packet verifier: `scripts/verify_evaluation_kit_packet.py`;
- benchmark output verifier: `scripts/verify_benchmark_run_artifacts.py`;
- whole-system smoke command: `scripts/compose_stack_smoke.sh`;
- production endpoint smoke command: `scripts/prod_smoke.sh`;
- Postgres restart proof harness: `scripts/verify_postgres_restart_proof.py`;
- generated API contract: `shared/mesh_runtime/schemas/control-plane.schema.json`;
- UI contract types: `web/src/types.ts` and `meshapp/frontend/src/types.ts`;
- benchmark harness entrypoint: `services/benchmark/__main__.py`.

Evaluation sequence:

1. Run unit and contract gates from `AGENTS.md`.
2. Run `docker compose -f docker-compose.stack.yml up --build`.
3. Rerun `docker compose -f docker-compose.stack.yml run --rm mesh-smoke` for a CI-style exit code.
4. Deploy `docker-compose.prod.yml` in a private environment with authenticated ingress, required operator identity headers, Kubernetes allowlists, and platform secret injection.
5. Run `scripts/prod_smoke.sh` against the private endpoint.
6. Run `scripts/verify_postgres_restart_proof.py --database-url "$MESH_DATABASE_URL" --json` against the pilot database.
7. Run `scripts/generate_evaluation_kit_packet.py --output-dir <evaluation-kit-dir> --json` to create a deterministic sample run export package, zip archive, retrieval proof, and formal benchmark command packet.
8. Run `scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json`.
9. Run the packet's benchmark command, then run `scripts/verify_benchmark_run_artifacts.py --run-dir <benchmark-run-dir> --expected-suite golden --expected-scenario-id feature_flag_latency_disable --expected-scenario-id kubernetes_crashloop_patch --json`.
10. Export the observed `/api/pilot/go-no-go` packet only after the above gates produce evidence.

Reference architectures:

- local full-stack proof: `docker-compose.stack.yml`;
- production-like single service: `docker-compose.prod.yml`;
- live Kubernetes recovery proof: `scripts/e2e_seed_failure.sh` plus `scripts/e2e_run_mesh.sh`;
- browser operator proof: `scripts/e2e_ui_operator.sh`;
- long-running evidence sweep: `scripts/run_breakthrough_proof.sh` and `scripts/run_overnight_mesh_breakthrough_cron.py`.

Compatibility review:

- treat Docker Compose and Kubernetes as validated paths;
- treat OCI-compatible runtimes and image builders as contract compatibility, not individual runtime integrations;
- treat Podman, K3s, OpenShift, Rancher-managed Kubernetes, managed Kubernetes, Cloud Run, Azure Container Apps, Fly.io, Railway, and Render as recipes until the evaluator supplies target-specific smoke and release evidence;
- treat ECS/Fargate as the first non-Kubernetes production target candidate after the Kubernetes pilot path is repeatable;
- reject broad "all orchestrators supported" claims.
- treat the provenance-recorded `agentic-operator-core-main/` source input as future CRD/operator/Helm/Argo/MCP/LiteLLM/metering/network-policy material, not as current Orbital Mesh runtime proof.

Enterprise pass criteria:

- readiness profile is `pilot` or `expansion` and `GET /api/readiness` returns `status: ready`;
- normal run creation produces an `ownership_boundary` artifact with a resolved owner, tenant, customer, approver roles, rollback authority, and policy refs;
- `GET /api/connectors/certification` returns `mesh.connector_certification.v1` with registry hash, connector states, authority posture, credential policy, degraded behavior, allowed scopes, and no runtime upgrade beyond the registry state;
- `GET /api/policy/lifecycle` returns signed policy hashes with no missing manifest coverage;
- every mutating decision's evaluation includes `stage_results.evidence_sufficiency` and no `evidence sufficiency gate did not pass` blocker before execution;
- `scripts/verify_data_classification_policy.py --json` passes with signal, log, trace, model-output, audit-proof, training-candidate, operator-identity, and secret-material coverage;
- `python3 scripts/verify_agentic_operator_source_provenance.py --json` passes and shows the source input is Apache-2.0, snapshot-bound, source-input-only, and not active runtime;
- `python3 scripts/verify_trigger_web_source_provenance.py --json` passes and shows the source input is Apache-2.0, snapshot-bound, source-input-only, and not active runtime;
- `scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json` passes and proves the sample export package, zip archive, retrieval proof, benchmark harness entrypoint, golden scenarios, command, and expected benchmark artifacts are present;
- `scripts/verify_benchmark_run_artifacts.py --run-dir <benchmark-run-dir> --expected-suite golden --expected-scenario-id feature_flag_latency_disable --expected-scenario-id kubernetes_crashloop_patch --json` passes after the formal benchmark command runs;
- `GET /api/runs/{run_id}/timeline-proof` returns gapless monotonic sequence checks, parseable `time_unix_nano` values, payload hashes, Merkle root, and a valid latest-event proof;
- run creation records `mesh.run_admission.v1` with queue depth, worker count, tenant active-run quota, target lock key, lock holder, decision, and blockers before worker admission;
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

- run `scripts/generate_evaluation_kit_packet.py --output-dir <evaluation-kit-dir> --json`;
- verify `mesh.evaluation_kit_packet.v1` with `scripts/verify_evaluation_kit_packet.py --packet <evaluation-kit-dir>/evaluation-kit-packet.json --json`;
- inspect `<evaluation-kit-dir>/evaluation-kit-packet.json`, the generated `run_exports/<run_id>.json` package, and the generated `run_exports/<run_id>.zip` archive;
- use the packet's benchmark command as the formal golden-suite handoff;
- verify the resulting benchmark directory with `scripts/verify_benchmark_run_artifacts.py`;
- treat target-environment sample exports and durable benchmark publication as deployment-specific evidence.

## Public Proof Package

`config/public-proof.package.json` is the release manifest for public proof claims. It uses `mesh.public_proof_package.v1` and must verify with:

```bash
scripts/verify_public_proof_package.py --json
```

The manifest binds benchmark reports, architecture papers, demo datasets, run exports, and limitations statements to repository artifacts and verification commands. Passing verification means the repository proof package is complete and secret-free. It does not replace durable public publication, target-environment benchmark outputs, or target-environment run exports.

Developer pass criteria:

- local readiness loads without requiring optional proposal CLIs;
- every mutating API is exercised through operator headers when identity is required;
- policy simulation returns `mutates: false`;
- evidence graph is the first run-inspection surface;
- no production kubeconfig is present in proposal-lane sandboxes.
