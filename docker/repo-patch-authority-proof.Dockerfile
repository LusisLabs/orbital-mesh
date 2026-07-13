FROM orbital-mesh-stack:chaos-arena-local

USER root
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0755 /opt/hsai/bin

COPY services/ ./services/
COPY shared/ ./shared/
COPY mesh_brain/ ./mesh_brain/
COPY scripts/repo_patch_authority_os_proof.py ./scripts/repo_patch_authority_os_proof.py

ENV MESH_OS_PROOF_HSAI_EXECUTABLE=/opt/hsai/bin/hsai-mesh-admission \
    MESH_OS_PROOF_HSAI_POLICY_ID=mesh_policy://repo-patch/os-boundary-proof \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace

ENTRYPOINT ["python3", "scripts/repo_patch_authority_os_proof.py"]
