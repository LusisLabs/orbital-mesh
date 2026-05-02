#!/usr/bin/env bash
set -euo pipefail

bundle="/Volumes/REDISTRO/mesh-offload/MeshOffload.sparsebundle"
mountpoint="/Volumes/MeshOffload"

if [[ -d "${mountpoint}" ]] && mount | grep -q "on ${mountpoint} "; then
  echo "MeshOffload already mounted at ${mountpoint}"
  exit 0
fi

if [[ ! -e "${bundle}" ]]; then
  echo "missing MeshOffload sparse bundle: ${bundle}" >&2
  exit 1
fi

hdiutil attach "${bundle}" -mountpoint "${mountpoint}"
echo "MeshOffload mounted at ${mountpoint}"
