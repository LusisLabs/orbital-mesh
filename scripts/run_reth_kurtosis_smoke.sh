#!/usr/bin/env bash
set -euo pipefail

# Historical Reth/Kurtosis bootstrap helper for research full-loop runs.
# Controlled production pilot release gates do not depend on Kurtosis.

ENCLAVE="${MESH_KURTOSIS_ENCLAVE:-mesh-reth}"
PACKAGE="${MESH_KURTOSIS_PACKAGE:-github.com/ethpandaops/ethereum-package}"
KURTOSIS_BIN="${MESH_KURTOSIS_COMMAND:-kurtosis}"
KURTOSIS_HOME="${MESH_KURTOSIS_HOME:-${HOME}}"
ARGS_FILE="${MESH_KURTOSIS_ARGS_FILE:-/tmp/mesh-reth-network-params.yaml}"
RETH_IMAGE="${MESH_KURTOSIS_RETH_IMAGE:-ghcr.io/paradigmxyz/reth:v1.9.3}"

if [[ "${KURTOSIS_HOME}" == "\$HOME" ]]; then
  KURTOSIS_HOME="${HOME}"
fi

if [[ "${DOCKER_HOST:-}" == "" || "${DOCKER_HOST:-}" == "unix:///var/run/docker.sock" ]]; then
  if [[ ! -S /var/run/docker.sock && -S "${HOME}/.docker/run/docker.sock" ]]; then
    export DOCKER_HOST="unix://${HOME}/.docker/run/docker.sock"
  fi
fi

mkdir -p "${KURTOSIS_HOME}"

cat > "${ARGS_FILE}" <<EOF
participants:
  - el_type: reth
    el_image: ${RETH_IMAGE}
    cl_type: lighthouse
network_params:
  network: kurtosis
additional_services: []
EOF

HOME="${KURTOSIS_HOME}" "${KURTOSIS_BIN}" run \
  --enclave "${ENCLAVE}" \
  "${PACKAGE}" \
  --args-file "${ARGS_FILE}"
