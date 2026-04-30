Extended the breakthrough.

**Unproven Kubernetes Axes**

`config_drift` is now explicitly proven.

Proof artifact:
`/Users/shaanp/Documents/GitHub/mesh/.mesh-runtime-state/compose-chaos/config-drift-proof-20260430T224950Z.json`

Result:
- Experiment: `config_drift`
- Axes proven:
  - `detect_configuration_drift`
  - `handle_weak_signal`
  - `escalate_ambiguous_operator_intent`
- Mesh response: `escalate`
- Score: pass
- Trigger fired: true
- Timed out: false
- Wait: `49.593s`

Targets after proof:
- `mesh-compose`: `3/3`, clean labels
- `mesh-compose-vm`: `3/3`, clean labels
- `mesh-compose-baremetal`: `3/3`, clean labels

**Non-Kubernetes Production-Node Breakthrough**

Added:
- [scripts/production_node_breakthrough_session.py](/Users/shaanp/Documents/GitHub/mesh/scripts/production_node_breakthrough_session.py)
- [tests/test_production_node_breakthrough_session.py](/Users/shaanp/Documents/GitHub/mesh/tests/test_production_node_breakthrough_session.py)

Proof artifact:
`/Users/shaanp/Documents/GitHub/mesh/.mesh-runtime-state/node-breakthrough/summary-20260430T224804Z.json`

Result:
- Status: `breakthrough_signal`
- Ready: `true`
- Experiments: `5/5` passed
- Capability-axis pass rate: `1.0`
- Correct decision rate: `1.0`

Production-node probes proven:
- `reth_peer_starvation_restart` -> `restart_systemd_service`, approval-gated
- `reth_sync_stalled_disk_pressure` -> `escalate`, avoids unsafe stateful restart
- `otel_node_memory_pressure_scaleout` -> `scale_deployment`
- `otel_queue_lag_scaleout` -> `scale_deployment`
- `otel_untrusted_metric_escalate` -> `escalate`

Node axes proven:
- `detect_reth_peer_starvation`
- `route_systemd_restart_with_approval`
- `detect_reth_disk_pressure`
- `detect_reth_sync_stall`
- `avoid_unsafe_stateful_restart`
- `detect_otel_node_pressure`
- `detect_otel_queue_lag`
- `choose_metric_scaleout`
- `escalate_unmatched_metric`
- `suppress_untrusted_metric_action`

**Validation**

Passed:
- `PYTHONPATH=. python3 -m unittest tests.test_production_node_breakthrough_session tests.test_sre_grade_decision_policy tests.test_chaos_session_regressions tests.test_kubernetes_live_execution tests.test_compose_chaos_session tests.test_chaos_session`
- `ruff check ...`
- `python3 -m py_compile scripts/production_node_breakthrough_session.py tests/test_production_node_breakthrough_session.py`
- `UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools TMPDIR=/tmp MYPY_CACHE_DIR=/tmp/mypy-cache uvx --with-editable . --with deepagents --with mypy mypy --strict scripts/breakthrough_evidence_bundle.py scripts/production_node_breakthrough_session.py tests/test_breakthrough_evidence_bundle.py tests/test_production_node_breakthrough_session.py`

Strict mypy scope:
- Repository-wide strict mypy is not clean. A direct whole-repo run with `.` as the target currently reports `1637` existing errors across `186` files.
- The breakthrough proof files are strict-mypy clean under the focused command above. Treat that as localized proof only, not a repo-wide type-safety claim.

Docs updated:
- [README.md](/Users/shaanp/Documents/GitHub/mesh/README.md)
- [docs/all-in-one-compose-stack.md](/Users/shaanp/Documents/GitHub/mesh/docs/all-in-one-compose-stack.md)

Current working tree for this step:
- Modified: `README.md`, `docs/all-in-one-compose-stack.md`
- Added: `scripts/production_node_breakthrough_session.py`, `tests/test_production_node_breakthrough_session.py`
