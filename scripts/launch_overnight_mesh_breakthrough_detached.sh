#!/usr/bin/env bash
set -euo pipefail

DURATION_SECONDS="${1:-10800}"
INTERVAL_SECONDS="${2:-1200}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LAUNCH_DIR="${ROOT_DIR}/.mesh-runtime-state/overnight-breakthrough/launcher-${STAMP}"
LOG_FILE="${LAUNCH_DIR}/launcher.log"
PID_FILE="${LAUNCH_DIR}/pid"

mkdir -p "${LAUNCH_DIR}"

cd "${ROOT_DIR}"

nohup python3 scripts/run_overnight_mesh_breakthrough_cron.py \
  --duration-seconds "${DURATION_SECONDS}" \
  --autoresearch-interval-seconds "${INTERVAL_SECONDS}" \
  --http-full-matrix \
  >"${LOG_FILE}" 2>&1 &

PID="$!"
printf '%s\n' "${PID}" >"${PID_FILE}"

printf 'pid=%s\n' "${PID}"
printf 'log=%s\n' "${LOG_FILE}"
printf 'pid_file=%s\n' "${PID_FILE}"
