ARG REPO_PATCH_PYTHON_BASE=python:3.13.14-alpine3.24
FROM ${REPO_PATCH_PYTHON_BASE} AS verifier-python-dependencies

ARG CRYPTOGRAPHY_VERSION=48.0.1

RUN python3 -m pip install \
      --no-cache-dir \
      --target /opt/verifier-python \
      "cryptography==${CRYPTOGRAPHY_VERSION}" \
    && find /opt/verifier-python -type d -name __pycache__ -prune -exec rm -rf {} +

FROM ${REPO_PATCH_PYTHON_BASE} AS verifier-python-backport
ARG PYTHON_HTML_PARSER_BACKPORT_COMMIT=7933f4bf7131aa4140750f9404f5de0aa2969ced
ARG PYTHON_HTML_PARSER_BACKPORT_SHA256=4274e9112adf3fa57c7f9afa7c9b5c631456b18b7403cc627cc5027d02cdd2ae

RUN apk add --no-cache curl \
    && curl --http1.1 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 15 --max-time 300 -fsSL \
      -o /tmp/python-html-parser.py \
      "https://raw.githubusercontent.com/python/cpython/${PYTHON_HTML_PARSER_BACKPORT_COMMIT}/Lib/html/parser.py" \
    && echo "${PYTHON_HTML_PARSER_BACKPORT_SHA256}  /tmp/python-html-parser.py" | sha256sum -c - \
    && install -m 0644 /tmp/python-html-parser.py /usr/local/lib/python3.13/html/parser.py \
    && rm -f /tmp/python-html-parser.py \
    && apk del curl

FROM ${REPO_PATCH_PYTHON_BASE}

WORKDIR /app

ARG MESH_BUILD_VERSION=dev
ARG MESH_BUILD_COMMIT=unknown

LABEL org.opencontainers.image.source="https://github.com/LusisLabs/orbital-mesh" \
      org.opencontainers.image.revision="${MESH_BUILD_COMMIT}" \
      org.opencontainers.image.version="${MESH_BUILD_VERSION}"

COPY --from=verifier-python-backport /usr/local/lib/python3.13/html/parser.py /usr/local/lib/python3.13/html/parser.py
COPY --from=verifier-python-dependencies /opt/verifier-python /opt/verifier-python

COPY services/__init__.py ./services/__init__.py
COPY services/actuators/__init__.py ./services/actuators/__init__.py
COPY services/actuators/repo_patch_verifier_service.py ./services/actuators/repo_patch_verifier_service.py
COPY shared/__init__.py ./shared/__init__.py
COPY shared/mesh_runtime/contracts.py ./shared/mesh_runtime/contracts.py
COPY shared/mesh_runtime/hsai_bridge.py ./shared/mesh_runtime/hsai_bridge.py
COPY shared/mesh_runtime/perennial/signing.py ./shared/mesh_runtime/perennial/signing.py
COPY shared/mesh_runtime/repo_patch_authority.py ./shared/mesh_runtime/repo_patch_authority.py
COPY shared/mesh_runtime/repo_patch_test_policy.py ./shared/mesh_runtime/repo_patch_test_policy.py
COPY shared/mesh_runtime/repo_patch_verifier.py ./shared/mesh_runtime/repo_patch_verifier.py
COPY shared/mesh_runtime/schema_validation.py ./shared/mesh_runtime/schema_validation.py
COPY shared/mesh_runtime/schemas/repo-patch-verifier-request.schema.json ./shared/mesh_runtime/schemas/repo-patch-verifier-request.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-verifier-response-v2.schema.json ./shared/mesh_runtime/schemas/repo-patch-verifier-response-v2.schema.json

RUN rm -rf \
      /usr/local/bin/pip* \
      /usr/local/lib/python3.13/site-packages/pip* \
    && : > ./shared/mesh_runtime/__init__.py \
    && : > ./shared/mesh_runtime/perennial/__init__.py \
    && python3 -m compileall -q /app \
    && find /app -type d -name __pycache__ -prune -exec rm -rf {} +

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/verifier-python:/app

ENTRYPOINT ["python3", "-m", "services.actuators.repo_patch_verifier_service"]
