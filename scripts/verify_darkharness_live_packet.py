#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig, load_fixture, validate_payload


OPERATOR_HEADERS = {
    "Content-Type": "application/json",
    "X-Mesh-Operator": "darkharness-live-verifier",
    "X-Mesh-Roles": "launcher,approver,admin",
}


def verify_darkharness_live_packet(*, state_directory: Path) -> dict[str, Any]:
    state_directory.mkdir(parents=True, exist_ok=True)
    kubectl_state_path, kubectl_command = _write_fake_kubectl(state_directory)
    mock_backend, mock_thread = _start_mock_openai_backend()
    mock_base_url = f"http://127.0.0.1:{mock_backend.server_address[1]}"
    config = RuntimeConfig(
        state_directory=str(state_directory),
        vault_path=str(state_directory / "vault"),
        integrations_config_path=str(state_directory / "integrations.json"),
        server_host="127.0.0.1",
        server_port=0,
        readiness_profile="local",
        promptfoo_command="/missing/promptfoo",
        hermes_command="/missing/hermes",
        goose_command="/missing/goose",
        evo_command="/missing/evo",
        kubernetes_live_execution_enabled=True,
        kubectl_command=kubectl_command,
        kubernetes_allowed_contexts=("k3d-mesh-e2e",),
        kubernetes_allowed_namespaces=("search",),
        kubernetes_rollout_timeout_seconds=5,
        mesh_brain_serving_base_url=mock_base_url,
        mesh_brain_serving_model="mesh-brain-live-smoke",
        darkharness_signing_key="darkharness-live-verifier-local-key",
        darkharness_signing_key_id="darkharness-live-verifier-hmac",
        access_log_enabled=False,
    )
    server, thread = start_server_in_thread(config, start_sidecar=False)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    cancelled_run_ids: list[str] = []
    try:
        allowed_run = _create_allowed_run(base_url)
        allowed_packet = _request_json(base_url, "GET", f"/api/runs/{allowed_run['run_id']}/darkharness-packet")
        validate_payload("perennial/darkharness-pilot-packet.schema.json", allowed_packet)
        _require(allowed_packet.get("status") != "blocked", "allowed run packet is blocked")
        _require(
            len(allowed_packet["implemented_evidence"]["allowed_action_proofs"]) == 1,
            "allowed run packet lacks one allowed action proof",
        )

        denied_run = _create_denied_run(base_url)
        cancelled_run_ids.append(str(denied_run["run_id"]))
        denied_packet = _request_json(base_url, "GET", f"/api/runs/{denied_run['run_id']}/darkharness-packet")
        validate_payload("perennial/darkharness-pilot-packet.schema.json", denied_packet)
        _require(denied_packet.get("status") != "blocked", "denied run packet is blocked")
        _require(
            len(denied_packet["implemented_evidence"]["denied_action_proofs"]) == 1,
            "denied run packet lacks one denied action proof",
        )

        model_kernel = _request_json(
            base_url,
            "POST",
            "/api/mesh-brain/model-kernel-probe",
            {"benchmark_iterations": 10},
            expected_status=HTTPStatus.CREATED,
        )
        live_smoke = _request_json(
            base_url,
            "POST",
            "/api/mesh-brain/live-serving-smoke",
            {
                "base_url": mock_base_url,
                "model": "mesh-brain-live-smoke",
                "judge_enabled": False,
                "deterministic_release_decision": "canary",
                "timeout_seconds": 5,
            },
            expected_status=HTTPStatus.CREATED,
        )
        rollback = _request_json(
            base_url,
            "POST",
            "/api/mesh-brain/rollback-drill",
            {},
            expected_status=HTTPStatus.CREATED,
        )

        go_no_go = _request_json(base_url, "GET", "/api/pilot/go-no-go")
        _require(go_no_go.get("status") == "go", f"go/no-go did not pass: {go_no_go.get('missing_evidence')}")
        checkpoint_packet = _request_json(base_url, "GET", "/api/darkharness/pilot-packet")
        validate_payload("perennial/darkharness-pilot-packet.schema.json", checkpoint_packet)
        _require(checkpoint_packet.get("status") != "blocked", "checkpoint packet is blocked")
        implemented = set(checkpoint_packet.get("claim_boundary", {}).get("implemented", []))
        _require("multi_run_checkpoint_export" in implemented, "checkpoint packet lacks multi-run claim")
        _require("rollback_drill_proof" in implemented, "checkpoint packet lacks rollback drill claim")
        _require(
            len(checkpoint_packet["implemented_evidence"]["allowed_action_proofs"]) >= 1,
            "checkpoint packet lacks allowed action proof",
        )
        _require(
            len(checkpoint_packet["implemented_evidence"]["denied_action_proofs"]) >= 1,
            "checkpoint packet lacks denied action proof",
        )

        return {
            "status": "pass",
            "control_plane_url": base_url,
            "mock_backend_url": mock_base_url,
            "state_directory": str(state_directory),
            "kubectl_state_path": str(kubectl_state_path),
            "run_ids": {
                "allowed": allowed_run["run_id"],
                "denied": denied_run["run_id"],
                "mesh_brain_model_kernel": model_kernel["run_id"],
                "mesh_brain_live_smoke": live_smoke["run_id"],
                "mesh_brain_rollback": rollback["run_id"],
            },
            "endpoint_proofs": {
                f"/api/runs/{allowed_run['run_id']}/darkharness-packet": {
                    "packet": allowed_packet["packet"],
                    "status": allowed_packet.get("status", "ready"),
                    "allowed_action_proofs": len(allowed_packet["implemented_evidence"]["allowed_action_proofs"]),
                },
                f"/api/runs/{denied_run['run_id']}/darkharness-packet": {
                    "packet": denied_packet["packet"],
                    "status": denied_packet.get("status", "ready"),
                    "denied_action_proofs": len(denied_packet["implemented_evidence"]["denied_action_proofs"]),
                },
                "/api/darkharness/pilot-packet": {
                    "packet": checkpoint_packet["packet"],
                    "status": checkpoint_packet.get("status", "ready"),
                    "run_export_count": len(checkpoint_packet["implemented_evidence"]["run_exports"]),
                },
            },
            "go_no_go": {
                "status": go_no_go["status"],
                "missing_evidence": go_no_go["missing_evidence"],
                "observed": go_no_go["observed"],
            },
            "boundaries": checkpoint_packet["boundaries"],
            "claim_boundary": checkpoint_packet["claim_boundary"],
        }
    finally:
        for run_id in cancelled_run_ids:
            try:
                _request_json(base_url, "POST", f"/api/runs/{run_id}/steer", {"command": "cancel"})
            except RuntimeError:
                pass
        _wait_for_workers(server.coordinator)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        mock_backend.shutdown()
        mock_backend.server_close()
        mock_thread.join(timeout=5)


