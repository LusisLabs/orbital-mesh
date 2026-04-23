#!/usr/bin/env bash
# End-to-end scenario runner for Mesh.
#
# What this does:
#   1. Creates (or reuses) a kind cluster named `mesh-e2e`.
#   2. Applies the baseline workload.
#   3. Runs the requested scenario through the harness.
#   4. Writes markdown + JSON reports into e2e-reports/.
#
# Prerequisites:
#   - kind        (https://kind.sigs.k8s.io/)
#   - kubectl     (any 1.20+)
#   - docker      (kind needs it)
#   - python3     (3.11+ with mesh repo deps installed)
#
# Usage:
#   scripts/run_e2e.sh                         # runs crash_loop, default
#   scripts/run_e2e.sh crash_loop             # runs a specific scenario
#   scripts/run_e2e.sh --keep-cluster ...     # skip cluster teardown
#   scripts/run_e2e.sh --reuse-cluster ...    # skip cluster creation
#
# The script is intentionally aggressive about setup and cleanup:
# bringing the cluster up is ~30s and tearing it down is ~5s, so for a
# fresh-state run that's fine. For iterative development, pass
# --reuse-cluster to skip both.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

CLUSTER_NAME="mesh-e2e"
KUBE_CONTEXT="kind-${CLUSTER_NAME}"
FIXTURES_DIR="${REPO_ROOT}/tests/e2e/fixtures"
REPORTS_DIR="${REPO_ROOT}/e2e-reports"
SCENARIO="crash_loop"
KEEP_CLUSTER=0
REUSE_CLUSTER=0

# --- argument parsing -------------------------------------------------------
# Positional: scenario name. Named: --keep-cluster, --reuse-cluster.
# Deliberately small — we don't want a flag zoo here. Add new flags only
# when there's a real operational need.
while [[ $# -gt 0 ]]; do
    case "$1" in
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
        -*)
            echo "unknown flag: $1" >&2
            exit 1
            ;;
        *)
            SCENARIO="$1"
            shift
            ;;
    esac
done

log() { printf '[e2e] %s\n' "$*" >&2; }

# --- prereq checks ----------------------------------------------------------
# Fail fast with clear messages so an operator missing a tool doesn't get
# a confusing error five commands deep.
for tool in kind kubectl docker python3; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "required tool '${tool}' not found on PATH" >&2
        exit 1
    fi
done

# --- cluster lifecycle ------------------------------------------------------
if [[ "${REUSE_CLUSTER}" -eq 0 ]]; then
    if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        log "kind cluster '${CLUSTER_NAME}' already exists; deleting for a clean run"
        kind delete cluster --name "${CLUSTER_NAME}"
    fi
    log "creating kind cluster '${CLUSTER_NAME}'"
    kind create cluster --config "${FIXTURES_DIR}/kind-config.yaml"
else
    log "reusing existing kind cluster '${CLUSTER_NAME}'"
fi

# Ensure kubectl points at our cluster. Leave the original current-context
# untouched for the operator; the harness always uses --context explicitly.
if ! kubectl --context "${KUBE_CONTEXT}" get nodes >/dev/null 2>&1; then
    echo "kubectl cannot reach context ${KUBE_CONTEXT}" >&2
    exit 1
fi

# --- baseline workload ------------------------------------------------------
log "applying baseline workload"
kubectl --context "${KUBE_CONTEXT}" apply -f "${FIXTURES_DIR}/workload-search-api.yaml"
kubectl --context "${KUBE_CONTEXT}" -n mesh-e2e rollout status deployment/search-api --timeout=120s

# --- run the scenario ------------------------------------------------------
mkdir -p "${REPORTS_DIR}"
log "running scenario: ${SCENARIO}"

# Python entrypoint: import the scenario module, run it through the
# harness, and write the report. Inlined here so the driver is a single
# self-contained file for anyone wanting to understand the flow.
export PYTHONPATH="${REPO_ROOT}"
python3 - "${SCENARIO}" "${KUBE_CONTEXT}" "${REPORTS_DIR}" <<'PY'
import importlib
import os
import sys

from tests.e2e.harness import Harness, ensure_cluster_reachable
from tests.e2e.report import write_report

scenario_name, kube_context, reports_dir = sys.argv[1], sys.argv[2], sys.argv[3]
ensure_cluster_reachable(kube_context)

try:
    module = importlib.import_module(f"tests.e2e.scenarios.{scenario_name}")
except ModuleNotFoundError:
    print(f"[e2e] unknown scenario: {scenario_name}", file=sys.stderr)
    print("      available scenarios: crash_loop", file=sys.stderr)
    sys.exit(2)

# Server log path lives in the reports dir alongside the markdown/JSON —
# one directory to grab, one to hand to a reviewer.
os.makedirs(reports_dir, exist_ok=True)
log_path = os.path.join(reports_dir, f"{scenario_name}.server.log")

harness = Harness(
    kube_context=kube_context,
    namespace="mesh-e2e",
    log_file=log_path,
)
run = harness.run_scenario(scenario_name, module.run)
paths = write_report(run, reports_dir)

print(f"[e2e] verdict: {run.verdict}")
print(f"[e2e] report (markdown): {paths['markdown']}")
print(f"[e2e] report (json):     {paths['json']}")
print(f"[e2e] server log:        {log_path}")

# Propagate the verdict to the shell so CI can gate on it.
sys.exit(0 if run.verdict == "pass" else 1)
PY

VERDICT_CODE=$?

# --- cluster teardown -------------------------------------------------------
if [[ "${KEEP_CLUSTER}" -eq 0 ]]; then
    log "deleting kind cluster '${CLUSTER_NAME}'"
    kind delete cluster --name "${CLUSTER_NAME}"
else
    log "keeping kind cluster '${CLUSTER_NAME}' (--keep-cluster was set)"
fi

exit "${VERDICT_CODE}"
