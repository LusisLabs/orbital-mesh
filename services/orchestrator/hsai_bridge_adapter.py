from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from shared.mesh_runtime.hsai_bridge import load_hsai_formal_backend_run_metadata, local_hsai_allow_decision


class LocalHsaiAdmissionAdapter:
    """Local HSAI-compatible metadata gate for repo-patch admission."""

    def __init__(self, formal_backend_bundle_path: str | None = None) -> None:
        self.formal_backend_bundle_path = formal_backend_bundle_path

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        formal_backend_metadata = (
            load_hsai_formal_backend_run_metadata(self.formal_backend_bundle_path)
            if self.formal_backend_bundle_path
            else None
        )
        return local_hsai_allow_decision(request, formal_backend_metadata=formal_backend_metadata)


class SubprocessHsaiAdmissionAdapter:
    def __init__(self, command: str, timeout_seconds: int = 30) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            shlex.split(self.command),
            input=json.dumps(request, sort_keys=True),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"hsai admission command failed: {completed.returncode}")
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise RuntimeError("hsai admission command returned non-object JSON")
        return payload


def build_hsai_admission_adapter() -> LocalHsaiAdmissionAdapter | SubprocessHsaiAdmissionAdapter:
    command = os.getenv("MESH_HSAI_ADMISSION_COMMAND", "").strip()
    if command:
        timeout = int(os.getenv("MESH_HSAI_ADMISSION_TIMEOUT_SECONDS", "30"))
        return SubprocessHsaiAdmissionAdapter(command, timeout_seconds=timeout)
    bundle_path = os.getenv("MESH_HSAI_FORMAL_BACKEND_RUN_BUNDLE_PATH", "").strip() or None
    return LocalHsaiAdmissionAdapter(formal_backend_bundle_path=bundle_path)
