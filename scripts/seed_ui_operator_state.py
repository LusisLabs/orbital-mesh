#!/usr/bin/env python3
"""Seed a file-backed Mesh state directory for the operator UI smoke test."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from services.control_plane import RunCoordinator
from shared.mesh_runtime import FileStateStore, RunEvent, RunSession, RuntimeConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-directory", required=True, help="Output Mesh state directory.")
    parser.add_argument(
        "--fixture",
        default=None,
        help="Optional run_final.json fixture to seed instead of generating a runtime run.",
    )
    parser.add_argument("--reset", action="store_true", help="Delete the state directory before seeding.")
    args = parser.parse_args()

    state_directory = Path(args.state_directory).resolve()
    fixture = Path(args.fixture).resolve() if args.fixture else None
    if args.reset and state_directory.exists():
        shutil.rmtree(state_directory)
    state_directory.mkdir(parents=True, exist_ok=True)

    if fixture is None:
        print(_seed_from_runtime(state_directory))
        return
    if not fixture.exists():
        raise FileNotFoundError(f"fixture not found: {fixture}")

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    events = payload.pop("events", [])
    payload.pop("merkle", None)

    config = RuntimeConfig(
        state_directory=str(state_directory),
        vault_path=str(state_directory / "vault"),
        integrations_config_path=str(state_directory / "integrations.json"),
        research_directory=str(state_directory / "research"),
        evaluation_mode="native",
        orchestration_mode="native",
        promptfoo_command=None,
        hermes_command=None,
        goose_command=None,
        evo_command=None,
        gitnexus_disable_autostart=True,
    )
    store = FileStateStore(config)
    store.ensure_default_goal()
    session = RunSession(**_run_session_payload(payload))
    store.save_run_session(session)
    for event in events:
        store.append_event(session.run_id, RunEvent(**event))
    store.save_run_session(RunSession(**_run_session_payload(payload)))
    (state_directory / "ui_operator_seed.json").write_text(
        json.dumps({"run_id": session.run_id, "fixture": str(fixture)}, indent=2),
        encoding="utf-8",
    )
    print(session.run_id)


def _seed_from_runtime(state_directory: Path) -> str:
    config = _runtime_config(state_directory)
    coordinator = RunCoordinator(config)
    try:
        run = coordinator.create_run(
            {
                "scenario_key": "search_latency_regression",
                "evaluation_mode": "native",
                "orchestration_mode": "native",
                "steering_mode": "interruptible_auto",
                "pause_points": [],
            }
        )
        run_id = run["run_id"]
        deadline = time.monotonic() + 30
        terminal = {"completed", "failed", "cancelled", "no_trigger", "recovery_spawned"}
        while time.monotonic() < deadline:
            session = coordinator.state_store.get_run_session(run_id)
            if session is not None and session.stage in terminal:
                (state_directory / "ui_operator_seed.json").write_text(
                    json.dumps({"run_id": run_id, "fixture": "generated:search_latency_regression"}, indent=2),
                    encoding="utf-8",
                )
                return run_id
            time.sleep(0.1)
        raise TimeoutError(f"seed run {run_id} did not reach a terminal stage")
    finally:
        coordinator.stop_background_workers(timeout=5.0)


def _runtime_config(state_directory: Path) -> RuntimeConfig:
    return RuntimeConfig(
        state_directory=str(state_directory),
        vault_path=str(state_directory / "vault"),
        integrations_config_path=str(state_directory / "integrations.json"),
        research_directory=str(state_directory / "research"),
        evaluation_mode="native",
        orchestration_mode="native",
        promptfoo_command=None,
        hermes_command=None,
        goose_command=None,
        evo_command=None,
        agent_tasks_mode="off",
        gitnexus_disable_autostart=True,
    )


def _run_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(RunSession.__dataclass_fields__)
    return {key: value for key, value in payload.items() if key in allowed}


if __name__ == "__main__":
    main()