def _create_allowed_run(base_url: str) -> dict[str, Any]:
    run = _request_json(
        base_url,
        "POST",
        "/api/runs",
        {
            "signal_payload": _kubernetes_live_signal(),
            "evaluation_mode": "native",
            "orchestration_mode": "native",
            "steering_mode": "approval_gate",
        },
        expected_status=HTTPStatus.CREATED,
    )
    run_id = str(run["run_id"])
    _poll_run(
        base_url,
        run_id,
        lambda payload: payload["stage"] == "awaiting_operator"
        and payload.get("pending_pause_stage") == "evaluation_ready",
    )
    _request_json(base_url, "POST", f"/api/runs/{run_id}/steer", {"command": "approve"})
    return _poll_run(base_url, run_id, lambda payload: payload["stage"] == "completed")


def _create_denied_run(base_url: str) -> dict[str, Any]:
    signal = load_fixture("signals", "search_latency_regression.json")
    signal["related_context"]["high_business_impact"] = True
    run = _request_json(
        base_url,
        "POST",
        "/api/runs",
        {
            "signal_payload": signal,
            "evaluation_mode": "native",
            "orchestration_mode": "native",
            "steering_mode": "interruptible_auto",
        },
        expected_status=HTTPStatus.CREATED,
    )
    return _poll_run(
        base_url,
        str(run["run_id"]),
        lambda payload: payload["stage"] == "awaiting_operator"
        and payload.get("pending_pause_stage") == "evaluation_ready"
        and bool(payload["artifacts"]["evaluation"].get("blocking_reasons")),
    )


