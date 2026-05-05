# Darkharness Operator Runbook

Darkharness packets are read-only governance exports. Postgres remains authoritative
for runs, events, memory, and audit state; packet endpoints must not write packet
artifacts, run events, vault notes, or side effects.

## Endpoints

- `GET /api/runs/{run_id}/darkharness-packet`: materializes one run into a
  Darkharness packet when the run has timeline, decision, evaluation, Merkle,
  scenario analysis, registry, reservoir, and policy evidence.
- `GET /api/darkharness/pilot-packet`: materializes the pilot checkpoint across
  observed runs after `/api/pilot/go-no-go` returns `status: go`.
- `GET /api/pilot/go-no-go`: source of readiness, allowed action, denied
  action, Merkle, Mesh Brain model-kernel, live-serving, rollback drill, and
  rollback-plan predicates.

## Operator Flow

1. Confirm `/api/readiness` is `ready` for the pilot profile.
2. Confirm `/api/pilot/go-no-go` is `go` and `missing_evidence` is empty.
3. Open the allowed remediation run and verify the operator approval record,
   action target, rollback metadata, and Merkle proof.
4. Open the denied-action run and verify the blocker reason is explicit.
5. Verify Mesh Brain model-kernel, live-serving, and rollback drill run ids are
   listed in the go/no-go packet.
6. Export `GET /api/darkharness/pilot-packet` for the checkpoint packet.
7. If a single run needs inspection, export
   `GET /api/runs/{run_id}/darkharness-packet`.

## Blocked States

- `decision_record_present`, `evaluation_record_present`,
  `scenario_analysis_present`, `merkle_root_present`, or `merkle_proof_valid`:
  the selected run is not packet-eligible. Re-run or repair the source run
  evidence; do not fabricate Perennial records.
- `registry_invalid:*`: `MESH_DARKHARNESS_REGISTRY_PATH` points to a missing or
  invalid registry, or the registry violates on-prem, egress, external-model, or
  approval boundaries.
- `policy_violation:production_action_has_operator_approval`: an allowed
  production-impacting action lacks an approval record.
- `policy_violation:raw_reservoir_egress_denied` or
  `policy_violation:external_model_calls_denied_by_default`: the pilot scope is
  not safe for Darkharness export.
- `allowed_remediation_run_present` or `denied_action_run_present`: go/no-go may
  have evidence, but no run also satisfies Darkharness packet requirements.
- `rollback_drill_run_export_present`: go/no-go reports rollback evidence, but
  the checkpoint packet cannot materialize the rollback run export.
- `materialization_failed:*`: schema or materializer failure. Treat this as a
  release blocker until the exact field mismatch is fixed.

## Release Checks

The release verifier must pass:

```bash
scripts/verify_release_cut_list.py --json
```

The focused Darkharness CI step must pass:

```bash
PYTHONPATH=. python3 -m unittest \
  tests.test_darkharness_packet \
  tests.test_darkharness_policy \
  tests.test_darkharness_export_path
```
