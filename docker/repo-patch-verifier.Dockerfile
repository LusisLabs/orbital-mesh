ARG REPO_PATCH_PYTHON_BASE=python:3.13.14-alpine3.24
FROM ${REPO_PATCH_PYTHON_BASE} AS verifier-python-dependencies

ARG CRYPTOGRAPHY_VERSION=48.0.1

RUN python3 -m pip install \
      --no-cache-dir \
      --target /opt/verifier-python \
      "cryptography==${CRYPTOGRAPHY_VERSION}" \
    && find /opt/verifier-python -type d -name __pycache__ -prune -exec rm -rf {} +

FROM ${REPO_PATCH_PYTHON_BASE}

WORKDIR /app

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
