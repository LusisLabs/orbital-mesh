#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.state_store_factory import build_mesh_state_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Postgres-backed run events, memory, and Merkle roots survive a store restart.")
    parser.add_argument("--database-url", default=os.getenv("MESH_DATABASE_URL"), help="Postgres connection URL. Defaults to MESH_DATABASE_URL.")
    parser.add_argument("--state-dir", default=None, help="Local scratch state directory for vault/runtime side files.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--skip-if-missing", action="store_true", help="Return success with status=skipped when no database URL is configured.")
    args = parser.parse_args()

    if not args.database_url:
        payload = {"status": "skipped", "reason": "MESH_DATABASE_URL is not set"}
        _emit(payload, json_mode=args.json)
        return 0 if args.skip_if_missing else 2

    try:
        payload = run_proof(args.database_url, state_dir=args.state_dir)
    except Exception as exc:  # noqa: BLE001 - this is a CLI proof harness.
        payload = {"status": "failed", "error": str(exc)}
        _emit(payload, json_mode=args.json)
        return 1
    _emit(payload, json_mode=args.json)
    return 0 if payload["status"] == "passed" else 1


def run_proof(database_url: str, *, state_dir: str | None = None) -> dict[str, Any]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if state_dir is None:
        temp_dir = tempfile.TemporaryDirectory()
        state_dir = temp_dir.name
    try:
        base = Path(state_dir)
        config = RuntimeConfig(
            state_backend="postgres",
            database_url=database_url,
            state_directory=str(base / "state"),
            vault_path=str(base / "vault"),
            integrations_config_path=str(base / "integrations.json"),
            vault_mirror_mode="sync",
        )
        store = build_mesh_state_store(config)
        session = store.create_run_session(
            goal_id=None,
            scenario_key="postgres_restart_proof",
            steering_mode="approval_gate",
            auto_mode=False,
            pause_points=["evaluation_ready"],
            evaluation_mode="native",
            orchestration_mode="native_hermes",
            artifacts={"proof": "postgres_restart"},
        )
        first_event = store.append_run_event(
            session.run_id,
            stage="queued",
            event_type="postgres_restart_proof_started",
            payload={"proof": "events"},
            status="recorded",
        )
        store.append_run_event(
            session.run_id,
            stage="completed",
            event_type="postgres_restart_proof_completed",
            payload={"proof": "merkle"},
            status="recorded",
        )
        observation = store.append_observation(
            {
                "observation_id": f"obs_{session.run_id}",
                "service": "postgres-proof",
                "run_id": session.run_id,
                "scope": {"service": "postgres-proof", "run_id": session.run_id},
                "kind": "restart-proof",
                "content": "Postgres restart proof memory record",
                "source_type": "postgres_restart_proof",
                "source_refs": [{"run_id": session.run_id}],
                "created_at": first_event.recorded_at,
                "author": "mesh",
                "tags": ["postgres", "restart-proof"],
                "metadata": {},
            }
        )
        root_before = store.get_merkle_snapshot(session.run_id).root_hash
        _close(store)

        reopened = build_mesh_state_store(config)
        try:
            restored = reopened.get_run_session(session.run_id)
            events = reopened.list_run_events(session.run_id)
            root_after = reopened.get_merkle_snapshot(session.run_id).root_hash
            observations = reopened.list_observations(
                {"service": "postgres-proof", "run_id": session.run_id},
                {"kind": "restart-proof", "limit": 10},
            )
            checks = {
                "run_restored": restored is not None,
                "events_restored": [event.sequence for event in events] == [1, 2],
                "first_event_proof_restored": reopened.get_merkle_proof(session.run_id, first_event.event_id) is not None,
                "merkle_root_stable": bool(root_before and root_before == root_after),
                "memory_restored": any(item.get("observation_id") == observation["observation_id"] for item in observations),
            }
            return {
                "status": "passed" if all(checks.values()) else "failed",
                "run_id": session.run_id,
                "checks": checks,
                "merkle_root": root_after,
            }
        finally:
            _close(reopened)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def _close(store: Any) -> None:
    close = getattr(store, "close", None)
    if callable(close):
        close(timeout=5.0)


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload["status"])
        for key, value in payload.items():
            if key != "status":
                print(f"{key}: {value}")


if __name__ == "__main__":
    sys.exit(main())
