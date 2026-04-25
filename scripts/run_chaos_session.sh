#!/usr/bin/env bash
# Continuous chaos engineering session runner.
#
# What this does:
#   1. Creates (or reuses) a kind cluster named `mesh-e2e`.
#   2. Applies the baseline workload (search-api).
#   3. Runs a :class:`ContinuousChaosSession` for N minutes, picking
#      experiments from the portfolio on a weighted-random schedule
#      with per-primitive cooldowns and a circuit breaker on
#      steady-state probe failures.
#   4. Writes a session report (markdown + JSON) into e2e-reports/
#      plus a server log with Mesh's own per-stage output.
#
# Usage:
#   scripts/run_chaos_session.sh                             # 60 minutes
#   scripts/run_chaos_session.sh --duration 600              # 10 minutes
#   scripts/run_chaos_session.sh --reuse-cluster --seed 42
#
# Flags:
#   --duration N       session duration in seconds (default 3600 = 1 hour)
#   --seed N           PRNG seed for deterministic replay (default none)
#   --keep-cluster     don't tear down kind at the end
#   --reuse-cluster    skip cluster creation if it already exists
#
# Prereqs: kind, kubectl, docker, python3.11+ — same as run_e2e.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

CLUSTER_NAME="mesh-e2e"
KUBE_CONTEXT="kind-${CLUSTER_NAME}"
FIXTURES_DIR="${REPO_ROOT}/tests/e2e/fixtures"
REPORTS_DIR="${REPO_ROOT}/e2e-reports"
DURATION_SECONDS=3600
SEED=""
KEEP_CLUSTER=0
REUSE_CLUSTER=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration)
            DURATION_SECONDS="$2"
            shift 2
            ;;
        --seed)
            SEED="$2"
            shift 2
            ;;
        --keep-cluster)
            KEEP_CLUSTER=1
            shift
            ;;
        --reuse-cluster)
            REUSE_CLUSTER=1
            shift
            ;;
        --help|-h)
            sed -n '2,/^set -euo/p' "$0" | sed 's/^#//'
            exit 0
            ;;
        *)
            echo "unknown flag: $1" >&2
            exit 1
            ;;
    esac
done

log() { printf '[chaos] %s\n' "$*" >&2; }

for tool in kind kubectl docker python3; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "required tool '${tool}' not found on PATH" >&2
        exit 1
    fi
done

# --- cluster lifecycle ------------------------------------------------------
if [[ "${REUSE_CLUSTER}" -eq 0 ]]; then
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        log "deleting existing cluster '${CLUSTER_NAME}' for a clean run"
        kind delete cluster --name "${CLUSTER_NAME}"
    fi
    log "creating kind cluster '${CLUSTER_NAME}'"
    kind create cluster --config "${FIXTURES_DIR}/kind-config.yaml"
else
    log "reusing kind cluster '${CLUSTER_NAME}'"
fi

if ! kubectl --context "${KUBE_CONTEXT}" get nodes >/dev/null 2>&1; then
    echo "kubectl cannot reach context ${KUBE_CONTEXT}" >&2
    exit 1
fi

# --- baseline workload ------------------------------------------------------
log "applying baseline workload"
kubectl --context "${KUBE_CONTEXT}" apply -f "${FIXTURES_DIR}/workload-search-api.yaml"
kubectl --context "${KUBE_CONTEXT}" -n mesh-e2e rollout status deployment/search-api --timeout=120s

# --- run the session -------------------------------------------------------
mkdir -p "${REPORTS_DIR}"
log "starting chaos session (duration=${DURATION_SECONDS}s seed=${SEED:-none})"

export PYTHONPATH="${REPO_ROOT}"
python3 - "${KUBE_CONTEXT}" "${REPORTS_DIR}" "${DURATION_SECONDS}" "${SEED}" <<'PY'
import logging
import os
import sys
import time

from tests.e2e.chaos.portfolio import DEFAULT_PORTFOLIO
from tests.e2e.continuous.metrics import Hypothesis
from tests.e2e.continuous.report import write_report
from tests.e2e.continuous.session import ContinuousChaosSession
from tests.e2e.harness import ensure_cluster_reachable


kube_context = sys.argv[1]
reports_dir = sys.argv[2]
duration_seconds = float(sys.argv[3])
seed_raw = sys.argv[4].strip()
seed = int(seed_raw) if seed_raw else None

ensure_cluster_reachable(kube_context)

# --- configure logging to a session-level file ------------------------
# Route every ``mesh.*`` logger at INFO+ to a log file alongside the
# session report. The same FileHandler pattern the per-scenario harness
# uses, applied here at session scope.
os.makedirs(reports_dir, exist_ok=True)
log_path = os.path.join(reports_dir, f"chaos_session_{int(time.time())}.server.log")
handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
handler.setLevel(logging.INFO)
handler.setFormatter(
    logging.Formatter("%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
)
mesh_logger = logging.getLogger("mesh")
mesh_logger.setLevel(logging.INFO)
mesh_logger.addHandler(handler)

print(f"[chaos] server log: {log_path}", file=sys.stderr)

# --- hypothesis ------------------------------------------------------
# Defaults match the per-metric discussion in the README. Tune them
# per-session by editing below; a future enhancement could load
# overrides from a config file.
hypothesis = Hypothesis(
    min_detection_rate=0.9,
    min_correct_decision_rate=0.85,
    max_false_positive_rate=0.1,
    min_probe_pass_rate=0.9,
    max_decision_p95_latency_seconds=10.0,
    min_pipeline_availability=1.0,
)

session = ContinuousChaosSession(
    kube_context=kube_context,
    namespace="mesh-e2e",
    targets=("search-api",),
    duration_seconds=duration_seconds,
    hypothesis=hypothesis,
    portfolio=DEFAULT_PORTFOLIO,
    probe_every_n=5,
    seed=seed,
)

result = session.run()
paths = write_report(result, reports_dir)

print(f"[chaos] verdict:           {result.verdict}")
if result.halt_reason:
    print(f"[chaos] halt reason:       {result.halt_reason}")
print(f"[chaos] experiments:       {result.aggregates.experiments_total}")
print(f"[chaos] passed:            {result.aggregates.experiments_passed}")
print(f"[chaos] probes:            {result.aggregates.probes_total} "
      f"({result.aggregates.probes_passed} ok)")
print(f"[chaos] report (markdown): {paths['markdown']}")
print(f"[chaos] report (json):     {paths['json']}")
print(f"[chaos] server log:        {log_path}")

# Verdict mapping:
#   pass → 0 (all hypothesis predictions held)
#   fail → 1 (hypothesis breached)
#   halted_by_circuit_breaker → 2 (operator should investigate)
sys.exit({"pass": 0, "fail": 1}.get(result.verdict, 2))
PY

VERDICT_CODE=$?

if [[ "${KEEP_CLUSTER}" -eq 0 ]]; then
    log "deleting kind cluster '${CLUSTER_NAME}'"
    kind delete cluster --name "${CLUSTER_NAME}"
else
    log "keeping kind cluster '${CLUSTER_NAME}'"
fi

exit "${VERDICT_CODE}"
