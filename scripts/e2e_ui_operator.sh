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
      echo "--- ${CONTROL_LOG} ---" >&2
      test -f "${CONTROL_LOG}" && tail -n 80 "${CONTROL_LOG}" >&2 || true
      echo "--- ${WEB_LOG} ---" >&2
      test -f "${WEB_LOG}" && tail -n 80 "${WEB_LOG}" >&2 || true
      exit 1
    fi
    sleep 1
  done
}

cd "${ROOT_DIR}"
RUN_ID="$(PYTHONPATH=. python3 scripts/seed_ui_operator_state.py --state-directory "${STATE_DIR}" --reset)"

MESH_STATE_DIRECTORY="${STATE_DIR}" \
MESH_VAULT_PATH="${STATE_DIR}/vault" \
MESH_RESEARCH_DIRECTORY="${STATE_DIR}/research" \
MESH_INTEGRATIONS_CONFIG_PATH="${STATE_DIR}/integrations.json" \
MESH_SERVER_PORT="${API_PORT}" \
MESH_EVALUATION_MODE=native \
MESH_ORCHESTRATION_MODE=native \
MESH_GITNEXUS_DISABLE_AUTOSTART=true \
MESH_WATCH_ENABLED=true \
MESH_WATCH_TARGETS='[{"deployment_name":"semantic-search","namespace":"search","kube_context":"k3d-mesh-e2e"}]' \
PYTHONPATH=. \
python3 run_server.py >"${CONTROL_LOG}" 2>&1 &
CONTROL_PID="$!"

npm --prefix web run dev -- --host 127.0.0.1 --port "${WEB_PORT}" >"${WEB_LOG}" 2>&1 &
WEB_PID="$!"

wait_for_url "${API_URL}/api/health" "control plane"
wait_for_url "${WEB_URL}" "web app"

MESH_E2E_BASE_URL="${WEB_URL}/?server=${API_URL}&run=${RUN_ID}" \
MESH_E2E_RUN_ID="${RUN_ID}" \
MESH_E2E_API_URL="${API_URL}" \
npm --prefix web run test:e2e:playwright
