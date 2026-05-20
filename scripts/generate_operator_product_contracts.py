#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.operator_product_contracts import render_schema_text, render_typescript_types

SCHEMA_PATH = REPO_ROOT / "shared" / "mesh_runtime" / "schemas" / "operator-product.schema.json"
TYPES_PATH = REPO_ROOT / "meshapp" / "frontend" / "src" / "product" / "types.ts"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate operator product JSON Schema and TypeScript contracts.")
    parser.add_argument("--check", action="store_true", help="Fail if generated product contracts are stale.")
    args = parser.parse_args()

    schema_text = render_schema_text()
    types_text = render_typescript_types()

    if args.check:
        stale = []
        if not SCHEMA_PATH.exists() or SCHEMA_PATH.read_text(encoding="utf-8") != schema_text:
            stale.append(str(SCHEMA_PATH.relative_to(REPO_ROOT)))
        if not TYPES_PATH.exists() or TYPES_PATH.read_text(encoding="utf-8") != types_text:
            stale.append(str(TYPES_PATH.relative_to(REPO_ROOT)))
        if stale:
            print("Generated operator product contracts are stale:", ", ".join(stale), file=sys.stderr)
            print("Run: python3 scripts/generate_operator_product_contracts.py", file=sys.stderr)
            return 1
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    TYPES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text, encoding="utf-8")
    TYPES_PATH.write_text(types_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
