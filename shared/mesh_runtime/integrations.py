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


DEFAULT_GITNEXUS_PORT = 4747
# GitNexus exposes `/api/heartbeat` as SSE (long-lived); use `/api/info` for probes and readiness.
GITNEXUS_LIVENESS_PATH = "/api/info"
PROMPTFOO_BRIDGE_MODULE = "services.evaluation.promptfoo_bridge"
GOOSE_BRIDGE_MODULE = "services.orchestrator.goose_bridge"
GOOSE_MODEL_PREFERENCE = (
    "gemma4:31b-it-q4_K_M",
    "qwen2.5:0.5b",
    "qwen2.5:latest",
    "glm-4.7-flash:latest",
)


@dataclass
class IntegrationsConfig:
    promptfoo_command: str | None = None
    goose_command: str | None = None
    gitnexus_sidecar_url: str | None = None
    gitnexus_sidecar_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "promptfoo_command": self.promptfoo_command,
            "goose_command": self.goose_command,
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
        goose_command=raw.get("goose_command"),
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
        git_command = runtime_config.gitnexus_sidecar_command or loaded.gitnexus_sidecar_command
    else:
        git_command = (
            runtime_config.gitnexus_sidecar_command
            or loaded.gitnexus_sidecar_command
            or _default_gitnexus_command()
        )
    return IntegrationsConfig(
        promptfoo_command=_resolve_promptfoo_command(runtime_config.promptfoo_command or loaded.promptfoo_command),
        goose_command=_resolve_goose_command(runtime_config.goose_command or loaded.goose_command),
        gitnexus_sidecar_url=runtime_config.gitnexus_sidecar_url
        or loaded.gitnexus_sidecar_url
        or f"http://127.0.0.1:{DEFAULT_GITNEXUS_PORT}",
        gitnexus_sidecar_command=git_command,
    )


def build_readiness(runtime_config: RuntimeConfig) -> IntegrationReadiness:
    resolved = resolve_integrations_config(runtime_config)
    checked_at = _timestamp()
    gitnexus_ready = (
        _url_responds(f"{resolved.gitnexus_sidecar_url.rstrip('/')}{GITNEXUS_LIVENESS_PATH}")
        if resolved.gitnexus_sidecar_url
        else False
    )
    promptfoo_status = _command_status("promptfoo", resolved.promptfoo_command)
    goose_status = _command_status("goose", resolved.goose_command)
    gitnexus_status = IntegrationStatus(
        name="gitnexus",
        ready=gitnexus_ready,
        detail="sidecar reachable" if gitnexus_ready else "sidecar unavailable",
        command=resolved.gitnexus_sidecar_command,
        url=resolved.gitnexus_sidecar_url,
    )
    return IntegrationReadiness(
        checked_at=checked_at,
        promptfoo=promptfoo_status,
        goose=goose_status,
        gitnexus=gitnexus_status,
        vault_path=runtime_config.vault_path,
        state_path=runtime_config.state_directory,
        integrations_config_path=runtime_config.integrations_config_path,
    )


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
        log_handle = stdout_path.open("a")
        # Repo root is two levels above this package (shared/mesh_runtime).
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


