from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from .mesh_state_store import MeshStateStore


DURABLE_WORKFLOW_VERSION = "mesh.durable_workflow_run.v1"
DURABLE_WORKFLOW_STATE_EVENT = "durable_workflow_state"


class WorkflowStore(Protocol):
    def load(self, workflow_id: str) -> dict[str, Any] | None: ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]: ...


class FileBackedWorkflowStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self, workflow_id: str) -> dict[str, Any] | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self._path(str(record["workflow_id"]))
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return record

    def _path(self, workflow_id: str) -> Path:
        return self.root / f"{workflow_id}.json"


class MeshStateWorkflowStore:
    def __init__(self, state_store: MeshStateStore, *, run_id: str) -> None:
        self.state_store = state_store
        self.run_id = run_id

    def load(self, workflow_id: str) -> dict[str, Any] | None:
        matched: dict[str, Any] | None = None
        for event in self.state_store.list_run_events(self.run_id):
            if event.event_type != DURABLE_WORKFLOW_STATE_EVENT:
                continue
            workflow = event.payload.get("workflow")
            if isinstance(workflow, dict) and workflow.get("workflow_id") == workflow_id:
                matched = dict(workflow)
        return matched

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self.state_store.append_run_event(
            self.run_id,
            stage="workflow",
            event_type=DURABLE_WORKFLOW_STATE_EVENT,
            payload={
                "workflow": dict(record),
                "authority": {
                    "mesh_state_store_authoritative": True,
                    "workflow_owns_remediation": False,
                },
            },
            summary={"workflow_id": record["workflow_id"], "status": record.get("status")},
            artifact_key="durable_workflow_state",
            integration_name="mesh_workflow",
            status="recorded",
        )
        return record


def start_or_replay_workflow(
    *,
    store: WorkflowStore,
    workflow_id: str,
    workflow_type: str,
    run_id: str,
    sleep_until: str | None = None,
) -> dict[str, Any]:
    existing = store.load(workflow_id)
    if existing is not None:
        return existing
    return store.save(
        {
            "schema_version": DURABLE_WORKFLOW_VERSION,
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "run_id": run_id,
            "status": "sleeping" if sleep_until else "ready",
            "sleep_until": sleep_until,
            "checkpoints": [],
            "created_at": _timestamp(),
            "updated_at": _timestamp(),
            "authority": {
                "mesh_run_session_authoritative": True,
                "workflow_owns_remediation": False,
            },
        }
    )


def attach_workflow_event(
    *,
    workflow: dict[str, Any],
    store: WorkflowStore,
    state_store: MeshStateStore,
    checkpoint_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoints = [cp for cp in workflow.get("checkpoints", []) if isinstance(cp, dict)]
    for checkpoint in checkpoints:
        if checkpoint.get("checkpoint_id") == checkpoint_id:
            return workflow
    event = state_store.append_run_event(
        str(workflow["run_id"]),
        stage="workflow",
        event_type="durable_workflow_checkpoint",
        payload={
            "workflow_id": workflow["workflow_id"],
            "workflow_type": workflow["workflow_type"],
            "checkpoint_id": checkpoint_id,
            "payload": dict(payload or {}),
            "authority": workflow.get("authority", {}),
        },
        summary={"workflow_id": workflow["workflow_id"], "checkpoint_id": checkpoint_id},
        artifact_key="durable_workflow",
        integration_name="mesh_workflow",
        status="recorded",
    )
    checkpoints.append(
        {
            "checkpoint_id": checkpoint_id,
            "run_event_id": event.event_id,
            "recorded_at": event.recorded_at,
        }
    )
    workflow = dict(workflow)
    workflow["checkpoints"] = checkpoints
    workflow["status"] = "recorded"
    workflow["updated_at"] = _timestamp()
    return store.save(workflow)


def resume_workflow(
    *,
    workflow: dict[str, Any],
    store: WorkflowStore,
    reason: str,
) -> dict[str, Any]:
    workflow = dict(workflow)
    workflow["status"] = "ready"
    workflow["sleep_until"] = None
    workflow["resume_reason"] = reason
    workflow["updated_at"] = _timestamp()
    return store.save(workflow)


def schedule_workflow_retry(
    *,
    workflow: dict[str, Any],
    store: WorkflowStore,
    retry_after: str,
    reason: str,
) -> dict[str, Any]:
    workflow = dict(workflow)
    workflow["status"] = "retry_scheduled"
    workflow["retry_after"] = retry_after
    workflow["retry_reason"] = reason
    workflow["retry_count"] = int(workflow.get("retry_count") or 0) + 1
    workflow["updated_at"] = _timestamp()
    return store.save(workflow)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
