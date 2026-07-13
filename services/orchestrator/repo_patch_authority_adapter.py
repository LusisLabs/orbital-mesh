"""Fail-closed construction of the out-of-process repo-patch authority client."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.repo_patch_authority import RepoPatchAuthorityClient


def build_repo_patch_authority_client(config: RuntimeConfig) -> RepoPatchAuthorityClient:
    socket_path = _required_absolute_path(
        config.repo_patch_authority_socket_path,
        "repo patch authority socket",
    )
    client_private_key_path = _required_absolute_path(
        config.repo_patch_authority_client_private_key_path,
        "repo patch authority client private key",
    )
    authority_public_key_path = _required_absolute_path(
        config.repo_patch_authority_public_key_path,
        "repo patch authority public key",
    )
    client_private_key_pem = _read_key_file(client_private_key_path, private=True)
    authority_public_key_pem = _read_key_file(authority_public_key_path, private=False)
    return RepoPatchAuthorityClient(
        socket_path,
        client_private_key_pem=client_private_key_pem,
        client_key_id=config.repo_patch_authority_client_key_id,
        authority_public_key_pem=authority_public_key_pem,
        authority_key_id=config.repo_patch_authority_key_id,
        timeout_seconds=config.repo_patch_authority_timeout_seconds,
        max_frame_bytes=config.repo_patch_authority_max_message_bytes,
    )


def _required_absolute_path(raw: str | None, label: str) -> Path:
    if raw is None or not raw.strip():
        raise ValueError(f"{label} path is required")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    if path.is_symlink():
        raise ValueError(f"{label} path must not be a symlink")
    return path


def _read_key_file(path: Path, *, private: bool) -> str:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"repo patch authority key file is unavailable: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("repo patch authority key path must be a regular file")
    if private:
        if metadata.st_uid != os.getuid():
            raise ValueError("repo patch authority private key must be owned by the current uid")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("repo patch authority private key permissions must exclude group and other access")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"repo patch authority key file cannot be read: {exc}") from exc
    if not value:
        raise ValueError("repo patch authority key file is empty")
    return value
