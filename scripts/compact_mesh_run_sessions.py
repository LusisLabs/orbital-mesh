#!/usr/bin/env python3
"""Compact file-backed Mesh run snapshots while preserving archived records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact Mesh file-state run_sessions.json.")
    parser.add_argument("state_directory", type=Path)
    parser.add_argument("--keep", type=int, default=500)
    args = parser.parse_args()

    state_directory = args.state_directory.resolve()
    run_sessions_path = state_directory / "run_sessions.json"
    archive_path = state_directory / "run_sessions.archive.jsonl"
    backup_path = state_directory / "run_sessions.precompact.json"
    if not run_sessions_path.exists():
        print(json.dumps({"status": "missing", "path": str(run_sessions_path)}, sort_keys=True))
        return 0

    payload = json.loads(run_sessions_path.read_text(encoding="utf-8"))
    records = [record for record in payload.get("runs", []) if isinstance(record, dict)]
    records.sort(key=lambda record: str(record.get("created_at", "")), reverse=True)
    keep = records[: max(50, args.keep)]
    archive = records[len(keep) :]

    backup_path.write_text(json.dumps({"runs": records}, sort_keys=True) + "\n", encoding="utf-8")
    with archive_path.open("a", encoding="utf-8") as archive_file:
        for record in archive:
            archive_file.write(json.dumps(record, sort_keys=True) + "\n")
    run_sessions_path.write_text(json.dumps({"runs": keep}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "compacted",
                "before": len(records),
                "kept": len(keep),
                "archived": len(archive),
                "bytes": run_sessions_path.stat().st_size,
                "backup": str(backup_path),
                "archive": str(archive_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
