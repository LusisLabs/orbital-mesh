#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge expired Mesh run export packages and archives.")
    parser.add_argument(
        "--state-dir",
        default=os.getenv("MESH_STATE_DIR", ".mesh-runtime-state"),
        help="Mesh state directory containing run_exports/.",
    )
    parser.add_argument("--apply", action="store_true", help="Delete expired exports. Default is dry-run.")
    parser.add_argument("--now", help="Override current time as an ISO-8601 timestamp for rehearsals and tests.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    payload = purge_run_exports(Path(args.state_dir), now=now, apply=args.apply)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode = "apply" if args.apply else "dry-run"
        print(f"mode: {mode}")
        print(f"state_dir: {payload['state_dir']}")
        print(f"expired_exports: {payload['expired_exports']}")
        print(f"deleted_files: {payload['deleted_files']}")
        for export in payload["exports"]:
            print(f"{export['status']}: {export['run_id']} delete_after={export.get('delete_after', 'unknown')}")
            for file_record in export.get("files", []):
                print(f"  {file_record['status']}: {file_record['path']}")
    return 0


def purge_run_exports(state_dir: Path, *, now: datetime, apply: bool = False) -> dict[str, Any]:
    state_root = state_dir.resolve()
    export_dir = (state_root / "run_exports").resolve()
    if not export_dir.exists():
        return {
            "status": "pass",
            "mode": "apply" if apply else "dry-run",
            "state_dir": str(state_root),
            "run_exports_dir": str(export_dir),
            "expired_exports": 0,
            "deleted_files": 0,
            "exports": [],
        }
    if not _is_relative_to(export_dir, state_root):
        raise ValueError("run_exports directory must remain inside state directory")

    exports: list[dict[str, Any]] = []
    expired_exports = 0
    deleted_files = 0
    for package_path in sorted(export_dir.glob("*.json")):
        export_record = _inspect_package(package_path, export_dir, now=now, apply=apply)
        exports.append(export_record)
        if export_record["status"] == "expired":
            expired_exports += 1
        deleted_files += sum(1 for file_record in export_record.get("files", []) if file_record["status"] == "deleted")

    return {
        "status": "pass",
        "mode": "apply" if apply else "dry-run",
        "state_dir": str(state_root),
        "run_exports_dir": str(export_dir),
        "expired_exports": expired_exports,
        "deleted_files": deleted_files,
        "exports": exports,
    }


def _inspect_package(package_path: Path, export_dir: Path, *, now: datetime, apply: bool) -> dict[str, Any]:
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "skipped", "run_id": package_path.stem, "path": str(package_path), "reason": str(exc)}
    if not isinstance(package, dict) or package.get("package_version") != "mesh.run_export.v1":
        return {
            "status": "skipped",
            "run_id": package_path.stem,
            "path": str(package_path),
            "reason": "not a mesh.run_export.v1 package",
        }

    retention = package.get("retention") if isinstance(package.get("retention"), dict) else {}
    delete_after_raw = retention.get("delete_after")
    if not delete_after_raw:
        return {"status": "skipped", "run_id": str(package.get("run_id") or package_path.stem), "path": str(package_path), "reason": "missing retention.delete_after"}
    delete_after = _parse_timestamp(str(delete_after_raw))
    run_id = str(package.get("run_id") or package_path.stem)
    if delete_after > now:
        return {
            "status": "retained",
            "run_id": run_id,
            "path": str(package_path),
            "delete_after": delete_after.isoformat(),
        }

    files = [_purge_file(path, export_dir=export_dir, apply=apply) for path in _export_files(package_path, run_id)]
    return {
        "status": "expired",
        "run_id": run_id,
        "path": str(package_path),
        "delete_after": delete_after.isoformat(),
        "files": files,
    }


def _export_files(package_path: Path, run_id: str) -> list[Path]:
    return [package_path, package_path.with_name(f"{run_id}.zip")]


def _purge_file(path: Path, *, export_dir: Path, apply: bool) -> dict[str, str]:
    resolved = path.resolve()
    if not _is_relative_to(resolved, export_dir):
        return {"path": str(path), "status": "blocked", "reason": "outside run_exports directory"}
    if not resolved.exists():
        return {"path": str(resolved), "status": "missing"}
    if not apply:
        return {"path": str(resolved), "status": "would_delete"}
    resolved.unlink()
    return {"path": str(resolved), "status": "deleted"}


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
