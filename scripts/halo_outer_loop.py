#!/usr/bin/env python3
"""HALO outer-loop utilities for Mesh run history."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime import RuntimeConfig, build_mesh_state_store  # noqa: E402
from shared.mesh_runtime.halo import (  # noqa: E402
    HaloExportResult,
    build_halo_patch_task,
    export_halo_traces,
    load_halo_report,
    record_halo_optimization_cycle,
    run_halo_engine,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Mesh traces and record HALO harness-optimization cycles.")
    parser.add_argument("--state-directory", default=None, help="Mesh state directory. Defaults to RuntimeConfig.from_env().")
    parser.add_argument("--vault-path", default=None, help="Vault path when using an explicit state directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export Mesh run history as HALO-compatible JSONL.")
    _add_filter_args(export_parser)
    export_parser.add_argument("--output", required=True, help="Output JSONL path.")

    run_parser = subparsers.add_parser("run", help="Export traces and invoke the HALO CLI.")
    _add_filter_args(run_parser)
    run_parser.add_argument("--output", required=True, help="Trace JSONL path.")
    run_parser.add_argument("--halo-command", default="halo", help="HALO CLI command.")
    run_parser.add_argument(
        "--prompt",
        default="Diagnose recurring Mesh harness failure modes and suggest bounded fixes.",
        help="Prompt passed to HALO.",
    )
    run_parser.add_argument("--report-path", default=None, help="Optional path to write HALO stdout.")
    run_parser.add_argument("--timeout-seconds", type=float, default=900.0)

    task_parser = subparsers.add_parser("task", help="Convert a HALO report into a bounded Mesh patch task artifact.")
    task_parser.add_argument("--trace-jsonl", required=True, help="Trace JSONL produced by the export or run command.")
    task_parser.add_argument("--report", required=True, help="HALO report path, markdown/text or JSON.")
    task_parser.add_argument("--optimization-id", default=None, help="Stable optimization id. Defaults to halo_<timestamp>.")
    task_parser.add_argument("--agents", default="", help="Comma-separated agent lanes. Defaults to all harness lanes.")
    task_parser.add_argument("--print-json", action="store_true", help="Print the recorded artifact JSON.")

    args = parser.parse_args()
    config = _config_from_args(args)
    store = build_mesh_state_store(config)

    if args.command == "export":
        result = export_halo_traces(
            store,
            args.output,
            limit=args.limit,
            status=args.status,
            stage=args.stage,
            goal_id=args.goal_id,
        )
        print(json.dumps(result.__dict__, sort_keys=True))
        return 0

    if args.command == "run":
        result = run_halo_engine(
            store,
            args.output,
            halo_command=args.halo_command,
            prompt=args.prompt,
            limit=args.limit,
            report_path=args.report_path,
            timeout_seconds=args.timeout_seconds,
            status=args.status,
            stage=args.stage,
            goal_id=args.goal_id,
        )
        print(json.dumps(_halo_run_result_dict(result), sort_keys=True))
        return result.returncode

    if args.command == "task":
        run_ids = _read_trace_run_ids(args.trace_jsonl)
        report = load_halo_report(args.report)
        optimization_id = args.optimization_id or _optimization_id()
        agents = [item.strip() for item in args.agents.split(",") if item.strip()] or None
        task = build_halo_patch_task(
            optimization_id=optimization_id,
            report=report,
            run_ids=run_ids,
            agents=agents,
        )
        artifact = record_halo_optimization_cycle(
            store,
            export=HaloExportResult(trace_count=len(run_ids), output_path=args.trace_jsonl, run_ids=run_ids),
            report=report,
            task=task,
            metadata={"source": "scripts/halo_outer_loop.py"},
        )
        if args.print_json:
            print(json.dumps(artifact, indent=2, sort_keys=True))
        else:
            print(json.dumps({"optimization_id": optimization_id, "task_id": task.task_id, "run_count": len(run_ids)}, sort_keys=True))
        return 0

    return 2


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--status", default=None)
    parser.add_argument("--stage", default=None)
    parser.add_argument("--goal-id", default=None)


def _config_from_args(args: argparse.Namespace) -> RuntimeConfig:
    config = RuntimeConfig.from_env()
    if args.state_directory:
        state_directory = str(Path(args.state_directory).resolve())
        vault_path = str(Path(args.vault_path).resolve()) if args.vault_path else str(Path(state_directory) / "vault")
        return RuntimeConfig(
            **{
                **config.__dict__,
                "state_directory": state_directory,
                "vault_path": vault_path,
                "research_directory": str(Path(state_directory) / "research"),
                "integrations_config_path": str(Path(state_directory) / "integrations.json"),
            }
        )
    return config


def _read_trace_run_ids(path: str) -> list[str]:
    run_ids: list[str] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            run_id = row.get("trace_id") or row.get("run", {}).get("run_id")
            if isinstance(run_id, str):
                run_ids.append(run_id)
    return run_ids


def _halo_run_result_dict(result: Any) -> dict[str, Any]:
    return {
        "trace_count": result.export.trace_count,
        "output_path": result.export.output_path,
        "run_ids": result.export.run_ids,
        "command": result.command,
        "returncode": result.returncode,
        "report_path": result.report_path,
        "stderr": result.stderr,
    }


def _optimization_id() -> str:
    from datetime import datetime, timezone
    from uuid import uuid4

    return f"halo_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"


if __name__ == "__main__":
    raise SystemExit(main())
