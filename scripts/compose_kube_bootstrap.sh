#!/usr/bin/env bash
set -euo pipefail

KUBECONFIG_PATH="${KUBECONFIG:-/mesh-kubeconfig/kubeconfig}"
KUBE_CONTEXT_NAME="${MESH_STACK_KUBE_CONTEXT:-mesh-compose}"
NAMESPACE="${MESH_STACK_NAMESPACE:-search}"
DEPLOYMENT_NAME="${MESH_STACK_DEPLOYMENT:-semantic-search}"
K3S_URL="${MESH_STACK_K3S_URL:-https://k3s:6443}"

until [ -s "${KUBECONFIG_PATH}" ]; do
  sleep 1
done

CURRENT_CONTEXT="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config current-context)"
CLUSTER_NAME="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view -o "jsonpath={.contexts[?(@.name==\"${CURRENT_CONTEXT}\")].context.cluster}")"
USER_NAME="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view -o "jsonpath={.contexts[?(@.name==\"${CURRENT_CONTEXT}\")].context.user}")"

kubectl --kubeconfig "${KUBECONFIG_PATH}" config set-cluster "${CLUSTER_NAME}" --server="${K3S_URL}" >/dev/null
kubectl --kubeconfig "${KUBECONFIG_PATH}" config set-context "${KUBE_CONTEXT_NAME}" --cluster="${CLUSTER_NAME}" --user="${USER_NAME}" >/dev/null
kubectl --kubeconfig "${KUBECONFIG_PATH}" config use-context "${KUBE_CONTEXT_NAME}" >/dev/null

cluster_ready=0
for _ in $(seq 1 120); do
  if kubectl --kubeconfig "${KUBECONFIG_PATH}" get nodes >/dev/null 2>&1; then
    cluster_ready=1
    break
  fi
  sleep 1
done

if [ "${cluster_ready}" != "1" ]; then
  echo "k3s did not become reachable through ${KUBECONFIG_PATH}" >&2
  exit 1
fi

kubectl --kubeconfig "${KUBECONFIG_PATH}" create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl --kubeconfig "${KUBECONFIG_PATH}" apply -f -

kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" apply -f - <<EOF
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

kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" --timeout=180s
kubectl --kubeconfig "${KUBECONFIG_PATH}" get nodes
kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get deployment "${DEPLOYMENT_NAME}"
