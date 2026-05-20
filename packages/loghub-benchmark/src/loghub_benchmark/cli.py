from __future__ import annotations

import argparse
from pathlib import Path

from .harbor import (
    HarborResultImportConfig,
    LoghubCaseBuildConfig,
    LoghubHarborExportConfig,
    build_loghub_cases,
    export_loghub_harbor_dataset,
    import_harbor_results,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and score Harbor-style Loghub SRE benchmark tasks.")
    subparsers = parser.add_subparsers(dest="command")

    build_parser = subparsers.add_parser("build", help="Build deterministic Loghub benchmark cases.")
    build_parser.add_argument("--dataset", required=True)
    build_parser.add_argument("--input", required=True)
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--max-cases", type=int, default=100)
    build_parser.add_argument("--context-lines", type=int, default=8)
    build_parser.add_argument("--window-lines", type=int, default=80)
    build_parser.add_argument("--track", choices=("auto", "gold", "silver", "stress"), default="auto")
    build_parser.add_argument("--split-salt", default="mesh-loghub-harbor-v1")
    build_parser.add_argument("--service", default="loghub-service")

    export_parser = subparsers.add_parser("export-harbor", help="Export built cases as Harbor task directories.")
    export_parser.add_argument("--cases", required=True)
    export_parser.add_argument("--output", required=True)
    export_parser.add_argument("--split", choices=("smoke", "dev", "eval", "full"), default="smoke")
    export_parser.add_argument("--track", choices=("all", "gold", "silver", "stress"), default="all")
    export_parser.add_argument("--max-tasks", type=int, default=None)
    export_parser.add_argument("--benchmark-name", default="Loghub-SRE-Harbor")

    import_parser = subparsers.add_parser("import-results", help="Import Harbor job results into benchmark reports.")
    import_parser.add_argument("--job", required=True)
    import_parser.add_argument("--output", default=None)
    import_parser.add_argument("--pass-threshold", type=float, default=0.75)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        raise SystemExit(2)

    if args.command == "build":
        result = build_loghub_cases(
            LoghubCaseBuildConfig(
                dataset=args.dataset,
                input_path=Path(args.input),
                output_dir=Path(args.output),
                max_cases=args.max_cases,
                context_lines=args.context_lines,
                window_lines=args.window_lines,
                track=args.track,
                split_salt=args.split_salt,
                service=args.service,
            )
        )
        print(f"case_count={len(result.cases)}")
        print(f"manifest={result.manifest_path}")
        return

    if args.command == "export-harbor":
        result = export_loghub_harbor_dataset(
            LoghubHarborExportConfig(
                case_root=Path(args.cases),
                output_dir=Path(args.output),
                split=args.split,
                track=args.track,
                max_tasks=args.max_tasks,
                benchmark_name=args.benchmark_name,
            )
        )
        print(f"task_count={len(result.task_dirs)}")
        print(f"dataset={result.output_dir}")
        print(f"oracles={result.oracle_dir}")
        return

    if args.command == "import-results":
        result = import_harbor_results(
            HarborResultImportConfig(
                job_dir=Path(args.job),
                output_dir=Path(args.output) if args.output else None,
                pass_threshold=args.pass_threshold,
            )
        )
        print(f"attempt_count={result.summary['attempt_count']}")
        print(f"mean_reward={result.summary['mean_reward']:.4f}")
        print(f"report={result.output_dir / 'report.md'}")
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
