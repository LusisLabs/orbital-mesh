#!/usr/bin/env bash
set -Eeuo pipefail

STATE_SLICE="lusislabs-preview-deployment"
BASE_DIR="${LUSIS_DEPLOY_BASE:-/opt/lusis-mesh-webapp}"
SOURCE_DIR="${BASE_DIR}/incoming/source"
RELEASE_ARTIFACT_ROOT=""
RELEASES_DIR="${BASE_DIR}/releases"
SHARED_DIR="${BASE_DIR}/shared"
CURRENT_LINK="${BASE_DIR}/current"
ENV_FILE="${LUSIS_PREVIEW_ENV_FILE:-/etc/lusis-mesh-webapp-preview.env}"
SERVICE_NAME="${LUSIS_PREVIEW_SERVICE:-lusis-mesh-preview.service}"
RELEASE_CONTAINER_NAME="${LUSIS_RELEASE_CONTAINER:-lusis-mesh-release}"
PUBLIC_URL="${LUSIS_PUBLIC_URL:-https://lusislabs.com}"
NODE_HOME="${LUSIS_NODE_HOME:-/root/.nvm/versions/node/v22.22.3}"
KEEP_RELEASES="${LUSIS_KEEP_RELEASES:-5}"
LOCK_FILE="${LUSIS_DEPLOY_LOCK:-/run/lusis-mesh-webapp-deploy.lock}"

usage() {
  printf 'Usage: %s [--source PATH] [--release-artifact-root PATH]\n' "$0" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE_DIR="${2:?--source requires a path}"
      shift 2
      ;;
    --release-artifact-root)
      RELEASE_ARTIFACT_ROOT="${2:?--release-artifact-root requires a path}"
      STATE_SLICE="release-image-runtime-binding"
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

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "missing required command: $1"
    exit 1
  fi
}

