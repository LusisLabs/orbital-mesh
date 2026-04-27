#!/usr/bin/env bash
# simulation/bootstrap_demo.sh — generate the JWT secret + bring up
# the docker-compose stack for the live demo.
#
# Usage:
#   ./simulation/bootstrap_demo.sh                # generate + up
#   ./simulation/bootstrap_demo.sh --kill         # tear down
#
# After bootstrap, run:
#   uv run python -m simulation.run_real
#
# Requires:
#   * docker + docker compose
#   * openssl (for the JWT)

set -euo pipefail

case "${1:-}" in
  --kill)
    docker compose -f docker-compose.reth-demo.yml down -v
    rm -f jwt-demo.hex
    exit 0
    ;;
esac

if [[ ! -f jwt-demo.hex ]]; then
  echo "[bootstrap] generating jwt-demo.hex (32 random bytes, hex)"
  openssl rand -hex 32 > jwt-demo.hex
  chmod 0644 jwt-demo.hex   # intentionally insecure for the demo
fi

echo "[bootstrap] starting stack..."
docker compose -f docker-compose.reth-demo.yml up -d

echo "[bootstrap] reth RPC will be at http://127.0.0.1:18545"
echo "[bootstrap] lighthouse beacon HTTP at http://127.0.0.1:15052"
echo "[bootstrap] Lighthouse needs ~5-10 min to checkpoint-sync from Hoodi."
echo "[bootstrap] Then run: uv run python -m simulation.run_real"
