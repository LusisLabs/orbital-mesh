# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && npm install -g promptfoo@latest \
  && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MESH_SERVER_HOST=0.0.0.0 \
    MESH_SERVER_PORT=8787 \
    MESH_WEB_ASSET_PATH=/app/web/dist \
    MESH_ENVIRONMENT=production \
    MESH_GITNEXUS_DISABLE_AUTOSTART=1 \
    MESH_ACCESS_LOG=1

COPY --from=web /web/dist ./web/dist
COPY control_plane_server.py run_server.py run_first_slice.py run_tui.py tui.py setup_integrations.py ./
COPY shared ./shared
COPY services ./services
COPY fixtures ./fixtures
COPY policies ./policies

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"

CMD ["python3", "run_server.py"]
