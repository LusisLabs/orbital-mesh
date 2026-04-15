#!/bin/sh
set -eu

STATE_DIR="${MESH_STATE_DIRECTORY:-/app/.mesh-runtime-state}"
INTEGRATIONS_PATH="${MESH_INTEGRATIONS_CONFIG_PATH:-$STATE_DIR/integrations.json}"
RESEARCH_DIR="${MESH_RESEARCH_DIRECTORY:-$STATE_DIR/research}"
VAULT_DIR="${MESH_VAULT_PATH:-$STATE_DIR/vault}"

mkdir -p "$STATE_DIR" "$RESEARCH_DIR" "$VAULT_DIR" "$(dirname "$INTEGRATIONS_PATH")"
chown -R mesh:mesh "$STATE_DIR"

exec sh -lc '/usr/local/bin/python3 /app/setup_integrations.py && exec /usr/local/bin/python3 /app/run_server.py'
