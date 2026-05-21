from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIRECTORY = _REPO_ROOT / ".mesh-runtime-state"
DEFAULT_RESEARCH_DIRECTORY = DEFAULT_STATE_DIRECTORY / "research"
DEFAULT_WEB_ASSET_PATH = _REPO_ROOT / "meshapp" / "frontend" / "out"
DEFAULT_VAULT_PATH = DEFAULT_STATE_DIRECTORY / "vault"
DEFAULT_INTEGRATIONS_CONFIG_PATH = DEFAULT_STATE_DIRECTORY / "integrations.json"
DEFAULT_OWNERSHIP_REGISTRY_PATH = _REPO_ROOT / "config" / "ownership.registry.json"
DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY_PATH = _REPO_ROOT / "config" / "connector-certification.registry.json"
DEFAULT_POLICY_LIFECYCLE_MANIFEST_PATH = _REPO_ROOT / "config" / "policy-lifecycle.manifest.json"
DEFAULT_ORCHESTRATION_TOPOLOGY_PROFILE_PATH = _REPO_ROOT / "config" / "orchestration-topology.profile.json"
DEFAULT_FAILURE_MODE_LIBRARY_PATH = _REPO_ROOT / "config" / "failure-mode.library.json"
DEFAULT_THREAT_MODEL_REGISTER_PATH = _REPO_ROOT / "config" / "threat-model.register.json"
DEFAULT_DATA_CLASSIFICATION_POLICY_PATH = _REPO_ROOT / "config" / "data-classification.policy.json"
DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH = _REPO_ROOT / "config" / "agentic-operator-source.provenance.json"
DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH = _REPO_ROOT / "config" / "deployment-compatibility.registry.json"
DEFAULT_PROCUREMENT_SECURITY_PACKAGE_PATH = _REPO_ROOT / "config" / "procurement-security.package.json"
DEFAULT_PUBLIC_PROOF_PACKAGE_PATH = _REPO_ROOT / "config" / "public-proof.package.json"
DEFAULT_RELEASE_PROVENANCE_PATH = DEFAULT_STATE_DIRECTORY / "release-provenance.json"
DEFAULT_AUTHENTICATED_INGRESS_PROOF_PATH = DEFAULT_STATE_DIRECTORY / "authenticated-ingress-deployment-proof.json"
DEFAULT_DESIGN_PARTNER_PACKET_PATH = DEFAULT_STATE_DIRECTORY / "design-partner-packet.json"
DEFAULT_AUDIT_SINK_PROOF_PATH = DEFAULT_STATE_DIRECTORY / "audit-sink-proof.json"
DEFAULT_AUDIT_SINK_CERTIFICATION_PATH = DEFAULT_STATE_DIRECTORY / "audit-sink-certification.json"
DEFAULT_BACKUP_RESTORE_REHEARSAL_PATH = DEFAULT_STATE_DIRECTORY / "backup-restore-rehearsal.json"
DEFAULT_LOAD_CONCURRENCY_REHEARSAL_PATH = DEFAULT_STATE_DIRECTORY / "load-concurrency-rehearsal.json"
DEFAULT_ORCHESTRATION_TOPOLOGY_DRILL_PATH = DEFAULT_STATE_DIRECTORY / "orchestration-topology-drill.json"
DEFAULT_FEATURE_FLAG_PROVIDER_PROOF_PATH = DEFAULT_STATE_DIRECTORY / "feature-flag-provider-proof.json"
DEFAULT_INCIDENT_PROVIDER_PROOF_PATH = DEFAULT_STATE_DIRECTORY / "incident-provider-proof.json"
DEFAULT_ON_CALL_DRILL_PATH = DEFAULT_STATE_DIRECTORY / "on-call-drill.json"
DEFAULT_DEEPAGENTS_WORKSPACE = DEFAULT_STATE_DIRECTORY / "deepagents"
DEFAULT_BENCHMARK_EXPORT_PATH = DEFAULT_STATE_DIRECTORY / "benchmarks" / "runs.jsonl"
DEFAULT_CORPUS_DATABASE_PATH = DEFAULT_STATE_DIRECTORY / "corpus" / "incident_corpus.sqlite"
DEFAULT_OPERATOR_IDENTITY_PATH = DEFAULT_STATE_DIRECTORY / "operator-identity.json"


def _env_path_anchored_to_repo(raw: str | None, *, default: str) -> str:
    value = (raw or "").strip() or default
    p = Path(value)
    if p.is_absolute():
        return str(p.resolve())
    return str((_REPO_ROOT / p).resolve())


def _read_env_or_file(raw: str | None, raw_path: str | None) -> str | None:
    value = (raw or "").strip()
    if value:
        return value
    path_value = (raw_path or "").strip()
    if not path_value:
        return None
    path = Path(_env_path_anchored_to_repo(path_value, default=""))
    return path.read_text(encoding="utf-8")


def _parse_watch_targets(raw: str | None) -> tuple[dict[str, str], ...]:
    if not raw:
        return ()
    try:
        targets = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ()
    if not isinstance(targets, list):
        return ()
    return tuple(t for t in targets if isinstance(t, dict) and "deployment_name" in t)


def _resolve_relative_path(raw: str, anchor: Path = _REPO_ROOT) -> str:
    """Convert a relative path to absolute, anchored at the repo root."""
    p = Path(raw)
    if p.is_absolute():
        return raw
    return str((anchor / p).resolve())


