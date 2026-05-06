from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from .config import RuntimeConfig
from .control_plane_models import IntegrationReadiness, IntegrationStatus
from .agentic_operator_provenance import agentic_operator_source_provenance_ready
from .audit_sink import audit_sink_proof_ready, verify_audit_sink_proof
from .backup_restore import backup_restore_rehearsal_ready
from .connector_certification import build_connector_certification_matrix, connector_certification_registry_ready
from .data_classification import data_classification_policy_ready
from .failure_modes import failure_mode_library_ready
from .ownership import ownership_registry_ready
from .policy_lifecycle import policy_lifecycle_ready
from .threat_model import threat_model_register_ready


DEFAULT_GITNEXUS_PORT = 4747
_READINESS_TTL_SECONDS = 10.0
_DEFAULT_READINESS_PROBE_TIMEOUT_SECONDS = 5.0
_readiness_lock = threading.Lock()
_readiness_cache: dict[tuple, tuple[float, IntegrationReadiness]] = {}
# GitNexus exposes `/api/heartbeat` as SSE (long-lived); use `/api/info` for probes.
GITNEXUS_LIVENESS_PATH = "/api/info"
PROMPTFOO_BRIDGE_MODULE = "services.evaluation.promptfoo_bridge"
HERMES_BRIDGE_MODULE = "services.orchestrator.hermes_bridge"
GOOSE_BRIDGE_MODULE = "services.orchestrator.goose_bridge"
_PROFILE_ORDER = {"local": 0, "staging": 1, "pilot": 2, "expansion": 3}
_DURABLE_ARTIFACT_URI_SCHEMES = frozenset({"s3", "gs", "az", "azblob", "r2", "https"})


@dataclass
class IntegrationsConfig:
    promptfoo_command: str | None = None
    hermes_command: str | None = None
    goose_command: str | None = None
    evo_command: str | None = None
    gitnexus_sidecar_url: str | None = None
    gitnexus_sidecar_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "promptfoo_command": self.promptfoo_command,
            "hermes_command": self.hermes_command,
            "goose_command": self.goose_command,
            "evo_command": self.evo_command,
            "gitnexus_sidecar_url": self.gitnexus_sidecar_url,
            "gitnexus_sidecar_command": self.gitnexus_sidecar_command,
        }


def load_integrations_config(path: str | Path) -> IntegrationsConfig:
    config_path = Path(path)
    if not config_path.exists():
        return IntegrationsConfig()
    raw = json.loads(config_path.read_text())
    return IntegrationsConfig(
        promptfoo_command=raw.get("promptfoo_command"),
        hermes_command=raw.get("hermes_command"),
        goose_command=raw.get("goose_command"),
        evo_command=raw.get("evo_command"),
        gitnexus_sidecar_url=raw.get("gitnexus_sidecar_url"),
        gitnexus_sidecar_command=raw.get("gitnexus_sidecar_command"),
    )


def save_integrations_config(path: str | Path, config: IntegrationsConfig) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n")


def resolve_integrations_config(runtime_config: RuntimeConfig) -> IntegrationsConfig:
    loaded = load_integrations_config(runtime_config.integrations_config_path)
    if runtime_config.gitnexus_disable_autostart:
        gitnexus_command = runtime_config.gitnexus_sidecar_command or loaded.gitnexus_sidecar_command
    else:
        gitnexus_command = (
            runtime_config.gitnexus_sidecar_command
            or loaded.gitnexus_sidecar_command
            or _default_gitnexus_command()
        )
    return IntegrationsConfig(
        promptfoo_command=_resolve_promptfoo_command(runtime_config.promptfoo_command or loaded.promptfoo_command),
        hermes_command=_resolve_hermes_command(runtime_config.hermes_command or loaded.hermes_command),
        goose_command=_resolve_goose_command(runtime_config.goose_command or loaded.goose_command),
        evo_command=_resolve_evo_command(runtime_config.evo_command or loaded.evo_command),
        gitnexus_sidecar_url=runtime_config.gitnexus_sidecar_url
        or loaded.gitnexus_sidecar_url
        or f"http://127.0.0.1:{DEFAULT_GITNEXUS_PORT}",
        gitnexus_sidecar_command=gitnexus_command,
    )


