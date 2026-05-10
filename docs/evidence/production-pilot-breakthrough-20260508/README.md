# Production Pilot Breakthrough Packet

This packet is the auditable handoff for the 2026-05-08 production-pilot breakthrough proof.

## Claim

Mesh can execute a controlled production-pilot remediation loop with evidence-backed policy, bounded action, recovery feedback, Merkle/audit proof, and release-bound go/no-go clearance.

This is not a claim of broad production autonomy. The release clearance is bound to release artifact commit `803b13e51f984a27f4bf42d0014ebb8d50cdd26a` and image digest `sha256:2c088dd6ae51e97f9560fbc9e65ff564d0ec173afdb33121b41219fa8684da2f`. The committed packet records the captured evidence; branch-tip proof is established by rerunning the replay gate on the checked-out commit. After merge, rerun release image provenance and the live breakthrough gate on the merged commit before pilot promotion.

## Evidence Index

- `packet.json`: top-level packet, claim boundary, pilot scope, expansion order, commands, and file hashes.
- `pilot-clearance.json`: historical container-local `scripts/verify_pilot_clearance.py` pass against release-bound runtime `803b13e51f984a27f4bf42d0014ebb8d50cdd26a`.
- `health-binding.json`: `/api/health` runtime binding capture with commit and image digest checks.
- `breakthrough-proof-summary.json`: captured replay-ready proof bundle summary and validation command hashes.
- `chaos-summary.json`: compose chaos breakthrough metrics, substrate coverage, multi-fault coverage, and source hashes.
- `node-summary.json`: production node breakthrough metrics and source hashes.
- `closed-loop-run-summary.json`: normalized postmortem/export summary for `run_20260508T033245_ad9bd5ac`.
- `completion-audit.md`: prompt-to-artifact checklist and remaining post-merge blockers.

Raw `.mesh-runtime-state` logs and full run exports are intentionally not committed here. The committed files capture stable hashes, bounded status fields, metrics, action facts, and Merkle proof identifiers.

Historical branch-tip replay proof for this packet: `.mesh-runtime-state/proofs/breakthrough-proof-20260508T131725Z.json` with bundle SHA `720bce8318418344de0c2d6c6b30a0c0925f2635a68be91c0094c6967842f83d`, generated from clean commit `2f9b909fb146865af6898fadb141da9091b56ff8`. This is not current-HEAD pilot clearance for commit `583eb3e2335cb416e1360d9f0b2cbd3420e04275`.

## Pilot Drill Scope

- workload: `search/semantic-search`
- namespace: `search`
- Kubernetes context: `mesh-compose`
- service class: Kubernetes deployment
- action class: `rollback_deployment`
- operator path: operator identity with approver/launcher roles, Mesh policy/evaluation/admission gates, and post-action feedback

The closed-loop run executed `rollback_deployment` for `semantic-search` in namespace `search`, recorded run admission, evaluation pass, native execution success, recovery feedback with `ready_replicas=3`, and Merkle root `9e3f0e0ea8ce651dac53f0426adf7d39216df39cef00555a1a419e1b077e7014`.

## Commands

```bash
curl -sS http://127.0.0.1:8787/api/health
```

```bash
docker compose -f docker-compose.stack.yml exec -T mesh sh -lc 'cd /workspace/orbital-mesh && PYTHONPATH=. python3 scripts/verify_pilot_clearance.py --base-url http://127.0.0.1:8787 --timeout-seconds 30 --json'
```

```bash
PYTHONPATH=. python3 scripts/breakthrough_evidence_bundle.py --repo-root . --output-dir .mesh-runtime-state/proofs --compose-summary .mesh-runtime-state/compose-chaos/summary-20260508T042643Z.json --compose-events .mesh-runtime-state/compose-chaos/events-20260508T042643Z.jsonl --validation-command 'python3 -m unittest tests.test_breakthrough_evidence_bundle tests.test_production_node_breakthrough_session tests.test_compose_chaos_session tests.test_pilot_breakthrough_packet tests.test_production_cut_list.PilotGoNoGoMeshBrainGateTests tests.test_pilot_clearance_audit' --validation-command 'env RUFF_CACHE_DIR=/tmp/ruff-cache ruff check scripts/breakthrough_evidence_bundle.py scripts/production_node_breakthrough_session.py scripts/compose_chaos_session.py scripts/generate_pilot_breakthrough_packet.py services/control_plane.py shared/mesh_runtime/control_plane_state.py shared/mesh_runtime/mesh_state_store.py shared/mesh_runtime/postgres_state.py tests/test_breakthrough_evidence_bundle.py tests/test_production_node_breakthrough_session.py tests/test_compose_chaos_session.py tests/test_pilot_breakthrough_packet.py tests/test_production_cut_list.py tests/test_pilot_clearance_audit.py' --validation-command 'python3 -m py_compile scripts/breakthrough_evidence_bundle.py scripts/production_node_breakthrough_session.py scripts/compose_chaos_session.py scripts/generate_pilot_breakthrough_packet.py services/control_plane.py shared/mesh_runtime/control_plane_state.py shared/mesh_runtime/mesh_state_store.py shared/mesh_runtime/postgres_state.py tests/test_breakthrough_evidence_bundle.py tests/test_production_node_breakthrough_session.py tests/test_compose_chaos_session.py tests/test_pilot_breakthrough_packet.py tests/test_production_cut_list.py tests/test_pilot_clearance_audit.py'
```

```bash
scripts/generate_pilot_breakthrough_packet.py --base-url http://127.0.0.1:8787 --run-id run_20260508T033245_ad9bd5ac --expected-head "$(git rev-parse HEAD)" --chaos-summary .mesh-runtime-state/compose-chaos/summary-20260508T042643Z.json --node-summary .mesh-runtime-state/node-breakthrough/summary-20260505T205538Z.json --output-dir .mesh-runtime-state/pilot-packets/production-pilot-breakthrough-latest --json
```

## Operating Model

- Approvers: operator identities carrying `approver` and `launcher` roles.
- Allowed action: one reviewed rollback on one allowlisted deployment.
- Evidence before action: trigger, evidence pack, scenario analysis, decision, policy/evaluation pass, admission, and operator identity.
- Pause conditions: missing release provenance, runtime binding mismatch, readiness blockers, nonempty go/no-go missing evidence, evaluation blockers, failed live action execution, action outside namespace/context/action class, missing rollback metadata, failed feedback, or ambiguous recovery.
- Rollback verification: feedback must confirm rollout health and target replica recovery before the run can support pilot clearance.
- Secrets/provider isolation: proposal lanes stay advisory; no raw secrets, kubeconfig contents, private keys, unrestricted production logs, or production actuator credentials enter the packet.

## Regression Guard

The CI release guard is the named `breakthrough-proof-replay` job. It runs focused replay tests, focused ruff, and syntax compilation for the breakthrough proof surfaces. The live promotion gate remains `scripts/run_breakthrough_proof.sh` plus `scripts/verify_pilot_clearance.py` against the deployed runtime.

Expansion stays one axis at a time: second service class, real external incident provider, real feature flag provider, external audit sink, multi-operator pilot, longer-running watch mode, then production SLO/error-budget reporting.
