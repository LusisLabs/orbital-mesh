from __future__ import annotations

import argparse
from pathlib import Path

from .compare import compare_benchmark_runs
from .gaps import generate_gap_report
from .gates import run_benchmark_gate
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
    providers = ("mesh", "mesh-control-plane", "mesh-agentic", "opensre-cli", "sregym", "cloudopsbench")
    run_parser.add_argument("--backend", choices=providers, default="mesh")
    run_parser.add_argument("--provider", choices=providers, default=None)
    run_parser.add_argument("--evaluation-mode", default="native")
    run_parser.add_argument("--orchestration-mode", default="native")
    run_parser.add_argument("--steering-mode", default="interruptible_auto")
    run_parser.add_argument("--agent-fabric-mode", choices=("native", "deepagents"), default=None)
    run_parser.add_argument("--agent-tasks-mode", choices=("off", "async", "blocking"), default="blocking")
    run_parser.add_argument("--agent-lane", action="append", default=[])
    run_parser.add_argument("--agent-task-timeout-seconds", type=float, default=15.0)
    run_parser.add_argument("--deepagents-model", default=None)
    run_parser.add_argument("--deepagents-timeout-seconds", type=float, default=None)
    run_parser.add_argument("--deepagents-max-artifact-chars", type=int, default=None)
    run_parser.add_argument("--deepagents-max-output-tokens", type=int, default=None)
    run_parser.add_argument("--control-plane-timeout-seconds", type=float, default=300.0)
    run_parser.add_argument("--opensre-command", default="uvx opensre")
    run_parser.add_argument("--backend-timeout-seconds", type=float, default=300.0)
    run_parser.add_argument("--attempt-artifact-mode", choices=("full", "errors", "none"), default="full")
    run_parser.add_argument("--runtime-state-mode", choices=("full", "none"), default="full")
    run_parser.add_argument("--compact-artifacts", action="store_true")
    run_parser.add_argument("--cloudopsbench-root", default=None)
    run_parser.add_argument("--cloudopsbench-ground-truth-mode", choices=("hidden", "oracle"), default="hidden")
    run_parser.add_argument("--sregym-server-url", default="http://localhost:8000")
    run_parser.add_argument("--sregym-target", default="local-kind")

    gate_parser = subparsers.add_parser("gate", help="Run a benchmark suite against a gate profile.")
    gate_parser.add_argument("--profile", default="ci")
    gate_parser.add_argument("--profile-config", default=None)
    gate_parser.add_argument("--baseline", default=None)
    gate_parser.add_argument("--suite", default="golden")
    gate_parser.add_argument("--output", default=".mesh-runtime-state/benchmarks")
    gate_parser.add_argument("--scenario-id", action="append", default=[])
    gate_parser.add_argument("--scenario-root", default=None)
    gate_parser.add_argument("--signal-fixture-root", default=None)
    gate_parser.add_argument("--repeat", type=int, default=None)
    gate_parser.add_argument("--backend", choices=providers, default="mesh")
    gate_parser.add_argument("--provider", choices=providers, default=None)
    gate_parser.add_argument("--evaluation-mode", default="native")
    gate_parser.add_argument("--orchestration-mode", default="native")
    gate_parser.add_argument("--steering-mode", default="interruptible_auto")
    gate_parser.add_argument("--agent-fabric-mode", choices=("native", "deepagents"), default=None)
    gate_parser.add_argument("--agent-tasks-mode", choices=("off", "async", "blocking"), default="blocking")
    gate_parser.add_argument("--agent-lane", action="append", default=[])
    gate_parser.add_argument("--agent-task-timeout-seconds", type=float, default=15.0)
    gate_parser.add_argument("--deepagents-model", default=None)
    gate_parser.add_argument("--deepagents-timeout-seconds", type=float, default=None)
    gate_parser.add_argument("--deepagents-max-artifact-chars", type=int, default=None)
    gate_parser.add_argument("--deepagents-max-output-tokens", type=int, default=None)
    gate_parser.add_argument("--control-plane-timeout-seconds", type=float, default=300.0)
    gate_parser.add_argument("--opensre-command", default="uvx opensre")
    gate_parser.add_argument("--backend-timeout-seconds", type=float, default=300.0)
    gate_parser.add_argument("--attempt-artifact-mode", choices=("full", "errors", "none"), default=None)
    gate_parser.add_argument("--runtime-state-mode", choices=("full", "none"), default=None)
    gate_parser.add_argument("--compact-artifacts", action=argparse.BooleanOptionalAction, default=None)
    gate_parser.add_argument("--cloudopsbench-root", default=None)
    gate_parser.add_argument("--cloudopsbench-ground-truth-mode", choices=("hidden", "oracle"), default="hidden")
    gate_parser.add_argument("--sregym-server-url", default="http://localhost:8000")
    gate_parser.add_argument("--sregym-target", default="local-kind")
    gate_parser.add_argument("--min-weighted-score", type=float, default=None)
    gate_parser.add_argument("--min-mesh-operational-score", type=float, default=None)
    gate_parser.add_argument("--min-agentic-rca-score", type=float, default=None)
    gate_parser.add_argument("--min-pass-rate", type=float, default=None)
    gate_parser.add_argument("--min-decision-match-rate", type=float, default=None)
    gate_parser.add_argument("--min-investigation-coverage-rate", type=float, default=None)
    gate_parser.add_argument("--max-unsafe-action-rate", type=float, default=None)
    gate_parser.add_argument("--max-p95-latency-ms", type=float, default=None)
    gate_parser.add_argument("--min-root-cause-accuracy", type=float, default=None)
    gate_parser.add_argument("--min-tool-coverage", type=float, default=None)
    gate_parser.add_argument("--min-trajectory-in-order-match", type=float, default=None)
    gate_parser.add_argument("--max-invalid-action-count", type=float, default=None)
    gate_parser.add_argument("--max-zero-tool-diagnosis-rate", type=float, default=None)
    gate_parser.add_argument("--max-weighted-regression", type=float, default=None)
    gate_parser.add_argument("--max-agentic-rca-regression", type=float, default=None)
    gate_parser.add_argument("--max-root-cause-regression", type=float, default=None)
    gate_parser.add_argument("--max-tool-coverage-regression", type=float, default=None)
    gate_parser.add_argument("--max-pass-rate-regression", type=float, default=None)
    gate_parser.add_argument("--max-unsafe-action-rate-increase", type=float, default=None)

    compare_parser = subparsers.add_parser("compare", help="Compare two benchmark run directories.")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--output", default=None)

    gaps_parser = subparsers.add_parser("gaps", help="Generate a benchmark capability gap report.")
    gaps_parser.add_argument("--provider", choices=providers, required=True)
    gaps_parser.add_argument("--run", required=True)
    gaps_parser.add_argument("--output", default=None)

    loghub_parser = subparsers.add_parser("extract-loghub", help="Extract scenarios from a local Loghub corpus.")
    loghub_parser.add_argument("--dataset", required=True)
    loghub_parser.add_argument("--input", required=True)
    loghub_parser.add_argument("--output", required=True)
    loghub_parser.add_argument("--max-scenarios", type=int, default=25)
    loghub_parser.add_argument("--context-lines", type=int, default=3)
    loghub_parser.add_argument("--service", default="loghub-service")

    args = parser.parse_args()
    # When invoked without a subcommand (``python -m services.benchmark``)
    # argparse leaves ``args.command`` as None and never populates the
    # subparser-scoped attributes (``suite``, ``output``, …). The fallback
    # ``run`` dispatch below would then crash with AttributeError. Surface
    # the right thing — usage on stderr, non-zero exit — instead.
    if args.command is None:
        parser.print_help()
        raise SystemExit(2)
    if args.command == "gate":
        gate = run_benchmark_gate(
            BenchmarkRunConfig(
                suite=args.suite,
                output_root=Path(args.output),
                scenario_ids=tuple(args.scenario_id),
                scenario_root=Path(args.scenario_root) if args.scenario_root else None,
                signal_fixture_root=Path(args.signal_fixture_root) if args.signal_fixture_root else None,
                evaluation_mode=args.evaluation_mode,
                orchestration_mode=args.orchestration_mode,
                steering_mode=args.steering_mode,
                agent_fabric_mode=args.agent_fabric_mode,
                agent_tasks_mode=args.agent_tasks_mode,
                agent_lanes=tuple(args.agent_lane),
                agent_task_timeout_seconds=args.agent_task_timeout_seconds,
                deepagents_model=args.deepagents_model,
                deepagents_timeout_seconds=args.deepagents_timeout_seconds,
                deepagents_max_artifact_chars=args.deepagents_max_artifact_chars,
                deepagents_max_output_tokens=args.deepagents_max_output_tokens,
                backend=args.backend,
                provider=args.provider,
                opensre_command=args.opensre_command,
                backend_timeout_seconds=args.backend_timeout_seconds,
                control_plane_timeout_seconds=args.control_plane_timeout_seconds,
                cloudopsbench_root=Path(args.cloudopsbench_root) if args.cloudopsbench_root else None,
                cloudopsbench_ground_truth_mode=args.cloudopsbench_ground_truth_mode,
                sregym_server_url=args.sregym_server_url,
                sregym_target=args.sregym_target,
            ),
            profile_name=args.profile,
            profile_config_path=Path(args.profile_config) if args.profile_config else None,
            baseline_dir=Path(args.baseline) if args.baseline else None,
            threshold_overrides=_gate_threshold_overrides(args),
            repeat_override=args.repeat,
            attempt_artifact_mode_override=args.attempt_artifact_mode,
            runtime_state_mode_override=args.runtime_state_mode,
            compact_artifacts_override=args.compact_artifacts,
        )
        print(f"gate_status={'pass' if gate.passed else 'fail'}")
        print(f"run_id={gate.run.run_id}")
        print(f"score={gate.run.scorecard.weighted_score:.2f}")
        print(f"gate={gate.output_dir / 'gate.md'}")
        if not gate.passed:
            raise SystemExit(1)
        return

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

    if args.command == "gaps":
        report = generate_gap_report(
            provider=args.provider,
            run_dir=Path(args.run),
            output_dir=Path(args.output) if args.output else None,
        )
        print(f"gap_count={report.gap_count}")
        print(f"report={report.output_dir / 'gap_report.md'}")
        return

    run = run_benchmark(
        BenchmarkRunConfig(
            suite=args.suite,
            output_root=Path(args.output),
            scenario_ids=tuple(args.scenario_id),
            scenario_root=Path(args.scenario_root) if args.scenario_root else None,
            signal_fixture_root=Path(args.signal_fixture_root) if args.signal_fixture_root else None,
            repeat=args.repeat,
            evaluation_mode=args.evaluation_mode,
            orchestration_mode=args.orchestration_mode,
            steering_mode=args.steering_mode,
            agent_fabric_mode=args.agent_fabric_mode,
            agent_tasks_mode=args.agent_tasks_mode,
            agent_lanes=tuple(args.agent_lane),
            agent_task_timeout_seconds=args.agent_task_timeout_seconds,
            deepagents_model=args.deepagents_model,
            deepagents_timeout_seconds=args.deepagents_timeout_seconds,
            deepagents_max_artifact_chars=args.deepagents_max_artifact_chars,
            deepagents_max_output_tokens=args.deepagents_max_output_tokens,
            backend=args.backend,
            provider=args.provider,
            opensre_command=args.opensre_command,
            backend_timeout_seconds=args.backend_timeout_seconds,
            control_plane_timeout_seconds=args.control_plane_timeout_seconds,
            attempt_artifact_mode=args.attempt_artifact_mode,
            runtime_state_mode=args.runtime_state_mode,
            compact_artifacts=args.compact_artifacts,
            cloudopsbench_root=Path(args.cloudopsbench_root) if args.cloudopsbench_root else None,
            cloudopsbench_ground_truth_mode=args.cloudopsbench_ground_truth_mode,
            sregym_server_url=args.sregym_server_url,
            sregym_target=args.sregym_target,
        )
    )
    print(f"run_id={run.run_id}")
    print(f"score={run.scorecard.weighted_score:.2f}")
    print(f"report={run.output_dir / 'report.md'}")