def build_readiness(runtime_config: RuntimeConfig, force: bool = False) -> IntegrationReadiness:
    # Module-level TTL cache: subprocess probes (promptfoo --version, goose
    # --version, evo --version) plus the latentmas/deepagents HTTP probes
    # dominate cold startup. Every service constructor in auto mode would
    # otherwise pay ~800ms per init. The key includes every field the probe
    # consults so changing e.g. latentmas_url in a new RuntimeConfig triggers
    # a fresh probe rather than returning a stale snapshot.
    cache_key = (
        runtime_config.state_directory,
        runtime_config.integrations_config_path,
        runtime_config.ownership_registry_path,
        runtime_config.connector_certification_registry_path,
        runtime_config.policy_lifecycle_manifest_path,
        runtime_config.failure_mode_library_path,
        runtime_config.threat_model_register_path,
        runtime_config.data_classification_policy_path,
        runtime_config.agentic_operator_source_provenance_path,
        runtime_config.audit_sink_proof_path,
        runtime_config.backup_restore_rehearsal_path,
        bool(runtime_config.policy_signing_key),
        runtime_config.policy_signing_key_id,
        runtime_config.promptfoo_command,
        runtime_config.hermes_command,
        runtime_config.goose_command,
        runtime_config.evo_command,
        runtime_config.gitnexus_sidecar_url,
        runtime_config.readiness_profile,
        runtime_config.operator_identity_required,
        runtime_config.state_backend,
        runtime_config.database_url,
        runtime_config.force_approval_gate,
        runtime_config.kubernetes_live_execution_enabled,
        runtime_config.kubernetes_allowed_contexts,
        runtime_config.kubernetes_allowed_namespaces,
        runtime_config.otel_receiver_enabled,
        runtime_config.otel_receiver_token,
        runtime_config.feedback_prometheus_enabled,
        runtime_config.prometheus_url,
        runtime_config.live_feedback_required,
        runtime_config.feature_flag_credentials_available,
        runtime_config.incident_credentials_available,
        runtime_config.audit_logging_available,
        runtime_config.latentmas_enabled,
        runtime_config.latentmas_url,
        runtime_config.latentmas_model_name,
        runtime_config.agent_fabric_mode,
        runtime_config.mesh_deepagents_model,
        runtime_config.run_export_retention_days,
        runtime_config.run_export_retention_reviewed,
    )
    now = time.monotonic()
    if not force:
        with _readiness_lock:
            entry = _readiness_cache.get(cache_key)
            if entry and now - entry[0] < _READINESS_TTL_SECONDS:
                return entry[1]
    resolved = resolve_integrations_config(runtime_config)
    checked_at = _timestamp()
    with ThreadPoolExecutor(max_workers=6) as executor:
        promptfoo_future = executor.submit(_command_status, "promptfoo", resolved.promptfoo_command)
        hermes_future = executor.submit(_command_status, "hermes", resolved.hermes_command)
        goose_future = executor.submit(_command_status, "goose", resolved.goose_command)
        evo_future = executor.submit(build_evo_status, runtime_config, resolved.evo_command)
        latentmas_future = executor.submit(_latentmas_status, runtime_config)
        deepagents_future = executor.submit(_deepagents_status, runtime_config)
        promptfoo_status = promptfoo_future.result()
        hermes_status = hermes_future.result()
        goose_status = goose_future.result()
        evo_status = evo_future.result()
        latentmas_status = latentmas_future.result()
        deepagents_status = deepagents_future.result()
    promptfoo_status = _with_certification(
        promptfoo_status,
        "staging-ready" if promptfoo_status.ready else "mock",
        required_before="staging",
        posture="evaluation gate",
    )
    hermes_status = _with_certification(
        hermes_status,
        "read-only" if hermes_status.ready else "mock",
        required_before="staging",
        posture="proposal lane",
    )
    goose_status = _with_certification(
        goose_status,
        "read-only" if goose_status.ready else "mock",
        required_before="staging",
        posture="review lane",
    )
    evo_status = _with_certification(
        evo_status,
        "proposal-only" if evo_status.ready else "mock",
        required_before="pilot",
        posture="scoped repo proposal lane",
    )
    latentmas_status = _with_certification(
        latentmas_status,
        "proposal-only" if latentmas_status.ready else "disabled",
        required_before="pilot",
        posture="model-lifecycle advisory lane",
    )
    deepagents_status = _with_certification(
        deepagents_status,
        "proposal-only" if deepagents_status.ready else "disabled",
        required_before="pilot",
        posture="sandboxed proposal fabric",
    )
    runtime_connector_states = _connector_certification(runtime_config, resolved)
    runtime_connector_states.update(
        {
            "promptfoo": _status_connector_state(promptfoo_status),
            "hermes": _status_connector_state(hermes_status),
            "goose": _status_connector_state(goose_status),
            "evo": _status_connector_state(evo_status),
            "latentmas": _status_connector_state(latentmas_status),
            "deepagents": _status_connector_state(deepagents_status),
        }
    )
    connector_certification_packet = build_connector_certification_matrix(
        registry_path=runtime_config.connector_certification_registry_path,
        runtime_states=runtime_connector_states,
    )
    connector_certification = connector_certification_packet["connectors"]
    profile, required_checks, optional_checks, blockers = _profile_checks(
        runtime_config,
        {
            "promptfoo": promptfoo_status,
            "hermes": hermes_status,
            "goose": goose_status,
            "evo": evo_status,
            "latentmas": latentmas_status,
            "deepagents": deepagents_status,
        },
        connector_certification,
    )
    readiness = IntegrationReadiness(
        checked_at=checked_at,
        profile=profile,
        status="ready" if not blockers else "blocked",
        required_checks=required_checks,
        optional_checks=optional_checks,
        blockers=blockers,
        connector_certification=connector_certification,
        promptfoo=promptfoo_status,
        hermes=hermes_status,
        goose=goose_status,
        evo=evo_status,
        latentmas=latentmas_status,
        deepagents=deepagents_status,
        vault_path=runtime_config.vault_path,
        state_path=runtime_config.state_directory,
        integrations_config_path=runtime_config.integrations_config_path,
    )
    with _readiness_lock:
        _readiness_cache[cache_key] = (now, readiness)
    return readiness


