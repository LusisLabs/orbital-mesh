#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase


SCHEMA_VERSION = "mesh.corpus_breakthrough_verification.v1"
DEFAULT_DATABASE_PATH = Path(".mesh-runtime-state/corpus/incident_corpus.sqlite")


def verify_corpus_breakthrough(database_path: str | Path, *, limit: int = 5000) -> dict[str, Any]:
    path = Path(database_path)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "ready": False,
            "database_path": str(path),
            "limit": limit,
            "errors": ["database_missing"],
            "missing": ["corpus_database"],
            "checklist": [],
            "breakthrough": None,
        }

    report = IncidentCorpusDatabase(path).breakthrough_report(limit=limit)
    criteria = report.get("criteria") if isinstance(report.get("criteria"), dict) else {}
    checklist = [_criterion_check(name, payload, database_path=str(path)) for name, payload in criteria.items()]
    missing = [item["requirement"] for item in checklist if item["status"] != "pass"]
    ready = report.get("ready") is True
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if ready else "fail",
        "ready": ready,
        "database_path": str(path),
        "limit": limit,
        "errors": [],
        "missing": missing,
        "checklist": checklist,
        "breakthrough": report,
    }


def _criterion_check(name: str, payload: Any, *, database_path: str) -> dict[str, Any]:
    criterion = payload if isinstance(payload, dict) else {}
    return {
        "requirement": name,
        "artifact": database_path,
        "status": "pass" if criterion.get("passed") is True else "fail",
        "observed": criterion.get("observed"),
        "threshold": criterion.get("threshold"),
        "details": criterion.get("details") if isinstance(criterion.get("details"), dict) else {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify measured incident-corpus Breakthrough thresholds from the SQLite corpus store."
    )
    parser.add_argument(
        "--database",
        default=str(DEFAULT_DATABASE_PATH),
        help=f"Path to incident_corpus.sqlite. Defaults to {DEFAULT_DATABASE_PATH}.",
    )
    parser.add_argument("--limit", type=int, default=5000, help="Maximum stored rows to score.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = verify_corpus_breakthrough(args.database, limit=args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for item in payload["checklist"]:
            print(f"{item['status']} {item['requirement']}: {item['observed']}/{item['threshold']}")
        for error in payload["errors"]:
            print(error, file=sys.stderr)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