def _gate_threshold_overrides(args: argparse.Namespace) -> dict[str, float]:
    mapping = {
        "min_weighted_score": "weighted_score_min",
        "min_mesh_operational_score": "mesh_operational_score_min",
        "min_agentic_rca_score": "agentic_rca_score_min",
        "min_pass_rate": "pass_rate_min",
        "min_decision_match_rate": "decision_match_rate_min",
        "min_investigation_coverage_rate": "investigation_coverage_rate_min",
        "max_unsafe_action_rate": "unsafe_action_rate_max",
        "max_p95_latency_ms": "p95_latency_ms_max",
        "min_root_cause_accuracy": "root_cause_accuracy_min",
        "min_tool_coverage": "tool_coverage_min",
        "min_trajectory_in_order_match": "trajectory_in_order_match_min",
        "max_invalid_action_count": "invalid_action_count_max",
        "max_zero_tool_diagnosis_rate": "zero_tool_diagnosis_rate_max",
        "max_weighted_regression": "weighted_score_regression_max",
        "max_agentic_rca_regression": "agentic_rca_score_regression_max",
        "max_root_cause_regression": "root_cause_accuracy_regression_max",
        "max_tool_coverage_regression": "tool_coverage_regression_max",
        "max_pass_rate_regression": "pass_rate_regression_max",
        "max_unsafe_action_rate_increase": "unsafe_action_rate_increase_max",
    }
    return {
        threshold_key: float(value)
        for arg_key, threshold_key in mapping.items()
        if (value := getattr(args, arg_key, None)) is not None
    }


if __name__ == "__main__":
    main()
