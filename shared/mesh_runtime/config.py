from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIRECTORY = _REPO_ROOT / ".mesh-runtime-state"
DEFAULT_RESEARCH_DIRECTORY = DEFAULT_STATE_DIRECTORY / "research"
DEFAULT_WEB_ASSET_PATH = _REPO_ROOT / "web" / "dist"
DEFAULT_VAULT_PATH = DEFAULT_STATE_DIRECTORY / "vault"
DEFAULT_INTEGRATIONS_CONFIG_PATH = DEFAULT_STATE_DIRECTORY / "integrations.json"
DEFAULT_DEEPAGENTS_WORKSPACE = DEFAULT_STATE_DIRECTORY / "deepagents"


def _env_path_anchored_to_repo(raw: str | None, *, default: str) -> str:
    value = (raw or "").strip() or default
    p = Path(value)
    if p.is_absolute():
        return str(p.resolve())
    return str((_REPO_ROOT / p).resolve())

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
    state_directory: str = str(DEFAULT_STATE_DIRECTORY)
    research_directory: str = str(DEFAULT_RESEARCH_DIRECTORY)
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    web_asset_path: str = str(DEFAULT_WEB_ASSET_PATH)
    vault_path: str = str(DEFAULT_VAULT_PATH)
    integrations_config_path: str = str(DEFAULT_INTEGRATIONS_CONFIG_PATH)
    default_steering_mode: str = "approval_gate"
    default_operator_pause_point: str = "evaluation_ready"
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
    access_log_enabled: bool = False
    security_headers_enabled: bool = True
    vault_ai_postprocess_enabled: bool = False
    build_version: str = "dev"
    build_commit: str = "unknown"
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
    agent_mesh_task_timeout_seconds: float = 15.0
    mesh_deepagents_model: str = "openai:MiniMax-M2.7"
    mesh_deepagents_timeout_seconds: float = 120.0
    mesh_deepagents_workspace_root: str = str(DEFAULT_DEEPAGENTS_WORKSPACE)
    mesh_deepagents_max_artifact_chars: int = 20_000
    sse_max_connection_seconds: int = 1800
    watch_enabled: bool = False
    watch_interval_seconds: int = 60
    watch_cooldown_seconds: int = 300
    watch_targets: tuple[dict[str, str], ...] = ()
    llm_escalation_enabled: bool = False
    llm_escalation_provider: str = "goose"
    llm_escalation_model: str | None = None
    llm_escalation_timeout_seconds: int = 30
    correlation_enabled: bool = False
    correlation_window_seconds: int = 300
    correlation_min_signals: int = 2

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
        if self.watch_interval_seconds < 10:
            raise ValueError(f"watch_interval_seconds must be >= 10, got {self.watch_interval_seconds}")
        if self.research_directory == str(DEFAULT_RESEARCH_DIRECTORY):
            self.research_directory = str(Path(self.state_directory) / "research")

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
            default_steering_mode=os.getenv("MESH_DEFAULT_STEERING_MODE", "approval_gate"),
            default_operator_pause_point=os.getenv("MESH_DEFAULT_OPERATOR_PAUSE_POINT", "evaluation_ready"),
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
            access_log_enabled=os.getenv("MESH_ACCESS_LOG", "").lower() in ("1", "true", "yes"),
            security_headers_enabled=os.getenv("MESH_SECURITY_HEADERS", "true").lower()
            not in ("0", "false", "no"),
            vault_ai_postprocess_enabled=os.getenv("MESH_VAULT_AI_POSTPROCESS_ENABLED", "").lower()
            in ("1", "true", "yes"),
            build_version=os.getenv("MESH_BUILD_VERSION") or os.getenv("MESH_IMAGE_TAG") or "dev",
            build_commit=os.getenv("MESH_BUILD_COMMIT") or os.getenv("GIT_COMMIT") or "unknown",
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
            agent_mesh_task_timeout_seconds=float(os.getenv("MESH_AGENT_TASK_TIMEOUT_SECONDS", "15")),
            mesh_deepagents_model=os.getenv("MESH_DEEPAGENTS_MODEL", "openai:MiniMax-M2.7"),
            mesh_deepagents_timeout_seconds=float(os.getenv("MESH_DEEPAGENTS_TIMEOUT_SECONDS", "120")),
            mesh_deepagents_workspace_root=_env_path_anchored_to_repo(
                os.getenv("MESH_DEEPAGENTS_WORKSPACE_ROOT"),
                default=str(DEFAULT_DEEPAGENTS_WORKSPACE),
            ),
            mesh_deepagents_max_artifact_chars=int(os.getenv("MESH_DEEPAGENTS_MAX_ARTIFACT_CHARS", "20000")),
            watch_enabled=os.getenv("MESH_WATCH_ENABLED", "").lower() in ("1", "true", "yes"),
            watch_interval_seconds=int(os.getenv("MESH_WATCH_INTERVAL_SECONDS", "60")),
            watch_cooldown_seconds=int(os.getenv("MESH_WATCH_COOLDOWN_SECONDS", "300")),
            watch_targets=_parse_watch_targets(os.getenv("MESH_WATCH_TARGETS")),
            llm_escalation_enabled=os.getenv("MESH_LLM_ESCALATION_ENABLED", "").lower()
            in ("1", "true", "yes"),
            llm_escalation_provider=os.getenv("MESH_LLM_ESCALATION_PROVIDER", "goose"),
            llm_escalation_model=os.getenv("MESH_LLM_ESCALATION_MODEL") or None,
            llm_escalation_timeout_seconds=int(os.getenv("MESH_LLM_ESCALATION_TIMEOUT_SECONDS", "30")),
            correlation_enabled=os.getenv("MESH_CORRELATION_ENABLED", "").lower()
            in ("1", "true", "yes"),
            correlation_window_seconds=int(os.getenv("MESH_CORRELATION_WINDOW_SECONDS", "300")),
            correlation_min_signals=int(os.getenv("MESH_CORRELATION_MIN_SIGNALS", "2")),
        )


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _normalize_agent_fabric_mode(raw: str) -> str:
    mode = (raw or "native").strip().lower()
    return mode if mode in ("native", "deepagents") else "native"


def _normalize_state_backend(raw: str) -> str:
    backend = (raw or "file").strip().lower()
    if backend not in ("file", "postgres"):
        raise ValueError(f"MESH_STATE_BACKEND must be 'file' or 'postgres', got {raw!r}")
    return backend
