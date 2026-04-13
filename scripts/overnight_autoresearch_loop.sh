#!/usr/bin/env bash
# Overnight Mesh autoresearch — thin wrapper around Python orchestration.
#
# The implementation lives in scripts/overnight_mesh_autoresearch.py:
#   - mesh_showcase_research with --embed-minimax-prompt when MiniMax is enabled
#   - each MiniMax cycle prepends the previous session's synthesis/final-report.md into manifest.question
#   - two full session snapshots under .mesh-runtime-state/research/_archive/…_archive_a|_archive_b
#   - optional: OVERNIGHT_ARCHIVE_VAULT_TWICE=1 duplicates the vault tree twice per cycle (large)
#   - OVERNIGHT_OLLAMA_FALLBACK=1 (default): MiniMax missing/failed → Ollama final-report.md;
#     HTTP e2e failed → notes/kubernetes_http_run_fallback.md (OVERNIGHT_OLLAMA_MODEL, OLLAMA_HOST)
#   - OVERNIGHT_HOLISTIC_MATRIX=1 (default): 12-run FirstSlice sweep (native/promptfoo × native/goose × 3 fixtures)
#   - OVERNIGHT_HTTP_FULL_MATRIX=1: each cycle POST live K8s + both scenario_keys × 4 mode pairs (12 HTTP runs)
#   - OVERNIGHT_HTTP_PER_RUN_TIMEOUT_SECONDS: per-run wait when using holistic HTTP (default 300)
#   - MESH_SHOWCASE_HOLISTIC_FAST=1: dev/CI shortcut — only native+native × 3 fixtures in mesh_showcase --holistic-matrix
#
# Environment: see overnight_mesh_autoresearch.py module docstring (OVERNIGHT_* vars).
#
# Usage:
#   OVERNIGHT_DURATION_SECONDS=$((8*3600)) OVERNIGHT_MINIMAX=1 ./scripts/overnight_autoresearch_loop.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

exec python3 scripts/overnight_mesh_autoresearch.py "$@"
