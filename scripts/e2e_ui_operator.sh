#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${MESH_UI_E2E_STATE_DIR:-${TMPDIR:-/tmp}/mesh-ui-operator-e2e}"
API_PORT="${MESH_UI_E2E_API_PORT:-18787}"
WEB_PORT="${MESH_UI_E2E_WEB_PORT:-14173}"
API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"
CONTROL_LOG="${STATE_DIR}/control-plane.log"
WEB_LOG="${STATE_DIR}/vite.log"

mkdir -p "${STATE_DIR}"

CONTROL_PID=""
WEB_PID=""

run_pnpm() {
  if command -v corepack >/dev/null 2>&1; then
    corepack pnpm "$@"
  else
    pnpm "$@"
  fi
}

print_recent_log() {
  local path="$1"
  local label="$2"
  echo "--- ${label} (${path}) ---" >&2
  if [[ ! -f "${path}" ]]; then
    return
  fi
  python3 - "${path}" <<'PY' >&2
from collections import deque
from pathlib import Path
import sys

lines: deque[str] = deque(maxlen=80)
try:
    with Path(sys.argv[1]).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
except OSError as exc:
    print(f"could not read log: {exc}")
else:
    for line in lines:
        print(line)
PY
}

cleanup() {
  if [[ -n "${WEB_PID}" ]] && kill -0 "${WEB_PID}" 2>/dev/null; then
    kill "${WEB_PID}" 2>/dev/null || true
  fi
  if [[ -n "${CONTROL_PID}" ]] && kill -0 "${CONTROL_PID}" 2>/dev/null; then
    kill "${CONTROL_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

wait_for_url() {
  local url="$1"
  local label="$2"
  local deadline=$((SECONDS + 45))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "${label} did not become ready at ${url}" >&2
      print_recent_log "${CONTROL_LOG}" "control plane"
      print_recent_log "${WEB_LOG}" "web app"
      exit 1
    fi
    sleep 1
  done
}

cd "${ROOT_DIR}"
RUN_ID="$(
  PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools \
    uv run --with-editable . python scripts/seed_ui_operator_state.py --state-directory "${STATE_DIR}" --reset
)"

MESH_STATE_DIRECTORY="${STATE_DIR}" \
MESH_VAULT_PATH="${STATE_DIR}/vault" \
MESH_RESEARCH_DIRECTORY="${STATE_DIR}/research" \
MESH_INTEGRATIONS_CONFIG_PATH="${STATE_DIR}/integrations.json" \
MESH_SERVER_PORT="${API_PORT}" \
MESH_EVALUATION_MODE=native \
MESH_ORCHESTRATION_MODE=native_hermes \
MESH_GITNEXUS_DISABLE_AUTOSTART=true \
MESH_WATCH_ENABLED=true \
MESH_WATCH_TARGETS='[{"deployment_name":"semantic-search","namespace":"search","kube_context":"k3d-mesh-e2e"}]' \
PYTHONPATH=. \
UV_CACHE_DIR=/tmp/uv-cache \
UV_TOOL_DIR=/tmp/uv-tools \
uv run --with-editable . python run_server.py >"${CONTROL_LOG}" 2>&1 &
CONTROL_PID="$!"

run_pnpm --dir web exec vite --host 127.0.0.1 --port "${WEB_PORT}" >"${WEB_LOG}" 2>&1 &
WEB_PID="$!"

wait_for_url "${API_URL}/api/health" "control plane"
wait_for_url "${WEB_URL}" "web app"

MESH_E2E_BASE_URL="${WEB_URL}/?server=${API_URL}&run=${RUN_ID}" \
MESH_E2E_RUN_ID="${RUN_ID}" \
MESH_E2E_API_URL="${API_URL}" \
run_pnpm --dir web run test:e2e:playwright
