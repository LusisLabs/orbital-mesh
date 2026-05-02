#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${MESH_BREAKTHROUGH_COMPOSE_FILE:-${ROOT_DIR}/docker-compose.stack.yml}"
PROJECT_ARGS=(-f "${COMPOSE_FILE}")
CHAOS_SERVICE="${MESH_BREAKTHROUGH_CHAOS_SERVICE:-mesh-chaos}"
OUTPUT_DIR="${MESH_BREAKTHROUGH_OUTPUT_DIR:-${ROOT_DIR}/.mesh-runtime-state/proofs}"
REPLAY_ONLY=0
CURRENT_STEP="startup"

usage() {
  cat <<'EOF'
Usage: scripts/run_breakthrough_proof.sh [--replay-only]

Runs the live compose breakthrough proof gate:
  1. verify all configured Kubernetes substrates are healthy
  2. run compose chaos with full-axis, substrate, and multi-fault gates
  3. verify all substrates recovered
  4. generate a replay-protected proof bundle
  5. assert the proof is ready

Options:
  --replay-only   Skip live chaos and validate the latest existing artifacts.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --replay-only)
      REPLAY_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "${OUTPUT_DIR}"

TARGETS="${MESH_STACK_CHAOS_TARGETS:-mesh-compose:search:semantic-search:container,mesh-compose-vm:search:semantic-search:vm,mesh-compose-baremetal:search:semantic-search:baremetal}"

log() {
  printf '%s\n' "$*" >&2
}

on_error() {
  local exit_code=$?
  cat >&2 <<EOF
breakthrough proof failed during: ${CURRENT_STEP}
exit code: ${exit_code}

If the output includes Docker overlay2 or kubeconfig input/output errors,
the Docker Desktop VM filesystem is unhealthy. Restart Docker Desktop, wait
for the compose stack to become healthy again, then rerun this script.
Do not trust partial live-chaos output as proof; only a final ready proof
bundle printed by this script is valid.
EOF
  exit "${exit_code}"
}

trap on_error ERR

docker_preflight() {
  CURRENT_STEP="docker preflight"
  docker info >/dev/null
  docker compose "${PROJECT_ARGS[@]}" ps mesh >/dev/null
}

verify_target_health() {
  local context="$1"
  local namespace="$2"
  local deployment="$3"
  local substrate="$4"
  local counts

  counts="$(
    docker compose "${PROJECT_ARGS[@]}" exec -T mesh \
      kubectl --context "${context}" -n "${namespace}" \
      get deployment "${deployment}" \
      -o "jsonpath={.spec.replicas} {.status.readyReplicas} {.status.availableReplicas} {.status.updatedReplicas}"
  )"
  if [ "${counts}" != "3 3 3 3" ]; then
    echo "unhealthy target ${substrate} (${context}/${namespace}/${deployment}): ${counts}" >&2
    exit 1
  fi
  log "healthy ${substrate}: ${counts}"
}

verify_stack_health() {
  CURRENT_STEP="stack health verification"
  local item context namespace deployment substrate
  IFS=',' read -r -a items <<< "${TARGETS}"
  for item in "${items[@]}"; do
    IFS=':' read -r context namespace deployment substrate <<< "${item}"
    if [ -z "${context}" ] || [ -z "${namespace}" ] || [ -z "${deployment}" ] || [ -z "${substrate}" ]; then
      echo "invalid MESH_STACK_CHAOS_TARGETS item: ${item}" >&2
      exit 1
    fi
    verify_target_health "${context}" "${namespace}" "${deployment}" "${substrate}"
  done
}

run_live_chaos() {
  CURRENT_STEP="live compose chaos"
  log "starting live compose chaos proof"
  docker compose "${PROJECT_ARGS[@]}" run --rm --no-deps \
    -e "MESH_STACK_CHAOS_TARGETS=${TARGETS}" \
    -e "MESH_STACK_CHAOS_DURATION_SECONDS=${MESH_STACK_CHAOS_DURATION_SECONDS:-10800}" \
    -e "MESH_STACK_CHAOS_MIN_SLEEP_SECONDS=${MESH_STACK_CHAOS_MIN_SLEEP_SECONDS:-2}" \
    -e "MESH_STACK_CHAOS_MAX_SLEEP_SECONDS=${MESH_STACK_CHAOS_MAX_SLEEP_SECONDS:-5}" \
    -e "MESH_STACK_CHAOS_HOLD_SECONDS=${MESH_STACK_CHAOS_HOLD_SECONDS:-8}" \
    -e "MESH_STACK_CHAOS_STOP_ON_BREAKTHROUGH=1" \
    -e "MESH_STACK_CHAOS_REQUIRE_FULL_AXIS_COVERAGE=1" \
    -e "MESH_STACK_CHAOS_REQUIRE_SUBSTRATE_COVERAGE=1" \
    -e "MESH_STACK_CHAOS_REQUIRE_MULTI_FAULT_BREADTH=1" \
    -e "MESH_STACK_CHAOS_COVERAGE_FIRST=1" \
    -e "MESH_STACK_CHAOS_SEED=${MESH_STACK_CHAOS_SEED:-$(date -u +%Y%m%d%H%M)}" \
    -e "MESH_STACK_CHAOS_RUN_WAIT_SECONDS=${MESH_STACK_CHAOS_RUN_WAIT_SECONDS:-900}" \
    -e "MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS=${MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS:-180}" \
    -e "MESH_STACK_CHAOS_RUN_STAGE_GRACE_SECONDS=${MESH_STACK_CHAOS_RUN_STAGE_GRACE_SECONDS:-900}" \
    -e "MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS=${MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS:-1800}" \
    "${CHAOS_SERVICE}"
}

