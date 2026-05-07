from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from .control_plane_models import MerkleSnapshot, RunEvent
from .merkle import build_merkle_proof, build_merkle_snapshot
from .schema_validation import validate_payload


def build_timeline_proof(
    *,
    run_id: str,
    events: list[RunEvent],
    merkle_snapshot: MerkleSnapshot | None = None,
    proof_event_id: str | None = None,
) -> dict[str, Any]:
    snapshot = merkle_snapshot or build_merkle_snapshot(run_id, events)
    selected_event_id = proof_event_id or (events[-1].event_id if events else None)
    proof = build_merkle_proof(run_id, events, selected_event_id).to_dict() if selected_event_id else None
    timeline = [_timeline_entry(event) for event in events]
    parsed_times = [entry["time_unix_nano"] for entry in timeline]
    parsed_only = [item for item in parsed_times if isinstance(item, int)]
    sequences = [event.sequence for event in events]
    expected = list(range(1, len(sequences) + 1))
    packet = {
        "schema_version": "mesh.timeline_proof.v1",
        "generated_at": _timestamp(),
        "run_id": run_id,
        "event_count": len(events),
        "timeline": timeline,
        "merkle": {
            "snapshot": snapshot.to_dict(),
            "latest_event_proof": proof,
        },
        "checks": {
            "sequence_monotonic": sequences == sorted(sequences),
            "sequence_gapless": sequences == expected,
            "timestamp_parseable": len(parsed_only) == len(parsed_times),
            "timestamp_non_decreasing": parsed_only == sorted(parsed_only),
            "merkle_root_present": bool(snapshot.root_hash),
            "latest_event_proof_valid": bool(proof and proof.get("valid")),
        },
    }
    validate_payload("timeline-proof.schema.json", packet)
    return packet


def _timeline_entry(event: RunEvent) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "stage": event.stage,
        "event_type": event.event_type,
        "recorded_at": event.recorded_at,
        "time_unix_nano": _time_unix_nano(event.recorded_at),
        "payload_sha256": _payload_hash(event.payload),
        "merkle_leaf_hash": event.merkle_leaf_hash,
        "artifact_key": event.artifact_key,
        "integration_name": event.integration_name,
        "status": event.status,
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _time_unix_nano(raw: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    return int(utc.timestamp()) * 1_000_000_000 + utc.microsecond * 1_000


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
