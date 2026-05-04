#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${MESH_BRAIN_RUN_NAME:-live-quality-training-8h-${run_stamp}}"
state_root="${MESH_STATE_DIRECTORY:-${repo_root}/.mesh-runtime-state}"
run_root="${MESH_BRAIN_OUTPUT:-${state_root}/mesh-brain/${run_name}}"
log_root="${run_root}/launcher"
control_plane_url="${MESH_BRAIN_CONTROL_PLANE_URL:-http://127.0.0.1:8787}"
model_id="${MESH_BRAIN_MODEL:-mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16}"

duration_seconds="${MESH_BRAIN_DURATION_SECONDS:-28800}"
sft_iters="${MESH_BRAIN_SFT_ITERS:-1200}"
preference_iters="${MESH_BRAIN_PREFERENCE_ITERS:-300}"
preference_method="${MESH_BRAIN_PREFERENCE_METHOD:-orpo}"
max_seq_length="${MESH_BRAIN_MAX_SEQ_LENGTH:-512}"
num_layers="${MESH_BRAIN_NUM_LAYERS:-2}"
eval_limit="${MESH_BRAIN_EVAL_LIMIT:-16}"
corpus_jsonl_limit="${MESH_BRAIN_CORPUS_JSONL_LIMIT:-512}"
pulse_interval_seconds="${MESH_BRAIN_PULSE_INTERVAL_SECONDS:-900}"

export PYTHONPATH="${repo_root}${PYTHONPATH:+:${PYTHONPATH}}"
export MESH_STATE_DIRECTORY="${state_root}"
export HF_HOME="${MESH_BRAIN_HF_HOME:-${state_root}/cache/huggingface}"
export HF_HUB_CACHE="${MESH_BRAIN_HF_HUB_CACHE:-${HF_HOME}/hub}"
export UV_CACHE_DIR="${MESH_BRAIN_UV_CACHE_DIR:-${state_root}/cache/uv}"
export TMPDIR="${MESH_BRAIN_TMPDIR:-${state_root}/tmp}"

mkdir -p "${run_root}" "${log_root}" "${HF_HOME}" "${HF_HUB_CACHE}" "${UV_CACHE_DIR}" "${TMPDIR}"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${log_root}/launcher.log"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "missing required command: $1"
    exit 1
  fi
}

http_get() {
  curl -sS --max-time 5 "$1"
}

control_plane_healthy() {
  http_get "${control_plane_url}/api/health" >/dev/null 2>&1
}

start_control_plane_if_needed() {
  if control_plane_healthy; then
    log "control plane already healthy at ${control_plane_url}"
    return
  fi

  log "starting local Mesh control plane at ${control_plane_url}"
  MESH_SERVER_HOST="${MESH_SERVER_HOST:-127.0.0.1}" \
  MESH_SERVER_PORT="${MESH_SERVER_PORT:-8787}" \
  nohup python3 -c 'from control_plane_server import serve_forever; serve_forever()' \
    >"${log_root}/control-plane.stdout.log" \
    2>"${log_root}/control-plane.stderr.log" &
  echo "$!" > "${log_root}/control-plane.pid"

  for _ in $(seq 1 60); do
    if control_plane_healthy; then
      log "control plane became healthy"
      return
    fi
    sleep 1
  done

  log "control plane did not become healthy"
  tail -80 "${log_root}/control-plane.stderr.log" 2>/dev/null || true
  exit 1
}

pulse_mesh() {
  local payload
  payload='{"tenant_id":"tenant_a"}'
  curl -sS --max-time 600 \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "${payload}" \
    "${control_plane_url}/api/mesh-brain/mvp-runs" \
    >"${log_root}/mesh-pulse-${run_stamp}-initial.json" \
    2>>"${log_root}/mesh-pulse.stderr.log" || true
}

mesh_pulse_loop() {
  local seq
  seq=0
  while true; do
    seq=$((seq + 1))
    local payload
    payload='{"tenant_id":"tenant_a"}'
    curl -sS --max-time 600 \
      -H 'Content-Type: application/json' \
      -X POST \
      --data "${payload}" \
      "${control_plane_url}/api/mesh-brain/mvp-runs" \
      >"${log_root}/mesh-pulse-${seq}.json" \
      2>>"${log_root}/mesh-pulse.stderr.log" || true
    curl -sS --max-time 30 "${control_plane_url}/api/runs?summary=1" \
      >"${log_root}/mesh-runs-${seq}.json" \
      2>>"${log_root}/mesh-pulse.stderr.log" || true
    sleep "${pulse_interval_seconds}"
  done
}

