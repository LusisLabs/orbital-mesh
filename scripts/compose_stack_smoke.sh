#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/workspace/mesh-intel"
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
export E2E_ACCEPT_AWAITING_OPERATOR="${E2E_ACCEPT_AWAITING_OPERATOR:-1}"

cp "${KUBECONFIG_SOURCE}" "${KUBECONFIG}"
chmod 600 "${KUBECONFIG}" >/dev/null 2>&1 || true
kubectl config use-context "${KUBE_CONTEXT}" >/dev/null

KUBE_SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
case "${KUBE_SERVER}" in
  https://127.0.0.1:*|http://127.0.0.1:*|https://localhost:*|http://localhost:*)
    echo "kubeconfig server ${KUBE_SERVER} is loopback inside the smoke container; expected a compose-reachable endpoint such as https://k3s:6443" >&2
    exit 1
    ;;
esac

if ! kubectl get nodes >/dev/null 2>&1; then
  echo "kube context ${KUBE_CONTEXT} is not reachable from the smoke container" >&2
  exit 1
fi

python3 "${REPO_ROOT}/scripts/compose_target_probe.py"

restore_baseline() {
  kubectl -n "${NAMESPACE}" apply -f - >/dev/null 2>&1 <<EOF || true
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${DEPLOYMENT_NAME}
  labels:
    app: ${DEPLOYMENT_NAME}
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ${DEPLOYMENT_NAME}
  template:
    metadata:
      labels:
        app: ${DEPLOYMENT_NAME}
    spec:
      containers:
        - name: ${DEPLOYMENT_NAME}
          image: busybox:1.36
          command:
            - /bin/sh
            - -c
            - while true; do echo healthy; sleep 30; done
EOF
  kubectl -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" --timeout=120s >/dev/null 2>&1 || true
}

trap restore_baseline EXIT

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

"${REPO_ROOT}/scripts/e2e_seed_failure.sh" crashloop
"${REPO_ROOT}/scripts/e2e_run_mesh.sh"
