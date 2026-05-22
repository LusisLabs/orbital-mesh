#!/usr/bin/env python3
"""Verify all CTO handover packages end-to-end."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [
    ("mesh-darkharness-sdk", "mesh_darkharness"),
    ("mesh-hardened-arena", "mesh_hardened_arena"),
    ("mesh-praxis", "mesh_praxis"),
    ("mesh-centaur-sandbox", "mesh_centaur_sandbox"),
]


def _run(package_name: str, module_name: str, *, json_output: bool, extra_args: list[str] | None = None) -> dict[str, object]:
    package_dir = REPO_ROOT / "packages" / package_name
    src_dir = package_dir / "src"
    args = [sys.executable, "-m", module_name, "verify-e2e"]
    args.extend(extra_args or [])
    if json_output:
        args.append("--json")
    completed = subprocess.run(
        args,
        cwd=package_dir,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    body: dict[str, object] = {
        "package": package_name,
        "returncode": completed.returncode,
        "status": "pass" if completed.returncode == 0 else "fail",
    }
    if json_output and completed.stdout.strip():
        try:
            body["result"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            body["stdout"] = completed.stdout.strip()
    else:
        body["stdout"] = completed.stdout.strip()
        body["stderr"] = completed.stderr.strip()
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CTO handover packages")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--with-darkharness-mesh-live", action="store_true")
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    for package_name, module_name in PACKAGES:
        extra: list[str] = []
        if package_name == "mesh-darkharness-sdk" and args.with_darkharness_mesh_live:
            extra.append("--with-mesh-live")
        results.append(_run(package_name, module_name, json_output=args.json, extra_args=extra or None))

    payload = {
        "status": "pass" if all(item["status"] == "pass" for item in results) else "fail",
        "packages": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: verified {len(results)} handover packages")
        for item in results:
            print(f"  {item['package']}: {item['status']}")
            if item["status"] != "pass":
                stderr = str(item.get("stderr") or "")
                stdout = str(item.get("stdout") or "")
                detail = stderr or stdout
                if detail:
                    print(f"    {detail.splitlines()[0]}")
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