write_manifest() {
  python3 - "$run_root" "$control_plane_url" "$model_id" "$duration_seconds" "$sft_iters" "$preference_iters" "$preference_method" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

run_root = Path(sys.argv[1])
manifest = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "run_root": str(run_root),
    "control_plane_url": sys.argv[2],
    "model_id": sys.argv[3],
    "duration_seconds": int(sys.argv[4]),
    "sft_iters": int(sys.argv[5]),
    "preference_iters": int(sys.argv[6]),
    "preference_method": sys.argv[7],
    "cache": {
        "HF_HOME": os.environ.get("HF_HOME"),
        "HF_HUB_CACHE": os.environ.get("HF_HUB_CACHE"),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR"),
        "TMPDIR": os.environ.get("TMPDIR"),
    },
}
(run_root / "launcher").mkdir(parents=True, exist_ok=True)
(run_root / "launcher" / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

preflight() {
  require_command curl
  require_command python3
  require_command mlx_lm_lora.train
  require_command mlx_lm.generate

  local available_kib
  available_kib="$(df -k "${repo_root}" | awk 'NR==2 {print $4}')"
  if [[ "${available_kib}" -lt 104857600 ]]; then
    log "refusing eight-hour run: less than 100GiB free on repo volume"
    df -h "${repo_root}" | tee -a "${log_root}/launcher.log"
    exit 1
  fi

  start_control_plane_if_needed
  pulse_mesh
  write_manifest
  log "preflight passed"
}

run_training() {
  log "starting Mesh pulse loop every ${pulse_interval_seconds}s"
  mesh_pulse_loop &
  pulse_pid="$!"
  echo "${pulse_pid}" > "${log_root}/mesh-pulse.pid"

  set +e
  python3 - "${duration_seconds}" "${log_root}/live-quality-training.stdout.log" "${log_root}/live-quality-training.stderr.log" -- \
    python3 -m mesh_brain.live_quality_training \
      --output "${run_root}" \
      --model "${model_id}" \
      --sft-iters "${sft_iters}" \
      --preference-iters "${preference_iters}" \
      --preference-method "${preference_method}" \
      --max-seq-length "${max_seq_length}" \
      --num-layers "${num_layers}" \
      --timeout-seconds "${duration_seconds}" \
      --eval-limit "${eval_limit}" \
      --corpus-jsonl-limit "${corpus_jsonl_limit}" \
      --json <<'PY'
import subprocess
import sys
from pathlib import Path

duration_seconds = float(sys.argv[1])
stdout_path = Path(sys.argv[2])
stderr_path = Path(sys.argv[3])
separator_index = sys.argv.index("--")
command = sys.argv[separator_index + 1 :]

with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
    try:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=duration_seconds, check=False)
    except subprocess.TimeoutExpired:
        sys.exit(124)
sys.exit(completed.returncode)
PY
  status="$?"
  set -e

  kill "${pulse_pid}" >/dev/null 2>&1 || true
  wait "${pulse_pid}" >/dev/null 2>&1 || true

  if [[ "${status}" -eq 124 ]]; then
    log "training reached duration timeout after ${duration_seconds}s"
  elif [[ "${status}" -ne 0 ]]; then
    log "training failed with exit status ${status}"
  else
    log "training command completed"
  fi

  if [[ -f "${run_root}/live_quality_training_summary.json" ]]; then
    python3 - "$run_root" <<'PY'
import json
import sys
from pathlib import Path

run_root = Path(sys.argv[1])
summary = json.loads((run_root / "live_quality_training_summary.json").read_text(encoding="utf-8"))
compact = {
    "run_id": summary.get("run_id"),
    "status": summary.get("status"),
    "dataset_version": summary.get("dataset_version"),
    "release_decision": (summary.get("quality_result") or {}).get("release_decision"),
    "promotion_reasons": ((summary.get("quality_result") or {}).get("promotion_gate") or {}).get("reasons"),
    "rubric_scores": (((summary.get("quality_result") or {}).get("eval_comparison") or {}).get("rubric_scores")),
}
(run_root / "launcher" / "final_status.json").write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(compact, sort_keys=True))
PY
  fi

  return "${status}"
}

preflight

if [[ "${MESH_BRAIN_PREFLIGHT_ONLY:-0}" == "1" ]]; then
  log "preflight-only mode complete"
  exit 0
fi

log "launching eight-hour posttraining run: ${run_root}"
run_training
