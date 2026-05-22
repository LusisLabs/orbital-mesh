from __future__ import annotations

import os
from typing import Mapping


def goose_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env["GOOSE_DISABLE_KEYRING"] = "1"
    return env
