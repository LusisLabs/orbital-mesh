#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8787}"
GOAL_ID="${GOAL_ID:-goal_default}"
EVALUATION_MODE="${EVALUATION_MODE:-native}"
ORCHESTRATION_MODE="${ORCHESTRATION_MODE:-native}"
STEERING_MODE="${STEERING_MODE:-interruptible_auto}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-semantic-search}"
NAMESPACE="${NAMESPACE:-search}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-mesh-e2e}"
ENVIRONMENT="${ENVIRONMENT:-local}"
EXPECT_MESH_EVAL_TOKENIZER_PROBE="${MESH_EXPECT_MESH_EVAL_TOKENIZER_PROBE:-0}"
E2E_AUTO_APPROVE="${E2E_AUTO_APPROVE:-0}"
MESH_E2E_OPERATOR_ID="${MESH_E2E_OPERATOR_ID:-mesh-e2e}"
MESH_E2E_OPERATOR_ROLES="${MESH_E2E_OPERATOR_ROLES:-launcher,approver}"
MESH_OPERATOR_HEADER="${MESH_OPERATOR_HEADER:-X-Mesh-Operator}"
MESH_OPERATOR_ROLES_HEADER="${MESH_OPERATOR_ROLES_HEADER:-X-Mesh-Roles}"

export BASE_URL
export GOAL_ID
export EVALUATION_MODE
export ORCHESTRATION_MODE
export STEERING_MODE
export DEPLOYMENT_NAME
export NAMESPACE
export KUBE_CONTEXT
export ENVIRONMENT
export EXPECT_MESH_EVAL_TOKENIZER_PROBE
export E2E_AUTO_APPROVE
export MESH_E2E_OPERATOR_ID
export MESH_E2E_OPERATOR_ROLES
export MESH_OPERATOR_HEADER
export MESH_OPERATOR_ROLES_HEADER

python3 - <<'PY'
import json
import os
import socket
import time
import urllib.request
from urllib.error import URLError
from http.client import RemoteDisconnected

def as_dict(value):
    return value if isinstance(value, dict) else {}

base_url = os.environ["BASE_URL"]
request_timeout_seconds = float(os.environ.get("E2E_RUN_REQUEST_TIMEOUT_SECONDS", "90"))
long_running_stages = {"scenario_analysis_ready", "evaluation_ready"}
auto_approve = os.environ.get("E2E_AUTO_APPROVE", "0").lower() in {"1", "true", "yes", "on"}
operator_header = os.environ.get("MESH_OPERATOR_HEADER", "X-Mesh-Operator")
operator_roles_header = os.environ.get("MESH_OPERATOR_ROLES_HEADER", "X-Mesh-Roles")
operator_id = os.environ.get("MESH_E2E_OPERATOR_ID", "mesh-e2e")
operator_roles = os.environ.get("MESH_E2E_OPERATOR_ROLES", "launcher,approver")
payload = {
    "goal_id": os.environ["GOAL_ID"],
    "evaluation_mode": os.environ["EVALUATION_MODE"],
    "orchestration_mode": os.environ["ORCHESTRATION_MODE"],
    "steering_mode": os.environ["STEERING_MODE"],
    "live_signal": {
        "source": "kubernetes",
        "deployment_name": os.environ["DEPLOYMENT_NAME"],
        "namespace": os.environ["NAMESPACE"],
        "kube_context": os.environ["KUBE_CONTEXT"],
        "environment": os.environ["ENVIRONMENT"],
    },
}

def json_headers():
    return {
        "Content-Type": "application/json",
        operator_header: operator_id,
        operator_roles_header: operator_roles,
    }

def post_json(url, body):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=json_headers(),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))

health_url = f"{base_url}/api/health"
deadline = time.time() + 60
while True:
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            if response.status == 200:
                break
    except Exception:
        pass
    if time.time() >= deadline:
        raise SystemExit("control plane did not become healthy in time")
    time.sleep(1)

