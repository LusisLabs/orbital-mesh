# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM node:22-bookworm-slim AS promptfoo
RUN npm install -g promptfoo@0.121.3 \
  && cd /usr/local/lib/node_modules/promptfoo \
  && npm install @anthropic-ai/sdk@0.86.1 --omit=dev \
  && npm dedupe --omit=dev \
  && npm cache clean --force \
  && rm -rf /root/.npm

FROM debian:12-slim AS goose
RUN apt-get update \
  && apt-get install -y --no-install-recommends bzip2 ca-certificates curl \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) goose_arch="x86_64" ;; \
    arm64) goose_arch="aarch64" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl -fsSL -o /tmp/goose.tar.bz2 "https://github.com/aaif-goose/goose/releases/download/stable/goose-${goose_arch}-unknown-linux-gnu.tar.bz2" \
  && tar -xjf /tmp/goose.tar.bz2 -C /tmp \
  && install -m 755 /tmp/goose /usr/local/bin/goose \
  && rm -f /tmp/goose /tmp/goose.tar.bz2 \
  && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends ca-certificates curl docker.io git libgomp1 \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) kubectl_arch="amd64" ;; \
    arm64) kubectl_arch="arm64" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/v1.31.5/bin/linux/${kubectl_arch}/kubectl" \
  && chmod +x /usr/local/bin/kubectl \
  && python3 -m pip install --no-cache-dir --upgrade pip \
  && rm -rf /var/lib/apt/lists/*

COPY --from=promptfoo /usr/local/bin/node /usr/local/bin/node
COPY --from=promptfoo /usr/local/lib/node_modules/promptfoo /usr/local/lib/node_modules/promptfoo
RUN ln -sf ../lib/node_modules/promptfoo/dist/src/entrypoint.js /usr/local/bin/promptfoo

COPY --from=goose /usr/local/bin/goose /usr/local/bin/goose

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MESH_SERVER_HOST=0.0.0.0 \
    MESH_SERVER_PORT=8787 \
    MESH_WEB_ASSET_PATH=/app/web/dist \
    MESH_ENVIRONMENT=production \
    MESH_GITNEXUS_DISABLE_AUTOSTART=1 \
    MESH_ACCESS_LOG=1 \
    MESH_STRUCTURED_LOGS=1

COPY --from=web /web/dist ./web/dist
COPY control_plane_server.py run_server.py run_first_slice.py run_tui.py tui.py setup_integrations.py ./
COPY shared ./shared
COPY services ./services
COPY scaffold ./scaffold
COPY fixtures ./fixtures
COPY policies ./policies

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"

CMD ["sh", "-lc", "python3 setup_integrations.py && exec python3 run_server.py"]
