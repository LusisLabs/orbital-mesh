from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .config import RuntimeConfig
from .control_plane_models import IntegrationReadiness, IntegrationStatus


PROMPTFOO_BRIDGE_MODULE = "services.evaluation.promptfoo_bridge"
HERMES_BRIDGE_MODULE = "services.orchestrator.hermes_bridge"
GOOSE_BRIDGE_MODULE = "services.orchestrator.goose_bridge"


@dataclass
class IntegrationsConfig:
    promptfoo_command: str | None = None
    hermes_command: str | None = None
    goose_command: str | None = None
    evo_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "promptfoo_command": self.promptfoo_command,
            "hermes_command": self.hermes_command,
            "goose_command": self.goose_command,
            "evo_command": self.evo_command,
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
    )


def save_integrations_config(path: str | Path, config: IntegrationsConfig) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n")


def resolve_integrations_config(runtime_config: RuntimeConfig) -> IntegrationsConfig:
    loaded = load_integrations_config(runtime_config.integrations_config_path)
    return IntegrationsConfig(
        promptfoo_command=_resolve_promptfoo_command(runtime_config.promptfoo_command or loaded.promptfoo_command),
        hermes_command=_resolve_hermes_command(runtime_config.hermes_command or loaded.hermes_command),
        goose_command=_resolve_goose_command(runtime_config.goose_command or loaded.goose_command),
        evo_command=_resolve_evo_command(runtime_config.evo_command or loaded.evo_command),
    )


def build_readiness(runtime_config: RuntimeConfig) -> IntegrationReadiness:
    resolved = resolve_integrations_config(runtime_config)
    checked_at = _timestamp()
    promptfoo_status = _command_status("promptfoo", resolved.promptfoo_command)
    hermes_status = _command_status("hermes", resolved.hermes_command)
    goose_status = _command_status("goose", resolved.goose_command)
    evo_status = build_evo_status(runtime_config, resolved.evo_command)
    latentmas_status = _latentmas_status(runtime_config)
    deepagents_status = _deepagents_status(runtime_config)
    return IntegrationReadiness(
        checked_at=checked_at,
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
            "`uv run --project /workspace/mesh-intelligence/evo/plugins/evo evo`. Mesh only probes "
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


def _command_status(name: str, command: str | None) -> IntegrationStatus:
    if not command:
        return IntegrationStatus(name=name, ready=False, detail="command not configured")
    executable = shlex.split(command)[0]
    binary = executable if os.path.isabs(executable) else shutil.which(executable)
    if binary is None and not Path(executable).exists():
        return IntegrationStatus(name=name, ready=False, detail="command not found", command=command)
    if name == "goose":
        ok, detail = _smoke_check(command, ["--version"])
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
        ok, detail = _smoke_check_with_fallback(command, [["--healthcheck"], ["--version"]])
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
    if lower.startswith("openai:") and not (os.getenv("OPENAI_API_KEY") or "").strip():
        warnings.append("OPENAI_API_KEY is not set for openai Deep Agents models")
    if lower.startswith("anthropic:") and not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        warnings.append("ANTHROPIC_API_KEY is not set for anthropic Deep Agents models")
    return warnings


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
    ready = _url_responds(health_url)
    return IntegrationStatus(
        name="latentmas",
        ready=ready,
        detail="sidecar reachable" if ready else "sidecar unavailable",
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


def _smoke_check_with_fallback(command: str | None, arg_sets: list[list[str]]) -> tuple[bool, str]:
    last_detail = "command not configured"
    for extra_args in arg_sets:
        ok, detail = _smoke_check(command, extra_args)
        if ok:
            return ok, detail
        last_detail = detail
    return False, last_detail


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


def _wait_for_url(url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _url_responds(url):
            return True
        time.sleep(0.5)
    return False


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
