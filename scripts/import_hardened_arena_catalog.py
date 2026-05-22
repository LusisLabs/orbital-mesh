#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hardened_arena_catalog import import_cli  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(import_cli())
