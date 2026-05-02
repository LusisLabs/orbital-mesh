#!/usr/bin/env python3
"""Seed a file-backed Mesh state directory for the operator UI smoke test."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from shared.mesh_runtime import FileStateStore, RunEvent, RunSession, RuntimeConfig


DEFAULT_FIXTURE = (
    Path(".mesh-runtime-state")
    / "reth-kurtosis-loop"
    / "session_20260426T193540Z"
    / "000005_disk_pressure_escalate"
    / "run_final.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-directory", required=True, help="Output Mesh state directory.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Fixture run_final.json to seed.")
    parser.add_argument("--reset", action="store_true", help="Delete the state directory before seeding.")
    args = parser.parse_args()

    state_directory = Path(args.state_directory).resolve()
    fixture = Path(args.fixture).resolve()
    if args.reset and state_directory.exists():
        shutil.rmtree(state_directory)
    state_directory.mkdir(parents=True, exist_ok=True)

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


def _run_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(RunSession.__dataclass_fields__)
    return {key: value for key, value in payload.items() if key in allowed}


if __name__ == "__main__":
    main()