@dataclass
class RuntimeConfig:
    environment: str = "local"
    # ``auto`` probes integration readiness at startup and uses Promptfoo /
    # Goose when they can actually run. Falls back to the in-process native
    # adapters when not ready (offline dev, air-gapped, CI without CLIs). Set
    # explicitly to ``native`` / ``promptfoo`` / ``goose`` to opt out of the
    # probe and pin one adapter.
    evaluation_mode: str = "auto"
    orchestration_mode: str = "auto"
    feature_flag_credentials_available: bool = True
    incident_credentials_available: bool = True
    audit_logging_available: bool = True
    max_transient_retries: int = 2
    max_retry_window_seconds: int = 60
    goose_timeout_seconds: int = 180
    state_backend: str = "file"
    database_url: str | None = None
    memory_graph_backend: str = "local"
    helix_api_endpoint: str | None = None
    helix_port: int = 6969
    helix_query_namespace: str = "mesh"
    zaxy_enabled: bool = False
    zaxy_namespace: str = "mesh"
    zaxy_tenant_id: str = "local"
    zaxy_project_id: str = "mesh"
    zaxy_eventloom_url: str | None = None
    zaxy_eventloom_outbox_path: str | None = None
    zaxy_mcp_url: str | None = None
    zaxy_neo4j_projection_enabled: bool = False
    zaxy_packet_capture_enabled: bool = False
    zaxy_timeout_seconds: float = 2.0
    # Connection pool sizing for ``state_backend=postgres``. The pool is
    # shared process-wide and keyed by ``database_url`` so a single mesh
    # instance never opens more than ``postgres_pool_max_size`` concurrent
    # connections regardless of how many ``PostgresStateStore`` objects
    # exist. Pre-pool implementation opened a fresh TCP+TLS+auth handshake
    # on every operation (27 sites in ``postgres_state.py``), so for any
    # non-trivial deployment the pool is the difference between sub-10ms
    # and ~100ms per-operation latency.
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10
    postgres_pool_max_idle_seconds: float = 600.0
    postgres_pool_connect_timeout_seconds: float = 10.0
    state_directory: str = str(DEFAULT_STATE_DIRECTORY)
    research_directory: str = str(DEFAULT_RESEARCH_DIRECTORY)
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    web_asset_path: str = str(DEFAULT_WEB_ASSET_PATH)
    vault_path: str = str(DEFAULT_VAULT_PATH)
    integrations_config_path: str = str(DEFAULT_INTEGRATIONS_CONFIG_PATH)
    ownership_registry_path: str = str(DEFAULT_OWNERSHIP_REGISTRY_PATH)
    connector_certification_registry_path: str = str(DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY_PATH)
    policy_lifecycle_manifest_path: str = str(DEFAULT_POLICY_LIFECYCLE_MANIFEST_PATH)
    orchestration_topology_profile_path: str = str(DEFAULT_ORCHESTRATION_TOPOLOGY_PROFILE_PATH)
    failure_mode_library_path: str = str(DEFAULT_FAILURE_MODE_LIBRARY_PATH)
    threat_model_register_path: str = str(DEFAULT_THREAT_MODEL_REGISTER_PATH)
    data_classification_policy_path: str = str(DEFAULT_DATA_CLASSIFICATION_POLICY_PATH)
    agentic_operator_source_provenance_path: str = str(DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH)
    deployment_compatibility_registry_path: str = str(DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH)
    procurement_security_package_path: str = str(DEFAULT_PROCUREMENT_SECURITY_PACKAGE_PATH)
    public_proof_package_path: str = str(DEFAULT_PUBLIC_PROOF_PACKAGE_PATH)
    release_provenance_path: str = str(DEFAULT_RELEASE_PROVENANCE_PATH)
    authenticated_ingress_proof_path: str | None = None
    design_partner_packet_path: str | None = None
    audit_sink_proof_path: str | None = None
    audit_sink_certification_path: str | None = None
    backup_restore_rehearsal_path: str | None = None
    load_concurrency_rehearsal_path: str | None = None
    orchestration_topology_drill_path: str | None = None
    feature_flag_provider_proof_path: str | None = None
    incident_provider_proof_path: str | None = None
    on_call_drill_path: str | None = None
    policy_signing_key: str | None = None
    policy_signing_key_id: str = "policy-lifecycle-hmac"
    darkharness_registry_path: str | None = None
    darkharness_packet_persistence_mode: str = "ephemeral"
    darkharness_signing_key: str | None = None
    darkharness_signing_key_id: str = "darkharness-local-hmac"
    darkharness_classical_signing_key_pem: str | None = None
    darkharness_classical_signing_key_id: str = "darkharness-ed25519"
    mesh_brain_artifact_uri_prefix: str | None = None
    mesh_brain_artifact_registry_path: str | None = None
    mesh_brain_artifact_upload_proof_path: str | None = None
    mesh_brain_serving_base_url: str | None = None
    mesh_brain_serving_model: str | None = None
    default_steering_mode: str = "approval_gate"
    default_operator_pause_point: str = "evaluation_ready"
    readiness_profile: str = "local"
    operator_identity_required: bool = False
    operator_header_name: str = "X-Mesh-Operator"
    operator_roles_header_name: str = "X-Mesh-Roles"
    auth_mode: str = "proxy_header"
    operator_identity_path: str = str(DEFAULT_OPERATOR_IDENTITY_PATH)
    session_cookie_name: str = "mesh_session"
    auth_allowed_origins: tuple[str, ...] = ()
    auth_product_redirect_url: str = ""
    signup_enabled: bool = True
    password_auth_enabled: bool = True
    auth_invite_allowlist: tuple[str, ...] = ()
    auth_invite_codes: tuple[str, ...] = ()
    captcha_provider: str = "disabled"
    captcha_site_key: str = ""
    captcha_secret_key: str = ""
    captcha_dev_bypass_enabled: bool = False
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_url: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_url: str = ""
    force_approval_gate: bool = False
    run_worker_count: int = 4
    run_queue_size: int = 100
    tenant_active_run_quota: int = 4
    promptfoo_command: str | None = None
    hermes_command: str | None = None
    hermes_command_timeout_seconds: int = 180
    goose_command: str | None = None
    goose_command_timeout_seconds: int = 180
    evo_command: str | None = None
    evo_command_timeout_seconds: int = 60
    kubernetes_live_execution_enabled: bool = False
    kubectl_command: str = "kubectl"
    kubernetes_rollout_timeout_seconds: int = 120
    kubernetes_allowed_contexts: tuple[str, ...] = ()
    kubernetes_allowed_namespaces: tuple[str, ...] = ()
    gitnexus_sidecar_url: str | None = None
    gitnexus_sidecar_command: str | None = None
    gitnexus_disable_autostart: bool = False
    max_json_body_bytes: int = 1_048_576
    run_export_max_bytes: int = 5_242_880
    run_export_retention_days: int = 30
    run_export_retention_reviewed: bool = False
    access_log_enabled: bool = False
    security_headers_enabled: bool = True
    vault_ai_postprocess_enabled: bool = False
    build_version: str = "dev"
    build_commit: str = "unknown"
    build_image_digest: str = ""
    latentmas_enabled: bool = False
    latentmas_url: str | None = None
    latentmas_timeout_seconds: float = 60.0
    latentmas_model_name: str = "Qwen/Qwen3-4B"
    latentmas_device: str = "cuda"
    latentmas_prompt_mode: str = "sequential"
    latentmas_latent_steps: int = 10
    latentmas_max_new_tokens: int = 1024
    latentmas_use_vllm: bool = False
    latentmas_max_artifact_chars: int = 20_000
    agent_fabric_mode: str = "native"
    agent_tasks_mode: str = "async"
    agent_mesh_agents: tuple[str, ...] = ()
    agent_mesh_task_timeout_seconds: float = 15.0
    langgraph_enabled: bool = False
    langgraph_checkpointer_url: str | None = None
    langgraph_timeout_seconds: float = 30.0
    mesh_deepagents_model: str = "openai:MiniMax-M2.7"
    mesh_deepagents_timeout_seconds: float = 120.0
    mesh_deepagents_workspace_root: str = str(DEFAULT_DEEPAGENTS_WORKSPACE)
    mesh_deepagents_max_artifact_chars: int = 20_000
    mesh_deepagents_max_output_tokens: int = 1024
    sse_max_connection_seconds: int = 1800
    watch_enabled: bool = False
    watch_interval_seconds: int = 60
    watch_cooldown_seconds: int = 300
    watch_targets: tuple[dict[str, str], ...] = ()
    llm_escalation_enabled: bool = False
    llm_escalation_provider: str = "goose"
    llm_escalation_model: str | None = None
    llm_escalation_timeout_seconds: int = 30
    # OpenAI-compatible LLM observer that reviews every deterministic
    # decision before it executes. Provider-neutral: any URL that speaks
    # ``/v1/chat/completions`` works (OpenAI, Anthropic via shim, vLLM,
    # Ollama, Together, Groq, OpenRouter, ...). Disabled by default; the
    # deterministic engine remains the safety floor when this is off.
    observer_enabled: bool = False
    observer_base_url: str = ""
    observer_api_key: str = ""
    observer_model: str = ""
    observer_timeout_seconds: float = 8.0
    observer_max_tokens: int = 512
    # ``openai`` for /v1/chat/completions (OpenAI, vLLM, Ollama, ...);
    # ``anthropic`` for /v1/messages with x-api-key auth.
    observer_provider: str = "openai"
    # Claude prompt caching knobs used by every Anthropic-native call routed
    # through the Mesh observer client. ``explicit`` marks the stable system
    # prefix; ``automatic`` adds Anthropic's top-level cache_control; ``both``
    # combines them; ``off`` disables cache hints.
    observer_prompt_cache_enabled: bool = True
    observer_prompt_cache_mode: str = "explicit"
    observer_prompt_cache_ttl: str = "5m"
    observer_secondary_provider: str = ""
    observer_secondary_base_url: str = ""
    observer_secondary_api_key: str = ""
    observer_secondary_model: str = ""
    sre_judge_enabled: bool = False
    sre_judge_provider: str = "openai"
    sre_judge_base_url: str = ""
    sre_judge_api_key: str = ""
    sre_judge_model: str = ""
    sre_judge_secondary_provider: str = ""
    sre_judge_secondary_base_url: str = ""
    sre_judge_secondary_api_key: str = ""
    sre_judge_secondary_model: str = ""
    correlation_enabled: bool = True
    correlation_window_seconds: int = 300
    correlation_min_signals: int = 2
    argocd_url: str | None = None
    argocd_token: str | None = None
    argocd_ca_bundle: str | None = None
    argocd_timeout_seconds: int = 30
    trust_ladder_enabled: bool = False
    trust_ladder_min_draft_runs: int = 3
    trust_ladder_min_approve_runs: int = 10
    trust_ladder_min_auto_runs: int = 30
    # OpenTelemetry consumer: Mesh accepts OTLP/HTTP pushes at POST /v1/metrics and can
    # pull Prometheus (or any PromQL-compatible endpoint exposed by an OTel collector)
    # during feedback verification. Disabled by default — the receiver has no auth
    # beyond the optional bearer token, so it's opt-in.
    otel_receiver_enabled: bool = False
    otel_receiver_token: str | None = None
    prometheus_url: str | None = None
    prometheus_query_timeout_seconds: float = 10.0
    feedback_prometheus_enabled: bool = False
    live_feedback_required: bool = False
    feedback_prometheus_latency_query: str = 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="{service}"}[{window}])) by (le)) * 1000'
    feedback_prometheus_error_rate_query: str = 'sum(rate(http_requests_total{service="{service}",status=~"5.."}[{window}])) / clamp_min(sum(rate(http_requests_total{service="{service}"}[{window}])), 1)'
    # Layer 3: LLM-backed decision fallback for OTel signals that don't match
    # any metric-action rule. Opt-in because it adds LLM latency (5-30s) to
    # the decision stage for unknown signals.
    llm_decision_fallback_enabled: bool = False
    llm_decision_fallback_timeout_seconds: float = 30.0
    # Layer 4: learn from operator overrides and surface candidate rules.
    rule_learning_enabled: bool = False
    rule_learning_min_observations: int = 5
    rule_learning_max_age_days: int = 30
    simulation_enabled: bool = False
    simulation_context_allowlist: tuple[str, ...] = ()
    benchmark_export_path: str = str(DEFAULT_BENCHMARK_EXPORT_PATH)
    service_agents_config_path: str | None = None
    agent_reconciliation_enabled: bool = True
    reasoning_bank_enabled: bool = False
    reasoning_bank_distiller: str = "deterministic"
    reasoning_bank_max_strategies: int = 5
    reasoning_bank_scaling_mode: str = "off"
    corpus_memory_enabled: bool = False
    corpus_database_path: str = str(DEFAULT_CORPUS_DATABASE_PATH)
    corpus_memory_projection_limit: int = 5000
    # Bare-metal SSH actuator: blockchain nodes (Solana/Agave, geth, reth,
    # lighthouse) run as systemd services on dedicated hardware, not in k8s.
    # Actuation goes through the SSH adapter with four overlapping safety
    # constraints: ssh_execution_enabled, the host allowlist, the service
    # allowlist, and a hardcoded command allowlist inside the adapter.
    # ALL FOUR must be set to meaningful values before real execution runs.
    ssh_execution_enabled: bool = False
    ssh_command: str = "ssh"
    ssh_identity_file: str | None = None
    ssh_connect_timeout_seconds: int = 10
    ssh_command_timeout_seconds: int = 30
    # ServerAlive tuning: send a keepalive probe every N seconds, declare
    # the connection dead after M missed probes. Default 30s * 3 = 90s to
    # detect a silently-dropped TCP flow — vastly better than the OS-level
    # retransmit timeout (~15 min) that would otherwise apply. These are
    # client-side only and don't require any change on the target node.
    ssh_server_alive_interval_seconds: int = 30
    ssh_server_alive_count_max: int = 3
    ssh_allowed_hosts: tuple[str, ...] = ()
    ssh_allowed_services: tuple[str, ...] = ()
    load_balancer_provider: str = "mock"
    load_balancer_drain_timeout_seconds: int = 60
    load_balancer_max_active_connections: int = 0
    # Node-health ingester targets (Solana RPC + geth/reth JSON-RPC). Each
    # entry is a JSON blob: {"name": "mainnet-07", "kind": "solana",
    # "rpc_url": "http://127.0.0.1:8899", "host": "vault-prod-07",
    # "service": "solana-validator.service"}
    bare_metal_node_targets: tuple[dict[str, str], ...] = ()
    reth_investigation_planner: str = "native"
    reth_investigation_probe_timeout_seconds: float = 5.0
    reth_investigation_budget_seconds: float = 15.0
    reth_investigation_max_probes: int = 6
    vault_mirror_mode: str = "async"

    def __post_init__(self) -> None:
        if not (0 <= self.server_port <= 65535):
            raise ValueError(f"server_port must be 0-65535, got {self.server_port}")
        if self.max_transient_retries < 0:
            raise ValueError(f"max_transient_retries must be >= 0, got {self.max_transient_retries}")
        if self.max_json_body_bytes < 0:
            raise ValueError(f"max_json_body_bytes must be >= 0, got {self.max_json_body_bytes}")
        if self.agent_mesh_task_timeout_seconds <= 0:
            raise ValueError(
                "agent_mesh_task_timeout_seconds must be > 0, "
                f"got {self.agent_mesh_task_timeout_seconds}"
            )
        if self.run_worker_count <= 0:
            raise ValueError(f"run_worker_count must be > 0, got {self.run_worker_count}")
        if self.run_queue_size <= 0:
            raise ValueError(f"run_queue_size must be > 0, got {self.run_queue_size}")
        if self.tenant_active_run_quota <= 0:
            raise ValueError(f"tenant_active_run_quota must be > 0, got {self.tenant_active_run_quota}")
        if self.auth_mode not in {"proxy_header", "app_session"}:
            raise ValueError("auth_mode must be proxy_header or app_session")
        if self.captcha_provider not in {"disabled", "hcaptcha", "recaptcha", "turnstile"}:
            raise ValueError("captcha_provider must be disabled, hcaptcha, recaptcha, or turnstile")
        if self.auth_mode == "app_session":
            if not self.operator_identity_path:
                raise ValueError("operator_identity_path is required for app_session auth")
            if self.signup_enabled and self.password_auth_enabled:
                captcha_configured = self.captcha_provider != "disabled" and bool(self.captcha_site_key and self.captcha_secret_key)
                if self.environment != "local" and not captcha_configured:
                    raise ValueError("captcha must be configured for app_session signup outside local")
        if self.watch_interval_seconds < 10:
            raise ValueError(f"watch_interval_seconds must be >= 10, got {self.watch_interval_seconds}")
        if self.reasoning_bank_max_strategies < 1:
            raise ValueError(
                "reasoning_bank_max_strategies must be >= 1, "
                f"got {self.reasoning_bank_max_strategies}"
            )
        if self.reasoning_bank_scaling_mode not in {"off", "sequential", "parallel"}:
            self.reasoning_bank_scaling_mode = "off"
        if self.reasoning_bank_distiller != "deterministic":
            self.reasoning_bank_distiller = "deterministic"
        if self.corpus_memory_projection_limit < 1:
            raise ValueError(
                "corpus_memory_projection_limit must be >= 1, "
                f"got {self.corpus_memory_projection_limit}"
            )
        if self.research_directory == str(DEFAULT_RESEARCH_DIRECTORY):
            self.research_directory = str(Path(self.state_directory) / "research")
        if self.corpus_database_path == str(DEFAULT_CORPUS_DATABASE_PATH):
            self.corpus_database_path = str(Path(self.state_directory) / "corpus" / "incident_corpus.sqlite")
        if self.reth_investigation_planner not in {"native", "llm"}:
            self.reth_investigation_planner = "native"
        if self.reth_investigation_probe_timeout_seconds <= 0:
            raise ValueError("reth_investigation_probe_timeout_seconds must be > 0")
        if self.reth_investigation_budget_seconds <= 0:
            raise ValueError("reth_investigation_budget_seconds must be > 0")
        if self.reth_investigation_max_probes < 1:
            raise ValueError("reth_investigation_max_probes must be >= 1")
        self.readiness_profile = _normalize_readiness_profile(self.readiness_profile, self.environment)
        self.memory_graph_backend = _normalize_memory_graph_backend(self.memory_graph_backend)
        if self.helix_port <= 0:
            raise ValueError(f"helix_port must be > 0, got {self.helix_port}")
        self.helix_query_namespace = _normalize_helix_query_namespace(self.helix_query_namespace)
        if self.zaxy_timeout_seconds <= 0:
            raise ValueError(f"zaxy_timeout_seconds must be > 0, got {self.zaxy_timeout_seconds}")
        if self.langgraph_timeout_seconds <= 0:
            raise ValueError(f"langgraph_timeout_seconds must be > 0, got {self.langgraph_timeout_seconds}")
        if self.darkharness_packet_persistence_mode != "ephemeral":
            raise ValueError("darkharness_packet_persistence_mode only supports ephemeral in this phase")
        if self.postgres_pool_min_size < 1:
            raise ValueError(
                f"postgres_pool_min_size must be >= 1, got {self.postgres_pool_min_size}"
            )
        if self.postgres_pool_max_size < self.postgres_pool_min_size:
            raise ValueError(
                "postgres_pool_max_size must be >= postgres_pool_min_size, got "
                f"max={self.postgres_pool_max_size} min={self.postgres_pool_min_size}"
            )
        if self.postgres_pool_max_idle_seconds <= 0:
            raise ValueError(
                f"postgres_pool_max_idle_seconds must be > 0, got {self.postgres_pool_max_idle_seconds}"
            )
        if self.postgres_pool_connect_timeout_seconds <= 0:
            raise ValueError(
                "postgres_pool_connect_timeout_seconds must be > 0, got "
                f"{self.postgres_pool_connect_timeout_seconds}"
            )
        self.observer_prompt_cache_mode = _normalize_prompt_cache_mode(
            self.observer_prompt_cache_mode
        )
        self.observer_prompt_cache_ttl = _normalize_prompt_cache_ttl(
            self.observer_prompt_cache_ttl
        )

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        state_directory = _resolve_relative_path(
            os.getenv("MESH_STATE_DIRECTORY", str(DEFAULT_STATE_DIRECTORY))
        )
        raw_research = os.getenv("MESH_RESEARCH_DIRECTORY")
        research_directory = (
            _resolve_relative_path(raw_research) if raw_research else str(Path(state_directory) / "research")
        )
        return cls(
            environment=os.getenv("MESH_ENVIRONMENT", "local"),
            evaluation_mode=os.getenv("MESH_EVALUATION_MODE", "auto"),
            orchestration_mode=os.getenv("MESH_ORCHESTRATION_MODE", "auto"),
            feature_flag_credentials_available=os.getenv("MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE", "true").lower() == "true",
            incident_credentials_available=os.getenv("MESH_INCIDENT_CREDENTIALS_AVAILABLE", "true").lower() == "true",
            audit_logging_available=os.getenv("MESH_AUDIT_LOGGING_AVAILABLE", "true").lower() == "true",
            max_transient_retries=int(os.getenv("MESH_MAX_TRANSIENT_RETRIES", "2")),
            max_retry_window_seconds=int(os.getenv("MESH_MAX_RETRY_WINDOW_SECONDS", "60")),
            goose_timeout_seconds=int(os.getenv("MESH_GOOSE_TIMEOUT_SECONDS", "180")),
            state_backend=_normalize_state_backend(os.getenv("MESH_STATE_BACKEND", "file")),
            database_url=os.getenv("MESH_DATABASE_URL") or None,
            memory_graph_backend=_normalize_memory_graph_backend(os.getenv("MESH_MEMORY_GRAPH_BACKEND", "local")),
            helix_api_endpoint=os.getenv("MESH_HELIX_API_ENDPOINT") or None,
            helix_port=int(os.getenv("MESH_HELIX_PORT", "6969")),
            helix_query_namespace=os.getenv("MESH_HELIX_QUERY_NAMESPACE", "mesh"),
            zaxy_enabled=_env_bool("MESH_ZAXY_ENABLED", default=False),
            zaxy_namespace=os.getenv("MESH_ZAXY_NAMESPACE", "mesh"),
            zaxy_tenant_id=os.getenv("MESH_ZAXY_TENANT_ID", "local"),
            zaxy_project_id=os.getenv("MESH_ZAXY_PROJECT_ID", "mesh"),
            zaxy_eventloom_url=os.getenv("MESH_ZAXY_EVENTLOOM_URL") or None,
            zaxy_eventloom_outbox_path=(
                _env_path_anchored_to_repo(os.getenv("MESH_ZAXY_EVENTLOOM_OUTBOX_PATH"), default="")
                if os.getenv("MESH_ZAXY_EVENTLOOM_OUTBOX_PATH")
                else None
            ),
            zaxy_mcp_url=os.getenv("MESH_ZAXY_MCP_URL") or None,
            zaxy_neo4j_projection_enabled=_env_bool("MESH_ZAXY_NEO4J_PROJECTION_ENABLED", default=False),
            zaxy_packet_capture_enabled=_env_bool("MESH_ZAXY_PACKET_CAPTURE_ENABLED", default=False),
            zaxy_timeout_seconds=max(0.1, float(os.getenv("MESH_ZAXY_TIMEOUT_SECONDS", "2"))),
            postgres_pool_min_size=max(1, int(os.getenv("MESH_POSTGRES_POOL_MIN_SIZE", "1"))),
            postgres_pool_max_size=max(1, int(os.getenv("MESH_POSTGRES_POOL_MAX_SIZE", "10"))),
            postgres_pool_max_idle_seconds=max(1.0, float(os.getenv("MESH_POSTGRES_POOL_MAX_IDLE_SECONDS", "600"))),
            postgres_pool_connect_timeout_seconds=max(0.1, float(os.getenv("MESH_POSTGRES_POOL_CONNECT_TIMEOUT_SECONDS", "10"))),
            state_directory=state_directory,
            research_directory=research_directory,
            server_host=os.getenv("MESH_SERVER_HOST", "127.0.0.1"),
            server_port=int(os.getenv("MESH_SERVER_PORT", "8787")),
            web_asset_path=os.getenv("MESH_WEB_ASSET_PATH", str(DEFAULT_WEB_ASSET_PATH)),
            vault_path=os.getenv("MESH_VAULT_PATH", str(DEFAULT_VAULT_PATH)),
            integrations_config_path=os.getenv(
                "MESH_INTEGRATIONS_CONFIG_PATH",
                str(DEFAULT_INTEGRATIONS_CONFIG_PATH),
            ),
            ownership_registry_path=_env_path_anchored_to_repo(
                os.getenv("MESH_OWNERSHIP_REGISTRY_PATH"),
                default=str(DEFAULT_OWNERSHIP_REGISTRY_PATH),
            ),
            connector_certification_registry_path=_env_path_anchored_to_repo(
                os.getenv("MESH_CONNECTOR_CERTIFICATION_REGISTRY_PATH"),
                default=str(DEFAULT_CONNECTOR_CERTIFICATION_REGISTRY_PATH),
            ),
            policy_lifecycle_manifest_path=_env_path_anchored_to_repo(
                os.getenv("MESH_POLICY_LIFECYCLE_MANIFEST_PATH"),
                default=str(DEFAULT_POLICY_LIFECYCLE_MANIFEST_PATH),
            ),
            orchestration_topology_profile_path=_env_path_anchored_to_repo(
                os.getenv("MESH_ORCHESTRATION_TOPOLOGY_PROFILE_PATH"),
                default=str(DEFAULT_ORCHESTRATION_TOPOLOGY_PROFILE_PATH),
            ),
            failure_mode_library_path=_env_path_anchored_to_repo(
                os.getenv("MESH_FAILURE_MODE_LIBRARY_PATH"),
                default=str(DEFAULT_FAILURE_MODE_LIBRARY_PATH),
            ),
            threat_model_register_path=_env_path_anchored_to_repo(
                os.getenv("MESH_THREAT_MODEL_REGISTER_PATH"),
                default=str(DEFAULT_THREAT_MODEL_REGISTER_PATH),
            ),
            data_classification_policy_path=_env_path_anchored_to_repo(
                os.getenv("MESH_DATA_CLASSIFICATION_POLICY_PATH"),
                default=str(DEFAULT_DATA_CLASSIFICATION_POLICY_PATH),
            ),
            agentic_operator_source_provenance_path=_env_path_anchored_to_repo(
                os.getenv("MESH_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH"),
                default=str(DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH),
            ),
            deployment_compatibility_registry_path=_env_path_anchored_to_repo(
                os.getenv("MESH_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH"),
                default=str(DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH),
            ),
            procurement_security_package_path=_env_path_anchored_to_repo(
                os.getenv("MESH_PROCUREMENT_SECURITY_PACKAGE_PATH"),
                default=str(DEFAULT_PROCUREMENT_SECURITY_PACKAGE_PATH),
            ),
            public_proof_package_path=_env_path_anchored_to_repo(
                os.getenv("MESH_PUBLIC_PROOF_PACKAGE_PATH"),
                default=str(DEFAULT_PUBLIC_PROOF_PACKAGE_PATH),
            ),
            release_provenance_path=_env_path_anchored_to_repo(
                os.getenv("MESH_RELEASE_PROVENANCE_PATH"),
                default=str(DEFAULT_RELEASE_PROVENANCE_PATH),
            ),
            authenticated_ingress_proof_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_AUTHENTICATED_INGRESS_PROOF_PATH"),
                    default=str(DEFAULT_AUTHENTICATED_INGRESS_PROOF_PATH),
                )
                if os.getenv("MESH_AUTHENTICATED_INGRESS_PROOF_PATH")
                else None
            ),
            design_partner_packet_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_DESIGN_PARTNER_PACKET_PATH"),
                    default=str(DEFAULT_DESIGN_PARTNER_PACKET_PATH),
                )
                if os.getenv("MESH_DESIGN_PARTNER_PACKET_PATH")
                else None
            ),
            audit_sink_proof_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_AUDIT_SINK_PROOF_PATH"),
                    default=str(DEFAULT_AUDIT_SINK_PROOF_PATH),
                )
                if os.getenv("MESH_AUDIT_SINK_PROOF_PATH")
                else None
            ),
            audit_sink_certification_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_AUDIT_SINK_CERTIFICATION_PATH"),
                    default=str(DEFAULT_AUDIT_SINK_CERTIFICATION_PATH),
                )
                if os.getenv("MESH_AUDIT_SINK_CERTIFICATION_PATH")
                else None
            ),
            backup_restore_rehearsal_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_BACKUP_RESTORE_REHEARSAL_PATH"),
                    default=str(DEFAULT_BACKUP_RESTORE_REHEARSAL_PATH),
                )
                if os.getenv("MESH_BACKUP_RESTORE_REHEARSAL_PATH")
                else None
            ),
            load_concurrency_rehearsal_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_LOAD_CONCURRENCY_REHEARSAL_PATH"),
                    default=str(DEFAULT_LOAD_CONCURRENCY_REHEARSAL_PATH),
                )
                if os.getenv("MESH_LOAD_CONCURRENCY_REHEARSAL_PATH")
                else None
            ),
            orchestration_topology_drill_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_ORCHESTRATION_TOPOLOGY_DRILL_PATH"),
                    default=str(DEFAULT_ORCHESTRATION_TOPOLOGY_DRILL_PATH),
                )
                if os.getenv("MESH_ORCHESTRATION_TOPOLOGY_DRILL_PATH")
                else None
            ),
            feature_flag_provider_proof_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_FEATURE_FLAG_PROVIDER_PROOF_PATH"),
                    default=str(DEFAULT_FEATURE_FLAG_PROVIDER_PROOF_PATH),
                )
                if os.getenv("MESH_FEATURE_FLAG_PROVIDER_PROOF_PATH")
                else None
            ),
            incident_provider_proof_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_INCIDENT_PROVIDER_PROOF_PATH"),
                    default=str(DEFAULT_INCIDENT_PROVIDER_PROOF_PATH),
                )
                if os.getenv("MESH_INCIDENT_PROVIDER_PROOF_PATH")
                else None
            ),
            on_call_drill_path=(
                _env_path_anchored_to_repo(
                    os.getenv("MESH_ON_CALL_DRILL_PATH"),
                    default=str(DEFAULT_ON_CALL_DRILL_PATH),
                )
                if os.getenv("MESH_ON_CALL_DRILL_PATH")
                else None
            ),
            policy_signing_key=_read_env_or_file(
                os.getenv("MESH_POLICY_SIGNING_KEY"),
                os.getenv("MESH_POLICY_SIGNING_KEY_PATH"),
            ),
            policy_signing_key_id=os.getenv("MESH_POLICY_SIGNING_KEY_ID", "policy-lifecycle-hmac"),
            darkharness_registry_path=(
                _env_path_anchored_to_repo(os.getenv("MESH_DARKHARNESS_REGISTRY_PATH"), default="")
                if os.getenv("MESH_DARKHARNESS_REGISTRY_PATH")
                else None
            ),
            darkharness_packet_persistence_mode=os.getenv(
                "MESH_DARKHARNESS_PACKET_PERSISTENCE_MODE",
                "ephemeral",
            ),
            darkharness_signing_key=os.getenv("MESH_DARKHARNESS_SIGNING_KEY") or None,
            darkharness_signing_key_id=os.getenv("MESH_DARKHARNESS_SIGNING_KEY_ID", "darkharness-local-hmac"),
            darkharness_classical_signing_key_pem=_read_env_or_file(
                os.getenv("MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_PEM"),
                os.getenv("MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_PATH"),
            ),
            darkharness_classical_signing_key_id=os.getenv(
                "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_ID",
                "darkharness-ed25519",
            ),
            mesh_brain_artifact_uri_prefix=os.getenv("MESH_BRAIN_ARTIFACT_URI_PREFIX") or None,
            mesh_brain_artifact_registry_path=(
                _env_path_anchored_to_repo(os.getenv("MESH_BRAIN_ARTIFACT_REGISTRY_PATH"), default="")
                if os.getenv("MESH_BRAIN_ARTIFACT_REGISTRY_PATH")
                else None
            ),
            mesh_brain_artifact_upload_proof_path=(
                _env_path_anchored_to_repo(os.getenv("MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH"), default="")
                if os.getenv("MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH")
                else None
            ),
            mesh_brain_serving_base_url=os.getenv("MESH_BRAIN_SERVING_BASE_URL") or None,
            mesh_brain_serving_model=os.getenv("MESH_BRAIN_SERVING_MODEL") or None,
            default_steering_mode=os.getenv("MESH_DEFAULT_STEERING_MODE", "approval_gate"),
            default_operator_pause_point=os.getenv("MESH_DEFAULT_OPERATOR_PAUSE_POINT", "evaluation_ready"),
            readiness_profile=_normalize_readiness_profile(
                os.getenv("MESH_READINESS_PROFILE", ""),
                os.getenv("MESH_ENVIRONMENT", "local"),
            ),
            operator_identity_required=_env_bool("MESH_OPERATOR_IDENTITY_REQUIRED", default=False),
            operator_header_name=os.getenv("MESH_OPERATOR_HEADER", "X-Mesh-Operator"),
            operator_roles_header_name=os.getenv("MESH_OPERATOR_ROLES_HEADER", "X-Mesh-Roles"),
            auth_mode=os.getenv("MESH_AUTH_MODE", "proxy_header"),
            operator_identity_path=_env_path_anchored_to_repo(
                os.getenv("MESH_OPERATOR_IDENTITY_PATH"),
                default=str(Path(state_directory) / "operator-identity.json"),
            ),
            session_cookie_name=os.getenv("MESH_SESSION_COOKIE_NAME", "mesh_session"),
            auth_allowed_origins=_csv_env("MESH_AUTH_ALLOWED_ORIGINS"),
            auth_product_redirect_url=os.getenv("MESH_AUTH_PRODUCT_REDIRECT_URL", ""),
            signup_enabled=_env_bool("MESH_SIGNUP_ENABLED", default=True),
            password_auth_enabled=_env_bool("MESH_PASSWORD_AUTH_ENABLED", default=True),
            auth_invite_allowlist=_csv_env("MESH_AUTH_INVITE_ALLOWLIST"),
            auth_invite_codes=_csv_env("MESH_AUTH_INVITE_CODES"),
            captcha_provider=os.getenv("MESH_CAPTCHA_PROVIDER", "disabled").lower(),
            captcha_site_key=os.getenv("MESH_CAPTCHA_SITE_KEY", ""),
            captcha_secret_key=os.getenv("MESH_CAPTCHA_SECRET_KEY", ""),
            captcha_dev_bypass_enabled=_env_bool("MESH_CAPTCHA_DEV_BYPASS", default=False),
            google_oauth_client_id=os.getenv("MESH_GOOGLE_OAUTH_CLIENT_ID", ""),
            google_oauth_client_secret=os.getenv("MESH_GOOGLE_OAUTH_CLIENT_SECRET", ""),
            google_oauth_redirect_url=os.getenv("MESH_GOOGLE_OAUTH_REDIRECT_URL", ""),
            github_oauth_client_id=os.getenv("MESH_GITHUB_OAUTH_CLIENT_ID", ""),
            github_oauth_client_secret=os.getenv("MESH_GITHUB_OAUTH_CLIENT_SECRET", ""),
            github_oauth_redirect_url=os.getenv("MESH_GITHUB_OAUTH_REDIRECT_URL", ""),
            force_approval_gate=_env_bool("MESH_FORCE_APPROVAL_GATE", default=False),
            run_worker_count=int(os.getenv("MESH_RUN_WORKER_COUNT", "4")),
            run_queue_size=int(os.getenv("MESH_RUN_QUEUE_SIZE", "100")),
            tenant_active_run_quota=int(os.getenv("MESH_TENANT_ACTIVE_RUN_QUOTA", "4")),
            promptfoo_command=os.getenv("MESH_PROMPTFOO_COMMAND") or None,
            hermes_command=os.getenv("MESH_HERMES_COMMAND") or None,
            hermes_command_timeout_seconds=int(os.getenv("MESH_HERMES_COMMAND_TIMEOUT_SECONDS", "180")),
            goose_command=os.getenv("MESH_GOOSE_COMMAND") or None,
            goose_command_timeout_seconds=int(
                os.getenv(
                    "MESH_GOOSE_COMMAND_TIMEOUT_SECONDS",
                    os.getenv("MESH_GOOSE_BRIDGE_TIMEOUT_SECONDS", "180"),
                )
            ),
            evo_command=os.getenv("MESH_EVO_COMMAND") or None,
            evo_command_timeout_seconds=int(os.getenv("MESH_EVO_COMMAND_TIMEOUT_SECONDS", "60")),
            kubernetes_live_execution_enabled=os.getenv("MESH_KUBERNETES_LIVE_EXECUTION_ENABLED", "").lower()
            in ("1", "true", "yes"),
            kubectl_command=os.getenv("MESH_KUBECTL_COMMAND", "kubectl"),
            kubernetes_rollout_timeout_seconds=int(os.getenv("MESH_KUBERNETES_ROLLOUT_TIMEOUT_SECONDS", "120")),
            kubernetes_allowed_contexts=_csv_env("MESH_KUBERNETES_ALLOWED_CONTEXTS"),
            kubernetes_allowed_namespaces=_csv_env("MESH_KUBERNETES_ALLOWED_NAMESPACES"),
            gitnexus_sidecar_url=os.getenv("MESH_GITNEXUS_SIDECAR_URL") or None,
            gitnexus_sidecar_command=os.getenv("MESH_GITNEXUS_SIDECAR_COMMAND") or None,
            gitnexus_disable_autostart=os.getenv("MESH_GITNEXUS_DISABLE_AUTOSTART", "").lower()
            in ("1", "true", "yes"),
            max_json_body_bytes=int(os.getenv("MESH_MAX_JSON_BODY_BYTES", "1048576")),
            run_export_max_bytes=int(os.getenv("MESH_RUN_EXPORT_MAX_BYTES", "5242880")),
            run_export_retention_days=int(os.getenv("MESH_RUN_EXPORT_RETENTION_DAYS", "30")),
            run_export_retention_reviewed=_env_bool("MESH_RUN_EXPORT_RETENTION_REVIEWED", default=False),
            access_log_enabled=os.getenv("MESH_ACCESS_LOG", "").lower() in ("1", "true", "yes"),
            security_headers_enabled=os.getenv("MESH_SECURITY_HEADERS", "true").lower()
            not in ("0", "false", "no"),
            vault_ai_postprocess_enabled=os.getenv("MESH_VAULT_AI_POSTPROCESS_ENABLED", "").lower()
            in ("1", "true", "yes"),
            build_version=os.getenv("MESH_BUILD_VERSION") or os.getenv("MESH_IMAGE_TAG") or "dev",
            build_commit=os.getenv("MESH_BUILD_COMMIT") or os.getenv("GIT_COMMIT") or "unknown",
            build_image_digest=os.getenv("MESH_BUILD_IMAGE_DIGEST")
            or os.getenv("MESH_IMAGE_DIGEST")
            or os.getenv("MESH_STACK_IMAGE_DIGEST")
            or "",
            latentmas_enabled=os.getenv("MESH_LATENTMAS_ENABLED", "").lower() in ("1", "true", "yes"),
            latentmas_url=os.getenv("MESH_LATENTMAS_URL") or None,
            latentmas_timeout_seconds=float(os.getenv("MESH_LATENTMAS_TIMEOUT_SECONDS", "60")),
            latentmas_model_name=os.getenv("MESH_LATENTMAS_MODEL_NAME", "Qwen/Qwen3-4B"),
            latentmas_device=os.getenv("MESH_LATENTMAS_DEVICE", "cuda"),
            latentmas_prompt_mode=os.getenv("MESH_LATENTMAS_PROMPT_MODE", "sequential"),
            latentmas_latent_steps=int(os.getenv("MESH_LATENTMAS_LATENT_STEPS", "10")),
            latentmas_max_new_tokens=int(os.getenv("MESH_LATENTMAS_MAX_NEW_TOKENS", "1024")),
            latentmas_use_vllm=os.getenv("MESH_LATENTMAS_USE_VLLM", "").lower() in ("1", "true", "yes"),
            latentmas_max_artifact_chars=int(os.getenv("MESH_LATENTMAS_MAX_ARTIFACT_CHARS", "20000")),
            agent_fabric_mode=_normalize_agent_fabric_mode(os.getenv("MESH_AGENT_FABRIC_MODE", "native")),
            agent_tasks_mode=_normalize_agent_tasks_mode(os.getenv("MESH_AGENT_TASKS_MODE", "async")),
            agent_mesh_agents=_csv_env("MESH_AGENT_MESH_AGENTS"),
            agent_mesh_task_timeout_seconds=float(os.getenv("MESH_AGENT_TASK_TIMEOUT_SECONDS", "15")),
            langgraph_enabled=_env_bool("MESH_LANGGRAPH_ENABLED", default=False),
            langgraph_checkpointer_url=os.getenv("MESH_LANGGRAPH_CHECKPOINTER_URL") or None,
            langgraph_timeout_seconds=max(0.1, float(os.getenv("MESH_LANGGRAPH_TIMEOUT_SECONDS", "30"))),
            mesh_deepagents_model=os.getenv("MESH_DEEPAGENTS_MODEL", "openai:MiniMax-M2.7"),
            mesh_deepagents_timeout_seconds=float(os.getenv("MESH_DEEPAGENTS_TIMEOUT_SECONDS", "120")),
            mesh_deepagents_workspace_root=_env_path_anchored_to_repo(
                os.getenv("MESH_DEEPAGENTS_WORKSPACE_ROOT"),
                default=str(DEFAULT_DEEPAGENTS_WORKSPACE),
            ),
            mesh_deepagents_max_artifact_chars=int(os.getenv("MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS", "20000")),
            mesh_deepagents_max_output_tokens=int(os.getenv("MESH_DEEPAGENTS_MAX_OUTPUT_TOKENS", "1024")),
            watch_enabled=os.getenv("MESH_WATCH_ENABLED", "").lower() in ("1", "true", "yes"),
            watch_interval_seconds=int(os.getenv("MESH_WATCH_INTERVAL_SECONDS", "60")),
            watch_cooldown_seconds=int(os.getenv("MESH_WATCH_COOLDOWN_SECONDS", "300")),
            watch_targets=_parse_watch_targets(os.getenv("MESH_WATCH_TARGETS")),
            llm_escalation_enabled=os.getenv("MESH_LLM_ESCALATION_ENABLED", "").lower()
            in ("1", "true", "yes"),
            llm_escalation_provider=os.getenv("MESH_LLM_ESCALATION_PROVIDER", "goose"),
            llm_escalation_model=os.getenv("MESH_LLM_ESCALATION_MODEL") or None,
            llm_escalation_timeout_seconds=int(os.getenv("MESH_LLM_ESCALATION_TIMEOUT_SECONDS", "30")),
            correlation_enabled=os.getenv("MESH_CORRELATION_ENABLED", "true").lower()
            in ("1", "true", "yes"),
            correlation_window_seconds=int(os.getenv("MESH_CORRELATION_WINDOW_SECONDS", "300")),
            correlation_min_signals=int(os.getenv("MESH_CORRELATION_MIN_SIGNALS", "2")),
            argocd_url=os.getenv("MESH_ARGOCD_URL") or None,
            argocd_token=os.getenv("MESH_ARGOCD_TOKEN") or None,
            argocd_ca_bundle=os.getenv("MESH_ARGOCD_CA_BUNDLE") or None,
            argocd_timeout_seconds=int(os.getenv("MESH_ARGOCD_TIMEOUT_SECONDS", "30")),
            trust_ladder_enabled=os.getenv("MESH_TRUST_LADDER_ENABLED", "").lower() in ("1", "true", "yes"),
            trust_ladder_min_draft_runs=int(os.getenv("MESH_TRUST_LADDER_MIN_DRAFT_RUNS", "3")),
            trust_ladder_min_approve_runs=int(os.getenv("MESH_TRUST_LADDER_MIN_APPROVE_RUNS", "10")),
            trust_ladder_min_auto_runs=int(os.getenv("MESH_TRUST_LADDER_MIN_AUTO_RUNS", "30")),
            otel_receiver_enabled=os.getenv("MESH_OTEL_RECEIVER_ENABLED", "").lower()
            in ("1", "true", "yes"),
            otel_receiver_token=os.getenv("MESH_OTEL_RECEIVER_TOKEN") or None,
            prometheus_url=os.getenv("MESH_PROMETHEUS_URL") or None,
            prometheus_query_timeout_seconds=float(os.getenv("MESH_PROMETHEUS_QUERY_TIMEOUT_SECONDS", "10")),
            feedback_prometheus_enabled=os.getenv("MESH_FEEDBACK_PROMETHEUS_ENABLED", "").lower()
            in ("1", "true", "yes"),
            live_feedback_required=_env_bool("MESH_LIVE_FEEDBACK_REQUIRED", default=False),
            feedback_prometheus_latency_query=os.getenv(
                "MESH_FEEDBACK_PROMETHEUS_LATENCY_QUERY",
                'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="{service}"}[{window}])) by (le)) * 1000',
            ),
            feedback_prometheus_error_rate_query=os.getenv(
                "MESH_FEEDBACK_PROMETHEUS_ERROR_RATE_QUERY",
                'sum(rate(http_requests_total{service="{service}",status=~"5.."}[{window}])) / clamp_min(sum(rate(http_requests_total{service="{service}"}[{window}])), 1)',
            ),
            llm_decision_fallback_enabled=os.getenv("MESH_LLM_DECISION_FALLBACK_ENABLED", "").lower()
            in ("1", "true", "yes"),
            llm_decision_fallback_timeout_seconds=float(os.getenv("MESH_LLM_DECISION_FALLBACK_TIMEOUT_SECONDS", "30")),
            rule_learning_enabled=os.getenv("MESH_RULE_LEARNING_ENABLED", "").lower() in ("1", "true", "yes"),
            rule_learning_min_observations=int(os.getenv("MESH_RULE_LEARNING_MIN_OBSERVATIONS", "5")),
            rule_learning_max_age_days=int(os.getenv("MESH_RULE_LEARNING_MAX_AGE_DAYS", "30")),
            simulation_enabled=os.getenv("MESH_SIMULATION_ENABLED", "").lower() in ("1", "true", "yes"),
            simulation_context_allowlist=_csv_env("MESH_SIMULATION_CONTEXT_ALLOWLIST"),
            benchmark_export_path=_env_path_anchored_to_repo(
                os.getenv("MESH_BENCHMARK_EXPORT_PATH"),
                default=str(DEFAULT_BENCHMARK_EXPORT_PATH),
            ),
            service_agents_config_path=(
                _env_path_anchored_to_repo(os.getenv("MESH_SERVICE_AGENTS_CONFIG_PATH"), default="")
                if os.getenv("MESH_SERVICE_AGENTS_CONFIG_PATH")
                else None
            ),
            agent_reconciliation_enabled=os.getenv("MESH_AGENT_RECONCILIATION_ENABLED", "true").lower()
            not in ("0", "false", "no"),
            reasoning_bank_enabled=os.getenv("MESH_REASONING_BANK_ENABLED", "").lower() in ("1", "true", "yes"),
            reasoning_bank_distiller=os.getenv("MESH_REASONING_BANK_DISTILLER", "deterministic"),
            reasoning_bank_max_strategies=int(os.getenv("MESH_REASONING_BANK_MAX_STRATEGIES", "5")),
            reasoning_bank_scaling_mode=os.getenv("MESH_REASONING_BANK_SCALING_MODE", "off"),
            corpus_memory_enabled=os.getenv("MESH_CORPUS_MEMORY_ENABLED", "").lower() in ("1", "true", "yes"),
            corpus_database_path=_env_path_anchored_to_repo(
                os.getenv("MESH_CORPUS_DATABASE_PATH"),
                default=str(Path(state_directory) / "corpus" / "incident_corpus.sqlite"),
            ),
            corpus_memory_projection_limit=int(os.getenv("MESH_CORPUS_MEMORY_PROJECTION_LIMIT", "5000")),
            ssh_execution_enabled=os.getenv("MESH_SSH_EXECUTION_ENABLED", "").lower() in ("1", "true", "yes"),
            ssh_command=os.getenv("MESH_SSH_COMMAND", "ssh"),
            ssh_identity_file=os.getenv("MESH_SSH_IDENTITY_FILE") or None,
            ssh_connect_timeout_seconds=int(os.getenv("MESH_SSH_CONNECT_TIMEOUT_SECONDS", "10")),
            ssh_command_timeout_seconds=int(os.getenv("MESH_SSH_COMMAND_TIMEOUT_SECONDS", "30")),
            ssh_server_alive_interval_seconds=int(os.getenv("MESH_SSH_SERVER_ALIVE_INTERVAL_SECONDS", "30")),
            ssh_server_alive_count_max=int(os.getenv("MESH_SSH_SERVER_ALIVE_COUNT_MAX", "3")),
            ssh_allowed_hosts=_csv_env("MESH_SSH_ALLOWED_HOSTS"),
            ssh_allowed_services=_csv_env("MESH_SSH_ALLOWED_SERVICES"),
            load_balancer_provider=os.getenv("MESH_LOAD_BALANCER_PROVIDER", "mock").lower(),
            load_balancer_drain_timeout_seconds=int(os.getenv("MESH_LOAD_BALANCER_DRAIN_TIMEOUT_SECONDS", "60")),
            load_balancer_max_active_connections=int(os.getenv("MESH_LOAD_BALANCER_MAX_ACTIVE_CONNECTIONS", "0")),
            bare_metal_node_targets=_parse_bare_metal_targets(os.getenv("MESH_BARE_METAL_NODE_TARGETS")),
            reth_investigation_planner=os.getenv("MESH_RETH_INVESTIGATION_PLANNER", "native").lower(),
            reth_investigation_probe_timeout_seconds=float(
                os.getenv("MESH_RETH_PROBE_TIMEOUT_SECONDS", "5.0")
            ),
            reth_investigation_budget_seconds=float(
                os.getenv("MESH_RETH_INVESTIGATION_BUDGET_SECONDS", "15.0")
            ),
            reth_investigation_max_probes=int(os.getenv("MESH_RETH_INVESTIGATION_MAX_PROBES", "6")),
            vault_mirror_mode=_normalize_vault_mirror_mode(os.getenv("MESH_VAULT_MIRROR_MODE", "async")),
            observer_enabled=os.getenv("MESH_OBSERVER_ENABLED", "").lower() in ("1", "true", "yes"),
            observer_base_url=os.getenv("MESH_OBSERVER_BASE_URL", ""),
            observer_api_key=os.getenv("MESH_OBSERVER_API_KEY", ""),
            observer_model=os.getenv("MESH_OBSERVER_MODEL", ""),
            observer_timeout_seconds=float(os.getenv("MESH_OBSERVER_TIMEOUT_SECONDS", "8.0")),
            observer_max_tokens=int(os.getenv("MESH_OBSERVER_MAX_TOKENS", "512")),
            observer_provider=os.getenv("MESH_OBSERVER_PROVIDER", "openai").lower(),
            observer_prompt_cache_enabled=_env_bool("MESH_OBSERVER_PROMPT_CACHE_ENABLED", default=True),
            observer_prompt_cache_mode=os.getenv("MESH_OBSERVER_PROMPT_CACHE_MODE", "explicit"),
            observer_prompt_cache_ttl=os.getenv("MESH_OBSERVER_PROMPT_CACHE_TTL", "5m"),
            observer_secondary_provider=os.getenv("MESH_OBSERVER_SECONDARY_PROVIDER", "").lower(),
            observer_secondary_base_url=os.getenv("MESH_OBSERVER_SECONDARY_BASE_URL", ""),
            observer_secondary_api_key=os.getenv("MESH_OBSERVER_SECONDARY_API_KEY", ""),
            observer_secondary_model=os.getenv("MESH_OBSERVER_SECONDARY_MODEL", ""),
            sre_judge_enabled=os.getenv("MESH_SRE_JUDGE_ENABLED", "").lower() in ("1", "true", "yes"),
            sre_judge_provider=os.getenv("MESH_SRE_JUDGE_PROVIDER", "openai").lower(),
            sre_judge_base_url=os.getenv("MESH_SRE_JUDGE_BASE_URL", ""),
            sre_judge_api_key=os.getenv("MESH_SRE_JUDGE_API_KEY", ""),
            sre_judge_model=os.getenv("MESH_SRE_JUDGE_MODEL", ""),
            sre_judge_secondary_provider=os.getenv("MESH_SRE_JUDGE_SECONDARY_PROVIDER", "").lower(),
            sre_judge_secondary_base_url=os.getenv("MESH_SRE_JUDGE_SECONDARY_BASE_URL", ""),
            sre_judge_secondary_api_key=os.getenv("MESH_SRE_JUDGE_SECONDARY_API_KEY", ""),
            sre_judge_secondary_model=os.getenv("MESH_SRE_JUDGE_SECONDARY_MODEL", ""),
        )


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_bare_metal_targets(raw: str | None) -> tuple[dict[str, str], ...]:
    """Parse MESH_BARE_METAL_NODE_TARGETS as a JSON array of node descriptors.

    Each descriptor has at minimum ``name``, ``kind`` (``solana`` /
    ``geth`` / ``reth``), ``rpc_url``, ``host``, and ``service``. We don't
    deep-validate here — the ingester does that on first use and surfaces
    a readable error if a field is wrong. Letting a typo surface at ingest
    time (with full context) beats failing RuntimeConfig construction with
    a stack trace that doesn't mention the offending entry.
    """
    if not raw:
        return ()
    try:
        targets = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ()
    if not isinstance(targets, list):
        return ()
    return tuple(
        target for target in targets
        if isinstance(target, dict) and all(k in target for k in ("name", "kind", "host"))
    )


