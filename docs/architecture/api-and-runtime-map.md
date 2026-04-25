# Mesh API & Runtime Map

Single-source reference for **how a signal becomes an executed action**, what
gates apply along the way, and the full HTTP surface that exposes the system.

Snapshot: master @ `1f0ba35` (post PRs #19 & #20).

---

## 1. Bird's-eye view

```
                    ┌─────────────── ENTRY POINTS ───────────────┐
                    │                                            │
   POST /api/runs   │  POST /api/webhooks/{id}   Watcher.tick()  │
        ▲           │           ▲                      ▲          │
        │           │           │                      │          │
   manual /         │      vendor alert          KubernetesWatcher│
   replay           │   (Prom/DD/Grafana/PD)     polls kubectl    │
                    │           │                      │          │
                    │           ▼                      ▼          │
                    │   build_signal_from_alert    live_signal    │
                    └───────────┬──────────────────────┬──────────┘
                                │                      │
                                ▼                      ▼
                       ┌───────────────────────────────────┐
                       │  RunCoordinator.create_run()      │  control_plane.py:669
                       │   • _resolve_signal               │
                       │   • integration readiness         │
                       │   • RUN_QUEUED                    │
                       │   • spawn _execute_run thread     │
                       └───────────────────┬───────────────┘
                                           ▼
   ┌──── stages: ingesting → trigger_ready → scenario_analysis_ready ──┐
   │                                                                   │
   │  IngestService.normalize_signal       → NORMALIZED_EVENT          │
   │      (2 paths: k8s, feature_flag)                                 │
   │  TriggerService.detect                → TRIGGER_READY | NO_TRIGGER│
   │      (gate predicates per type)                                   │
   │  ScenarioAnalysisService.analyze      → SCENARIO_ANALYSIS_READY   │
   │      (6 analyzers → evidence + subdecisions)                      │
   │                                                                   │
   ├── stage: decision_ready ─────────────────────────────────────────┤
   │                                                                   │
   │  DecisionService.decide                                           │
   │      (rule tree → hypothesis upgrade → LLM upgrade →              │
   │       confidence factors → scenario overlay → autonomy tier)      │
   │                                                                   │
   ├── stage: evaluation_ready ───────────────────────────────────────┤
   │                                                                   │
   │  EvaluationService.evaluate                                       │
   │      (14+ blocking_reasons → recommendation: execute|review|reject)│
   │  AgentMeshService.build_tasks                                     │
   │      (6 lanes parallel → first non-risk-flagged wins)             │
   │  ⚑ pause point: approve / cancel / override_decision / launch_evo │
   │                                                                   │
   ├── stage: executing ──────────────────────────────────────────────┤
   │                                                                   │
   │  OrchestratorService.execute                                     │
   │      (bounded retries → incident on exhaustion)                  │
   │      → adapters: kubernetes, argocd, feature_flag,               │
   │        repo_patch, audit_log, incident                           │
   │                                                                   │
   ├── stage: feedback_ready → completed ─────────────────────────────┤
   │                                                                   │
   │  FeedbackService.record                                          │
   │  _record_learning:                                               │
   │      LearningStore.record_outcome                                │
   │      ContextStore.update_from_run                                │
   │      TrustLadder.record_outcome                                  │
   │  MemoryLifecycleService.crystallize_run                          │
   └───────────────────────────────────────────────────────────────────┘
```

---

## 2. Entry points (how signals arrive)

| Source | Path / trigger | Code | What it produces |
|--------|----------------|------|------------------|
| Manual / replay | `POST /api/runs` | [control_plane_server.py:435](../../control_plane_server.py) → `coordinator.create_run` ([control_plane.py:669](../../services/control_plane.py)) | Direct signal payload (`signal_payload`, `live_signal`, or `scenario_key`) |
| Vendor webhook | `POST /api/webhooks/{source_id}` | [control_plane_server.py:476](../../control_plane_server.py) → `WebhookIngestService` ([services/ingest/webhook_service.py](../../services/ingest/webhook_service.py)) | `AlertEvent` → `build_signal_from_alert` → `create_run` (when `auto_run=true` & `action=fire`) → `signal_type=webhook_alert` ingest/trigger/decision lane |
| Watcher poll | per-tick poll | `KubernetesWatcher.tick()` → `_poll_target` ([services/watchers/kubernetes.py:78,119](../../services/watchers/kubernetes.py)) → `coordinator.create_run` | `live_signal` payload built from `collect_kubernetes_signal` (kubectl) |
| Cross-signal correlation | piggybacks on watcher signals | `SignalCorrelator.correlate` ([services/signal_correlator.py:59](../../services/signal_correlator.py)) | Adds `live_signal.correlation` (`none|same_namespace|cascading|blast_wave`) |

### Webhook templates

`shared/mesh_runtime/webhook_templates.py` + `fixtures/webhook_templates/`:

| Provider | Action mapping | Signature header |
|----------|----------------|------------------|
| Prometheus Alertmanager | `firing→fire`, `resolved→resolve` | `X-Mesh-Signature` (HMAC-SHA256, `sha256=` prefix) |
| Datadog | `triggered/error→fire`, `recovered→resolve` | same |
| Grafana v9+ | `firing/alerting→fire`, `ok→resolve` | same |
| PagerDuty V3 | `trigger→fire`, `resolve→resolve` | same |

Field extraction is JSONPath-ish (`extract_path` / `_resolve_field`) with `default/map/format/join` transformers (`format: unix|unix_ms|iso8601|strftime:`). Verification is constant-time HMAC-SHA256.

---

## 3. Ingest pipeline

`services/ingest/service.py:19` — `IngestService.normalize_signal(raw_signal)` branches on `signal_type`:

### 3a. Kubernetes path (`signal_type == "kubernetes_deployment_issue"`)

1. `validate_payload("kubernetes-signal.schema.json", raw_signal)` (line 21)
2. Seed `related_context` defaults: `active_suppression`, `incident_owned_by_human`, `known_upstream_outage`, `active_incidents=0`, `similar_prior_cases=0`, `rollbacks_last_24h=0`, `cluster_access_available=True`
3. `_enrich_from_learning(service, endpoint)` — non-destructive: only raises `similar_prior_cases / rollbacks_last_24h / regressions_last_7d` when currently zero (line 128)
4. `summarize_kubernetes_logs(logs, events, pods)` ([services/ingest/kubernetes_summary.py](../../services/ingest/kubernetes_summary.py)) — extracts `error_signatures`, `likely_layer`, `primary_symptom`
5. Emits `EventEnvelope(event_type="normalized_signal", payload=…)` carrying deployment/pods/events/logs/log_summary/related_context

### 3b. Feature-flag path

1. Seed defaults: `active_suppression`, `incident_owned_by_human`, `known_upstream_outage`, `conflicting_signals`, `high_business_impact`, `rollbacks_last_24h`, `regressions_last_7d`, `multi_service_impact`, `feature_flag_credentials_available`, `audit_logging_available`
2. Same `_enrich_from_learning` call but with `flag_key` extra
3. Emits `EventEnvelope` carrying `feature_flag`, `request_telemetry`, `deployment`, `comparison_window`, `segment`, `related_context`

### 3c. Webhook path (`signal_type == "webhook_alert"`)

1. Preserve the raw `alert_event` plus normalized `webhook.{source_id,alert_id,action,severity,title,description,labels,annotations}`
2. Seed incident-routing context: `webhook_source_id`, `webhook_alert_id`, `webhook_source_type`, `severity`, `incident_credentials_available`, `audit_logging_available`
3. Default segment to `{customer_tier:"system", region:<label or unknown>}` so policy and vault surfaces treat webhook runs as first-class sessions

---

## 4. Trigger detection

`services/trigger/service.py:11` — `TriggerService.detect(envelope)` dispatches on payload `signal_type`. Returns `Trigger | None` (None → `NO_TRIGGER` event, run terminates).

### 4a. `kubernetes_deployment_unhealthy` ([trigger/service.py:96](../../services/trigger/service.py))

All must hold:
- NOT `related_context.active_suppression | incident_owned_by_human | known_upstream_outage` (lines 103-107)
- `deployment.rollout_status in {"degraded","failed"}` **OR** any pod has `ready=False` or `restarts>0` (lines 108-110)

Output carries: `error_signatures`, `restart_count_total`, replica counts, `likely_layer`, `event_reasons`, `primary_symptom`.

### 4b. `feature_flag_performance_regression` ([trigger/service.py:17](../../services/trigger/service.py))

All must hold:
- Flag changed 0–30 min ago (`emitted_at - feature_flag.changed_at`) (lines 25-31)
- `telemetry.sample_size >= 500` (line 32)
- `telemetry.persistent_windows >= 2` (line 36)
- NOT `feature_flag.under_rollback`, `active_suppression`, `incident_owned_by_human`, `known_upstream_outage` (lines 44-49)
- At least one of: p95 observed >= baseline·1.25; baseline error_rate>0 AND observed >= baseline·1.5; `timeout_rate >= 0.02` (lines 33-35, 54-55)

Output carries `trigger_signals`: `latency_regression`, `error_regression`, `timeout_regression`.

---

## 5. Scenario analysis (6 analyzers)

`services/scenario_analysis/service.py` — runs *before* the decision service so its evidence + subdecisions can override the rule tree.

| Analyzer | Class:line | Evaluates | Subdecision |
|----------|-----------|-----------|-------------|
| `RegressionAnalyzer` | L204 | FF telemetry deltas | `disable_flag` (timeout≥0.02 / ratio≥2 / delta≥40) else `reduce_rollout`, conf 0.86 |
| `KubernetesAnalyzer` | L254 | error_signatures, rollout_status, correlation | `rollback_deployment` (0.90) / `restart_deployment` (0.78) / `escalate` (0.62); blast_wave/cascading → requires_review |
| `HistoricalOutcomeAnalyzer` | L313 | success rates, recovery patterns | weak actions (<0.4) + corroborating<2 → `approval_required` (0.68) |
| `RiskScopeAnalyzer` | L374 | rollbacks_last_24h, multi_service, high_business, missing creds, blast_wave/cascading | any → `approval_required` 0.82 + requires_review |
| `MemoryRelevanceAnalyzer` | L403 | active_memory packet, recent runs, search hits | always advisory `no_action` 0.7 |
| `EdgeCaseAnalyzer` | L438 | unknown trigger_type, conflicting_signals, no source events, missing K8s signatures | unresolved → `escalate` 0.9 + requires_review |

**Synthesis** (`DecisionSynthesisService.synthesize`, L487-535): picks highest-confidence actionable subdecision. With review_reasons present, the autonomy_tier is forced upward (approval_required / escalated) and confidence capped at 0.74 if classifier flags terminal/unclassified reasons.

---

## 6. Decision pipeline

`services/decision/service.py` — converts a Trigger (and optional ScenarioAnalysis) into a single `Decision`.

### 6a. Feature-flag rule tree (first match wins)

| # | Condition | decision_type | conf | risk |
|---|-----------|---------------|------|------|
| 0 | default | `reduce_rollout` | 0.82 | medium |
| 1 | `code_remediation_candidate` + repo bundle complete | `investigate_and_patch` | 0.78 | medium |
| 2 | `high_business_impact` | `escalate` | 0.64 | high |
| 3 | `flag_causality_confidence ≤ 0.35` AND `timeout_rate < 0.02` | `no_action` | 0.79 | low |
| 4 | `timeout_rate ≥ 0.02` OR `error_multiplier ≥ 2` OR `latency_delta_pct ≥ 40` | `disable_flag` | 0.88 | medium |
| 5 | `latency_delta_pct < 25` AND `error_multiplier < 1.5` | `no_action` | 0.77 | low |
| Promote | `no_action` AND `active_incidents > 0` AND `flag_causality ≥ 0.7` | upgrade → `reduce_rollout` | max(conf, 0.8) | medium |
| Demote | `disable_flag/reduce_rollout` AND no FF creds | downgrade → `escalate` | min(conf, 0.7) | medium |

### 6b. Kubernetes rule tree (`_decide_kubernetes`)

| # | Condition | decision_type | conf | autonomy_tier |
|---|-----------|---------------|------|---------------|
| 1 | `code_remediation_candidate` + `application_error` + repo bundle | `investigate_and_patch` | 0.81 | autonomous (or approval if repeated rollback) |
| 2 | `image_pull_failure` OR `rollout_status==failed` | `rollback_deployment` | 0.90 | autonomous |
| 3 | `crash_loop` OR `probe_failure` OR `oom_killed` | `restart_deployment` | 0.78 | autonomous (or approval if repeated rollback) |
| 4 | else | `escalate` | 0.65 | escalated |
| Hypothesis upgrade | `escalate` AND top hypothesis posterior ≥ 0.55 AND action ∈ allowed | upgrade to that action | min(posterior, 0.82) | autonomous/approval |
| LLM upgrade | `escalate` OR conf < 0.65 → `EscalationReasoner.reason()` returns better action | upgrade to that action | min(reasoning.conf, 0.85) | autonomous/approval |
| Correlation override | `correlation.type ∈ {blast_wave, cascading}` | (unchanged) | forces `approval_required` |

### 6c. Hypothesis engine bias

`services/decision/hypothesis_engine.py` generates 1–3 falsifiable hypotheses per error signature (`crash_loop`, `oom_killed`, `image_pull_failure`, `probe_failure`); unknown sigs → single `h_unknown → escalate`.

Posterior = `prior · (1 + 0.2·support_weight − 0.3·disconfirm_weight)` clamped `[0.05, 0.95]`.

Predicates query AlertStore (recent_deploy, configmap_or_secret_change), InfraGraph (upstream_service_degraded), ContextStore (past action success), and SignalCorrelator (blast_wave).

**Guardrail:** only fires when rule tree said `escalate`; never overrides concrete rule matches.

### 6d. EscalationReasoner (LLM)

`services/decision/llm_reasoning.py` shells `goose run`. Fires when `decision_type == escalate` OR `confidence < 0.65`.

`_LLM_ALLOWED_ACTIONS` = `{reduce_rollout, disable_flag, restart_deployment, rollback_deployment, no_action}` (`escalate` stripped).

Confidence cap: `min(reasoning.confidence, 0.85)`. Disallowed actions collapse to escalate (conf 0.0).

### 6e. Confidence factors (`_build_confidence_factors`)

Final confidence = `max(0.5, min(sum(factors), 0.95))`.

| Input | Effect |
|-------|--------|
| similar_prior_cases > 0 | `+ min(n,3) · 0.01` |
| flag_causality_confidence | `+ clamp(x−0.5, ±0.2) · 0.1` |
| trigger_signals ≥ 2 | `+0.01` |
| historical_success_rate ≥ 0.8 | `+0.02` |
| historical_success_rate < 0.4 | `−0.03` |
| corroborating_evidence_count > 0 | `+ min(n,4) · 0.015` |
| active_memory_count > 0 | `+ min(n,3) · 0.01` |
| similar_incident_count > 0 | `+ min(n,3) · 0.01` |
| related_run_count > 0 | `+ min(n,4) · 0.005` |

### 6f. Scenario overlay (`_apply_scenario_analysis`)

If review_reasons present and rule said `escalate` and classifier flags terminal/unclassified → force `escalate`. Tier is overwritten by `autonomy_tier_hint` if present, else any review reasons on `autonomous` upgrade to `approval_required`. Risk level can only ratchet up (low→medium/high), never downgrade. Confidence: terminal reasons → `min(current, scenario_conf, 0.74)`.

---

## 7. Evaluation gates (conditions for execution)

`services/evaluation/service.py:57-217` builds `blocking_reasons[]`. Recommendation: `reject` if hard-reject; else `execute` if no blockers; else `human_review`.

| blocking_reason | Trigger condition | reject? |
|-----------------|-------------------|---------|
| schema validation error | trigger / decision validation fail | no |
| autonomy violation (decision_type) | type ∉ `autonomy.policy.allowed_decision_types` | **yes** |
| autonomy violation (execution_plan) | system or action ∉ allow-list | **yes** |
| duplicate evaluation suppressed | trigger_id already evaluated AND `allow_rereevaluation=False` | **yes** |
| scope requires approval before execution | autonomous + (protected_tier OR repeated_rollback OR multi_service) | no |
| approval required before execution | `autonomy_tier == approval_required` | no |
| recent rollback cooldown conflict | `rollbacks_last_24h>0` AND autonomous | no |
| decision routes to human review | `decision_type == escalate` | no |
| promptfoo quality gate did not pass | adapter passed=False | no |
| confidence below minimum threshold | conf < `rollback.minimum_confidence` (0.75) | no |
| risk level is high | `decision.risk.level == high` | no |
| action is not idempotent | action ∉ `autonomy.idempotent_actions` | no |
| rollback parameters missing | decision_type in rollback list AND no `rollback_plan` | no |
| required credentials unavailable | system-specific creds missing | no |
| repo patch readiness | repo path / allowed_paths / test_commands / patch_template missing | no |

### Policy files (`policies/`)

| File | Key thresholds |
|------|----------------|
| `autonomy.policy.json` | 13 decision_types, 6 systems, per-system allow-lists, idempotent_actions set |
| `protected-scope.policy.json` | approval_required tiers `[strategic, platinum]`; `escalate_on_multi_service=true` |
| `rollback.policy.json` | `minimum_confidence=0.75`; `cooldown_hours_after_rollback=24`; rollback_plan required for 5 decision_types |

---

## 8. Triage / agent mesh routing

`services/orchestrator/agent_mesh.py:41` — `build_tasks()` constructs one `AgentTask` per run with memory_packet from `state_store.retrieve_memory`.

**Two modes** (`agent_fabric_mode` config):

- `deepagents` — all 6 lanes via `DeepAgentsAdapter.build_lane_attempt`; each spins a sandboxed deepagents graph with 5–6 sub-subagents (root-cause-analyst, patch-proposer, reviewer, staging-validator, rollback-planner, evo-benchmark-advisor)
- `native_contract` — hand-written builders:

| Lane | Role | Gate |
|------|------|------|
| `goose` | operational coordination | always |
| `hermes` | root-cause hypothesis from `related_context.log_summary` | always |
| `codex` | repo patch | requires `allowed_paths` + `test_commands` |
| `claudecode` | review (risk=`evaluation_failed` if not passed) | always |
| `openclaw` | staging k8s validation | requires namespace + context |
| `evo` | optimization advisory | requires evo CLI + workspace + `code_remediation_candidate` |
| `latentmas` | optional 7th lane | `config.latentmas_enabled` |

**Selection (current)**: first `completed && !risk_flags` wins; else first attempt is selected.

**No domain routing today** — every lane sees every signal regardless of source. See [docs/plans/sub-agent-specialization.md](../plans/sub-agent-specialization.md) for the planned per-domain routing layer.

### Trust ladder (per-action-class autonomy graduation)

`shared/mesh_runtime/trust_ladder.py:145-159` — independent state per `(action_class, service)`:

| Transition | Min runs | Min success rate |
|-----------|----------|-------------------|
| suggest → draft | 3 | 0.5 |
| draft → approve | 10 | 0.7 |
| approve → auto | 30 | 0.85 |
| Demote one level | 2 consecutive failures | — |

`override_level()` forces a level without affecting stats. `record_outcome(override=True)` bypasses ladder entirely.

---

## 9. Steering (operator interventions)

11 commands ([control_plane.py:77-91](../../services/control_plane.py)). Single transport: `POST /api/runs/{id}/steer`.

| Command | Allowed at stage | Notes |
|---------|------------------|-------|
| `approve` | any pauseable | unblocks the wait |
| `cancel` | any non-terminal | terminates run |
| `pause_after_stage` | any | adds a future pause point |
| `resume` | paused | resumes execution |
| `set_auto_mode` | any | toggles auto-progression |
| `override_decision` | only `evaluation_ready` (paused), pre-actuation | rejected in early/late stages |
| `override_execution_parameters` | only `evaluation_ready` (paused) | same |
| `explain_blockers` | only `evaluation_ready` (paused) | invokes Hermes summarizer |
| `chat_with_hermes` | only `evaluation_ready` (paused) | requires non-empty `message` |
| `attach_note` | any (incl. terminal) | append-only operator note |
| `launch_evo` | `evaluation_ready` (paused) OR `completed` | spawns evo workspace |

Pauseable stages: `{trigger_ready, decision_ready, evaluation_ready, feedback_ready}`.
Terminal stages: `{completed, failed, cancelled, no_trigger, recovery_spawned}`.

Payload cap: 64 KB (`MESH_MAX_STEERING_PAYLOAD_BYTES`).

---

## 10. Execution & retry

`services/orchestrator/service.py:79-184` — `OrchestratorService.execute(decision, evaluation)`.

| Condition | Result |
|-----------|--------|
| `not evaluation.passed` OR `recommendation != execute` | `ExecutionRecord.status="rejected"`, no actuator call |
| adapter `succeeded` | break, return success |
| `not retryable` failure | break, mark failed |
| `attempts > max_transient_retries` (default 2) | break |
| retry window exceeded (`max_retry_window_seconds`, default 60) | break |
| retryable failure | exponential backoff `min(2^(n-1), 8)` s, `execution_retry_scheduled` event |
| post-loop retryable failure | `adapter.open_execution_incident()`, marks `human_review_route=human_review` |

### Adapter dispatch (`hermes_adapter.execute_decision`)

| `system` | Action → Adapter |
|----------|------------------|
| `feature_flag_service` | `set_rollout` → `FeatureFlagAdapter` *(stub)* |
| `incident_service` | `open_incident` → `IncidentAdapter` *(stub)* |
| `kubernetes_service` | `rollback_deployment | restart_deployment | restart_pod | scale_deployment | cordon_node | drain_node` → `KubernetesAdapter` (kubectl, with allowlist guards) |
| `argocd_service` | `sync_application | rollback_application` → `ArgoCDAdapter` (REST API; dry-run if no creds) |
| `repo_patch_service` | `investigate_and_patch` → `RepoPatchAdapter` (find/replace + tests + auto-rollback) |
| `audit_log_sink` | `record_no_action` → `AuditLogAdapter` *(stub)* |

---

## 11. Feedback & learning loop

`control_plane.py:_record_learning` (line 1148) runs after `RUN_COMPLETED`:

1. `LearningStore.record_outcome(decision_type, service, endpoint, outcome, world_model_updates)` — outcomes capped at 500
2. `ContextStore.update_from_run(session_dict)` — service registry + incident history (cap 200, 20 patterns/service)
3. `TrustLadder.record_outcome(action_class, service, outcome)` — skipped for `no_action`/`escalate`
4. `MemoryLifecycleService.crystallize_run` ([shared/mesh_runtime/memory_lifecycle.py](../../shared/mesh_runtime/memory_lifecycle.py)) — promotes facts working→episodic→semantic→procedural

These feed back into the **next** run via:
- `IngestService._enrich_from_learning` → fills `similar_prior_cases`, `rollbacks_last_24h`, `regressions_last_7d`
- `DecisionService` confidence adjustments (historical_success_rate)
- `HypothesisEngine._check_past_success` (via ContextStore)
- `ActiveMemoryStore.compact` → `MEMORY_COMPACTION_RECORDED` event

---

## 12. Run event types

21 typed events in `shared/mesh_runtime/run_events.py`:

```
run_queued                    integration_readiness_recorded
normalized_event              no_trigger
trigger_ready                 evidence_node_recorded
subdecision_recorded          scenario_analysis_ready
memory_compaction_recorded    decision_ready
evaluation_ready              integration_artifact_recorded
agent_task_recorded           steering_command
steering_rejected             approval_blocked
execution_recorded            feedback_recorded
run_completed                 run_failed
run_cancelled
```

Every event hashes into a per-run **Merkle tree** with persistent root on `RunSession.latest_merkle_root`. Verifiable via `GET /api/runs/{id}/merkle/proof/{event_id}`.

---

## 13. Memory & state stores

| Store | File | Persistence | Purpose |
|-------|------|------------|---------|
| `RuntimeStateStore` | `shared/mesh_runtime/state.py` | file-locked JSON | Per-run loop output |
| `ControlPlaneStateStore` | `shared/mesh_runtime/control_plane_state.py` | JSON or Postgres | Run sessions, events, merkle |
| `MeshStateStore` | `shared/mesh_runtime/mesh_state_store.py` | JSON or Postgres | Memory artifacts (claims, observations, evidence) |
| `LearningStore` | `shared/mesh_runtime/learning.py` | JSON | Outcome aggregation (cap 500) |
| `ContextStore` | `shared/mesh_runtime/context_store.py` | JSON (cap 200) | Service registry + incident history |
| `TrustLadder` | `shared/mesh_runtime/trust_ladder.py` | JSON | Per-(action,service) autonomy graduation |
| `ActiveMemoryStore` | `shared/mesh_runtime/active_memory.py` | JSON (cap 25/service) | Compacted active facts per service |
| `InfraGraph` | `shared/mesh_runtime/infra_graph.py` | JSON + versioned snapshots (cap 50) | K8s topology |
| `AlertStore` | `shared/mesh_runtime/alert_store.py` | JSON tail per source | Webhook event log |
| `VaultManager` | `shared/mesh_runtime/vault.py` | Markdown files | Obsidian-readable run mirror |

Backend factory: `state_store_factory.build_mesh_state_store(config)` — picks JSON or Postgres based on `MESH_STATE_BACKEND`.

---

## 14. Watcher registry

`services/watchers/base.py:44` — `WatcherRegistry`. Each registered watcher runs on its own daemon thread with **±20% jitter** to avoid thundering herd.

`Watcher` Protocol (lines 26-41):
```python
name: str
signal_source: str    # "kubernetes" | (future: "feature_flag" | "argocd" | ...)
interval_seconds: int
def tick(self) -> None: ...
def status(self) -> dict[str, Any]: ...
```

**Today: only `KubernetesWatcher`** ([services/watchers/kubernetes.py](../../services/watchers/kubernetes.py)).

Per-target gates (`_poll_target`):
1. Active-run dedup — skip if prior run still in-flight (`coordinator.get_run`)
2. Cooldown — skip if `time.monotonic() - last_run_time < cooldown_seconds`
3. Actionable check — same predicate as `TriggerService._detect_kubernetes_trigger()`: failed rollout, failing pods (`restarts > 0` or hard failing container state), or degraded rollout plus hard error signatures
4. Error-signature dedup — skip if `error_sig == last_error_signature`
5. Enqueue: `coordinator.create_run({"live_signal": {…}, "steering_mode": "interruptible_auto"})`

Compat shim (`services/watchers/compat.py`): if `MESH_WATCH_TARGETS` set but `MESH_WATCHER_CONFIG_PATH` not, registers a single `legacy-k8s` watcher with byte-identical legacy behavior.

### 14a. Live feedback verification

When `MESH_FEEDBACK_PROMETHEUS_ENABLED=true` and `MESH_PROMETHEUS_URL` is set, the feedback stage overlays live Prometheus samples onto `post_action_observations` for the `10m` and `30m` windows. Query templates are configurable via:

- `MESH_FEEDBACK_PROMETHEUS_LATENCY_QUERY`
- `MESH_FEEDBACK_PROMETHEUS_ERROR_RATE_QUERY`

Both templates accept `{service}` and `{window}` placeholders. If Prometheus returns no data or errors, Mesh falls back to the signal-carried observations and still completes the run.

---

## 15. Complete HTTP API surface

### Health / readiness
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Status, version, commit, environment |
| GET | `/api/readiness` | Integration availability snapshot |

### Goals & scenarios
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/scenarios` | List scenario templates |
| GET | `/api/goals` | List goals |
| POST | `/api/goals` | Create goal (201) |

### Runs
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/runs` | List recent runs |
| POST | `/api/runs` | Create + queue a run (201) |
| GET | `/api/runs/{id}` | Run snapshot |
| GET | `/api/runs/{id}/events?after={seq}` | Event timeline since seq |
| GET | `/api/runs/{id}/scenario-analysis` | Scenario analysis payload |
| GET | `/api/runs/{id}/evidence-graph` | Evidence + subdecision graph |
| GET | `/api/runs/{id}/merkle` | Full merkle snapshot |
| GET | `/api/runs/{id}/merkle/proof/{event_id}` | Inclusion proof for one event |
| GET | `/api/runs/{id}/agent-tasks` | Agent attempt list |
| GET | `/api/runs/{id}/memory-crystallization` | Crystallization payload |
| POST | `/api/runs/{id}/steer` | Apply steering command (see §9) |
| GET | `/api/stream/runs/{id}` | SSE: events + heartbeat + complete |
| GET | `/api/stream/system` | SSE: runs + readiness every 2s |

### Memory
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory/active?service=` | Active memory packet |
| GET | `/api/memory/query?q=&service=&limit=` | Memory search |
| GET | `/api/memory/claims/{claim_id}` | Single claim |
| GET | `/api/memory/graph?service=` | Memory graph view |
| POST | `/api/memory/maintenance/run` | Kick maintenance pass |

### Research
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/research-sessions` | List research sessions |
| GET | `/api/research-sessions/{id}` | Session detail (URL-decoded) |
| GET | `/api/research-corpus` | Corpus snapshot |

### Vault (Obsidian mirror)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/vault/tree` | Vault directory tree |
| GET | `/api/vault/document?path=` | Read doc (rejects `..`/absolute) |

### Webhooks / alerts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/webhook-sources` | List sources |
| GET | `/api/webhook-sources/{id}` | Source detail |
| POST | `/api/webhook-sources` | Register source (201) |
| DELETE | `/api/webhook-sources/{id}` | Delete source |
| POST | `/api/webhooks/{source_id}` | Ingest alert (verifies HMAC); 202 |
| GET | `/api/alerts?source_id=&limit=` | List alert events |

### Watch (legacy global daemon)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watch/status` | Status of legacy K8s watcher |
| POST | `/api/watch/start` | Start it |
| POST | `/api/watch/stop` | Stop it |

### Watchers (per-named, new)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchers` | All watchers + statuses |
| GET | `/api/watchers/{name}` | Single watcher detail |
| POST | `/api/watchers/{name}/start` | Start one watcher |
| POST | `/api/watchers/{name}/stop` | Stop one watcher |

### Infrastructure graph
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/graph/status` | Node/edge counts, version count |
| GET | `/api/graph/snapshot` | Full snapshot |
| GET | `/api/graph/neighbors/{kind}/{namespace}/{name}?depth=&direction=&edge_kinds=` | BFS neighbors (`_cluster`/`-` for cluster-scope) |
| GET | `/api/graph/node/{kind}/{namespace}/{name}` | Single node |
| GET | `/api/graph/affected/{namespace}/{deployment}` | Services impacted by a deployment |
| POST | `/api/graph/refresh` | Re-collect topology via kubectl |

### Trust ladder
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/trust-ladder` | All entries |
| GET | `/api/trust-ladder/{action_class}/{service}` | Single entry |
| POST | `/api/trust-ladder/override` | Operator override |

### Agent SLO / Prometheus
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agent/slo` | Structured SLO JSON (24h/7d/30d windows) |
| GET | `/metrics` | Prometheus exposition (`text/plain; version=0.0.4`) |

### Static / meta
| Method | Path | Description |
|--------|------|-------------|
| HEAD | `/api/*` | 200 + JSON content-type |
| OPTIONS | `*` | CORS preflight (204) |
| GET | `/`, `/{anything}` | SPA static asset (falls back to `index.html`); 503 if not built |

### Cross-cutting behaviors

- Request bodies capped by `config.max_json_body_bytes` (413 if over)
- Non-dict JSON roots wrapped as `{"root": payload}` for webhook arrays
- Security headers: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`
- CORS: reflect-origin on JSON + static
- SSE: honors `Last-Event-ID`, sends `:heartbeat` comments, self-terminates at `sse_max_connection_seconds` or terminal stage
- No DELETE endpoints other than `/api/webhook-sources/{id}`

---

## 16. Quick mental model — when to look where

| Question | File |
|----------|------|
| "How did this signal arrive?" | [control_plane.py:_resolve_signal](../../services/control_plane.py), [watchers/kubernetes.py](../../services/watchers/kubernetes.py), [ingest/webhook_service.py](../../services/ingest/webhook_service.py) |
| "Why didn't this trigger fire?" | [trigger/service.py](../../services/trigger/service.py) |
| "Why did decision pick X?" | [decision/service.py](../../services/decision/service.py), then `decision.reasoning.evidence_pack.hypotheses` for posterior bias |
| "Why was execution blocked?" | [evaluation/service.py](../../services/evaluation/service.py) → `blocking_reasons[]` |
| "What action got executed and how?" | [orchestrator/service.py](../../services/orchestrator/service.py) → `applied_action`, retry log via `execution_retry_scheduled` events |
| "Why did multiple lanes disagree?" | [agent_mesh.py](../../services/orchestrator/agent_mesh.py) → `AgentTask.attempts[]` |
| "What past runs influenced this?" | `decision.reasoning.evidence_pack` → `recovery_context`, `confidence_factors`, `hypotheses[].supporting_evidence` |
| "How does the agent itself perform?" | `GET /api/agent/slo` and `/metrics` |
| "What can the operator do at this point?" | `PAUSEABLE_STAGES`, [_validate_steering_command](../../services/control_plane.py) |