def bootstrap_integrations(runtime_config: RuntimeConfig, install_missing: bool = False) -> dict[str, Any]:
    actions: list[str] = []
    if install_missing and not shutil.which("promptfoo") and shutil.which("npm"):
        subprocess.run(["npm", "install", "-g", "promptfoo"], check=False)
        actions.append("attempted global promptfoo install via npm")
    if install_missing and not shutil.which("goose") and shutil.which("brew"):
        subprocess.run(["brew", "install", "block-goose-cli"], check=False)
        actions.append("attempted Goose CLI install via Homebrew")

    current = resolve_integrations_config(runtime_config)
    goose_detail = _describe_goose_command(current.goose_command)
    if goose_detail:
        actions.append(goose_detail)
    goose_warnings = _goose_warnings(current.goose_command)
    for warning in goose_warnings:
        actions.append(f"warning: {warning}")

    save_integrations_config(runtime_config.integrations_config_path, current)

    smoke_checks = {
        "promptfoo": _smoke_check_with_fallback(current.promptfoo_command, [["--healthcheck"], ["--version"]]),
        "goose": _smoke_check_with_fallback(current.goose_command, [["--healthcheck"], ["--version"]]),
    }
    guidance = {
        "promptfoo": (
            "Install with `npm install -g promptfoo` if missing. "
            "The bridge command runs a local Promptfoo eval and returns the mesh evaluation contract."
        ),
        "goose": (
            "Install Goose CLI from the official Block Goose distribution if missing. "
            "If you want a local path without vendor credentials, install Ollama and pull a small model such as "
            "`qwen2.5:0.5b`, then rerun `python3 setup_integrations.py`."
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


def _default_gitnexus_command() -> str | None:
    """Return a GitNexus CLI launch command only when the vendor tree is present."""
    here = Path(__file__).resolve()
    candidate_roots = (here.parents[2], here.parents[3])
    for root in candidate_roots:
        tsx = root / "GitNexus" / "gitnexus" / "node_modules" / ".bin" / "tsx"
        cli_entry = root / "GitNexus" / "gitnexus" / "src" / "cli" / "index.ts"
        if tsx.is_file() and cli_entry.is_file():
            return (
                f"{tsx} {cli_entry} serve --host 127.0.0.1 --port {DEFAULT_GITNEXUS_PORT}"
            )
    return None


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


def _smoke_check(command: str | None, extra_args: list[str]) -> tuple[bool, str]:
    if not command:
        return False, "command not configured"
    try:
        completed = subprocess.run(
            shlex.split(command) + extra_args,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
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


def _resolve_goose_command(command: str | None) -> str | None:
    if command and GOOSE_BRIDGE_MODULE in command:
        return command
    discovered = _resolve_vendor_binary(command, "goose")
    if discovered is None:
        return command
    provider, model, fallback_provider, fallback_model = _configured_goose_profile()
    if provider is None and model is None:
        provider, model = _discover_goose_profile(discovered)
    return _build_goose_bridge_command(
        discovered,
        provider=provider,
        model=model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
    )


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
    model = os.getenv("GOOSE_MODEL") or os.getenv("HERMES_MODEL") or os.getenv("LLM_MODEL") or None
    if provider is None:
        hermes_provider = os.getenv("HERMES_INFERENCE_PROVIDER") or None
        if hermes_provider and hermes_provider.lower() != "auto":
            provider = hermes_provider
        elif hermes_provider and hermes_provider.lower() == "auto" and os.getenv("OPENAI_BASE_URL"):
            provider = "openai"
    fallback_provider = os.getenv("GOOSE_FALLBACK_PROVIDER") or None
    fallback_model = os.getenv("GOOSE_FALLBACK_MODEL") or None
    if fallback_provider is None and os.getenv("OPENAI_BASE_URL"):
        if provider != "openai":
            fallback_provider = "openai"
            fallback_model = fallback_model or os.getenv("HERMES_FALLBACK_MODEL") or "MiniMax-M2.5"
    return provider, model, fallback_provider, fallback_model


def _discover_goose_profile(goose_bin: str) -> tuple[str | None, str | None]:
    ollama_bin = shutil.which("ollama")
    if ollama_bin:
        models = _list_ollama_models(ollama_bin)
        preferred = [model for model in GOOSE_MODEL_PREFERENCE if model in models]
        fallbacks = [model for model in models if model not in preferred]
        for model in preferred + fallbacks:
            if _probe_goose_profile(goose_bin, provider="ollama", model=model):
                return "ollama", model
    if _probe_goose_profile(goose_bin, provider=None, model=None):
        return None, None
    return None, None


def _list_ollama_models(ollama_bin: str) -> list[str]:
    try:
        completed = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    models: list[str] = []
    for line in completed.stdout.splitlines():
        columns = line.split()
        if not columns or columns[0] == "NAME":
            continue
        models.append(columns[0])
    return models


def _probe_goose_profile(goose_bin: str, provider: str | None, model: str | None) -> bool:
    command = [
        goose_bin,
        "run",
        "--text",
        "Reply with OK.",
        "--no-session",
        "--quiet",
        "--output-format",
        "json",
    ]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    return '"assistant"' in completed.stdout or '"role": "assistant"' in completed.stdout


def _url_responds(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return 200 <= response.status < 300
    except (URLError, ValueError):
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