def _with_certification(
    status: IntegrationStatus,
    certification: str,
    *,
    required_before: str,
    posture: str,
) -> IntegrationStatus:
    return replace(
        status,
        certification=certification,
        required_before=required_before,
        posture=posture,
    )


def _status_connector_state(status: IntegrationStatus) -> dict[str, Any]:
    blockers = [] if status.ready else [f"{status.name}_connector_probe_not_ready"]
    return {
        "state": status.certification,
        "blockers": blockers,
    }


def _connector_certification(
    runtime_config: RuntimeConfig,
    resolved: IntegrationsConfig,
) -> dict[str, Any]:
    kubernetes_allowlisted = bool(runtime_config.kubernetes_allowed_contexts and runtime_config.kubernetes_allowed_namespaces)
    kubernetes_state = (
        "pilot-ready"
        if runtime_config.kubernetes_live_execution_enabled and kubernetes_allowlisted
        else ("read-only" if kubernetes_allowlisted else "mock")
    )
    otel_state = (
        "staging-ready"
        if runtime_config.otel_receiver_enabled and bool(runtime_config.otel_receiver_token)
        else ("read-only" if runtime_config.prometheus_url else "mock")
    )
    return {
        "kubernetes": {
            "state": kubernetes_state,
            "required_before": "pilot",
            "detail": "Live execution requires explicit context and namespace allowlists.",
        },
        "webhooks": {
            "state": "read-only",
            "required_before": "staging",
            "detail": "Webhook sources are accepted only through registered HMAC sources.",
        },
        "otel": {
            "state": otel_state,
            "required_before": "staging",
            "detail": "OTLP ingest requires a bearer token when enabled; Prometheus feedback is read-only.",
        },
        "promptfoo": {
            "state": "staging-ready" if resolved.promptfoo_command else "mock",
            "required_before": "staging",
            "detail": "Compatibility bridge; Mesh-native evaluation remains authoritative.",
        },
        "feature_flag_adapter": {
            "state": "unfinished" if runtime_config.feature_flag_credentials_available else "disabled",
            "required_before": "pilot",
            "detail": "Local deterministic seam. Disable for pilot until a real provider adapter is certified.",
        },
        "incident_adapter": {
            "state": "unfinished" if runtime_config.incident_credentials_available else "disabled",
            "required_before": "pilot",
            "detail": "Local deterministic seam. Disable for pilot until a real incident provider is certified.",
        },
        "audit_sink": _audit_sink_connector_state(runtime_config),
        "deepagents": {
            "state": "proposal-only" if runtime_config.agent_fabric_mode == "deepagents" else "disabled",
            "required_before": "pilot",
            "detail": "Sandbox lane cannot mutate production or write repos directly.",
        },
        "evo": {
            "state": "proposal-only" if resolved.evo_command else "mock",
            "required_before": "pilot",
            "detail": "Operator-launched scoped repo proposal lane.",
        },
    }


