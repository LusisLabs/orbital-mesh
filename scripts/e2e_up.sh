#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-mesh-e2e}"
NAMESPACE="${NAMESPACE:-search}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-semantic-search}"
E2E_DIR=".mesh-runtime-state/e2e"
KUBECONFIG_PATH="${E2E_DIR}/kubeconfig"

mkdir -p "${E2E_DIR}"

if ! k3d cluster list | awk 'NR>1 {print $1}' | grep -qx "${CLUSTER_NAME}"; then
  k3d cluster create "${CLUSTER_NAME}" --servers 1 --agents 1 --wait
fi

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "${NAMESPACE}" delete deployment "${DEPLOYMENT_NAME}" --ignore-not-found

kubectl -n "${NAMESPACE}" apply -f - <<EOF
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

kubectl -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" --timeout=120s

k3d kubeconfig get "${CLUSTER_NAME}" > "${KUBECONFIG_PATH}"
python3 - <<'PY'
from pathlib import Path
import re

path = Path(".mesh-runtime-state/e2e/kubeconfig")
text = path.read_text()
text = re.sub(r"https://(0\.0\.0\.0|127\.0\.0\.1|localhost):", "https://host.docker.internal:", text)
text = re.sub(r"\n(\s*)certificate-authority-data: .*\n", r"\n\1insecure-skip-tls-verify: true\n", text)
path.write_text(text)
PY

docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build

echo "Mesh e2e is ready."
echo "Cluster: ${CLUSTER_NAME}"
echo "Namespace: ${NAMESPACE}"
echo "Deployment: ${DEPLOYMENT_NAME}"
echo "Control plane: http://127.0.0.1:8787"
