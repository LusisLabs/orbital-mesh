**Validation Summary**
Committed branch: `codex/reth-kurtosis-full-loop`  
Commit: `5fe06cd Add Kurtosis Reth full-loop remediation`

This page is archived research provenance. The referenced
`tests/test_kurtosis_reth_actuation.py` test file is not present in the current
checkout and is not a controlled-production-pilot release gate.

Static and unit validation passed:

```bash
python3 -m py_compile services/control_plane.py services/ingest/bare_metal_node.py services/feedback/service.py scripts/run_reth_kurtosis_full_loop.py tests/test_kurtosis_reth_actuation.py
```

Outcome: passed. No syntax/import-level failures in the changed Python paths.

```bash
python3 -m unittest tests.test_kurtosis_reth_actuation
```

Outcome: passed. Final run after commit staging showed `21 tests OK`.

```bash
python3 -m unittest tests.test_kurtosis_reth_actuation tests.test_scenario_analysis tests.test_integrations tests.test_contracts
```

Outcome: passed earlier during validation. `48 tests OK`.

```bash
UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .
```

Outcome: passed. No lint violations after pinning uv/ruff cache paths to `/tmp`.

```bash
git diff --cached --check
```

Outcome: passed. No staged whitespace errors.

**Docker/Stack Validation**
```bash
docker compose -f docker-compose.stack.yml build mesh
docker compose -f docker-compose.stack.yml up -d --force-recreate mesh
curl -sS http://127.0.0.1:8787/api/health
```

Outcome: passed.

The mesh image rebuilt with Kurtosis CLI support and the updated feedback/recovery code. The recreated control plane returned:

```json
{
  "status": "ok",
  "environment": "production",
  "version": "dev"
}
```

**Live Full-Loop Outcome**
Session inspected: `.mesh-runtime-state/reth-kurtosis-loop/session_20260426T193540Z`

Report counts:

```text
total_cycles: 11
baseline_no_trigger_count: 2
restart_decisions: 2
successful_executions: 2
policy_held_escalations: 7
signal_refreshes: 2
skipped_cycles: 0
failed_cycles: 0
```

No failed cycles. No skipped cycles. Two real restart remediations executed and recovered.

**Cycle Outcomes**
```text
cycle 0  healthy_baseline                 completed     no_trigger
cycle 1  peer_starvation_restart           completed     restart succeeded, feedback successful
cycle 2  sync_stalled_restart              policy_held   human_review
cycle 3  rpc_degraded_restart              policy_held   human_review
cycle 4  consensus_disconnect_escalate     policy_held   human_review
cycle 5  disk_pressure_escalate            policy_held   human_review
cycle 6  jwt_missing_escalate              policy_held   human_review
cycle 7  rpc_exposed_escalate              policy_held   human_review
cycle 8  healthy_baseline                  completed     no_trigger
cycle 9  peer_starvation_restart           completed     restart succeeded, feedback successful
cycle 10 sync_stalled_restart              policy_held   human_review
```

**Main Insight**
The full Mesh loop is now working for the intended safe-autonomy boundary:

```text
ingestion -> chaos overlay -> evidence -> AI decision -> evaluation -> bounded remediation -> recovery probe -> feedback -> report
```

The system executed only the peer-starvation restart path. It correctly refused autonomous action for disk pressure, JWT missing, RPC exposure, consensus disconnect, and sync-stall escalation paths.

**Peer-Starvation Restart**
Both peer-starvation cycles reached:

```json
"decision_type": "restart_systemd_service"
"evaluation_recommendation": "execute"
"execution_status": "succeeded"
"feedback_outcome": "successful"
```

This proves the key fix worked: post-action Reth observations now feed `FeedbackService`, so successful restart is no longer mislabeled as `escalated`.

**Signal Refresh**
`signal_refreshes: 2` is expected. Kurtosis/Docker Desktop republished Reth ports after restart, and the harness refreshed RPC/metrics URLs instead of crashing.

Transient messages like this are acceptable:

```text
rpc failed: eth_syncing connection refused
```

They occurred during restart recovery and did not break the session.

**Policy-Held Escalations**
The escalation profiles now summarize as terminal policy outcomes:

```json
"status": "policy_held"
```

This is correct. These runs are not active executions. They reached evaluation, got a human-review recommendation, and stopped.

**Disk-Pressure Case**
The disk-pressure test did the right thing:

```text
disk_used_pct=97.0
decision_type=escalate
evaluation_recommendation=human_review
status=policy_held
```

Blocking reasons included:

```text
decision routes to human review
promptfoo quality gate did not pass
confidence below minimum threshold
risk level is high
```

Correct behavior: disk pressure must not restart Reth autonomously.

**Remaining Issue**
Harness summaries now show `policy_held`, but some underlying `run_final.json` artifacts still show internal control-plane status as:

```json
"stage": "evaluation_ready",
"status": "running"
```

That is an artifact-level semantic mismatch. Next fix should terminalize non-execute evaluation outcomes inside the control plane itself, not only in the harness report.

**Overall Result**
The session passed the full-loop objective. The bounded autonomous remediation path works for peer starvation, recovery is verified, feedback is accurate, escalation profiles are held by policy, and reporting gives usable run-level counts.