def _profile_checks(
    runtime_config: RuntimeConfig,
    statuses: dict[str, IntegrationStatus],
    connector_certification: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], list[str]]:
    profile = runtime_config.readiness_profile
    optional_checks = {
        name: {
            "ready": status.ready,
            "certification": status.certification,
            "detail": status.detail,
        }
        for name, status in statuses.items()
    }
    required_checks: dict[str, Any] = {
        "state_path_configured": bool(runtime_config.state_directory),
        "vault_path_configured": bool(runtime_config.vault_path),
        "security_headers_enabled": runtime_config.security_headers_enabled,
    }
    if _profile_at_least(profile, "staging"):
        required_checks.update(
            {
                "operator_identity_required": runtime_config.operator_identity_required,
                "ownership_registry_configured": ownership_registry_ready(runtime_config.ownership_registry_path),
                "connector_certification_registry_configured": connector_certification_registry_ready(
                    runtime_config.connector_certification_registry_path
                ),
                "policy_lifecycle_signed": policy_lifecycle_ready(
                    manifest_path=runtime_config.policy_lifecycle_manifest_path,
                    signing_key=runtime_config.policy_signing_key,
                    signing_key_id=runtime_config.policy_signing_key_id,
                ),
                "failure_mode_library_configured": failure_mode_library_ready(
                    runtime_config.failure_mode_library_path
                ),
                "threat_model_register_reviewed": threat_model_register_ready(
                    runtime_config.threat_model_register_path
                ),
                "data_classification_policy_reviewed": data_classification_policy_ready(
                    runtime_config.data_classification_policy_path
                ),
                "agentic_operator_source_provenance_recorded": agentic_operator_source_provenance_ready(
                    runtime_config.agentic_operator_source_provenance_path
                ),
                "backup_restore_rehearsal_verified": backup_restore_rehearsal_ready(
                    runtime_config.backup_restore_rehearsal_path
                ),
                "otel_ingest_protected": (
                    not runtime_config.otel_receiver_enabled
                    or bool(runtime_config.otel_receiver_token)
                ),
                "live_execution_allowlisted": (
                    not runtime_config.kubernetes_live_execution_enabled
                    or bool(
                        runtime_config.kubernetes_allowed_contexts
                        and runtime_config.kubernetes_allowed_namespaces
                    )
                ),
                "audit_logging_available": runtime_config.audit_logging_available,
            }
        )
    if _profile_at_least(profile, "pilot"):
        live_feedback_required = runtime_config.live_feedback_required or _profile_at_least(profile, "pilot")
        live_feedback_source_configured = bool(
            runtime_config.feedback_prometheus_enabled
            and runtime_config.prometheus_url
        ) or runtime_config.kubernetes_live_execution_enabled
        required_checks.update(
            {
                "state_backend_postgres": runtime_config.state_backend == "postgres",
                "database_url_configured": bool(runtime_config.database_url),
                "force_approval_gate": runtime_config.force_approval_gate
                or runtime_config.default_steering_mode == "approval_gate",
                "live_feedback_required": live_feedback_required,
                "live_feedback_source_configured": live_feedback_source_configured,
                "mesh_brain_artifact_uri_prefix_configured": _durable_artifact_uri_prefix_configured(
                    runtime_config.mesh_brain_artifact_uri_prefix
                ),
                "mesh_brain_serving_backend_configured": bool(
                    runtime_config.mesh_brain_serving_base_url and runtime_config.mesh_brain_serving_model
                ),
                "run_export_retention_reviewed": runtime_config.run_export_retention_reviewed,
                "run_export_retention_days_positive": runtime_config.run_export_retention_days > 0,
                "unfinished_feature_flag_adapter_disabled": not runtime_config.feature_flag_credentials_available,
                "unfinished_incident_adapter_disabled": not runtime_config.incident_credentials_available,
            }
        )
    if _profile_at_least(profile, "expansion"):
        required_checks.update(
            {
                "postgres_required_for_multi_operator": runtime_config.state_backend == "postgres",
                "external_audit_sink_certified": connector_certification.get("audit_sink", {}).get("state")
                in {"pilot-ready", "production-ready"},
                "external_audit_sink_contract_verified": audit_sink_proof_ready(
                    runtime_config.audit_sink_proof_path
                ),
            }
        )
    blockers = [
        name
        for name, passed in required_checks.items()
        if isinstance(passed, bool) and not passed
    ]
    return profile, required_checks, optional_checks, blockers


def _profile_at_least(profile: str, minimum: str) -> bool:
    return _PROFILE_ORDER.get(profile, 0) >= _PROFILE_ORDER.get(minimum, 0)


def _durable_artifact_uri_prefix_configured(uri_prefix: str | None) -> bool:
    parsed = urlparse((uri_prefix or "").strip())
    return parsed.scheme in _DURABLE_ARTIFACT_URI_SCHEMES and bool(parsed.netloc)


