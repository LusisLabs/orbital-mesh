ARG REPO_PATCH_PYTHON_BASE=python:3.13.14-alpine3.24
FROM ${REPO_PATCH_PYTHON_BASE}

WORKDIR /app

ARG CRYPTOGRAPHY_VERSION=48.0.1

RUN apk add --no-cache ca-certificates git \
    && python3 -m pip install --no-cache-dir "cryptography==${CRYPTOGRAPHY_VERSION}" \
    && rm -rf \
      /usr/local/bin/pip* \
      /usr/local/lib/python3.13/site-packages/pip* \
      /root/.cache

COPY services/__init__.py ./services/__init__.py
COPY services/actuators/__init__.py ./services/actuators/__init__.py
COPY services/actuators/repo_patch.py ./services/actuators/repo_patch.py
COPY services/actuators/repo_patch_authority_service.py ./services/actuators/repo_patch_authority_service.py
COPY services/actuators/repo_patch_workspace.py ./services/actuators/repo_patch_workspace.py
COPY services/orchestrator/__init__.py ./services/orchestrator/__init__.py
COPY services/orchestrator/hsai_bridge_adapter.py ./services/orchestrator/hsai_bridge_adapter.py
COPY shared/__init__.py ./shared/__init__.py
COPY shared/mesh_runtime/config.py ./shared/mesh_runtime/config.py
COPY shared/mesh_runtime/contracts.py ./shared/mesh_runtime/contracts.py
COPY shared/mesh_runtime/hsai_bridge.py ./shared/mesh_runtime/hsai_bridge.py
COPY shared/mesh_runtime/json_store.py ./shared/mesh_runtime/json_store.py
COPY shared/mesh_runtime/perennial/signing.py ./shared/mesh_runtime/perennial/signing.py
COPY shared/mesh_runtime/repo_patch_authority.py ./shared/mesh_runtime/repo_patch_authority.py
COPY shared/mesh_runtime/repo_patch_authority_store.py ./shared/mesh_runtime/repo_patch_authority_store.py
COPY shared/mesh_runtime/repo_patch_permit_validation.py ./shared/mesh_runtime/repo_patch_permit_validation.py
COPY shared/mesh_runtime/repo_patch_permits.py ./shared/mesh_runtime/repo_patch_permits.py
COPY shared/mesh_runtime/repo_patch_test_policy.py ./shared/mesh_runtime/repo_patch_test_policy.py
COPY shared/mesh_runtime/repo_patch_verifier.py ./shared/mesh_runtime/repo_patch_verifier.py
COPY shared/mesh_runtime/schema_validation.py ./shared/mesh_runtime/schema_validation.py
COPY shared/mesh_runtime/schemas/combined-proof-packet.schema.json ./shared/mesh_runtime/schemas/combined-proof-packet.schema.json
COPY shared/mesh_runtime/schemas/decision.schema.json ./shared/mesh_runtime/schemas/decision.schema.json
COPY shared/mesh_runtime/schemas/evaluation-result.schema.json ./shared/mesh_runtime/schemas/evaluation-result.schema.json
COPY shared/mesh_runtime/schemas/hsai-admission-decision.schema.json ./shared/mesh_runtime/schemas/hsai-admission-decision.schema.json
COPY shared/mesh_runtime/schemas/hsai-admission-request-v2.schema.json ./shared/mesh_runtime/schemas/hsai-admission-request-v2.schema.json
COPY shared/mesh_runtime/schemas/hsai-admission-request.schema.json ./shared/mesh_runtime/schemas/hsai-admission-request.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-authority-request.schema.json ./shared/mesh_runtime/schemas/repo-patch-authority-request.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-authority-response.schema.json ./shared/mesh_runtime/schemas/repo-patch-authority-response.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-execution-permit.schema.json ./shared/mesh_runtime/schemas/repo-patch-execution-permit.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-verifier-request.schema.json ./shared/mesh_runtime/schemas/repo-patch-verifier-request.schema.json
COPY shared/mesh_runtime/schemas/repo-patch-verifier-response-v2.schema.json ./shared/mesh_runtime/schemas/repo-patch-verifier-response-v2.schema.json

RUN printf '%s\n' \
      'from .config import RuntimeConfig' \
      'from .contracts import Decision, EvaluationResult' \
      '' \
      '__all__ = ["Decision", "EvaluationResult", "RuntimeConfig"]' \
      > ./shared/mesh_runtime/__init__.py \
    && : > ./shared/mesh_runtime/perennial/__init__.py \
    && python3 -m compileall -q /app \
    && find /app -type d -name __pycache__ -prune -exec rm -rf {} +

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

ENTRYPOINT ["python3", "-m", "services.actuators.repo_patch_authority_service"]
