#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.public_corpus_cleaner import build_clean_public_corpus_index


DEFAULT_RAW_MANIFEST = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "raw_manifest.json"
DEFAULT_PUBLIC_FIXTURE = REPO_ROOT / "fixtures" / "monitoring_corpus" / "public_sources.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".mesh-runtime-state" / "monitoring-corpus" / "clean"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-manifest", type=Path, default=DEFAULT_RAW_MANIFEST)
    parser.add_argument("--public-fixture", type=Path, default=DEFAULT_PUBLIC_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--zip-sample-limit", type=int, default=50)
    args = parser.parse_args()

    report = build_clean_public_corpus_index(
        raw_manifest_path=_resolve_path(args.raw_manifest),
        public_fixture_path=_resolve_path(args.public_fixture),
        output_dir=_resolve_path(args.output_dir),
        zip_sample_limit=args.zip_sample_limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    main()