def _audit_sink_connector_state(runtime_config: RuntimeConfig) -> dict[str, Any]:
    if not runtime_config.audit_logging_available:
        return {
            "state": "disabled",
            "required_before": "pilot",
            "detail": "Audit logging is disabled.",
            "blockers": ["audit_logging_disabled"],
        }
    verification = verify_audit_sink_proof(runtime_config.audit_sink_proof_path)
    if verification["status"] == "pass":
        return {
            "state": "production-ready",
            "required_before": "expansion",
            "detail": "External audit sink append-only contract proof is present.",
        }
    blockers = ["external_audit_sink_contract_not_verified"]
    blockers.extend(
        f"audit_sink_contract:{name}"
        for name, passed in verification["checks"].items()
        if not passed
    )
    return {
        "state": "mock",
        "required_before": "pilot",
        "detail": "Local audit seam. Mirror to durable external storage before compliance reliance.",
        "blockers": blockers,
    }


def invalidate_readiness_cache() -> None:
    """Drop every cached readiness snapshot. Call after integration config changes."""
    with _readiness_lock:
        _readiness_cache.clear()


def bootstrap_integrations(runtime_config: RuntimeConfig, install_missing: bool = False) -> dict[str, Any]:
    actions: list[str] = []
    if install_missing and not shutil.which("promptfoo") and shutil.which("npm"):
        subprocess.run(["npm", "install", "-g", "promptfoo"], check=False)
        actions.append("attempted global promptfoo install via npm")
    if install_missing and not shutil.which("goose") and shutil.which("brew"):
        subprocess.run(["brew", "install", "block-goose-cli"], check=False)
        actions.append("attempted Goose CLI install via Homebrew")

    current = resolve_integrations_config(runtime_config)
    hermes_detail = _describe_hermes_command(current.hermes_command)
    if hermes_detail:
        actions.append(hermes_detail)
    goose_detail = _describe_goose_command(current.goose_command)
    if goose_detail:
        actions.append(goose_detail)
    goose_warnings = _goose_warnings(current.goose_command)
    for warning in goose_warnings:
        actions.append(f"warning: {warning}")
    evo_detail = _describe_evo_command(current.evo_command)
    if evo_detail:
        actions.append(evo_detail)

    save_integrations_config(runtime_config.integrations_config_path, current)

    smoke_checks = {
        "promptfoo": _smoke_check_with_fallback(current.promptfoo_command, [["--healthcheck"], ["--version"]]),
        "hermes": _smoke_check_with_fallback(current.hermes_command, [["--healthcheck"], ["--version"]]),
        "goose": _smoke_check_with_fallback(current.goose_command, [["--healthcheck"], ["--version"]]),
        "evo": _evo_smoke_check(current.evo_command, runtime_config.evo_command_timeout_seconds),
    }
    guidance = {
        "promptfoo": (
            "Install with `npm install -g promptfoo` if missing. "
            "The bridge command runs a local Promptfoo eval and returns the mesh evaluation contract."
        ),
        "hermes": (
            "Install or expose a Hermes CLI wrapper that supports `chat -q` and `version`, "
            "or point `MESH_HERMES_COMMAND` at a Docker-backed runtime command."
        ),
        "goose": (
            "Install Goose CLI from the official Block Goose distribution if missing. "
            "For automatic provider inference, set an OpenAI-compatible MiniMax endpoint via "
            "`OPENAI_BASE_URL` plus a model such as `GOOSE_MODEL=MiniMax-M2.5`."
        ),
        "evo": (
            "Install `evo-hq-cli` globally or set `MESH_EVO_COMMAND` to a local command such as "
            "`uv run --project /workspace/orbital-mesh/evo/plugins/evo evo`. Mesh only probes "
            "`evo --version` in this proposal-lane integration."
        ),
    }
    return {
        "platform": platform.platform(),
        "actions": actions,
        "config": current.to_dict(),
        "smoke_checks": smoke_checks,
        "warnings": {"goose": goose_warnings},
        "guidance": guidance,
    }


