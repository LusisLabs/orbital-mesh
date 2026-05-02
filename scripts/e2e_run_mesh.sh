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

python3 - <<'PY'
import json
import os
import socket
import time
import urllib.request
from urllib.error import URLError
from http.client import RemoteDisconnected

base_url = os.environ["BASE_URL"]
request_timeout_seconds = float(os.environ.get("E2E_RUN_REQUEST_TIMEOUT_SECONDS", "90"))
long_running_stages = {"scenario_analysis_ready", "evaluation_ready"}
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
    request = urllib.request.Request(
        f"{base_url}/api/runs",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
            run = json.loads(response.read().decode("utf-8"))
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
    if run["stage"] in terminal_stages:
        artifacts = run.get("artifacts") or {}
        task_trace = artifacts.get("task_trace") or {}
        mesh_eval = task_trace.get("mesh_eval") if isinstance(task_trace, dict) else {}
        latent_mesh = mesh_eval.get("latent_mesh") if isinstance(mesh_eval, dict) else {}
        tokenizer_probe = latent_mesh.get("tokenizer_probe") if isinstance(latent_mesh, dict) else {}
        if os.environ.get("EXPECT_MESH_EVAL_TOKENIZER_PROBE", "0").lower() in {"1", "true", "yes"}:
            if tokenizer_probe.get("status") != "ok":
                raise SystemExit(f"mesh_eval tokenizer probe did not complete: {tokenizer_probe}")
        summary = {
            "run_id": run["run_id"],
            "scenario_key": run.get("scenario_key"),
            "stage": run["stage"],
            "status": run["status"],
            "decision_type": (run.get("artifacts") or {}).get("decision", {}).get("decision_type"),
            "execution_status": (run.get("artifacts") or {}).get("execution", {}).get("status"),
            "feedback_outcome": (run.get("artifacts") or {}).get("feedback", {}).get("outcome"),
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
