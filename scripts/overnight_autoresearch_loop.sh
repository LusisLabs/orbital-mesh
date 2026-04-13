#!/usr/bin/env bash
# Long-running autoresearch loop for mesh-intelligence: empirical pipeline digest
# (FirstSlicePipeline) with Promptfoo + Goose, optional MiniMax multi-wave synthesis,
# and optional live Kubernetes runs via the HTTP control plane.
#
# Prerequisites (pick what you need):
#   - Python 3 with repo on PYTHONPATH (run from repo root).
#   - For Promptfoo + Goose modes: working integrations (see README / .env.example).
#     Hermes-style routing: set HERMES_INFERENCE_PROVIDER, HERMES_MODEL (and/or GOOSE_*)
#     before starting Docker or native mesh so `shared.mesh_runtime.integrations` resolves.
#   - For --minimax / OVERNIGHT_MINIMAX=1: OPENAI_API_KEY + OPENAI_BASE_URL or Anthropic keys
#     (see .cursor/skills/goose-autoresearch/SKILL.md).
#   - For OVERNIGHT_HTTP_RUNS=1: control plane up (e.g. docker compose), live cluster + allowlists
#     (MESH_KUBERNETES_*), and kubectl context that matches KUBE_CONTEXT.
#   - "Knowledge base" in-repo: sessions under MESH_RESEARCH_DIRECTORY (default
#     .mesh-runtime-state/research); control plane exposes GET /api/research-corpus and
#     per-session intelligence. Run bundles mirror into MESH_VAULT_PATH; optional
#     MESH_VAULT_AI_POSTPROCESS_ENABLED=1 enriches vault markdown after runs.
#   - Optional GitNexus: MESH_GITNEXUS_SIDECAR_URL for sidecar-linked workflows.
#
# Usage:
#   chmod +x scripts/overnight_autoresearch_loop.sh
#   OVERNIGHT_DURATION_SECONDS=$((8*3600)) ./scripts/overnight_autoresearch_loop.sh
#
# Environment (all optional):
#   OVERNIGHT_DURATION_SECONDS   default 28800 (8 hours)
#   OVERNIGHT_INTERVAL_SECONDS   sleep between cycles, default 900 (15 min)
#   OVERNIGHT_EVALUATION_MODE    default promptfoo
#   OVERNIGHT_ORCHESTRATION_MODE default goose
#   OVERNIGHT_MINIMAX            set to 1 to chain MiniMax after each showcase (needs API keys)
#   OVERNIGHT_HTTP_RUNS          set to 1 to also POST /api/runs with live_signal each cycle
#   BASE_URL, GOAL_ID, KUBE_CONTEXT, etc. — passed through to scripts/e2e_run_mesh.sh when HTTP on
#   E2E_RUN_TERMINAL_WAIT_SECONDS max wait for a single HTTP run (default 3600 here when HTTP on)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

DURATION_SECONDS="${OVERNIGHT_DURATION_SECONDS:-$((8 * 3600))}"
INTERVAL_SECONDS="${OVERNIGHT_INTERVAL_SECONDS:-900}"
EVAL_MODE="${OVERNIGHT_EVALUATION_MODE:-promptfoo}"
ORCH_MODE="${OVERNIGHT_ORCHESTRATION_MODE:-goose}"

END_TS=$(( $(date +%s) + DURATION_SECONDS ))
CYCLE=0

MINIMAX_FLAG=()
if [[ "${OVERNIGHT_MINIMAX:-0}" == "1" ]]; then
  MINIMAX_FLAG=(--minimax)
fi

echo "Overnight loop: repo=${REPO_ROOT}"
echo "Until: $(date -u -r "${END_TS}" +%Y-%m-%dT%H:%M:%SZ) (UTC) | interval=${INTERVAL_SECONDS}s | eval=${EVAL_MODE} orch=${ORCH_MODE}"
if [[ "${#MINIMAX_FLAG[@]}" -gt 0 ]]; then
  echo "MiniMax: enabled after each showcase cycle"
fi
if [[ "${OVERNIGHT_HTTP_RUNS:-0}" == "1" ]]; then
  echo "HTTP live runs: enabled (BASE_URL=${BASE_URL:-http://127.0.0.1:8787})"
fi

while (( $(date +%s) < END_TS )); do
  CYCLE=$((CYCLE + 1))
  echo ""
  echo "=== cycle ${CYCLE} $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

  set +e
  python3 scripts/mesh_showcase_research.py \
    --evaluation-mode "${EVAL_MODE}" \
    --orchestration-mode "${ORCH_MODE}" \
    "${MINIMAX_FLAG[@]}"
  showcase_rc=$?
  set -e
  if [[ "${showcase_rc}" -ne 0 ]]; then
    echo "warning: mesh_showcase_research exited ${showcase_rc}; continuing"
  fi

  if [[ "${OVERNIGHT_HTTP_RUNS:-0}" == "1" ]]; then
    export BASE_URL="${BASE_URL:-http://127.0.0.1:8787}"
    export GOAL_ID="${GOAL_ID:-goal_default}"
    export EVALUATION_MODE="${EVAL_MODE}"
    export ORCHESTRATION_MODE="${ORCH_MODE}"
    export STEERING_MODE="${STEERING_MODE:-interruptible_auto}"
    export E2E_RUN_TERMINAL_WAIT_SECONDS="${E2E_RUN_TERMINAL_WAIT_SECONDS:-3600}"
    set +e
    bash scripts/e2e_run_mesh.sh
    http_rc=$?
    set -e
    if [[ "${http_rc}" -ne 0 ]]; then
      echo "warning: e2e_run_mesh.sh exited ${http_rc}; continuing"
    fi
  fi

  if (( $(date +%s) >= END_TS )); then
    break
  fi
  echo "sleeping ${INTERVAL_SECONDS}s …"
  sleep "${INTERVAL_SECONDS}"
done

echo "Overnight loop finished after ${CYCLE} cycle(s)."
