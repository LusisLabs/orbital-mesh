from __future__ import annotations

import json
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .json_store import LockedJsonFile


@dataclass
class RegistrationResult:
    accepted: bool
    record: dict[str, Any] | None = None


@dataclass
class RunRecord:
    run_id: str
    scenario_name: str
    recorded_at: str
    trigger_id: str | None
    decision_type: str | None
    final_recommendation: str | None
    execution_status: str | None
    feedback_outcome: str | None
    snapshot_path: str
    evaluation_mode: str
    orchestration_mode: str
    trigger_emitted: bool
    stage_event_count: int = 0
    integration_artifact_count: int = 0


def parse_state_json_file(path: Path, raw: str) -> dict[str, Any]:
    """Parse JSON from *raw*, returning {} on failure and writing a .corrupt backup."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        backup = path.with_suffix(
            f"{path.suffix}.corrupt.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(raw, encoding="utf-8")
        return {}


class RuntimeStateStore:
    def __init__(self, state_directory: str | Path):
        self.state_directory = Path(state_directory)
        self.state_directory.mkdir(parents=True, exist_ok=True)
        self._evaluations_path = self.state_directory / "evaluated_triggers.json"
        self._run_history_path = self.state_directory / "run_history.json"
        self._run_snapshots_dir = self.state_directory / "runs"
        self._run_snapshots_dir.mkdir(parents=True, exist_ok=True)

    def register_evaluation(self, trigger_id: str, decision_id: str) -> RegistrationResult:
        with self._locked_json(self._evaluations_path) as payload:
            records = payload.setdefault("evaluated_triggers", {})
            existing = records.get(trigger_id)
            if existing is not None:
                return RegistrationResult(accepted=False, record=existing)

            record = {
                "decision_id": decision_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            records[trigger_id] = record
            return RegistrationResult(accepted=True, record=record)

    def list_evaluations(self) -> dict[str, dict[str, Any]]:
        if not self._evaluations_path.exists():
            return {}
        with self._locked_json(self._evaluations_path) as payload:
            return deepcopy(payload.get("evaluated_triggers", {}))

    def record_loop_run(
        self,
        scenario_name: str,
        evaluation_mode: str,
        orchestration_mode: str,
        result: dict[str, Any],
    ) -> RunRecord:
        recorded_at = datetime.now(timezone.utc).isoformat()
        run_id = f"run_{recorded_at.replace(':', '').replace('-', '').replace('.', '')}_{uuid4().hex[:8]}"
        run_record = RunRecord(
            run_id=run_id,
            scenario_name=scenario_name,
            recorded_at=recorded_at,
            trigger_id=(result.get("trigger") or {}).get("trigger_id") if isinstance(result.get("trigger"), dict) else None,
            decision_type=(result.get("decision") or {}).get("decision_type") if isinstance(result.get("decision"), dict) else None,
            final_recommendation=(result.get("evaluation") or {}).get("final_recommendation")
            if isinstance(result.get("evaluation"), dict)
            else None,
            execution_status=(result.get("execution") or {}).get("status") if isinstance(result.get("execution"), dict) else None,
            feedback_outcome=(result.get("feedback") or {}).get("outcome") if isinstance(result.get("feedback"), dict) else None,
            snapshot_path=str(self._run_snapshots_dir / f"{run_id}.json"),
            evaluation_mode=evaluation_mode,
            orchestration_mode=orchestration_mode,
            trigger_emitted=bool(result.get("trigger")),
            stage_event_count=len(result.get("run_events", [])) if isinstance(result.get("run_events"), list) else 0,
            integration_artifact_count=(
                len(
                    [
                        event
                        for event in result.get("run_events", [])
                        if isinstance(event, dict) and event.get("integration_name")
                    ]
                )
                if isinstance(result.get("run_events"), list)
                else 0
            ),
        )
        snapshot_path = Path(run_record.snapshot_path)
        snapshot_payload = deepcopy(result)
        snapshot_payload["run_metadata"] = run_record.__dict__
        with snapshot_path.open("w") as handle:
            json.dump(snapshot_payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

        with self._locked_json(self._run_history_path) as payload:
            records = payload.setdefault("runs", [])
            records.insert(0, run_record.__dict__)
            del records[50:]
        return run_record

    def list_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self._run_history_path.exists():
            return []
        with self._locked_json(self._run_history_path) as payload:
            records = payload.get("runs", [])
            if not isinstance(records, list):
                return []
            return deepcopy(records[:limit])

    def load_run_snapshot(self, run_id: str) -> dict[str, Any] | None:
        snapshot_path = self._run_snapshots_dir / f"{run_id}.json"
        if not snapshot_path.exists():
            return None
        with snapshot_path.open() as handle:
            return json.load(handle)

    def reset(self) -> None:
        if self._evaluations_path.exists():
            self._evaluations_path.unlink()
        if self._run_history_path.exists():
            self._run_history_path.unlink()
        if self._run_snapshots_dir.exists():
            shutil.rmtree(self._run_snapshots_dir)
            self._run_snapshots_dir.mkdir(parents=True, exist_ok=True)

    _locked_json = LockedJsonFile