generate_proof_bundle() {
  CURRENT_STEP="proof bundle generation"
  log "generating proof bundle"
  local compose_summary
  local compose_events
  compose_summary="$(latest_ready_compose_summary)"
  compose_events="$(events_path_for_summary "${compose_summary}")"
  PYTHONPATH="${ROOT_DIR}" python3 "${ROOT_DIR}/scripts/breakthrough_evidence_bundle.py" \
    --repo-root "${ROOT_DIR}" \
    --output-dir "${OUTPUT_DIR}" \
    --compose-summary "${compose_summary}" \
    --compose-events "${compose_events}"
}

latest_ready_compose_summary() {
  PYTHONPATH="${ROOT_DIR}" python3 - <<'PY' "${ROOT_DIR}"
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
summary_dir = repo_root / ".mesh-runtime-state" / "compose-chaos"
for path in sorted(summary_dir.glob("summary-*.json"), reverse=True):
    summary = json.loads(path.read_text(encoding="utf-8"))
    probe = summary.get("breakthrough_probe") or {}
    capabilities = summary.get("capabilities") or {}
    substrates = summary.get("substrate_coverage") or {}
    multi_fault = summary.get("multi_fault_coverage") or {}
    if probe.get("ready") is not True:
        continue
    if capabilities.get("missing_axes") or capabilities.get("failed_or_unproven_axes"):
        continue
    if not substrates or any((coverage or {}).get("passed", 0) < 1 for coverage in substrates.values()):
        continue
    if multi_fault.get("missing_experiments"):
        continue
    events_path = summary.get("events_path")
    if not isinstance(events_path, str) or not events_path:
        continue
    event_file = Path(events_path)
    if not event_file.is_absolute():
        event_file = repo_root / event_file
    if not event_file.exists():
        sibling = path.with_name(Path(events_path).name)
        if not sibling.exists():
            continue
    print(path)
    raise SystemExit(0)
raise SystemExit(f"no ready compose chaos summary found under {summary_dir}")
PY
}

events_path_for_summary() {
  PYTHONPATH="${ROOT_DIR}" python3 - <<'PY' "${ROOT_DIR}" "$1"
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
events_path = summary.get("events_path")
if not isinstance(events_path, str) or not events_path:
    raise SystemExit(f"{summary_path} does not include events_path")
path = Path(events_path)
if not path.is_absolute():
    path = repo_root / path
if path.exists():
    print(path)
    raise SystemExit(0)
sibling = summary_path.with_name(Path(events_path).name)
if sibling.exists():
    print(sibling)
    raise SystemExit(0)
raise SystemExit(f"events file for {summary_path} not found: {events_path}")
PY
}

assert_latest_proof_ready() {
  CURRENT_STEP="proof bundle readiness assertion"
  PYTHONPATH="${ROOT_DIR}" python3 - <<'PY' "${ROOT_DIR}" "${OUTPUT_DIR}"
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
proofs = sorted(output_dir.glob("breakthrough-proof-*.json"))
if not proofs:
    raise SystemExit(f"no breakthrough proof bundle found under {output_dir}")
proof_path = proofs[-1]
proof = json.loads(proof_path.read_text(encoding="utf-8"))
breakthrough = proof.get("breakthrough_proof") or {}
if breakthrough.get("ready") is not True:
    raise SystemExit(f"proof bundle is not ready: {proof_path}")
reports = proof.get("replay", {}).get("reports", [])
failed = [report.get("kind") for report in reports if report.get("passed") is not True]
if failed:
    raise SystemExit(f"proof replay reports failed: {failed}")
compose_checks = {}
for check in proof.get("summary_checks", []):
    if check.get("kind") == "compose":
        compose_checks = check.get("coverage_checks") or {}
        break
if any(compose_checks.values()):
    raise SystemExit(f"compose coverage checks are not empty: {compose_checks}")
print(json.dumps({
    "proof": str(proof_path.relative_to(repo_root)),
    "ready": breakthrough.get("ready"),
    "status": breakthrough.get("status"),
    "bundle_sha256": proof.get("bundle_sha256"),
    "compose_coverage_checks": compose_checks,
}, sort_keys=True))
PY
}

if [ "${REPLAY_ONLY}" = "0" ]; then
  docker_preflight
  verify_stack_health
  run_live_chaos
  verify_stack_health
else
  CURRENT_STEP="replay-only proof validation"
  log "replay-only mode: skipping live chaos and stack mutation"
fi

generate_proof_bundle
assert_latest_proof_ready
