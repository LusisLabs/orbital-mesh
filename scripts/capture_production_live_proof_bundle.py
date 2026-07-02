#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "mesh.production_live_proof_capture.v1"
TERMINAL_STAGES = {"completed", "failed", "cancelled", "no_trigger"}


def main() -> int:
    args = _parser().parse_args()
    output_dir = Path(args.output_dir)
    api_dir = output_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    base_url = args.base_url.rstrip("/")
    launcher_headers = _headers(args.operator_id, args.operator_roles)
    approver_headers = _headers(args.approver_id, args.approver_roles)
    launcher_only_headers = _headers(args.operator_id, "launcher")

    _wait_for_health(base_url, args.timeout_seconds)
    health = _capture("health", _request_json("GET", f"{base_url}/api/health", headers=launcher_headers), api_dir)
    readiness = _capture("readiness", _request_json("GET", f"{base_url}/api/readiness", headers=launcher_headers), api_dir)
    kill_switch = _capture(
        "kill-switch",
        _request_json("GET", f"{base_url}/api/kill-switch", headers=launcher_headers),
        api_dir,
    )

    target_run = _launch_and_complete(
        base_url,
        scenario_key=args.target_scenario_key,
        goal_id=args.goal_id,
        headers=launcher_headers,
        approver_headers=approver_headers,
        timeout_seconds=args.timeout_seconds,
    )
    denied_action = _request_json(
        "POST",
        f"{base_url}/api/runs/{target_run['run_id']}/steer",
        headers=launcher_only_headers,
        body={"command": "approve", "summary": "capture denied launcher-only approval"},
        allow_http_error=True,
    )
    denied_path = _capture("denied-action", denied_action, api_dir)
    target_paths = _capture_run_artifacts(base_url, api_dir, "target", target_run["run_id"], launcher_headers)

    if args.recreate_between_runs_command:
        _run_recreate_command(args.recreate_between_runs_command)
        _wait_for_health(base_url, args.timeout_seconds)
        health = _capture("health", _request_json("GET", f"{base_url}/api/health", headers=launcher_headers), api_dir)
        readiness = _capture("readiness", _request_json("GET", f"{base_url}/api/readiness", headers=launcher_headers), api_dir)
        kill_switch = _capture(
            "kill-switch",
            _request_json("GET", f"{base_url}/api/kill-switch", headers=launcher_headers),
            api_dir,
        )

    repeat_run = _launch_and_complete(
        base_url,
        scenario_key=args.repeat_scenario_key,
        goal_id=args.goal_id,
        headers=launcher_headers,
        approver_headers=approver_headers,
        timeout_seconds=args.timeout_seconds,
    )
    repeat_paths = _capture_run_artifacts(base_url, api_dir, "repeat", repeat_run["run_id"], launcher_headers)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "base_url": base_url,
        "target_run_id": target_run["run_id"],
        "repeat_run_id": repeat_run["run_id"],
        "health": str(health),
        "readiness": str(readiness),
        "kill_switch": str(kill_switch),
        "denied_action": str(denied_path),
        "target": {key: str(path) for key, path in target_paths.items()},
        "repeat": {key: str(path) for key, path in repeat_paths.items()},
    }
    manifest_path = _write_json(output_dir / "capture-manifest.json", manifest)

    bundle_result: dict[str, Any] | None = None
    if not args.skip_generate:
        bundle_result = _run_generator(args, manifest, output_dir)

    print(
        json.dumps(
            {
                "status": "captured" if bundle_result is None else bundle_result.get("status"),
                "manifest": str(manifest_path),
                "bundle": bundle_result,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if bundle_result is None or bundle_result.get("status") in {"pass", "partial"} else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture live API artifacts and generate a production live proof bundle.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--environment", default="pilot")
    parser.add_argument("--goal-id", default="goal_production_live_proof")
    parser.add_argument("--target-scenario-key", default="search_latency_regression")
    parser.add_argument("--repeat-scenario-key", default="kubernetes_crashloop_patch")
    parser.add_argument("--operator-id", default="mesh-live-proof-launcher@example.internal")
    parser.add_argument("--operator-roles", default="launcher,approver")
    parser.add_argument("--approver-id", default="mesh-live-proof-approver@example.internal")
    parser.add_argument("--approver-roles", default="approver")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--generator-script", default="scripts/generate_production_live_proof_bundle.py")
    parser.add_argument("--release-provenance", required=True)
    parser.add_argument("--release-runtime-binding", required=True)
    parser.add_argument("--on-call-drill", required=True)
    parser.add_argument("--ingress-url", default="https://mesh.pilot.local")
    parser.add_argument("--authenticated-ingress-ref", default="artifact://authenticated-ingress-deployment-proof.json")
    parser.add_argument("--credential-rotation-ref", default="rotation://mesh/pilot/live-proof")
    parser.add_argument("--rollback-ref", default="rollback://kubernetes/pilot/edge/api-gateway")
    parser.add_argument("--runtime-secret-ref", action="append", default=["secret://mesh/kubernetes-service-account"])
    parser.add_argument("--target-ref", default="kubernetes://pilot/edge/api-gateway")
    parser.add_argument("--repeat-target-ref", default="kubernetes://pilot/edge/repeatability")
    parser.add_argument("--healthy-target-ref", default="kubernetes://pilot/edge/healthy-control")
    parser.add_argument("--provider-failure-target-ref", default="kubernetes://pilot/edge/provider")
    parser.add_argument("--build-command", default="docker compose -f docker-compose.stack.yml -f docker-compose.e2estack.yml up -d --build mesh")
    parser.add_argument("--recreate-between-runs-command", default="")
    parser.add_argument("--clean-env-recreated", action="store_true")
    parser.add_argument("--fresh-image-built", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--skip-generate", action="store_true")
    return parser


def _launch_and_complete(
    base_url: str,
    *,
    scenario_key: str,
    goal_id: str,
    headers: dict[str, str],
    approver_headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "goal_id": goal_id,
        "scenario_key": scenario_key,
        "evaluation_mode": "native",
        "orchestration_mode": "native_hermes",
        "steering_mode": "approval_gate",
    }
    run = _request_json("POST", f"{base_url}/api/runs", headers=headers, body=payload)
    run_id = str(run["run_id"])
    deadline = time.monotonic() + timeout_seconds
    approved = False
    last_stage = ""
    while time.monotonic() < deadline:
        current = _request_json("GET", f"{base_url}/api/runs/{run_id}", headers=headers)
        stage = str(current.get("stage") or "")
        last_stage = stage
        artifacts = current.get("artifacts") if isinstance(current.get("artifacts"), dict) else {}
        evaluation = artifacts.get("evaluation") if isinstance(artifacts.get("evaluation"), dict) else {}
        if (
            not approved
            and stage in ("evaluation_ready", "awaiting_operator")
            and evaluation.get("passed") is True
            and evaluation.get("final_recommendation") == "execute"
        ):
            _request_json(
                "POST",
                f"{base_url}/api/runs/{run_id}/steer",
                headers=approver_headers,
                body={"command": "approve", "summary": "production live proof capture approval"},
            )
            approved = True
            time.sleep(0.5)
            continue
        if stage in TERMINAL_STAGES:
            if stage != "completed":
                raise SystemExit(f"run {run_id} reached terminal stage {stage}; expected completed")
            return current
        time.sleep(1.0)
    raise SystemExit(f"run {run_id} did not reach terminal stage before timeout; last_stage={last_stage}")


def _capture_run_artifacts(base_url: str, api_dir: Path, prefix: str, run_id: str, headers: dict[str, str]) -> dict[str, Path]:
    return {
        "run": _capture(f"{prefix}-{run_id}", _request_json("GET", f"{base_url}/api/runs/{run_id}", headers=headers), api_dir),
        "events": _capture(
            f"{prefix}-{run_id}-events",
            _request_json("GET", f"{base_url}/api/runs/{run_id}/events", headers=headers),
            api_dir,
        ),
        "export": _capture(
            f"{prefix}-{run_id}-export",
            _request_json("POST", f"{base_url}/api/runs/{run_id}/export", headers=headers, body={}),
            api_dir,
        ),
        "timeline": _capture(
            f"{prefix}-{run_id}-timeline-proof",
            _request_json("GET", f"{base_url}/api/runs/{run_id}/timeline-proof", headers=headers),
            api_dir,
        ),
        "merkle": _capture(
            f"{prefix}-{run_id}-merkle",
            _request_json("GET", f"{base_url}/api/runs/{run_id}/merkle", headers=headers),
            api_dir,
        ),
    }


def _run_generator(args: argparse.Namespace, manifest: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        args.generator_script,
        "--repo-root",
        args.repo_root,
        "--output-dir",
        str(output_dir),
        "--environment",
        args.environment,
        "--operator-id",
        args.operator_id,
        "--operator-identity-ref",
        f"proxy-header://X-Mesh-Operator/{args.operator_id}",
        "--approver-identity-ref",
        f"proxy-header://X-Mesh-Operator/{args.approver_id}",
        "--target-ref",
        args.target_ref,
        "--repeat-target-ref",
        args.repeat_target_ref,
        "--healthy-target-ref",
        args.healthy_target_ref,
        "--provider-failure-target-ref",
        args.provider_failure_target_ref,
        "--ingress-url",
        args.ingress_url,
        "--authenticated-ingress-ref",
        args.authenticated_ingress_ref,
        "--credential-rotation-ref",
        args.credential_rotation_ref,
        "--rollback-ref",
        args.rollback_ref,
        "--health",
        manifest["health"],
        "--readiness",
        manifest["readiness"],
        "--kill-switch",
        manifest["kill_switch"],
        "--denied-action",
        manifest["denied_action"],
        "--release-provenance",
        args.release_provenance,
        "--release-runtime-binding",
        args.release_runtime_binding,
        "--on-call-drill",
        args.on_call_drill,
        "--target-run-json",
        manifest["target"]["run"],
        "--target-events",
        manifest["target"]["events"],
        "--target-export",
        manifest["target"]["export"],
        "--target-timeline",
        manifest["target"]["timeline"],
        "--target-merkle",
        manifest["target"]["merkle"],
        "--repeat-run-json",
        manifest["repeat"]["run"],
        "--repeat-events",
        manifest["repeat"]["events"],
        "--repeat-export",
        manifest["repeat"]["export"],
        "--repeat-timeline",
        manifest["repeat"]["timeline"],
        "--repeat-merkle",
        manifest["repeat"]["merkle"],
        "--build-command",
        args.build_command,
        "--target-run-command",
        f"POST /api/runs scenario_key={args.target_scenario_key}",
        "--repeat-run-command",
        f"POST /api/runs scenario_key={args.repeat_scenario_key}",
    ]
    for secret_ref in args.runtime_secret_ref:
        command.extend(["--runtime-secret-ref", secret_ref])
    if args.clean_env_recreated:
        command.append("--clean-env-recreated")
    if args.fresh_image_built:
        command.append("--fresh-image-built")
    if args.allow_partial:
        command.append("--allow-partial")
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout or f"generator exited {completed.returncode}")
    return json.loads(completed.stdout)


def _run_recreate_command(command: str) -> None:
    completed = subprocess.run(command, shell=True, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        detail = completed.stderr or completed.stdout or f"command exited {completed.returncode}"
        raise SystemExit(f"recreate-between-runs command failed: {detail}")


def _wait_for_health(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + min(timeout_seconds, 120.0)
    while time.monotonic() < deadline:
        try:
            payload = _request_json("GET", f"{base_url}/api/health", headers={})
            if payload.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise SystemExit(f"{base_url}/api/health did not become healthy before timeout")


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    allow_http_error: bool = False,
) -> dict[str, Any]:
    data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        if not allow_http_error:
            raise
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"body": raw}
        payload["http_status"] = exc.code
        payload["url"] = url
        return payload


def _capture(name: str, payload: dict[str, Any], output_dir: Path) -> Path:
    return _write_json(output_dir / f"{name}.json", payload)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _headers(operator_id: str, roles: str) -> dict[str, str]:
    return {"X-Mesh-Operator": operator_id, "X-Mesh-Roles": roles}


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
