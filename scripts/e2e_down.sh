#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-mesh-e2e}"

docker compose -f docker-compose.yml -f docker-compose.e2e.yml down

if k3d cluster list | awk 'NR>1 {print $1}' | grep -qx "${CLUSTER_NAME}"; then
  k3d cluster delete "${CLUSTER_NAME}"
fi

echo "Mesh e2e stack and cluster removed."
