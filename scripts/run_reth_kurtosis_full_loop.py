#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.ingest.bare_metal_node import BareMetalNodeTarget, RethNodeIngester
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase
from shared.mesh_runtime.incident_corpus import write_cycle_corpus_artifacts


STATE_DIR = REPO_ROOT / ".mesh-runtime-state" / "reth-kurtosis-loop"
CORPUS_DB_PATH = Path(os.environ.get("MESH_CORPUS_DATABASE_PATH", REPO_ROOT / ".mesh-runtime-state" / "corpus" / "incident_corpus.sqlite"))
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_ENCLAVE = "mesh-reth"
DEFAULT_SERVICE = "el-1-reth-lighthouse"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_repo_dotenv() -> None:
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or " " in key or key in os.environ:
            continue
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        os.environ[key] = os.path.expanduser(os.path.expandvars(value))


def _run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _server_healthy(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_server_if_needed(base_url: str, session_dir: Path) -> subprocess.Popen[str] | None:
    if _server_healthy(base_url):
        return None
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8787)
    env = os.environ.copy()
    env.setdefault("MESH_SERVER_HOST", host)
    env.setdefault("MESH_SERVER_PORT", port)
    env.setdefault("MESH_OBSERVER_ENABLED", "1" if _observer_possible() else "0")
    env.setdefault("MESH_EVALUATION_MODE", "native")
    env.setdefault("MESH_ORCHESTRATION_MODE", "native_hermes")
    env.setdefault("MESH_KURTOSIS_EXECUTION_ENABLED", "1")
    env.setdefault("MESH_KURTOSIS_ALLOWED_ENCLAVES", os.environ.get("MESH_KURTOSIS_ENCLAVE", DEFAULT_ENCLAVE))
    env.setdefault("MESH_KURTOSIS_ALLOWED_SERVICES", os.environ.get("MESH_KURTOSIS_SERVICE", DEFAULT_SERVICE))
    env.setdefault("MESH_KURTOSIS_HOME", os.environ.get("MESH_KURTOSIS_HOME", str(Path.home())))
    if os.environ.get("RETH_KURTOSIS_AUTONOMOUS_REMEDIATION", "").lower() in {"1", "true", "yes"}:
        env["MESH_KURTOSIS_AUTONOMOUS_RESTART_ENABLED"] = "1"
    log_path = session_dir / "control-plane.log"
    log_file = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "run_server.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        if _server_healthy(base_url):
            return proc
        time.sleep(1)
    raise RuntimeError(f"control plane did not become healthy; inspect {log_path}")


def _observer_possible() -> bool:
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


def _kurtosis_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = os.path.expanduser(os.path.expandvars(os.environ.get("MESH_KURTOSIS_HOME", str(Path.home()))))
    _normalize_docker_host(env)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def _normalize_docker_host(env: dict[str, str]) -> None:
    docker_host = env.get("DOCKER_HOST", "")
    desktop_socket = Path.home() / ".docker" / "run" / "docker.sock"
    if docker_host and docker_host != "unix:///var/run/docker.sock":
        return
    if Path("/var/run/docker.sock").exists():
        return
    if desktop_socket.exists():
        env["DOCKER_HOST"] = f"unix://{desktop_socket}"


