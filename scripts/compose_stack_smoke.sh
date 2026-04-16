#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/workspace/mesh-intelligence"
KUBECONFIG_SOURCE="${KUBECONFIG:-/mesh-kubeconfig/kubeconfig}"
export KUBECONFIG="/tmp/mesh-stack-kubeconfig"
export BASE_URL="${BASE_URL:-http://mesh:8787}"
export KUBE_CONTEXT="${KUBE_CONTEXT:-mesh-compose}"
export NAMESPACE="${NAMESPACE:-search}"
export DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-semantic-search}"
export EVALUATION_MODE="${EVALUATION_MODE:-native}"
export ORCHESTRATION_MODE="${ORCHESTRATION_MODE:-native}"
export STEERING_MODE="${STEERING_MODE:-interruptible_auto}"
export MESH_EXPECT_LATENTMAS="${MESH_EXPECT_LATENTMAS:-0}"
export MESH_AGENT_FABRIC_MODE="${MESH_AGENT_FABRIC_MODE:-native}"

cp "${KUBECONFIG_SOURCE}" "${KUBECONFIG}"
chmod 600 "${KUBECONFIG}" >/dev/null 2>&1 || true

python3 - <<'PY'
import json
import os
import time
import urllib.request

base_url = os.environ["BASE_URL"].rstrip("/")
deadline = time.time() + 180
health_url = f"{base_url}/api/health"
while True:
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            if response.status == 200:
                break
    except Exception:
        pass
    if time.time() >= deadline:
        raise SystemExit("mesh did not become healthy in time")
    time.sleep(1)

required = ["promptfoo", "hermes"]
readiness_url = f"{base_url}/api/readiness"
deadline = time.time() + 180
readiness = {}
last_issue = "readiness was not checked"
while True:
    try:
        with urllib.request.urlopen(readiness_url, timeout=30) as response:
            readiness = json.loads(response.read().decode("utf-8"))
        missing = [
            f"{name}: {readiness.get(name)}"
            for name in required
            if not readiness.get(name, {}).get("ready")
        ]
        if os.environ.get("MESH_AGENT_FABRIC_MODE", "native") == "deepagents":
            if not readiness.get("deepagents", {}).get("ready"):
                missing.append(f"deepagents: {readiness.get('deepagents')}")
        if os.environ.get("MESH_EXPECT_LATENTMAS", "0").lower() in {"1", "true", "yes"}:
            if not readiness.get("latentmas", {}).get("ready"):
                missing.append(f"latentmas: {readiness.get('latentmas')}")
        if not missing:
            break
        last_issue = "; ".join(missing)
    except Exception as exc:
        last_issue = repr(exc)
    if time.time() >= deadline:
        raise SystemExit(f"mesh readiness did not complete in time: {last_issue}")
    time.sleep(2)

if os.environ.get("MESH_AGENT_FABRIC_MODE", "native") == "deepagents":
    if not readiness.get("deepagents", {}).get("ready"):
        raise SystemExit(f"deepagents is not ready: {readiness.get('deepagents')}")

if os.environ.get("MESH_EXPECT_LATENTMAS", "0").lower() in {"1", "true", "yes"}:
    if not readiness.get("latentmas", {}).get("ready"):
        raise SystemExit(f"latentmas is not ready: {readiness.get('latentmas')}")

print(json.dumps({
    "health": "ok",
    "required_integrations": {name: readiness.get(name, {}) for name in required},
    "deepagents": readiness.get("deepagents", {}),
    "latentmas": readiness.get("latentmas", {}),
}, indent=2))
PY

kubectl config use-context "${KUBE_CONTEXT}" >/dev/null
"${REPO_ROOT}/scripts/e2e_seed_failure.sh" crashloop
"${REPO_ROOT}/scripts/e2e_run_mesh.sh"
