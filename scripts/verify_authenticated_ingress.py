#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig


OPERATOR_HEADER = "X-Mesh-Operator"
ROLES_HEADER = "X-Mesh-Roles"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse app-level operator identity and role gates behind authenticated ingress."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--state-dir", help="Use this scratch state directory instead of a temp directory.")
    args = parser.parse_args()

    try:
        payload = run_rehearsal(state_dir=args.state_dir)
    except Exception as exc:  # noqa: BLE001 - CLI proof harness reports hard failures as JSON.
        payload = {
            "schema_version": "mesh.authenticated_ingress_rehearsal.v1",
            "status": "failed",
            "error": str(exc),
        }
        _emit(payload, json_mode=args.json)
        return 1

    _emit(payload, json_mode=args.json)
    return 0 if payload["status"] == "passed" else 1


def run_rehearsal(*, state_dir: str | None = None) -> dict[str, Any]:
    temp_dir_path: Path | None = None
    if state_dir is None:
        temp_dir_path = Path(tempfile.mkdtemp(prefix="mesh-authenticated-ingress-"))
        state_dir = str(temp_dir_path)
    base = Path(state_dir)
    server = None
    thread = None
    checks: list[dict[str, Any]] = []
    run_id: str | None = None
    try:
        config = RuntimeConfig(
            state_directory=str(base / "state"),
            vault_path=str(base / "vault"),
            integrations_config_path=str(base / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            evaluation_mode="native",
            orchestration_mode="native_hermes",
            default_steering_mode="approval_gate",
            operator_identity_required=True,
            operator_header_name=OPERATOR_HEADER,
            operator_roles_header_name=ROLES_HEADER,
            feature_flag_credentials_available=False,
            incident_credentials_available=False,
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
            evo_command="/missing/evo",
            vault_mirror_mode="sync",
            run_worker_count=1,
        )
        server, thread = start_server_in_thread(config, start_sidecar=False)
        base_url = f"http://127.0.0.1:{server.server_address[1]}"

        run_payload = {
            "scenario_key": "search_latency_regression",
            "evaluation_mode": "native",
            "orchestration_mode": "native_hermes",
            "steering_mode": "approval_gate",
        }
        anonymous_run = _request_json(base_url, "POST", "/api/runs", run_payload)
        checks.append(
            _check(
                "anonymous_run_creation_denied",
                anonymous_run["status"] == 401,
                f"status={anonymous_run['status']}",
            )
        )

        viewer_run = _request_json(
            base_url,
            "POST",
            "/api/runs",
            run_payload,
            headers=_headers("ingress-viewer@example.com", "viewer"),
        )
        checks.append(
            _check(
                "viewer_run_creation_denied",
                viewer_run["status"] == 403,
                f"status={viewer_run['status']}",
            )
        )

        viewer_simulation = _request_json(
            base_url,
            "POST",
            "/api/policy/simulate",
            {"scenario_key": "search_latency_regression"},
            headers=_headers("ingress-viewer@example.com", "viewer"),
        )
        checks.append(
            _check(
                "viewer_policy_simulation_accepted",
                viewer_simulation["status"] == 200
                and viewer_simulation["body"].get("mutates") is False
                and viewer_simulation["body"].get("triggered") is True,
                f"status={viewer_simulation['status']}",
            )
        )

        launcher_run = _request_json(
            base_url,
            "POST",
            "/api/runs",
            run_payload,
            headers=_headers("ingress-launcher@example.com", "launcher"),
        )
        launcher_body = launcher_run["body"]
        operator = launcher_body.get("artifacts", {}).get("operator", {})
        run_id = launcher_body.get("run_id")
        checks.append(
            _check(
                "launcher_run_creation_accepted",
                launcher_run["status"] == 201
                and operator.get("operator_id") == "ingress-launcher@example.com"
                and operator.get("roles") == ["launcher"]
                and operator.get("source") == "proxy_header"
                and isinstance(run_id, str),
                f"status={launcher_run['status']}, run_id={run_id}",
            )
        )

        if not isinstance(run_id, str):
            raise RuntimeError("launcher run did not return a run id")

        paused = _poll_run(base_url, run_id, "awaiting_operator")
        checks.append(
            _check(
                "launcher_run_inspectable",
                paused["status"] == 200 and paused["body"].get("run_id") == run_id,
                f"stage={paused['body'].get('stage')}",
            )
        )

        launcher_approval = _request_json(
            base_url,
            "POST",
            f"/api/runs/{run_id}/steer",
            {"command": "approve"},
            headers=_headers("ingress-launcher@example.com", "launcher"),
        )
        checks.append(
            _check(
                "launcher_approval_denied",
                launcher_approval["status"] == 403,
                f"status={launcher_approval['status']}",
            )
        )

        approver_approval = _request_json(
            base_url,
            "POST",
            f"/api/runs/{run_id}/steer",
            {"command": "approve"},
            headers=_headers("ingress-approver@example.com", "approver"),
        )
        command_events = [
            event
            for event in approver_approval["body"].get("events", [])
            if event.get("event_type") == "steering_command"
        ]
        last_operator = {}
        if command_events:
            last_operator = command_events[-1].get("payload", {}).get("operator", {})
        checks.append(
            _check(
                "approver_approval_accepted",
                approver_approval["status"] == 200
                and last_operator.get("operator_id") == "ingress-approver@example.com"
                and last_operator.get("roles") == ["approver"],
                f"status={approver_approval['status']}",
            )
        )

        launcher_kill_switch = _request_json(
            base_url,
            "POST",
            "/api/kill-switch",
            {"force_approval_gate": True},
            headers=_headers("ingress-launcher@example.com", "launcher"),
        )
        checks.append(
            _check(
                "launcher_kill_switch_denied",
                launcher_kill_switch["status"] == 403,
                f"status={launcher_kill_switch['status']}",
            )
        )

        admin_kill_switch = _request_json(
            base_url,
            "POST",
            "/api/kill-switch",
            {"force_approval_gate": True},
            headers=_headers("ingress-admin@example.com", "admin"),
        )
        checks.append(
            _check(
                "admin_kill_switch_accepted",
                admin_kill_switch["status"] == 200
                and "approval_gate_forced" in admin_kill_switch["body"].get("actions", []),
                f"status={admin_kill_switch['status']}",
            )
        )

        status = "passed" if all(check["status"] == "pass" for check in checks) else "failed"
        return {
            "schema_version": "mesh.authenticated_ingress_rehearsal.v1",
            "status": status,
            "base_url": base_url,
            "state_directory": str(base),
            "operator_headers": {
                "identity": OPERATOR_HEADER,
                "roles": ROLES_HEADER,
            },
            "run_id": run_id,
            "checks": checks,
        }
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        if temp_dir_path is not None:
            shutil.rmtree(temp_dir_path, ignore_errors=True)


def _poll_run(base_url: str, run_id: str, stage: str, timeout_seconds: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_response: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_response = _request_json(base_url, "GET", f"/api/runs/{run_id}")
        if last_response["status"] == 200 and last_response["body"].get("stage") == stage:
            return last_response
        time.sleep(0.1)
    last_stage = None
    if last_response is not None:
        last_stage = last_response["body"].get("stage")
    raise RuntimeError(f"run {run_id} did not reach {stage}; last_stage={last_stage}")


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    body_bytes = None
    request_headers = dict(headers or {})
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url}{path}",
        data=body_bytes,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return {
                "status": response.status,
                "body": _decode_json(response.read()),
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "body": _decode_json(exc.read()),
        }


def _decode_json(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    decoded = json.loads(raw.decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {"root": decoded}


def _headers(operator_id: str, roles: str) -> dict[str, str]:
    return {
        OPERATOR_HEADER: operator_id,
        ROLES_HEADER: roles,
    }


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"{payload['status']}: {payload['schema_version']}")
    for check in payload.get("checks", []):
        print(f"{check['status']}: {check['name']} - {check['detail']}")


if __name__ == "__main__":
    sys.exit(main())
