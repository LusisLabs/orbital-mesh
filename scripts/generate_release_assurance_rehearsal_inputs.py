#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic release-assurance inputs for CI contract rehearsal.")
    parser.add_argument("--output-dir", required=True, help="Directory for raw rehearsal inputs.")
    parser.add_argument("--component-name", default="orbital-mesh")
    parser.add_argument("--component-version", default=os.getenv("GITHUB_SHA") or "local")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = output_dir / "raw-sbom.cdx.json"
    scan_path = output_dir / "raw-vulnerability-scan.json"

    sbom = _sbom(component_name=args.component_name, component_version=args.component_version)
    scan = _scan()
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scan_path.write_text(json.dumps(scan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": "mesh.release_assurance_rehearsal_inputs.v1",
                "status": "complete",
                "sbom": str(sbom_path),
                "vulnerability_scan": str(scan_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _sbom(*, component_name: str, component_version: str) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {
            "timestamp": _timestamp(),
            "component": {
                "type": "application",
                "name": component_name,
                "version": component_version,
            },
            "tools": [
                {
                    "vendor": "orbital-mesh",
                    "name": "release-assurance-rehearsal",
                }
            ],
        },
        "components": [],
    }


def _scan() -> dict[str, Any]:
    return {
        "schema_version": "mesh.raw_vulnerability_scan_rehearsal.v1",
        "scanner": "release-assurance-rehearsal",
        "findings": [],
    }


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
