#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MESH_SMOKE_BASE_URL:-http://127.0.0.1:8787}"
HTTP_TIMEOUT_SECONDS="${MESH_SMOKE_HTTP_TIMEOUT_SECONDS:-30}"

require_json_field() {
  local url="$1"
  local field="$2"
  python3 - "$url" "$field" "$HTTP_TIMEOUT_SECONDS" <<'PY'
import json
import sys
import urllib.request

url, field, timeout_seconds = sys.argv[1:4]
with urllib.request.urlopen(url, timeout=float(timeout_seconds)) as response:
    if response.status < 200 or response.status >= 300:
        raise SystemExit(f"{url} returned HTTP {response.status}")
    payload = json.loads(response.read().decode("utf-8"))

cursor = payload
for part in field.split("."):
    if not isinstance(cursor, dict) or part not in cursor:
        raise SystemExit(f"{url} missing JSON field {field}")
    cursor = cursor[part]
print(json.dumps({field: cursor}, sort_keys=True))
PY
}

require_json_field "${BASE_URL}/api/health" "status"
require_json_field "${BASE_URL}/api/readiness" "state_path"
require_json_field "${BASE_URL}/api/readiness" "goose.ready"

if [[ "${MESH_SMOKE_HERMES:-0}" == "1" ]]; then
  require_json_field "${BASE_URL}/api/readiness" "hermes.ready"
fi

if [[ "${MESH_SMOKE_KUBERNETES:-0}" == "1" ]]; then
  : "${MESH_SMOKE_KUBE_CONTEXT:?set MESH_SMOKE_KUBE_CONTEXT for Kubernetes smoke}"
  : "${MESH_SMOKE_KUBE_NAMESPACE:?set MESH_SMOKE_KUBE_NAMESPACE for Kubernetes smoke}"
  kubectl --context "${MESH_SMOKE_KUBE_CONTEXT}" auth can-i get deployments -n "${MESH_SMOKE_KUBE_NAMESPACE}" >/dev/null
fi

echo "prod smoke passed: ${BASE_URL}"
