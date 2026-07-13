from __future__ import annotations

import os
from typing import Mapping


REPO_PATCH_AUTHORITY_SECRET_ENV_KEYS = (
    "MESH_REPO_PATCH_PERMIT_SIGNING_KEY",
    "MESH_REPO_PATCH_PERMIT_SIGNING_KEY_PATH",
    "MESH_REPO_PATCH_AUTHORITY_CLIENT_PRIVATE_KEY_PATH",
    "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_PATH",
    "MESH_REPO_PATCH_AUTHORITY_TRUSTED_CLIENT_PUBLIC_KEY_PATH",
    "MESH_REPO_PATCH_AUTHORITY_PUBLIC_KEY_PATH",
    "MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH",
)


def model_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for key in REPO_PATCH_AUTHORITY_SECRET_ENV_KEYS:
        env.pop(key, None)
    return env


def goose_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = model_subprocess_env(base)
    env["GOOSE_DISABLE_KEYRING"] = "1"
    return env
