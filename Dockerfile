FROM node:24-bookworm-slim AS operator-ui
WORKDIR /repo
ARG NEXT_PUBLIC_MESH_API_URL=https://app.lusislabs.com
ENV NEXT_PUBLIC_MESH_API_URL=$NEXT_PUBLIC_MESH_API_URL
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 \
  && rm -rf /var/lib/apt/lists/*
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY meshapp/frontend/package.json ./meshapp/frontend/
RUN corepack enable \
  && corepack prepare pnpm@10.24.0 --activate \
  && pnpm install --filter meshapp --frozen-lockfile
COPY meshapp/frontend/ ./meshapp/frontend/
COPY scripts/generate_control_plane_contracts.py /repo/scripts/generate_control_plane_contracts.py
COPY shared /repo/shared
RUN cd meshapp/frontend && pnpm run build

FROM node:24-bookworm-slim AS promptfoo
RUN npm install -g promptfoo@0.121.17 \
  && cd /usr/local/lib/node_modules/promptfoo \
  && npm install @anthropic-ai/sdk@0.101.0 --omit=dev \
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

FROM golang:1.26.4-bookworm AS kubectl-builder
ARG KUBECTL_VERSION=v1.36.2
ARG KUBERNETES_SRC_SHA512=fad7f78605f87a93199316f7fb3f586e4531c41476c53fedee92fdd5bd641a9128c5cde45b6859e07eb2ab254873f1845236c0a33934cba918ff5b97d0cf571d
WORKDIR /src
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl make rsync \
  && curl --http1.1 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL -o /tmp/kubernetes-src.tar.gz "https://dl.k8s.io/release/${KUBECTL_VERSION}/kubernetes-src.tar.gz" \
  && echo "${KUBERNETES_SRC_SHA512}  /tmp/kubernetes-src.tar.gz" | sha512sum -c - \
  && tar -xzf /tmp/kubernetes-src.tar.gz -C /src \
  && make WHAT=cmd/kubectl KUBE_BUILD_PLATFORMS="linux/$(go env GOARCH)" \
  && mkdir -p /out \
  && install -m 755 "_output/local/bin/linux/$(go env GOARCH)/kubectl" /out/kubectl \
  && rm -rf /tmp/kubernetes-src.tar.gz /var/lib/apt/lists/*

FROM rust:1.92-slim-bookworm AS latentmas-rust
WORKDIR /repo/latent-mesh/LatentMAS
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential cmake pkg-config \
  && rm -rf /var/lib/apt/lists/*
COPY latent-mesh/LatentMAS/Cargo.toml latent-mesh/LatentMAS/Cargo.lock ./
COPY latent-mesh/LatentMAS/src ./src
RUN cargo build --release --bin latentmas

FROM python:3.13.14-slim-trixie
WORKDIR /app

ARG MESH_BUILD_VERSION=dev
ARG MESH_BUILD_COMMIT=unknown
ARG MESH_BUILD_IMAGE_DIGEST=
ARG HERMES_AGENT_REF=7c1a029553d87c43ecff8a3821336bc95872213b
ARG UV_VERSION=0.11.6
ARG DOCKER_CLI_VERSION=29.6.1

RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends ca-certificates curl git libgomp1 \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) docker_arch="x86_64"; docker_sha="b0df4a43a98d7ecb708acbdb5a34a3416e13b6e39bcbbdf296f51f0f3442b29f" ;; \
    arm64) docker_arch="aarch64"; docker_sha="917a4bb83565bcacb38c430f08daae8b59db3256331ac23f22394f0542509881" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl --http1.1 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL -o /tmp/docker.tgz "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" \
  && echo "${docker_sha}  /tmp/docker.tgz" | sha256sum -c - \
  && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
  && install -m 755 /tmp/docker/docker /usr/local/bin/docker \
  && python3 -m pip install --no-cache-dir --upgrade pip \
  && rm -rf /tmp/docker /tmp/docker.tgz /var/lib/apt/lists/*

COPY --from=kubectl-builder /out/kubectl /usr/local/bin/kubectl
COPY --from=promptfoo /usr/local/bin/node /usr/local/bin/node
COPY --from=promptfoo /usr/local/lib/node_modules/promptfoo /usr/local/lib/node_modules/promptfoo
RUN ln -sf ../lib/node_modules/promptfoo/dist/src/entrypoint.js /usr/local/bin/promptfoo

COPY --from=goose /usr/local/bin/goose /usr/local/bin/goose
COPY --from=latentmas-rust /repo/latent-mesh/LatentMAS/target/release/latentmas /usr/local/bin/latentmas

RUN groupadd -r mesh && useradd -r -g mesh -d /app mesh

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/workspace/orbital-mesh/.hermes-local \
    PATH=/opt/hermes-agent/venv/bin:$PATH

RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh \
  && install -m 755 /root/.local/bin/uv /usr/local/bin/uv \
  && if [ -f /root/.local/bin/uvx ]; then install -m 755 /root/.local/bin/uvx /usr/local/bin/uvx; fi \
  && rm -f /root/.local/bin/uv /root/.local/bin/uvx \
  && git init /opt/hermes-agent \
  && cd /opt/hermes-agent \
  && git remote add origin https://github.com/NousResearch/hermes-agent.git \
  && git fetch --depth 1 origin "${HERMES_AGENT_REF}" \
  && git checkout --detach FETCH_HEAD \
  && uv venv venv --python /usr/local/bin/python3 \
  && VIRTUAL_ENV=/opt/hermes-agent/venv uv --no-cache pip install -e ".[cli]" \
  && VIRTUAL_ENV=/opt/hermes-agent/venv uv --no-cache pip install "cryptography>=48.0.1,<49" "deno>=2.8.1,<3" \
  && mkdir -p /opt/venv/bin /workspace/orbital-mesh/.hermes-local \
  && ln -sf /opt/hermes-agent/venv/bin/hermes /opt/venv/bin/hermes \
  && ln -sf /opt/hermes-agent/venv/bin/hermes /usr/local/bin/hermes \
  && rm -f /usr/local/bin/uv /usr/local/bin/uvx \
  && apt-get purge -y --auto-remove curl \
  && rm -rf /var/lib/apt/lists/* /root/.cache

ENV MESH_SERVER_HOST=0.0.0.0 \
    MESH_SERVER_PORT=8787 \
    MESH_WEB_ASSET_PATH=/app/meshapp/frontend/out \
    MESH_ENVIRONMENT=production \
    MESH_ACCESS_LOG=1 \
    MESH_STRUCTURED_LOGS=1 \
    MESH_BUILD_VERSION=$MESH_BUILD_VERSION \
    MESH_BUILD_COMMIT=$MESH_BUILD_COMMIT \
    MESH_BUILD_IMAGE_DIGEST=$MESH_BUILD_IMAGE_DIGEST

COPY --from=operator-ui /repo/meshapp/frontend/out ./meshapp/frontend/out
COPY control_plane_server.py run_server.py run_first_slice.py run_tui.py tui.py setup_integrations.py ./
COPY scripts/compose_mesh_entrypoint.sh /usr/local/bin/compose_mesh_entrypoint.sh
COPY shared ./shared
COPY services ./services
COPY mesh_brain ./mesh_brain
COPY deepagents/libs/deepagents /app/deepagents/libs/deepagents
# Hermes prepends its venv to PATH; use the image Python for Mesh deps and runtime.
RUN /usr/local/bin/python3 -m pip install --no-cache-dir "halo-engine" "helix-py" "langchain-openai>=1.1.14,<2.0.0" "psycopg[binary,pool]>=3.2,<4" "cryptography>=48.0.1,<49" /app/deepagents/libs/deepagents \
  && /usr/local/bin/python3 -m pip install --no-cache-dir --force-reinstall --no-deps "deno>=2.8.1,<3"
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY policies ./policies
COPY config ./config

RUN chown -R mesh:mesh /app
RUN chmod +x /usr/local/bin/compose_mesh_entrypoint.sh

USER mesh

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD /usr/local/bin/python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"

USER root

CMD ["/usr/local/bin/compose_mesh_entrypoint.sh"]
