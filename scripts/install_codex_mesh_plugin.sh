#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_source="${repo_root}/plugins/mesh-intelligence"
plugin_target="${HOME}/plugins/mesh-intelligence"
marketplace_dir="${HOME}/.agents/plugins"
marketplace_path="${marketplace_dir}/marketplace.json"

if [[ ! -f "${plugin_source}/.codex-plugin/plugin.json" ]]; then
  echo "missing plugin manifest: ${plugin_source}/.codex-plugin/plugin.json" >&2
  exit 1
fi

mkdir -p "${HOME}/plugins" "${marketplace_dir}"
ln -sfn "${plugin_source}" "${plugin_target}"

cat >"${marketplace_path}" <<JSON
{
  "name": "mesh-intelligence-local",
  "interface": {
    "displayName": "Mesh Intelligence Local"
  },
  "plugins": [
    {
      "name": "mesh-intelligence",
      "source": {
        "source": "local",
        "path": "./plugins/mesh-intelligence"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Developer Tools"
    }
  ]
}
JSON

echo "installed Codex plugin link: ${plugin_target} -> ${plugin_source}"
echo "wrote marketplace: ${marketplace_path}"
