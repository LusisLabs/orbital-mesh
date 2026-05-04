#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

state_root="${MESH_STATE_DIRECTORY:-${repo_root}/.mesh-runtime-state}"
run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${MESH_BRAIN_RUN_NAME:-live-quality-training-8h-${run_stamp}}"
run_root="${MESH_BRAIN_OUTPUT:-${state_root}/mesh-brain/${run_name}}"
log_root="${run_root}/launcher"
mkdir -p "${log_root}"

export MESH_BRAIN_RUN_NAME="${run_name}"
export MESH_BRAIN_OUTPUT="${run_root}"

nohup bash "${repo_root}/scripts/run_mesh_brain_8h_posttraining.sh" \
  >"${log_root}/detached.stdout.log" \
  2>"${log_root}/detached.stderr.log" &
pid="$!"

echo "${pid}" > "${log_root}/detached.pid"
ln -sfn "${run_root}" "${state_root}/mesh-brain/live-quality-training-8h-latest"

cat <<EOF
detached_pid=${pid}
run_root=${run_root}
stdout=${log_root}/detached.stdout.log
stderr=${log_root}/detached.stderr.log
launcher_log=${log_root}/launcher.log
EOF
