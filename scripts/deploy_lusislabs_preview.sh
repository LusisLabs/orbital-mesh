#!/usr/bin/env bash
set -Eeuo pipefail

STATE_SLICE="lusislabs-preview-deployment"
BASE_DIR="${LUSIS_DEPLOY_BASE:-/opt/lusis-mesh-webapp}"
SOURCE_DIR="${BASE_DIR}/incoming/source"
RELEASES_DIR="${BASE_DIR}/releases"
SHARED_DIR="${BASE_DIR}/shared"
CURRENT_LINK="${BASE_DIR}/current"
ENV_FILE="${LUSIS_PREVIEW_ENV_FILE:-/etc/lusis-mesh-webapp-preview.env}"
SERVICE_NAME="${LUSIS_PREVIEW_SERVICE:-lusis-mesh-preview.service}"
PUBLIC_URL="${LUSIS_PUBLIC_URL:-https://lusislabs.com}"
NODE_HOME="${LUSIS_NODE_HOME:-/root/.nvm/versions/node/v22.22.3}"
KEEP_RELEASES="${LUSIS_KEEP_RELEASES:-5}"
LOCK_FILE="${LUSIS_DEPLOY_LOCK:-/run/lusis-mesh-webapp-deploy.lock}"

usage() {
  printf 'Usage: %s [--source PATH]\n' "$0" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE_DIR="${2:?--source requires a path}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

log() {
  printf '[%s] state_slice=%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$STATE_SLICE" "$*"
}

require_path() {
  if [ ! -e "$1" ]; then
    log "missing required path: $1"
    exit 1
  fi
}

healthcheck() {
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:8788/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

rollback_to() {
  local previous_target="$1"
  if [ -n "$previous_target" ] && [ -d "$previous_target" ]; then
    log "rolling back current symlink to $previous_target"
    ln -sfn "$previous_target" "${CURRENT_LINK}.next"
    mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"
    systemctl restart "$SERVICE_NAME" || true
  fi
}

cleanup_old_releases() {
  if ! [ "$KEEP_RELEASES" -gt 0 ] 2>/dev/null; then
    log "invalid LUSIS_KEEP_RELEASES=$KEEP_RELEASES"
    return
  fi
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -print0 \
    | xargs -0 ls -1dt 2>/dev/null \
    | awk -v keep="$KEEP_RELEASES" 'NR > keep { print }' \
    | while IFS= read -r stale_release; do
        [ -n "$stale_release" ] || continue
        rm -rf -- "$stale_release"
        log "removed stale release $stale_release"
      done
}

main() {
  umask 022
  install -d -m 755 "$BASE_DIR" "$RELEASES_DIR" "$SHARED_DIR"
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    log "another deploy is already running"
    exit 1
  fi

  require_path "$SOURCE_DIR"
  require_path "$ENV_FILE"
  export PATH="${NODE_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  require_path "${NODE_HOME}/bin/node"
  if ! command -v pnpm >/dev/null 2>&1; then
    log "missing required command: pnpm"
    exit 1
  fi

  local commit release_id release_dir previous_target
  if [ -s "${SOURCE_DIR}/.deploy-commit" ]; then
    commit="$(tr -d '[:space:]' < "${SOURCE_DIR}/.deploy-commit")"
  elif git -C "$SOURCE_DIR" rev-parse --short=12 HEAD >/dev/null 2>&1; then
    commit="$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD)"
  else
    commit="unknown"
  fi
  release_id="$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
  release_dir="${RELEASES_DIR}/${release_id}"
  previous_target="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"

  log "building release $release_id from $SOURCE_DIR"
  install -d -m 755 "$release_dir"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'node_modules/' \
    --exclude '.next/' \
    --exclude 'out/' \
    --exclude 'dist/' \
    --exclude '.mesh-runtime-state/' \
    --exclude '.mesh-runtime-state-preview/' \
    --exclude 'artifacts/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '.mypy_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.turbo/' \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude '.DS_Store' \
    --exclude '*.pyc' \
    "${SOURCE_DIR}/" "${release_dir}/"

  printf 'MESH_BUILD_COMMIT=%s\nMESH_BUILD_VERSION=%s\n' "$commit" "$release_id" > "${release_dir}/.deploy-env"

  cd "$release_dir"
  if ! pnpm --dir meshapp/frontend install --frozen-lockfile; then
    log "pnpm install failed; approving pending build scripts and retrying once"
    pnpm --dir meshapp/frontend approve-builds --all
    pnpm --dir meshapp/frontend install --frozen-lockfile
  fi
  NEXT_PUBLIC_MESH_API_URL="$PUBLIC_URL" pnpm --dir meshapp/frontend run build
  require_path "${release_dir}/meshapp/frontend/out/index.html"

  ln -sfn "$release_dir" "${CURRENT_LINK}.next"
  mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"

  log "restarting $SERVICE_NAME"
  tmux kill-session -t lusis-webapp-preview 2>/dev/null || true
  if ! systemctl restart "$SERVICE_NAME"; then
    rollback_to "$previous_target"
    exit 1
  fi
  if ! healthcheck; then
    log "healthcheck failed after restart"
    rollback_to "$previous_target"
    exit 1
  fi

  cleanup_old_releases
  log "deployed release $release_id"
}

main "$@"
