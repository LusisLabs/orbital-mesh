FROM node:22-bookworm-slim AS web
WORKDIR /repo/web
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 \
  && rm -rf /var/lib/apt/lists/*
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY scripts/generate_control_plane_contracts.py /repo/scripts/generate_control_plane_contracts.py
COPY shared /repo/shared
RUN npm run build

FROM node:22-bookworm-slim AS promptfoo
RUN npm install -g promptfoo@0.121.3 \
  && cd /usr/local/lib/node_modules/promptfoo \
  && npm install @anthropic-ai/sdk@0.86.1 --omit=dev \
  && npm dedupe --omit=dev \
  && npm cache clean --force \
  && rm -rf /root/.npm

FROM debian:12-slim AS goose
ARG GOOSE_VERSION=v1.30.0
RUN apt-get update \
  && apt-get install -y --no-install-recommends bzip2 ca-certificates curl \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) goose_arch="x86_64" ;; \
    arm64) goose_arch="aarch64" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl --http1.1 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL -o /tmp/goose.tar.bz2 "https://github.com/aaif-goose/goose/releases/download/${GOOSE_VERSION}/goose-${goose_arch}-unknown-linux-gnu.tar.bz2" \
  && tar -xjf /tmp/goose.tar.bz2 -C /tmp \
  && install -m 755 /tmp/goose /usr/local/bin/goose \
  && rm -f /tmp/goose /tmp/goose.tar.bz2 \
  && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim-bookworm
WORKDIR /app

ARG MESH_BUILD_VERSION=dev
ARG MESH_BUILD_COMMIT=unknown
ARG HERMES_AGENT_REF=1525624904159e7c2d6ac3feef951e27ad0d23bb
ARG UV_VERSION=0.11.6

RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends ca-certificates curl docker.io git gosu libgomp1 \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) kubectl_arch="amd64" ;; \
    arm64) kubectl_arch="arm64" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl --http1.1 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/v1.31.5/bin/linux/${kubectl_arch}/kubectl" \
  && chmod +x /usr/local/bin/kubectl \
  && python3 -m pip install --no-cache-dir --upgrade pip \
  && rm -rf /var/lib/apt/lists/*

COPY --from=promptfoo /usr/local/bin/node /usr/local/bin/node
COPY --from=promptfoo /usr/local/lib/node_modules/promptfoo /usr/local/lib/node_modules/promptfoo
RUN ln -sf ../lib/node_modules/promptfoo/dist/src/entrypoint.js /usr/local/bin/promptfoo

COPY --from=goose /usr/local/bin/goose /usr/local/bin/goose

RUN groupadd -r mesh && useradd -r -g mesh -d /app mesh

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/workspace/mesh-intelligence/.hermes-local \
    PATH=/root/.local/bin:/opt/hermes-agent/venv/bin:$PATH

RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh \
  && install -m 755 /root/.local/bin/uv /usr/local/bin/uv \
  && if [ -f /root/.local/bin/uvx ]; then install -m 755 /root/.local/bin/uvx /usr/local/bin/uvx; fi \
  && git init /opt/hermes-agent \
  && cd /opt/hermes-agent \
  && git remote add origin https://github.com/NousResearch/hermes-agent.git \
  && git fetch --depth 1 origin "${HERMES_AGENT_REF}" \
  && git checkout --detach FETCH_HEAD \
  && uv venv venv --python 3.11 \
  && VIRTUAL_ENV=/opt/hermes-agent/venv uv --no-cache pip install -e ".[cli]" \
  && mkdir -p /opt/venv/bin /workspace/mesh-intelligence/.hermes-local \
  && ln -sf /opt/hermes-agent/venv/bin/hermes /opt/venv/bin/hermes \
  && ln -sf /opt/hermes-agent/venv/bin/hermes /usr/local/bin/hermes \
  && rm -rf /var/lib/apt/lists/* /root/.cache

ENV MESH_SERVER_HOST=0.0.0.0 \
    MESH_SERVER_PORT=8787 \
    MESH_WEB_ASSET_PATH=/app/web/dist \
    MESH_ENVIRONMENT=production \
    MESH_ACCESS_LOG=1 \
    MESH_STRUCTURED_LOGS=1 \
    MESH_BUILD_VERSION=$MESH_BUILD_VERSION \
    MESH_BUILD_COMMIT=$MESH_BUILD_COMMIT

COPY --from=web /repo/web/dist ./web/dist
COPY control_plane_server.py run_server.py run_first_slice.py run_tui.py tui.py setup_integrations.py ./
COPY scripts/compose_mesh_entrypoint.sh /usr/local/bin/compose_mesh_entrypoint.sh
COPY shared ./shared
COPY services ./services
COPY deepagents/libs/deepagents /app/deepagents/libs/deepagents
# Hermes prepends its venv to PATH; use the image Python for Mesh deps and runtime.
RUN /usr/local/bin/python3 -m pip install --no-cache-dir "langchain-openai>=1.0.0,<2.0.0" "psycopg[binary]>=3.2,<4" /app/deepagents/libs/deepagents
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY policies ./policies

RUN chown -R mesh:mesh /app
RUN chmod +x /usr/local/bin/compose_mesh_entrypoint.sh

USER mesh

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD /usr/local/bin/python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"

USER root

CMD ["/usr/local/bin/compose_mesh_entrypoint.sh"]