last_error = None
for _ in range(5):
    try:
        run = post_json(f"{base_url}/api/runs", payload)
        run_id = run["run_id"]
        break
    except (URLError, RemoteDisconnected, ConnectionResetError, TimeoutError, socket.timeout) as exc:
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(f"run launch failed after retries: {last_error}")

wait_seconds = float(os.environ.get("E2E_RUN_TERMINAL_WAIT_SECONDS", "600"))
progress_grace_seconds = float(os.environ.get("E2E_RUN_PROGRESS_GRACE_SECONDS", "120"))
stage_grace_seconds = float(os.environ.get("E2E_RUN_STAGE_GRACE_SECONDS", "600"))
max_wait_seconds = float(os.environ.get("E2E_RUN_MAX_WAIT_SECONDS", "1800"))
started = time.monotonic()
deadline = started + wait_seconds
hard_deadline = started + max(max_wait_seconds, wait_seconds)
last_progress = None
last_progress_at = started
terminal_stages = {"completed", "failed", "cancelled", "no_trigger"}
if os.environ.get("E2E_ACCEPT_AWAITING_OPERATOR", "0").lower() in {"1", "true", "yes"}:
    terminal_stages.add("awaiting_operator")
approval_submitted = False
while True:
    now = time.monotonic()
    with urllib.request.urlopen(f"{base_url}/api/runs/{run_id}", timeout=request_timeout_seconds) as response:
        run = json.loads(response.read().decode("utf-8"))
    progress = (run.get("stage"), run.get("status"))
    if progress != last_progress:
        last_progress = progress
        last_progress_at = now
        grace = stage_grace_seconds if run.get("stage") in long_running_stages else progress_grace_seconds
        deadline = min(hard_deadline, max(deadline, now + grace))
    if (
        auto_approve
        and not approval_submitted
        and run.get("stage") == "awaiting_operator"
        and run.get("pending_pause_stage") == "evaluation_ready"
    ):
        artifacts = as_dict(run.get("artifacts"))
        evaluation = as_dict(artifacts.get("evaluation"))
        if evaluation.get("passed") is True and evaluation.get("final_recommendation") == "execute":
            post_json(
                f"{base_url}/api/runs/{run_id}/steer",
                {"command": "approve", "summary": "compose smoke approval"},
            )
            approval_submitted = True
            continue
    if run["stage"] in terminal_stages:
        artifacts = as_dict(run.get("artifacts"))
        task_trace = as_dict(artifacts.get("task_trace"))
        mesh_eval = as_dict(task_trace.get("mesh_eval"))
        latent_mesh = as_dict(mesh_eval.get("latent_mesh"))
        tokenizer_probe = as_dict(latent_mesh.get("tokenizer_probe"))
        decision = as_dict(artifacts.get("decision"))
        execution = as_dict(artifacts.get("execution"))
        feedback = as_dict(artifacts.get("feedback"))
        if os.environ.get("EXPECT_MESH_EVAL_TOKENIZER_PROBE", "0").lower() in {"1", "true", "yes"}:
            if tokenizer_probe.get("status") != "ok":
                raise SystemExit(f"mesh_eval tokenizer probe did not complete: {tokenizer_probe}")
        summary = {
            "run_id": run["run_id"],
            "scenario_key": run.get("scenario_key"),
            "stage": run["stage"],
            "status": run["status"],
            "decision_type": decision.get("decision_type"),
            "execution_status": execution.get("status"),
            "feedback_outcome": feedback.get("outcome"),
            "mesh_eval_tokenizer_probe": tokenizer_probe,
        }
        print(json.dumps(summary, indent=2))
        raise SystemExit(0)
    if now >= deadline:
        elapsed = round(now - started, 3)
        stalled = round(now - last_progress_at, 3)
        raise SystemExit(
            f"run {run_id} did not reach a terminal stage in time "
            f"(stage={run.get('stage')} status={run.get('status')} elapsed={elapsed}s stalled={stalled}s)"
        )
    time.sleep(1)
PY