class GitNexusSidecarManager:
    def __init__(self, runtime_config: RuntimeConfig):
        self.runtime_config = runtime_config
        self._process: subprocess.Popen[str] | None = None

    def ensure_running(self) -> bool:
        resolved = resolve_integrations_config(self.runtime_config)
        base = resolved.gitnexus_sidecar_url.rstrip("/") if resolved.gitnexus_sidecar_url else ""
        live_url = f"{base}{GITNEXUS_LIVENESS_PATH}"
        if resolved.gitnexus_sidecar_url and _url_responds(live_url):
            return True
        if not resolved.gitnexus_sidecar_command:
            return False
        if self._process is not None and self._process.poll() is None:
            return _wait_for_url(live_url, timeout_seconds=8)

        stdout_path = Path(self.runtime_config.state_directory) / "gitnexus-sidecar.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = stdout_path.open("a", encoding="utf-8")
        repo_root = Path(__file__).resolve().parents[2]
        self._process = subprocess.Popen(
            shlex.split(resolved.gitnexus_sidecar_command),
            cwd=repo_root,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return _wait_for_url(live_url, timeout_seconds=8)

    def stop(self) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()


def _default_gitnexus_command() -> str | None:
    here = Path(__file__).resolve()
    candidate_roots = (here.parents[2], here.parents[3])
    for root in candidate_roots:
        tsx = root / "GitNexus" / "gitnexus" / "node_modules" / ".bin" / "tsx"
        cli_entry = root / "GitNexus" / "gitnexus" / "src" / "cli" / "index.ts"
        if tsx.is_file() and cli_entry.is_file():
            return f"{tsx} {cli_entry} serve --host 127.0.0.1 --port {DEFAULT_GITNEXUS_PORT}"
    return None


def _command_status(name: str, command: str | None) -> IntegrationStatus:
    if not command:
        return IntegrationStatus(name=name, ready=False, detail="command not configured")
    executable = shlex.split(command)[0]
    binary = executable if os.path.isabs(executable) else shutil.which(executable)
    if binary is None and not Path(executable).exists():
        return IntegrationStatus(name=name, ready=False, detail="command not found", command=command)
    timeout = _readiness_probe_timeout_seconds()
    if name == "goose":
        ok, detail = _smoke_check(command, ["--version"], timeout=timeout)
        primary_route, fallback_route = _goose_routes(command)
        warnings = _goose_warnings(command)
        profile_detail = _describe_goose_command(command)
        if profile_detail:
            detail = f"{profile_detail}; probe={detail}"
        return IntegrationStatus(
            name=name,
            ready=ok,
            detail=detail,
            command=command,
            primary_route=primary_route,
            fallback_route=fallback_route,
            warnings=warnings,
        )
    else:
        ok, detail = _smoke_check_with_fallback(command, [["--healthcheck"], ["--version"]], timeout=timeout)
    return IntegrationStatus(name=name, ready=ok, detail=detail, command=command)


def build_evo_status(runtime_config: RuntimeConfig, command: str | None = None) -> IntegrationStatus:
    resolved_command = command if command is not None else resolve_integrations_config(runtime_config).evo_command
    ok, detail = _evo_smoke_check(resolved_command, runtime_config.evo_command_timeout_seconds)
    return IntegrationStatus(name="evo", ready=ok, detail=detail, command=resolved_command)


def _evo_smoke_check(command: str | None, timeout_seconds: int | float) -> tuple[bool, str]:
    if not command:
        return False, "command not configured"
    executable = shlex.split(command)[0]
    binary = executable if os.path.isabs(executable) else shutil.which(executable)
    if binary is None and not Path(executable).exists():
        return False, "command not found"
    ok, detail = _smoke_check(command, ["--version"], timeout=timeout_seconds)
    if not ok:
        return False, detail
    if "evo-hq-cli" not in detail:
        return False, f"unexpected evo package: {detail}"
    return True, detail


def _deepagents_env_warnings(model: str) -> list[str]:
    warnings: list[str] = []
    lower = model.lower()
    if lower.startswith("openai:") and not _deepagents_openai_api_key(model):
        warnings.append("OPENAI_API_KEY is not set for openai Deep Agents models")
    if lower.startswith("anthropic:") and not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        warnings.append("ANTHROPIC_API_KEY is not set for anthropic Deep Agents models")
    return warnings


def _deepagents_openai_api_key(model: str) -> str:
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if openai_api_key:
        return openai_api_key
    if "minimax" in model.lower():
        return (os.getenv("MINIMAX_API_KEY") or "").strip()
    return ""


def _deepagents_status(runtime_config: RuntimeConfig) -> IntegrationStatus:
    if runtime_config.agent_fabric_mode != "deepagents":
        return IntegrationStatus(
            name="deepagents",
            ready=False,
            detail="disabled (MESH_AGENT_FABRIC_MODE is not deepagents)",
        )
    try:
        import deepagents  # noqa: F401
    except ImportError:
        return IntegrationStatus(
            name="deepagents",
            ready=False,
            detail="deepagents package is not installed or not on PYTHONPATH",
        )
    warnings = _deepagents_env_warnings(runtime_config.mesh_deepagents_model)
    detail = (
        f"fabric=deepagents model={runtime_config.mesh_deepagents_model} "
        f"workspace={runtime_config.mesh_deepagents_workspace_root}"
    )
    return IntegrationStatus(
        name="deepagents",
        ready=True,
        detail=detail,
        warnings=warnings,
    )


def _latentmas_status(runtime_config: RuntimeConfig) -> IntegrationStatus:
    if not runtime_config.latentmas_enabled:
        return IntegrationStatus(
            name="latentmas",
            ready=False,
            detail="disabled",
            url=runtime_config.latentmas_url,
        )
    if not runtime_config.latentmas_url:
        return IntegrationStatus(
            name="latentmas",
            ready=False,
            detail="enabled but MESH_LATENTMAS_URL is not configured",
        )
    health_url = f"{runtime_config.latentmas_url.rstrip('/')}/health"
    health = _read_json_url(health_url)
    ready = bool(health and health.get("ready"))
    detail = "sidecar reachable" if ready else "sidecar unavailable"
    if isinstance(health, dict) and health.get("detail"):
        detail = str(health["detail"])
    return IntegrationStatus(
        name="latentmas",
        ready=ready,
        detail=detail,
        url=runtime_config.latentmas_url,
    )


def _smoke_check(
    command: str | None,
    extra_args: list[str],
    timeout: int | float = 20,
) -> tuple[bool, str]:
    if not command:
        return False, "command not configured"
    try:
        completed = subprocess.run(
            shlex.split(command) + extra_args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "command not found"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        return False, completed.stderr.strip() or "command returned a non-zero exit code"
    output = completed.stdout.strip() or completed.stderr.strip() or "ready"
    return True, output


def _smoke_check_with_fallback(
    command: str | None,
    arg_sets: list[list[str]],
    *,
    timeout: int | float = 20,
) -> tuple[bool, str]:
    last_detail = "command not configured"
    for extra_args in arg_sets:
        ok, detail = _smoke_check(command, extra_args, timeout=timeout)
        if ok:
            return ok, detail
        last_detail = detail
    return False, last_detail


def _readiness_probe_timeout_seconds() -> float:
    raw = os.getenv("MESH_READINESS_PROBE_TIMEOUT_SECONDS")
    if not raw:
        return _DEFAULT_READINESS_PROBE_TIMEOUT_SECONDS
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_READINESS_PROBE_TIMEOUT_SECONDS


def _resolve_promptfoo_command(command: str | None) -> str | None:
    if command and PROMPTFOO_BRIDGE_MODULE in command:
        return command
    discovered = _resolve_vendor_binary(command, "promptfoo")
    if discovered is None:
        return command
    return _build_promptfoo_bridge_command(discovered)


def _resolve_hermes_command(command: str | None) -> str | None:
    if command and HERMES_BRIDGE_MODULE in command:
        return command
    if command:
        return _build_hermes_bridge_command(command)
    discovered = shutil.which("hermes")
    if discovered is None:
        return None
    return _build_hermes_bridge_command(discovered)


def _resolve_goose_command(command: str | None) -> str | None:
    if command and GOOSE_BRIDGE_MODULE in command:
        return command
    discovered = _resolve_vendor_binary(command, "goose")
    if discovered is None:
        return command
    provider, model, fallback_provider, fallback_model = _configured_goose_profile()
    return _build_goose_bridge_command(
        discovered,
        provider=provider,
        model=model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
    )


def _resolve_evo_command(command: str | None) -> str | None:
    if command:
        return command
    return shutil.which("evo")


def _resolve_vendor_binary(command: str | None, executable_name: str) -> str | None:
    if command:
        tokens = shlex.split(command)
        if len(tokens) == 1 and Path(tokens[0]).name == executable_name:
            return tokens[0]
        return None
    return shutil.which(executable_name)


def _build_promptfoo_bridge_command(promptfoo_bin: str) -> str:
    return shlex.join(
        [
            sys.executable,
            "-m",
            PROMPTFOO_BRIDGE_MODULE,
            "--promptfoo-bin",
            promptfoo_bin,
        ]
    )


def _build_hermes_bridge_command(hermes_command: str) -> str:
    return shlex.join(
        [
            sys.executable,
            "-m",
            HERMES_BRIDGE_MODULE,
            "--hermes-command",
            hermes_command,
        ]
    )


def _build_goose_bridge_command(
    goose_bin: str,
    provider: str | None,
    model: str | None,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
) -> str:
    command = [
        sys.executable,
        "-m",
        GOOSE_BRIDGE_MODULE,
        "--goose-bin",
        goose_bin,
    ]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    if fallback_provider:
        command.extend(["--fallback-provider", fallback_provider])
    if fallback_model:
        command.extend(["--fallback-model", fallback_model])
    return shlex.join(command)


def _describe_goose_command(command: str | None) -> str | None:
    if not command:
        return None
    primary_route, fallback_route = _goose_routes(command)
    if primary_route and fallback_route:
        return f"configured Goose bridge for {primary_route} with fallback {fallback_route}"
    if primary_route:
        return f"configured Goose bridge for {primary_route}"
    return "configured Goose bridge with the default Goose profile"


def _describe_hermes_command(command: str | None) -> str | None:
    if not command:
        return None
    tokens = shlex.split(command)
    forwarded = _flag_value(tokens, "--hermes-command")
    if forwarded:
        return f"configured Hermes bridge for {forwarded}"
    return "configured Hermes bridge"


def _describe_evo_command(command: str | None) -> str | None:
    if not command:
        return None
    return f"configured Evo proposal lane for {command}"


def _goose_routes(command: str | None) -> tuple[str | None, str | None]:
    if not command:
        return None, None
    tokens = shlex.split(command)
    provider = _flag_value(tokens, "--provider")
    model = _flag_value(tokens, "--model")
    fallback_provider = _flag_value(tokens, "--fallback-provider")
    fallback_model = _flag_value(tokens, "--fallback-model")
    primary_route = f"{provider}/{model}" if provider and model else None
    fallback_route = f"{fallback_provider}/{fallback_model}" if fallback_provider and fallback_model else None
    return primary_route, fallback_route


def _goose_warnings(command: str | None) -> list[str]:
    primary_route, _fallback_route = _goose_routes(command)
    if not primary_route or not primary_route.startswith("ollama/"):
        return []
    _, model = primary_route.split("/", 1)
    return _ollama_route_warnings(model)


def _ollama_route_warnings(model: str) -> list[str]:
    host = (os.getenv("OLLAMA_HOST") or "").rstrip("/")
    if not host:
        return ["ollama route selected but OLLAMA_HOST is not configured"]
    tags_url = f"{host}/api/tags"
    try:
        with urlopen(tags_url, timeout=2) as response:
            if response.status < 200 or response.status >= 300:
                return [f"ollama self-check returned HTTP {response.status}"]
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
        return [f"ollama self-check failed: {exc}"]
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return ["ollama self-check returned an unexpected payload"]
    available = {
        str(entry.get("name")).strip()
        for entry in models
        if isinstance(entry, dict) and entry.get("name")
    }
    if model not in available:
        return [f"ollama reachable but model `{model}` is not loaded"]
    return []


def _flag_value(tokens: list[str], flag: str) -> str | None:
    try:
        index = tokens.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1]


def _configured_goose_profile() -> tuple[str | None, str | None, str | None, str | None]:
    provider = os.getenv("GOOSE_PROVIDER") or None
    model = (
        os.getenv("GOOSE_MODEL")
        or os.getenv("HERMES_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("MINIMAX_MODEL")
        or None
    )
    openai_base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_HOST") or None
    if provider is None:
        hermes_provider = os.getenv("HERMES_INFERENCE_PROVIDER") or None
        if hermes_provider and hermes_provider.lower() != "auto":
            provider = hermes_provider
        elif hermes_provider and hermes_provider.lower() == "auto" and openai_base_url:
            provider = "openai"
        elif openai_base_url:
            provider = "openai"
    if provider == "openai" and model is None and openai_base_url:
        model = "MiniMax-M2.5"
    fallback_provider = os.getenv("GOOSE_FALLBACK_PROVIDER") or None
    fallback_model = os.getenv("GOOSE_FALLBACK_MODEL") or None
    if fallback_provider is None and openai_base_url:
        if provider != "openai":
            fallback_provider = "openai"
            fallback_model = (
                fallback_model
                or os.getenv("HERMES_FALLBACK_MODEL")
                or os.getenv("MINIMAX_MODEL")
                or "MiniMax-M2.5"
            )
    return provider, model, fallback_provider, fallback_model


def _url_responds(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return 200 <= response.status < 300
    except (URLError, ValueError, TimeoutError, OSError):
        return False


def _read_json_url(url: str) -> dict[str, object] | None:
    try:
        with urlopen(url, timeout=2) as response:
            if response.status < 200 or response.status >= 300:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, ValueError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _wait_for_url(url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _url_responds(url):
            return True
        time.sleep(0.5)
    return False


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
