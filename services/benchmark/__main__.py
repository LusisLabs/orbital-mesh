from __future__ import annotations

import argparse
from pathlib import Path

from .compare import compare_benchmark_runs
from .loghub import LoghubExtractionConfig, extract_loghub_scenarios
from .runner import BenchmarkRunConfig, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mesh architecture benchmarks.")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a benchmark suite.")
    run_parser.add_argument("--suite", default="golden")
    run_parser.add_argument("--output", default=".mesh-runtime-state/benchmarks")
    run_parser.add_argument("--scenario-id", action="append", default=[])
    run_parser.add_argument("--scenario-root", default=None)
    run_parser.add_argument("--signal-fixture-root", default=None)
    run_parser.add_argument("--repeat", type=int, default=1)
    run_parser.add_argument("--backend", choices=("mesh", "opensre-cli"), default="mesh")
    run_parser.add_argument("--opensre-command", default="uvx opensre")
    run_parser.add_argument("--backend-timeout-seconds", type=float, default=300.0)

    compare_parser = subparsers.add_parser("compare", help="Compare two benchmark run directories.")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--output", default=None)

    loghub_parser = subparsers.add_parser("extract-loghub", help="Extract scenarios from a local Loghub corpus.")
    loghub_parser.add_argument("--dataset", required=True)
    loghub_parser.add_argument("--input", required=True)
    loghub_parser.add_argument("--output", required=True)
    loghub_parser.add_argument("--max-scenarios", type=int, default=25)
    loghub_parser.add_argument("--context-lines", type=int, default=3)
    loghub_parser.add_argument("--service", default="loghub-service")

    args = parser.parse_args()
    if args.command == "compare":
        comparison = compare_benchmark_runs(
            Path(args.baseline),
            Path(args.candidate),
            output_dir=Path(args.output) if args.output else None,
        )
        print(f"weighted_score_delta={comparison.weighted_score_delta:+.2f}")
        print(f"candidate={comparison.candidate_run_id}")
        return

    if args.command == "extract-loghub":
        written = extract_loghub_scenarios(
            LoghubExtractionConfig(
                dataset=args.dataset,
                input_path=Path(args.input),
                output_dir=Path(args.output),
                max_scenarios=args.max_scenarios,
                context_lines=args.context_lines,
                service=args.service,
            )
        )
        print(f"wrote {len(written)} scenarios")
        for path in written:
            print(path)
        return

    run = run_benchmark(
        BenchmarkRunConfig(
            suite=args.suite,
            output_root=Path(args.output),
            scenario_ids=tuple(args.scenario_id),
            scenario_root=Path(args.scenario_root) if args.scenario_root else None,
            signal_fixture_root=Path(args.signal_fixture_root) if args.signal_fixture_root else None,
            repeat=args.repeat,
            backend=args.backend,
            opensre_command=args.opensre_command,
            backend_timeout_seconds=args.backend_timeout_seconds,
        )
    )
    print(f"run_id={run.run_id}")
    print(f"score={run.scorecard.weighted_score:.2f}")
    print(f"report={run.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
