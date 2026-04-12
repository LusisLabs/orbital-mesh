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

export BASE_URL
export GOAL_ID
export EVALUATION_MODE
export ORCHESTRATION_MODE
export STEERING_MODE
export DEPLOYMENT_NAME
export NAMESPACE
export KUBE_CONTEXT
export ENVIRONMENT

python3 - <<'PY'
import json
import os
import time
import urllib.request
from urllib.error import URLError
from http.client import RemoteDisconnected

base_url = os.environ["BASE_URL"]
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
        with urllib.request.urlopen(request, timeout=30) as response:
            run = json.loads(response.read().decode("utf-8"))
            run_id = run["run_id"]
            break
    except (URLError, RemoteDisconnected, ConnectionResetError) as exc:
        last_error = exc
        time.sleep(1)
else:
    raise SystemExit(f"run launch failed after retries: {last_error}")

deadline = time.time() + 120
terminal_stages = {"completed", "failed", "cancelled", "no_trigger"}
while True:
    with urllib.request.urlopen(f"{base_url}/api/runs/{run_id}", timeout=30) as response:
        run = json.loads(response.read().decode("utf-8"))
    if run["stage"] in terminal_stages:
        summary = {
            "run_id": run["run_id"],
            "scenario_key": run.get("scenario_key"),
            "stage": run["stage"],
            "status": run["status"],
            "decision_type": (run.get("artifacts") or {}).get("decision", {}).get("decision_type"),
            "execution_status": (run.get("artifacts") or {}).get("execution", {}).get("status"),
            "feedback_outcome": (run.get("artifacts") or {}).get("feedback", {}).get("outcome"),
        }
        print(json.dumps(summary, indent=2))
        raise SystemExit(0)
    if time.time() >= deadline:
        raise SystemExit(f"run {run_id} did not reach a terminal stage in time")
    time.sleep(1)
PY
