#!/usr/bin/env bash
set -euo pipefail

KUBECONFIG_PATH="${KUBECONFIG:-/mesh-kubeconfig/kubeconfig}"
KUBE_CONTEXT_NAME="${MESH_STACK_KUBE_CONTEXT:-mesh-compose}"
NAMESPACE="${MESH_STACK_NAMESPACE:-search}"
DEPLOYMENT_NAME="${MESH_STACK_DEPLOYMENT:-semantic-search}"
K3S_URL="${MESH_STACK_K3S_URL:-https://k3s:6443}"
NODE_NAME="${MESH_STACK_NODE_NAME:-mesh-compose-k3s}"
WORKLOAD_IMAGE="${MESH_STACK_WORKLOAD_IMAGE:-nginx:1.25-alpine}"

until [ -s "${KUBECONFIG_PATH}" ]; do
  sleep 1
done

CURRENT_CONTEXT="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config current-context)"
CLUSTER_NAME="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view -o "jsonpath={.contexts[?(@.name==\"${CURRENT_CONTEXT}\")].context.cluster}")"
USER_NAME="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view -o "jsonpath={.contexts[?(@.name==\"${CURRENT_CONTEXT}\")].context.user}")"
UNIQUE_CLUSTER_NAME="${KUBE_CONTEXT_NAME}-cluster"
UNIQUE_USER_NAME="${KUBE_CONTEXT_NAME}-user"
CA_DATA="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view --raw -o "jsonpath={.clusters[?(@.name==\"${CLUSTER_NAME}\")].cluster.certificate-authority-data}")"
CLIENT_CERT_DATA="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view --raw -o "jsonpath={.users[?(@.name==\"${USER_NAME}\")].user.client-certificate-data}")"
CLIENT_KEY_DATA="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view --raw -o "jsonpath={.users[?(@.name==\"${USER_NAME}\")].user.client-key-data}")"
TOKEN="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config view --raw -o "jsonpath={.users[?(@.name==\"${USER_NAME}\")].user.token}")"

kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "clusters.${UNIQUE_CLUSTER_NAME}.server" "${K3S_URL}" >/dev/null
if [ -n "${CA_DATA}" ]; then
  kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "clusters.${UNIQUE_CLUSTER_NAME}.certificate-authority-data" "${CA_DATA}" >/dev/null
fi
if [ -n "${CLIENT_CERT_DATA}" ] && [ -n "${CLIENT_KEY_DATA}" ]; then
  kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "users.${UNIQUE_USER_NAME}.client-certificate-data" "${CLIENT_CERT_DATA}" >/dev/null
  kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "users.${UNIQUE_USER_NAME}.client-key-data" "${CLIENT_KEY_DATA}" >/dev/null
elif [ -n "${TOKEN}" ]; then
  kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "users.${UNIQUE_USER_NAME}.token" "${TOKEN}" >/dev/null
else
  kubectl --kubeconfig "${KUBECONFIG_PATH}" config set-credentials "${UNIQUE_USER_NAME}" >/dev/null
fi
kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "contexts.${KUBE_CONTEXT_NAME}.cluster" "${UNIQUE_CLUSTER_NAME}" >/dev/null
kubectl --kubeconfig "${KUBECONFIG_PATH}" config set "contexts.${KUBE_CONTEXT_NAME}.user" "${UNIQUE_USER_NAME}" >/dev/null
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

for node in $(kubectl --kubeconfig "${KUBECONFIG_PATH}" get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'); do
  if [ "${node}" != "${NODE_NAME}" ]; then
    kubectl --kubeconfig "${KUBECONFIG_PATH}" delete node "${node}" --ignore-not-found
  fi
done

kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" delete deployment "${DEPLOYMENT_NAME}" --ignore-not-found

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
          image: ${WORKLOAD_IMAGE}
          imagePullPolicy: IfNotPresent
          command:
            - nginx
          args:
            - -g
            - daemon off;
          ports:
            - containerPort: 80
              name: http
          resources:
            requests:
              memory: 32Mi
              cpu: 50m
            limits:
              memory: 64Mi
              cpu: 200m
          livenessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 1
            periodSeconds: 3
            failureThreshold: 2
---
apiVersion: v1
kind: Service
metadata:
  name: ${DEPLOYMENT_NAME}
  namespace: ${NAMESPACE}
spec:
  selector:
    app: ${DEPLOYMENT_NAME}
  ports:
    - port: 80
      targetPort: http
      name: http
EOF

kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" rollout status "deployment/${DEPLOYMENT_NAME}" --timeout=180s
kubectl --kubeconfig "${KUBECONFIG_PATH}" get nodes
kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get deployment "${DEPLOYMENT_NAME}"
