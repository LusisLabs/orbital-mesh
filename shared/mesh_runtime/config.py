from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_DIRECTORY = _REPO_ROOT / ".mesh-runtime-state"
DEFAULT_RESEARCH_DIRECTORY = DEFAULT_STATE_DIRECTORY / "research"
DEFAULT_WEB_ASSET_PATH = _REPO_ROOT / "web" / "dist"
DEFAULT_VAULT_PATH = DEFAULT_STATE_DIRECTORY / "vault"
DEFAULT_INTEGRATIONS_CONFIG_PATH = DEFAULT_STATE_DIRECTORY / "integrations.json"


def _env_path_anchored_to_repo(raw: str | None, *, default: str) -> str:
    """Resolve MESH_* paths relative to the repository root (not the process cwd).

    Relative entries in .env (for example ``.mesh-runtime-state``) must match where
    CLI tools write state (e.g. research sessions) regardless of cwd.
    """
    value = (raw or "").strip() or default
    p = Path(value)
    if p.is_absolute():
        return str(p.resolve())
    return str((_REPO_ROOT / p).resolve())


@dataclass
class RuntimeConfig:
    environment: str = "local"
    evaluation_mode: str = "native"
    orchestration_mode: str = "native"
    feature_flag_credentials_available: bool = True
    incident_credentials_available: bool = True
    audit_logging_available: bool = True
    max_transient_retries: int = 2
    max_retry_window_seconds: int = 60
    goose_timeout_seconds: int = 180
    state_directory: str = str(DEFAULT_STATE_DIRECTORY)
    research_directory: str | None = None
    server_host: str = "127.0.0.1"
    server_port: int = 8787
    web_asset_path: str = str(DEFAULT_WEB_ASSET_PATH)
    vault_path: str = str(DEFAULT_VAULT_PATH)
    integrations_config_path: str = str(DEFAULT_INTEGRATIONS_CONFIG_PATH)
    default_steering_mode: str = "approval_gate"
    default_operator_pause_point: str = "evaluation_ready"
    promptfoo_command: str | None = None
    goose_command: str | None = None
    goose_command_timeout_seconds: int = 180
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

    def __post_init__(self) -> None:
        if self.research_directory is None:
            self.research_directory = str(Path(self.state_directory) / "research")

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            environment=os.getenv("MESH_ENVIRONMENT", "local"),
            evaluation_mode=os.getenv("MESH_EVALUATION_MODE", "native"),
            orchestration_mode=os.getenv("MESH_ORCHESTRATION_MODE", "native"),
            feature_flag_credentials_available=os.getenv("MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE", "true").lower() == "true",
            incident_credentials_available=os.getenv("MESH_INCIDENT_CREDENTIALS_AVAILABLE", "true").lower() == "true",
            audit_logging_available=os.getenv("MESH_AUDIT_LOGGING_AVAILABLE", "true").lower() == "true",
            max_transient_retries=int(os.getenv("MESH_MAX_TRANSIENT_RETRIES", "2")),
            max_retry_window_seconds=int(os.getenv("MESH_MAX_RETRY_WINDOW_SECONDS", "60")),
            goose_timeout_seconds=int(os.getenv("MESH_GOOSE_TIMEOUT_SECONDS", "180")),
            state_directory=_env_path_anchored_to_repo(
                os.getenv("MESH_STATE_DIRECTORY"),
                default=str(DEFAULT_STATE_DIRECTORY),
            ),
            research_directory=_env_path_anchored_to_repo(
                os.getenv("MESH_RESEARCH_DIRECTORY"),
                default=str(DEFAULT_RESEARCH_DIRECTORY),
            ),
            server_host=os.getenv("MESH_SERVER_HOST", "127.0.0.1"),
            server_port=int(os.getenv("MESH_SERVER_PORT", "8787")),
            web_asset_path=_env_path_anchored_to_repo(
                os.getenv("MESH_WEB_ASSET_PATH"),
                default=str(DEFAULT_WEB_ASSET_PATH),
            ),
            vault_path=_env_path_anchored_to_repo(
                os.getenv("MESH_VAULT_PATH"),
                default=str(DEFAULT_VAULT_PATH),
            ),
            integrations_config_path=_env_path_anchored_to_repo(
                os.getenv("MESH_INTEGRATIONS_CONFIG_PATH"),
                default=str(DEFAULT_INTEGRATIONS_CONFIG_PATH),
            ),
            default_steering_mode=os.getenv("MESH_DEFAULT_STEERING_MODE", "approval_gate"),
            default_operator_pause_point=os.getenv("MESH_DEFAULT_OPERATOR_PAUSE_POINT", "evaluation_ready"),
            promptfoo_command=os.getenv("MESH_PROMPTFOO_COMMAND") or None,
            goose_command=os.getenv("MESH_GOOSE_COMMAND") or None,
            goose_command_timeout_seconds=int(
                os.getenv(
                    "MESH_GOOSE_COMMAND_TIMEOUT_SECONDS",
                    os.getenv("MESH_GOOSE_BRIDGE_TIMEOUT_SECONDS", "180"),
                )
            ),
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
        )


def _csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())
