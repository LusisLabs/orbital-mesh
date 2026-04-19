#!/usr/bin/env bash
set -euo pipefail

SCENARIO="${1:-imagepull}"
NAMESPACE="${NAMESPACE:-search}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-semantic-search}"

case "${SCENARIO}" in
  imagepull)
    kubectl -n "${NAMESPACE}" set image "deployment/${DEPLOYMENT_NAME}" "${DEPLOYMENT_NAME}=busybox:does-not-exist"
    ;;
  crashloop)
    kubectl -n "${NAMESPACE}" patch deployment "${DEPLOYMENT_NAME}" --type='merge' -p "{
      \"spec\": {
        \"template\": {
          \"spec\": {
            \"containers\": [
              {
                \"name\": \"${DEPLOYMENT_NAME}\",
                \"image\": \"busybox:1.36\",
                \"command\": [\"/bin/sh\", \"-c\", \"echo 'ModuleNotFoundError: No module named search.semantic_query_parser' 1>&2; sleep 2; exit 1\"]
              }
            ]
          }
        }
      }
    }"
    ;;
  healthy)
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
    ;;
  *)
    echo "Unsupported scenario: ${SCENARIO}" >&2
    echo "Use one of: healthy, imagepull, crashloop" >&2
    exit 1
    ;;
esac

sleep 8
kubectl -n "${NAMESPACE}" get deployment "${DEPLOYMENT_NAME}"
kubectl -n "${NAMESPACE}" get pods
