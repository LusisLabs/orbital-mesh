#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.control_plane import RunCoordinator
from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.evaluation_kit import EVALUATION_KIT_PACKET_VERSION, verify_evaluation_kit_packet
from shared.mesh_runtime.run_export_retrieval import verify_run_export_retrieval
from shared.mesh_runtime.schema_validation import validate_payload

if EVALUATION_KIT_PACKET_VERSION != "mesh.evaluation_kit_packet.v1":
    raise RuntimeError("unexpected evaluation-kit packet schema version")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an Orbital Mesh evaluation-kit packet.")
    parser.add_argument("--output-dir", default=".mesh-runtime-state/evaluation-kit", help="Directory for generated packet artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet = build_evaluation_kit_packet(output_dir)
    packet_path = output_dir / "evaluation-kit-packet.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verification = verify_evaluation_kit_packet(packet_path)
    payload = {**packet, "packet_path": str(packet_path), "verification": verification}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{packet['status']}: {packet_path}")
        for blocker in packet["blockers"]:
            print(f"blocker {blocker}")
    return 0 if packet["status"] == "complete" and verification["status"] == "pass" else 1


def build_evaluation_kit_packet(output_dir: Path) -> dict:
    runtime_state = output_dir / "runtime-state"
    coordinator = RunCoordinator(
        RuntimeConfig(
            state_directory=str(runtime_state),
            vault_path=str(runtime_state / "vault"),
            integrations_config_path=str(runtime_state / "integrations.json"),
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
            evo_command="/missing/evo",
            run_export_retention_reviewed=True,
            vault_mirror_mode="sync",
        )
    )
    try:
        sample_export = _build_sample_export(coordinator)
    finally:
        coordinator.stop_background_workers()

    benchmark_packet = _benchmark_packet(output_dir)
    checks = {
        "sample_export_retrieval_passed": sample_export["retrieval"]["status"] == "pass",
        "sample_archive_present": Path(sample_export["archive_path"]).is_file(),
        "benchmark_harness_present": (REPO_ROOT / benchmark_packet["harness_entrypoint"]).is_file(),
        "benchmark_scenarios_present": all(
            (REPO_ROOT / "benchmarks" / "scenarios" / "golden" / f"{scenario_id}.json").is_file()
            for scenario_id in benchmark_packet["scenario_ids"]
        ),
        "no_live_execution_required": True,
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    packet = {
        "schema_version": EVALUATION_KIT_PACKET_VERSION,
        "generated_at": _timestamp(),
        "status": "complete" if not blockers else "incomplete",
        "output_dir": str(output_dir),
        "sample_export": sample_export,
        "benchmark_packet": benchmark_packet,
        "checks": checks,
        "blockers": blockers,
    }
    validate_payload("evaluation-kit-packet.schema.json", packet)
    return packet


def _build_sample_export(coordinator: RunCoordinator) -> dict:
    session = coordinator.state_store.create_run_session(
        goal_id=coordinator.state_store.ensure_default_goal().goal_id,
        scenario_key="search_latency_regression",
        steering_mode="approval_gate",
        auto_mode=False,
        pause_points=[],
        evaluation_mode="native",
        orchestration_mode="native",
        artifacts={
            "input_signal": {
                "service": "search",
                "environment": "evaluation-kit",
                "api_key": "sample-secret-value",
            },
            "decision": {
                "decision_type": "reduce_rollout",
                "execution_plan": {"rollback_plan": "restore previous deployment revision"},
            },
            "evaluation": {"passed": True, "blocking_reasons": []},
            "execution": {"status": "succeeded", "external_refs": {"live_execution": False}},
            "feedback": {"outcome": "recovered", "source": "sample_export"},
            "approvals": [
                {
                    "operator": {"operator_id": "approver@example.com", "roles": ["approver"]},
                    "command_type": "approve",
                    "status": "accepted",
                }
            ],
        },
    )
    coordinator.state_store.append_run_event(
        session.run_id,
        stage="completed",
        event_type="run_completed",
        payload={"status": "completed", "authorization": "Bearer sample-secret-value"},
        status="completed",
    )
    current = coordinator.state_store.get_run_session(session.run_id)
    if current is None:
        raise RuntimeError("sample export run was not persisted")
    current.stage = "completed"
    current.status = "completed"
    coordinator.state_store.save_run_session(current)
    package = coordinator.export_run_package(session.run_id)
    archive = coordinator.export_run_archive(session.run_id)
    if package is None or archive is None:
        raise RuntimeError("sample export package or archive was not generated")
    retrieval = verify_run_export_retrieval(
        package_path=package["path"],
        archive_path=archive["path"],
    )
    return {
        "run_id": session.run_id,
        "package_path": package["path"],
        "package_sha256": _file_sha(Path(package["path"])),
        "archive_path": archive["path"],
        "archive_sha256": archive["sha256"],
        "retrieval": retrieval,
    }


def _benchmark_packet(output_dir: Path) -> dict:
    scenario_ids = ["feature_flag_latency_disable", "kubernetes_crashloop_patch"]
    command = [
        "python3",
        "-m",
        "services.benchmark",
        "run",
        "--suite",
        "golden",
        "--scenario-id",
        scenario_ids[0],
        "--scenario-id",
        scenario_ids[1],
        "--runtime-state-mode",
        "none",
        "--output",
        str(output_dir / "benchmark-runs"),
    ]
    return {
        "suite": "golden",
        "scenario_ids": scenario_ids,
        "command": command,
        "harness_entrypoint": "services/benchmark/__main__.py",
        "expected_artifacts": [
            "benchmark.json",
            "scorecard.json",
            "scenario-results.jsonl",
            "report.md",
        ],
    }


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