def _normalize_agent_fabric_mode(raw: str) -> str:
    mode = (raw or "native").strip().lower()
    return mode if mode in ("native", "deepagents", "langgraph") else "native"


def _normalize_agent_tasks_mode(raw: str) -> str:
    mode = (raw or "async").strip().lower()
    return mode if mode in ("off", "async", "blocking") else "async"


def _normalize_vault_mirror_mode(raw: str) -> str:
    mode = (raw or "async").strip().lower()
    return mode if mode in ("off", "async", "sync") else "async"


def _normalize_state_backend(raw: str) -> str:
    backend = (raw or "file").strip().lower()
    if backend not in ("file", "postgres"):
        raise ValueError(f"MESH_STATE_BACKEND must be 'file' or 'postgres', got {raw!r}")
    return backend


def _normalize_memory_graph_backend(raw: str) -> str:
    backend = (raw or "local").strip().lower()
    if backend in {"off", "none", "disabled"}:
        return "local"
    if backend not in {"local", "helix"}:
        raise ValueError(f"MESH_MEMORY_GRAPH_BACKEND must be 'local' or 'helix', got {raw!r}")
    return backend


def _normalize_helix_query_namespace(raw: str) -> str:
    namespace = (raw or "mesh").strip()
    if not namespace:
        return "mesh"
    if not (namespace[0].isalpha() or namespace[0] == "_"):
        raise ValueError("MESH_HELIX_QUERY_NAMESPACE must start with a letter or underscore")
    if not all(char.isalnum() or char == "_" for char in namespace):
        raise ValueError("MESH_HELIX_QUERY_NAMESPACE may contain only letters, numbers, and underscores")
    return namespace


def _normalize_readiness_profile(raw: str, environment: str = "local") -> str:
    profile = (raw or "").strip().lower()
    if not profile:
        profile = (environment or "local").strip().lower()
    aliases = {
        "dev": "local",
        "development": "local",
        "prod": "pilot",
        "production": "pilot",
        "phase4": "expansion",
    }
    profile = aliases.get(profile, profile)
    return profile if profile in {"local", "staging", "pilot", "expansion"} else "local"


def _normalize_prompt_cache_mode(raw: str) -> str:
    mode = (raw or "explicit").strip().lower()
    if mode in {"off", "none", "disabled", "false", "0"}:
        return "off"
    return mode if mode in {"explicit", "automatic", "both"} else "explicit"


def _normalize_prompt_cache_ttl(raw: str) -> str:
    ttl = (raw or "5m").strip().lower()
    if ttl in {"", "5m", "5min", "5-minute", "ephemeral"}:
        return "5m"
    if ttl in {"1h", "1hr", "60m", "60min", "hour"}:
        return "1h"
    return "5m"
