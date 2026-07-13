from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.hsai_bridge import load_hsai_formal_backend_run_metadata, local_hsai_allow_decision


HSAI_AUTHORITY_MODE_DISABLED = "disabled"
HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2 = "rust_evidence_v2"
HSAI_RUST_EVIDENCE_V2_IDENTITY_VERSION = "mesh.hsai.rust_evidence_v2_cli_identity.v1"
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class LocalHsaiAdmissionAdapter:
    """Local HSAI-compatible metadata gate for repo-patch admission."""

    authority_eligible = False
    adapter_identity = "mesh.hsai.local_metadata_adapter.v1"

    def __init__(self, formal_backend_bundle_path: str | None = None) -> None:
        self.formal_backend_bundle_path = formal_backend_bundle_path

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        formal_backend_metadata = (
            load_hsai_formal_backend_run_metadata(self.formal_backend_bundle_path)
            if self.formal_backend_bundle_path
            else None
        )
        return cast(
            dict[str, Any],
            local_hsai_allow_decision(request, formal_backend_metadata=formal_backend_metadata),
        )


class SubprocessHsaiAdmissionAdapter:
    """Unpinned proposal-only subprocess adapter."""

    authority_eligible = False
    adapter_identity = "mesh.hsai.subprocess_adapter.unpinned.v1"

    def __init__(
        self,
        command: str,
        timeout_seconds: int = 30,
    ) -> None:
        self.command = command.strip()
        self.timeout_seconds = timeout_seconds
        if not self.command:
            raise ValueError("hsai admission command is required")
        if timeout_seconds <= 0:
            raise ValueError("hsai admission timeout must be positive")

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
        return cast(dict[str, Any], payload)


class RustEvidenceV2HsaiAdmissionAdapter(SubprocessHsaiAdmissionAdapter):
    """Authority-eligible Rust evidence-v2 CLI pinned to caller-supplied bytes."""

    authority_eligible = True
    authority_mode = HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2

    def __init__(
        self,
        command: str,
        *,
        executable_sha256: str,
        timeout_seconds: int = 30,
    ) -> None:
        super().__init__(command, timeout_seconds=timeout_seconds)
        argv = shlex.split(self.command)
        if not argv:
            raise ValueError("HSAI Rust evidence-v2 command is required")
        executable = Path(argv[0])
        if not executable.is_absolute():
            raise ValueError("HSAI Rust evidence-v2 executable must be an absolute path")
        if len(argv) != 3 or argv[1] != "--current-policy-id" or not argv[2].strip():
            raise ValueError(
                "HSAI Rust evidence-v2 command must be exactly "
                "<absolute executable> --current-policy-id <nonempty policy id>"
            )
        if not _SHA256_PATTERN.fullmatch(executable_sha256):
            raise ValueError("HSAI Rust evidence-v2 executable SHA-256 pin must use sha256:<64 lowercase hex>")
        self.executable_path = executable
        self.executable_sha256 = executable_sha256
        self.current_policy_id = argv[2]
        self._verify_executable_identity()
        self.adapter_identity = (
            f"{HSAI_RUST_EVIDENCE_V2_IDENTITY_VERSION}:"
            f"{self.executable_sha256}:{self.current_policy_id}"
        )

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        self._verify_executable_identity()
        return super().admit(request)

    def _verify_executable_identity(self) -> None:
        try:
            metadata = self.executable_path.stat(follow_symlinks=False)
        except OSError as exc:
            raise RuntimeError(f"HSAI Rust evidence-v2 executable is unavailable: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("HSAI Rust evidence-v2 executable must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("HSAI Rust evidence-v2 executable must be a regular file")
        if not os.access(self.executable_path, os.X_OK):
            raise RuntimeError("HSAI Rust evidence-v2 executable must be executable")
        current_digest = _file_sha256(self.executable_path)
        if current_digest != self.executable_sha256:
            raise RuntimeError("HSAI Rust evidence-v2 executable SHA-256 pin mismatch")


def build_hsai_admission_adapter(
    config: RuntimeConfig | None = None,
) -> LocalHsaiAdmissionAdapter | SubprocessHsaiAdmissionAdapter:
    resolved = config or RuntimeConfig.from_env()
    command = (resolved.hsai_admission_command or "").strip()
    authority_mode = resolved.hsai_admission_authority_mode.strip().lower()
    if command:
        if authority_mode == HSAI_AUTHORITY_MODE_DISABLED:
            if resolved.hsai_admission_executable_sha256 is not None:
                raise ValueError("HSAI executable SHA-256 pin requires explicit Rust evidence-v2 authority mode")
            return SubprocessHsaiAdmissionAdapter(
                command,
                timeout_seconds=resolved.hsai_admission_timeout_seconds,
            )
        if authority_mode != HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2:
            raise ValueError(f"unsupported HSAI admission authority mode: {authority_mode}")
        if resolved.hsai_admission_executable_sha256 is None:
            raise ValueError("HSAI Rust evidence-v2 authority mode requires an executable SHA-256 pin")
        return RustEvidenceV2HsaiAdmissionAdapter(
            command,
            executable_sha256=resolved.hsai_admission_executable_sha256,
            timeout_seconds=resolved.hsai_admission_timeout_seconds,
        )
    if authority_mode != HSAI_AUTHORITY_MODE_DISABLED or resolved.hsai_admission_executable_sha256 is not None:
        raise ValueError("HSAI authority mode and executable pin require an admission command")
    bundle_path = os.getenv("MESH_HSAI_FORMAL_BACKEND_RUN_BUNDLE_PATH", "").strip() or None
    return LocalHsaiAdmissionAdapter(formal_backend_bundle_path=bundle_path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeError(f"HSAI Rust evidence-v2 executable cannot be hashed: {exc}") from exc
    return f"sha256:{digest.hexdigest()}"