def _ensure_enclave(session_dir: Path, enclave: str, service: str) -> None:
    try:
        _inspect_service(enclave, service)
        return
    except Exception:
        pass
    env = _kurtosis_env()
    script = REPO_ROOT / "scripts" / "run_reth_kurtosis_smoke.sh"
    log_path = session_dir / "kurtosis-bootstrap.log"
    with log_path.open("a", encoding="utf-8") as log_file:
        proc = subprocess.run(
            [str(script)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1800,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"kurtosis bootstrap failed; inspect {log_path}")


def _inspect_service(enclave: str, service: str) -> str:
    env = _kurtosis_env()
    kurtosis_bin = os.environ.get("MESH_KURTOSIS_COMMAND", "kurtosis")
    proc = _run([kurtosis_bin, "service", "inspect", enclave, service], env=env, timeout=120)
    return proc.stdout


def _discover_urls(enclave: str, service: str) -> tuple[str, str | None]:
    text = _inspect_service(enclave, service)
    rpc_match = re.search(r"(?m)^\s*rpc:\s+\S+\s+->\s+([^\s]+)", text)
    metrics_match = re.search(r"(?m)^\s*metrics:\s+\S+\s+->\s+([^\s]+)", text)
    if not rpc_match:
        raise RuntimeError(f"could not find rpc port for {service} in Kurtosis inspect output")
    return _httpize(rpc_match.group(1)), _httpize(metrics_match.group(1)) if metrics_match else None


def _httpize(value: str) -> str:
    text = value.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return f"http://{text}"


def _base_target(enclave: str, service: str, rpc_url: str, metrics_url: str | None) -> BareMetalNodeTarget:
    return BareMetalNodeTarget.from_dict(
        {
            "name": service,
            "kind": "reth",
            "rpc_url": rpc_url,
            "host": service,
            "service": "reth.service",
            "region": "kurtosis-local",
            "deployment_mode": "docker",
            "network": "kurtosis",
            "role": "full",
            "consensus_client": "lighthouse",
            "min_peer_count": 0,
            "max_block_lag": 32,
            "metrics_url": metrics_url,
            "kurtosis_enclave": enclave,
            "kurtosis_service": service,
        }
    )


def _healthy_signal(target: BareMetalNodeTarget) -> dict[str, Any]:
    signal, metadata = _collect_live_signal(target)
    if signal is None:
        raise RuntimeError(f"live Reth signal collection failed after {metadata['attempts']} attempts")
    return signal


def _collect_live_signal(target: BareMetalNodeTarget) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    timeout_seconds = int(os.environ.get("RETH_KURTOSIS_SIGNAL_TIMEOUT_SECONDS", "180"))
    retry_seconds = max(1, int(os.environ.get("RETH_KURTOSIS_SIGNAL_RETRY_SECONDS", "3")))
    deadline = time.time() + max(0, timeout_seconds)
    attempts = 0
    url_refreshes: list[dict[str, Any]] = []
    while True:
        attempts += 1
        signal = RethNodeIngester(target).build_signal()
        if signal is not None:
            return signal, {
                "attempts": attempts,
                "status": "collected",
                "timeout_seconds": timeout_seconds,
                "retry_seconds": retry_seconds,
                "rpc_url": target.rpc_url,
                "url_refreshes": url_refreshes,
            }
        refreshed = _refresh_target_urls(target)
        if refreshed is not None:
            url_refreshes.append(refreshed)
            if refreshed.get("changed"):
                continue
        if time.time() >= deadline:
            return None, {
                "attempts": attempts,
                "status": "unavailable",
                "timeout_seconds": timeout_seconds,
                "retry_seconds": retry_seconds,
                "rpc_url": target.rpc_url,
                "url_refreshes": url_refreshes,
            }
        time.sleep(retry_seconds)


def _refresh_target_urls(target: BareMetalNodeTarget) -> dict[str, Any] | None:
    if not target.kurtosis_enclave or not target.kurtosis_service:
        return None
    before = {"rpc_url": target.rpc_url, "metrics_url": target.metrics_url}
    try:
        rpc_url, metrics_url = _discover_urls(target.kurtosis_enclave, target.kurtosis_service)
    except Exception as exc:
        return {"status": "failed", "error": str(exc), **before}
    target.rpc_url = rpc_url
    target.metrics_url = metrics_url
    after = {"rpc_url": target.rpc_url, "metrics_url": target.metrics_url}
    return {"status": "refreshed", "changed": before != after, "before": before, "after": after}


def _fault_profiles() -> list[dict[str, Any]]:
    return [
        {"name": "healthy_baseline", "kind": "baseline"},
        {"name": "peer_starvation_restart", "kind": "overlay", "peer_count": 1, "min_peer_count": 3},
        {"name": "sync_stalled_restart", "kind": "overlay", "syncing": True, "block_lag": 128},
        {"name": "rpc_degraded_restart", "kind": "overlay", "error_rate": 0.12},
        {"name": "consensus_disconnect_escalate", "kind": "overlay", "engine_api_reachable": False, "forkchoice_updates_recent": False},
        {"name": "disk_pressure_escalate", "kind": "overlay", "disk_used_pct": 97.0},
        {"name": "jwt_missing_escalate", "kind": "overlay", "jwt_configured": False, "jwt_secret_exists": False},
        {"name": "rpc_exposed_escalate", "kind": "overlay", "rpc_exposed": True, "authrpc_exposed": True},
    ]


def _apply_profile(signal: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(signal)
    if profile["kind"] == "baseline":
        payload.setdefault("logs", {}).setdefault("error_signatures", [])
        return payload
    if "peer_count" in profile:
        payload["execution"]["peer_count"] = int(profile["peer_count"])
    if "min_peer_count" in profile:
        payload["execution"]["min_peer_count"] = int(profile["min_peer_count"])
        payload.setdefault("related_context", {}).setdefault("execution", {})["min_peer_count"] = int(profile["min_peer_count"])
        payload.setdefault("resource_attributes", {})["mesh.node.min_peer_count"] = int(profile["min_peer_count"])
    if "syncing" in profile:
        payload["execution"]["syncing"] = bool(profile["syncing"])
    if "block_lag" in profile:
        payload["execution"]["block_lag"] = int(profile["block_lag"])
    if "error_rate" in profile:
        payload["rpc"]["error_rate"] = float(profile["error_rate"])
    if "engine_api_reachable" in profile:
        payload["consensus"]["engine_api_reachable"] = bool(profile["engine_api_reachable"])
    if "forkchoice_updates_recent" in profile:
        payload["consensus"]["forkchoice_updates_recent"] = bool(profile["forkchoice_updates_recent"])
    if "disk_used_pct" in profile:
        payload["storage"]["disk_used_pct"] = float(profile["disk_used_pct"])
    if "jwt_configured" in profile:
        payload["consensus"]["jwt_configured"] = bool(profile["jwt_configured"])
    if "jwt_secret_exists" in profile:
        payload["consensus"]["jwt_secret_exists"] = bool(profile["jwt_secret_exists"])
    if "rpc_exposed" in profile:
        payload["rpc"]["publicly_exposed"] = bool(profile["rpc_exposed"])
    if "authrpc_exposed" in profile:
        payload["rpc"]["authrpc_publicly_exposed"] = bool(profile["authrpc_exposed"])
    payload["signal_id"] = f"{payload['signal_id']}_{profile['name']}"
    return payload


def _launch_run(base_url: str, signal_payload: dict[str, Any]) -> dict[str, Any]:
    return _http_json(
        "POST",
        f"{base_url.rstrip('/')}/api/runs",
        {
            "signal_payload": signal_payload,
            "evaluation_mode": os.environ.get("MESH_EVALUATION_MODE", "native"),
            "orchestration_mode": os.environ.get("MESH_ORCHESTRATION_MODE", "native_hermes"),
            "steering_mode": "interruptible_auto",
        },
        timeout=60,
    )


def _wait_for_run(base_url: str, run_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = _http_json("GET", f"{base_url.rstrip('/')}/api/runs/{run_id}", timeout=30)
        stage = str(run.get("stage") or "")
        if stage in {"completed", "failed", "cancelled", "no_trigger", "recovery_spawned"}:
            return run
        evaluation = ((run.get("artifacts") or {}).get("evaluation") or {})
        if stage in {"evaluation_ready", "awaiting_operator"} and evaluation.get("final_recommendation") != "execute":
            return run
        time.sleep(2)
    raise RuntimeError(f"run {run_id} did not finish within {timeout_seconds}s")


def _fetch_run_artifacts(base_url: str, run_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for suffix in ("", "/events", "/scenario-analysis", "/evidence-graph", "/merkle"):
        url = f"{base_url.rstrip('/')}/api/runs/{run_id}{suffix}"
        key = "run" if not suffix else suffix.strip("/").replace("-", "_")
        try:
            out[key] = _http_json("GET", url, timeout=30)
        except Exception as exc:
            out[key] = {"error": str(exc)}
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_corpus_cycle(cycle_dir: Path, session_dir: Path) -> None:
    row = write_cycle_corpus_artifacts(cycle_dir, session_dir=session_dir)
    IncidentCorpusDatabase(CORPUS_DB_PATH).upsert_row(row)


def _cycle_status(final_run: dict[str, Any]) -> str | None:
    artifacts = final_run.get("artifacts") or {}
    evaluation = artifacts.get("evaluation") or {}
    execution = artifacts.get("execution") or {}
    recommendation = evaluation.get("final_recommendation")
    if recommendation and recommendation != "execute" and not execution:
        return "policy_held"
    return final_run.get("status")


def _cycle(session_dir: Path, base_url: str, target: BareMetalNodeTarget, profile: dict[str, Any], index: int) -> None:
    cycle_dir = session_dir / f"{index:06d}_{profile['name']}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    healthy, signal_metadata = _collect_live_signal(target)
    _write_json(cycle_dir / "signal_collection.json", signal_metadata)
    if healthy is None:
        summary = {
            "cycle": index,
            "profile": profile["name"],
            "run_id": None,
            "stage": "signal_unavailable",
            "status": "skipped",
            "decision_type": None,
            "execution_status": None,
            "feedback_outcome": None,
            "timestamp": _now(),
        }
        _write_json(cycle_dir / "summary.json", summary)
        _write_corpus_cycle(cycle_dir, session_dir)
        _write_session_report(session_dir)
        print(json.dumps(summary), flush=True)
        return
    payload = _apply_profile(healthy, profile)
    _write_json(cycle_dir / "live_signal.json", healthy)
    _write_json(cycle_dir / "signal_payload.json", payload)
    created = _launch_run(base_url, payload)
    run_id = created["run_id"]
    final_run = _wait_for_run(base_url, run_id, timeout_seconds=int(os.environ.get("RETH_KURTOSIS_RUN_TIMEOUT_SECONDS", "240")))
    _write_json(cycle_dir / "run_create.json", created)
    _write_json(cycle_dir / "run_final.json", final_run)
    artifacts = _fetch_run_artifacts(base_url, run_id)
    for name, body in artifacts.items():
        _write_json(cycle_dir / f"{name}.json", body)
    summary = {
        "cycle": index,
        "profile": profile["name"],
        "run_id": run_id,
        "stage": final_run.get("stage"),
        "status": _cycle_status(final_run),
        "decision_type": ((final_run.get("artifacts") or {}).get("decision") or {}).get("decision_type"),
        "evaluation_recommendation": ((final_run.get("artifacts") or {}).get("evaluation") or {}).get("final_recommendation"),
        "execution_status": ((final_run.get("artifacts") or {}).get("execution") or {}).get("status"),
        "feedback_outcome": ((final_run.get("artifacts") or {}).get("feedback") or {}).get("outcome"),
        "timestamp": _now(),
    }
    _write_json(cycle_dir / "summary.json", summary)
    _write_corpus_cycle(cycle_dir, session_dir)
    _write_session_report(session_dir)
    print(json.dumps(summary), flush=True)


def _write_session_report(session_dir: Path) -> None:
    summaries = []
    signal_refreshes = 0
    for summary_path in sorted(session_dir.glob("[0-9][0-9][0-9][0-9][0-9][0-9]_*/*summary.json")):
        summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
        signal_path = summary_path.parent / "signal_collection.json"
        if signal_path.is_file():
            signal_payload = json.loads(signal_path.read_text(encoding="utf-8"))
            signal_refreshes += sum(
                1 for refresh in signal_payload.get("url_refreshes", []) if refresh.get("changed")
            )
    counts = {
        "total_cycles": len(summaries),
        "baseline_no_trigger_count": sum(
            1 for item in summaries if item.get("profile") == "healthy_baseline" and item.get("stage") == "no_trigger"
        ),
        "restart_decisions": sum(1 for item in summaries if item.get("decision_type") == "restart_systemd_service"),
        "successful_executions": sum(1 for item in summaries if item.get("execution_status") == "succeeded"),
        "policy_held_escalations": sum(1 for item in summaries if item.get("status") == "policy_held"),
        "signal_refreshes": signal_refreshes,
        "skipped_cycles": sum(1 for item in summaries if item.get("status") == "skipped"),
        "failed_cycles": sum(
            1 for item in summaries if item.get("status") == "failed" or item.get("stage") == "failed"
        ),
    }
    report = {
        "generated_at": _now(),
        "session_dir": str(session_dir),
        "counts": counts,
        "cycles": summaries,
    }
    _write_json(session_dir / "run_report.json", report)
    lines = [
        "# Reth Kurtosis Full-Loop Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- total_cycles: `{counts['total_cycles']}`",
        f"- baseline_no_trigger_count: `{counts['baseline_no_trigger_count']}`",
        f"- restart_decisions: `{counts['restart_decisions']}`",
        f"- successful_executions: `{counts['successful_executions']}`",
        f"- policy_held_escalations: `{counts['policy_held_escalations']}`",
        f"- signal_refreshes: `{counts['signal_refreshes']}`",
        f"- skipped_cycles: `{counts['skipped_cycles']}`",
        f"- failed_cycles: `{counts['failed_cycles']}`",
        "",
        "## Cycles",
        "",
    ]
    for item in summaries:
        lines.append(
            "- "
            f"cycle={item.get('cycle')} profile={item.get('profile')} status={item.get('status')} "
            f"stage={item.get('stage')} decision={item.get('decision_type')} "
            f"execution={item.get('execution_status')} feedback={item.get('feedback_outcome')}"
        )
    (session_dir / "run_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--enclave", default=os.environ.get("MESH_KURTOSIS_ENCLAVE", DEFAULT_ENCLAVE))
    parser.add_argument("--service", default=os.environ.get("MESH_KURTOSIS_SERVICE", DEFAULT_SERVICE))
    parser.add_argument("--interval-seconds", type=int, default=int(os.environ.get("RETH_KURTOSIS_INTERVAL_SECONDS", "20")))
    parser.add_argument("--duration-seconds", type=int, default=int(os.environ.get("RETH_KURTOSIS_DURATION_SECONDS", "0")))
    parser.add_argument("--seed", type=int, default=int(os.environ.get("RETH_KURTOSIS_SEED", "42")))
    parser.add_argument(
        "--autonomous-remediation",
        action="store_true",
        default=os.environ.get("RETH_KURTOSIS_AUTONOMOUS_REMEDIATION", "").lower() in {"1", "true", "yes"},
        help="Permit local Kurtosis restart execution when evaluation returns execute.",
    )
    args = parser.parse_args()

    _load_repo_dotenv()
    if args.autonomous_remediation:
        os.environ["RETH_KURTOSIS_AUTONOMOUS_REMEDIATION"] = "1"
        os.environ["MESH_KURTOSIS_AUTONOMOUS_RESTART_ENABLED"] = "1"
    random.seed(args.seed)
    session_dir = STATE_DIR / f"session_{_now()}"
    session_dir.mkdir(parents=True, exist_ok=True)
    _ensure_enclave(session_dir, args.enclave, args.service)
    rpc_url, metrics_url = _discover_urls(args.enclave, args.service)
    target = _base_target(args.enclave, args.service, rpc_url, metrics_url)
    server_proc = _start_server_if_needed(args.base_url, session_dir)
    _write_json(
        session_dir / "session_manifest.json",
        {
            "started_at": _now(),
            "base_url": args.base_url,
            "enclave": args.enclave,
            "service": args.service,
            "rpc_url": rpc_url,
            "metrics_url": metrics_url,
            "observer_enabled": os.environ.get("MESH_OBSERVER_ENABLED", ""),
            "autonomous_remediation": bool(args.autonomous_remediation),
            "kurtosis_autonomous_restart_enabled": os.environ.get("MESH_KURTOSIS_AUTONOMOUS_RESTART_ENABLED", ""),
            "server_spawned": bool(server_proc),
            "profiles": [p["name"] for p in _fault_profiles()],
        },
    )

    start = time.time()
    profiles = _fault_profiles()
    cycle = 0
    try:
        while True:
            profile = profiles[cycle % len(profiles)]
            _cycle(session_dir, args.base_url, target, profile, cycle)
            cycle += 1
            if args.duration_seconds > 0 and (time.time() - start) >= args.duration_seconds:
                return
            time.sleep(max(1, args.interval_seconds))
    finally:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()


if __name__ == "__main__":
    main()