json_field() {
  local path="$1"
  local expression="$2"
  python3 - "$path" "$expression" <<'PY'
import json
import sys

path, expression = sys.argv[1:3]
value = json.loads(open(path, encoding="utf-8").read())
for part in expression.split("."):
    if not isinstance(value, dict):
        value = ""
        break
    value = value.get(part, "")
if value is None:
    value = ""
print(value)
PY
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

deploy_release_image() {
  require_path "$RELEASE_ARTIFACT_ROOT"
  require_path "$ENV_FILE"
  require_command python3
  require_command docker
  require_command curl

  local manifest image_archive release_provenance image_tag commit digest release_id release_dir
  manifest="${RELEASE_ARTIFACT_ROOT}/release-image-handoff/release-image-handoff.json"
  image_archive="${RELEASE_ARTIFACT_ROOT}/release-image-handoff/orbital-mesh-handoff-image.tar.gz"
  release_provenance="${RELEASE_ARTIFACT_ROOT}/release-provenance-draft.json"
  require_path "$manifest"
  require_path "$image_archive"
  require_path "$release_provenance"

  image_tag="$(json_field "$manifest" "image.tag")"
  commit="$(json_field "$manifest" "git.commit")"
  digest="$(json_field "$manifest" "image.digest")"
  if [ -z "$image_tag" ] || [ -z "$commit" ] || [ -z "$digest" ]; then
    log "handoff manifest missing image tag, commit, or digest"
    exit 1
  fi

  release_id="$(date -u +%Y%m%dT%H%M%SZ)-release-image-${commit:0:12}"
  release_dir="${RELEASES_DIR}/${release_id}"
  local state_dir runtime_env_tmp previous_container previous_service_active
  state_dir="${SHARED_DIR}/state"
  runtime_env_tmp="${release_dir}/release-runtime.env"
  previous_container=""
  previous_service_active=0

  install -d -m 755 "$release_dir" "$state_dir"
  log "loading release image $image_tag from $image_archive"
  docker load -i "$image_archive"

  log "verifying handoff image, signed provenance, and runtime env"
  python3 scripts/verify_release_image_handoff.py \
    --manifest "$manifest" \
    --image-archive "$image_archive" \
    --artifact-root "$RELEASE_ARTIFACT_ROOT" \
    --require-artifacts \
    --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
    --image-ref "$image_tag" \
    --complete-release-provenance "$release_provenance" \
    --env-output "$runtime_env_tmp" \
    --json >/dev/null

  install -m 644 "$manifest" "${release_dir}/release-image-handoff.json"
  install -m 644 "$release_provenance" "${state_dir}/release-provenance.json"
  install -m 644 "$runtime_env_tmp" "${state_dir}/release-runtime.env"
  printf 'MESH_BUILD_COMMIT=%s\nMESH_BUILD_VERSION=%s\nMESH_BUILD_IMAGE_DIGEST=%s\n' \
    "$commit" "$release_id" "$digest" > "${release_dir}/.deploy-env"

  if systemctl is-active --quiet "$SERVICE_NAME"; then
    previous_service_active=1
  fi
  if docker container inspect "$RELEASE_CONTAINER_NAME" >/dev/null 2>&1; then
    previous_container="${RELEASE_CONTAINER_NAME}.previous.${release_id}"
    docker rm -f "$previous_container" >/dev/null 2>&1 || true
    docker stop "$RELEASE_CONTAINER_NAME" >/dev/null
    docker rename "$RELEASE_CONTAINER_NAME" "$previous_container"
  fi

  log "stopping source preview service before binding port 8788"
  systemctl stop "$SERVICE_NAME" || true

  if ! docker run -d \
    --name "$RELEASE_CONTAINER_NAME" \
    --restart unless-stopped \
    --env-file "$ENV_FILE" \
    --env-file "$runtime_env_tmp" \
    -e MESH_SERVER_HOST=0.0.0.0 \
    -e MESH_SERVER_PORT=8787 \
    -e MESH_ENVIRONMENT=pilot \
    -e MESH_READINESS_PROFILE=pilot \
    -e MESH_STATE_DIRECTORY=/app/.mesh-runtime-state \
    -e MESH_RELEASE_PROVENANCE_PATH=/app/.mesh-runtime-state/release-provenance.json \
    -e MESH_WEB_ASSET_PATH=/app/meshapp/frontend/out \
    -p 127.0.0.1:8788:8787 \
    -v "${state_dir}:/app/.mesh-runtime-state" \
    "$image_tag" >/dev/null; then
    log "release image container failed to start"
    docker rm -f "$RELEASE_CONTAINER_NAME" >/dev/null 2>&1 || true
    if [ -n "$previous_container" ]; then
      docker rename "$previous_container" "$RELEASE_CONTAINER_NAME" || true
      docker start "$RELEASE_CONTAINER_NAME" || true
    elif [ "$previous_service_active" -eq 1 ]; then
      systemctl start "$SERVICE_NAME" || true
    fi
    exit 1
  fi

  if ! healthcheck; then
    log "release image healthcheck failed; rolling back"
    docker rm -f "$RELEASE_CONTAINER_NAME" >/dev/null 2>&1 || true
    if [ -n "$previous_container" ]; then
      docker rename "$previous_container" "$RELEASE_CONTAINER_NAME" || true
      docker start "$RELEASE_CONTAINER_NAME" || true
    elif [ "$previous_service_active" -eq 1 ]; then
      systemctl start "$SERVICE_NAME" || true
    fi
    exit 1
  fi

  if [ -n "$previous_container" ]; then
    docker rm -f "$previous_container" >/dev/null 2>&1 || true
  fi
  ln -sfn "$release_dir" "${CURRENT_LINK}.next"
  mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"
  cleanup_old_releases
  log "deployed release image $image_tag digest=$digest commit=$commit"
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

  if [ -n "$RELEASE_ARTIFACT_ROOT" ]; then
    deploy_release_image
    return
  fi

  require_path "$SOURCE_DIR"
  require_path "$ENV_FILE"
  export PATH="${NODE_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  require_path "${NODE_HOME}/bin/node"
  require_command pnpm

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