def _poll_run(base_url: str, run_id: str, predicate: Any, *, timeout_seconds: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = _request_json(base_url, "GET", f"/api/runs/{run_id}")
        if predicate(last):
            return last
        time.sleep(0.05)
    raise RuntimeError(f"run {run_id} did not reach expected state; last={last}")


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    expected_status: HTTPStatus = HTTPStatus.OK,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urlrequest.Request(
        f"{base_url}{path}",
        data=data,
        headers=OPERATOR_HEADERS,
        method=method,
    )
    try:
        with urlrequest.urlopen(request, timeout=10) as response:
            status = HTTPStatus(response.status)
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    if status != expected_status:
        raise RuntimeError(f"{method} {path} returned HTTP {status}, expected {expected_status}: {body}")
    loaded = json.loads(body)
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{method} {path} returned non-object JSON")
    return loaded


def _start_mock_openai_backend() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, name="mock-openai-backend", daemon=True)
    thread.start()
    return server, thread


def _write_fake_kubectl(state_directory: Path) -> tuple[Path, str]:
    state_path = state_directory / "fake-kubectl-state.json"
    script_path = state_directory / "fake_kubectl.py"
    state_path.write_text(json.dumps(_fake_kubectl_state(), indent=2) + "\n", encoding="utf-8")
    script_path.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["FAKE_KUBECTL_STATE"])
            state = json.loads(state_path.read_text())
            args = sys.argv[1:]
            if args[:2] == ["--context", state["context"]]:
                args = args[2:]

            def save() -> None:
                state_path.write_text(json.dumps(state, indent=2) + "\\n")

            if args == ["config", "current-context"]:
                print(state["context"])
                raise SystemExit(0)

            if args[:3] == ["get", "deployment", "semantic-search"]:
                print(json.dumps(state["deployment"]))
                raise SystemExit(0)

            if args[:2] == ["get", "pods"]:
                print(json.dumps(state["pods"]))
                raise SystemExit(0)

            if args[:2] == ["get", "events"]:
                print(json.dumps(state["events"]))
                raise SystemExit(0)

            if args[:2] == ["rollout", "restart"]:
                state["actions"].append({"action": "restart", "args": args})
                state["deployment"] = state["after_restart"]
                save()
                print("deployment.apps/semantic-search restarted")
                raise SystemExit(0)

            if args[:2] == ["rollout", "undo"]:
                state["actions"].append({"action": "undo", "args": args})
                state["deployment"] = state["after_undo"]
                save()
                print("deployment.apps/semantic-search rolled back")
                raise SystemExit(0)

            if args[:2] == ["rollout", "status"]:
                state["actions"].append({"action": "status", "args": args})
                save()
                print('deployment "semantic-search" successfully rolled out')
                raise SystemExit(0)

            if args and args[0] == "logs":
                pod_name = args[1]
                print(state["logs"].get(pod_name, ""))
                raise SystemExit(0)

            print(f"unsupported fake kubectl args: {args}", file=sys.stderr)
            raise SystemExit(1)
            """
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    os.environ["FAKE_KUBECTL_STATE"] = str(state_path)
    return state_path, f"{sys.executable} {script_path}"


def _fake_kubectl_state() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    event_time = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "semantic-search",
            "namespace": "search",
            "annotations": {"deployment.kubernetes.io/revision": "2"},
        },
        "spec": {"replicas": 3, "selector": {"matchLabels": {"app": "semantic-search"}}},
        "status": {
            "replicas": 3,
            "updatedReplicas": 3,
            "readyReplicas": 0,
            "availableReplicas": 0,
            "conditions": [{"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}],
        },
    }
    healthy_deployment = {
        **deployment,
        "status": {
            "replicas": 3,
            "updatedReplicas": 3,
            "readyReplicas": 3,
            "availableReplicas": 3,
            "conditions": [{"type": "Available", "status": "True", "reason": "MinimumReplicasAvailable"}],
        },
    }
    return {
        "context": "k3d-mesh-e2e",
        "deployment": deployment,
        "after_restart": healthy_deployment,
        "after_undo": healthy_deployment,
        "pods": {
            "items": [
                {
                    "metadata": {
                        "name": "semantic-search-abc",
                        "namespace": "search",
                        "labels": {"app": "semantic-search"},
                    },
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {
                                "name": "semantic-search",
                                "ready": False,
                                "restartCount": 4,
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                            }
                        ],
                    },
                }
            ]
        },
        "events": {
            "items": [
                {
                    "lastTimestamp": event_time,
                    "reason": "BackOff",
                    "message": "Back-off restarting failed container",
                    "count": 7,
                    "type": "Warning",
                }
            ]
        },
        "logs": {"semantic-search-abc": "ModuleNotFoundError: No module named search.semantic_query_parser"},
        "actions": [],
    }


def _kubernetes_live_signal() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    deploy_ts = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    return {
        "signal_type": "kubernetes_deployment_issue",
        "signal_id": f"sig_darkharness_live_{int(now.timestamp())}",
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "environment": "staging",
        "cluster": "k3d-mesh-e2e",
        "namespace": "search",
        "service": "semantic-search",
        "deployment": {
            "name": "semantic-search",
            "revision": "2",
            "image": "busybox:1.36",
            "rollout_started_at": deploy_ts,
            "rollout_status": "degraded",
            "desired_replicas": 3,
            "updated_replicas": 3,
            "available_replicas": 0,
            "last_deploy_timestamp": deploy_ts,
            "seconds_since_deploy": 120,
        },
        "pods": [
            {
                "name": "semantic-search-abc",
                "phase": "Running",
                "ready": False,
                "restarts": 4,
                "container_status": "CrashLoopBackOff",
                "last_state_reason": "Error",
            }
        ],
        "events": [
            {
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "count": 7,
                "type": "Warning",
            }
        ],
        "logs": [
            {
                "pod": "semantic-search-abc",
                "container": "semantic-search",
                "stream": "stderr",
                "message": "ModuleNotFoundError: No module named search.semantic_query_parser",
            }
        ],
        "related_context": {
            "active_incidents": 0,
            "similar_prior_cases": 0,
            "rollbacks_last_24h": 0,
            "cluster_access_available": True,
            "audit_logging_available": True,
            "kube_context": "k3d-mesh-e2e",
        },
        "post_action_observations": {
            "30m": {
                "rollout_status": "healthy",
                "desired_replicas": 3,
                "ready_replicas": 3,
                "restart_delta": 0,
                "new_error_signatures": [],
                "measured_at": now.isoformat().replace("+00:00", "Z"),
            }
        },
    }


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
        model = str(payload.get("model") or "mesh-brain-live-smoke")
        response = {
            "id": "chatcmpl-darkharness-live-proof",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Evidence observed. Use bounded reversible remediation, keep rollback scope explicit, "
                            "and require operator approval before production action."
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 24, "completion_tokens": 20, "total_tokens": 44},
        }
        body = json.dumps(response, sort_keys=True).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _wait_for_workers(coordinator: Any) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with coordinator._lock:
            workers = list(coordinator._threads.values())
        if not any(worker.is_alive() for worker in workers):
            return
        time.sleep(0.05)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Darkharness packets against live local control-plane runs.")
    parser.add_argument("--state-directory", type=Path, help="state directory for the proof run")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    if args.state_directory is not None:
        result = verify_darkharness_live_packet(state_directory=args.state_directory)
    else:
        with tempfile.TemporaryDirectory(prefix="darkharness-live-proof-") as tmp:
            result = verify_darkharness_live_packet(state_directory=Path(tmp))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"pass: Darkharness live packet proof ({result['state_directory']})")
        print(json.dumps(result["run_ids"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
