from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class EventEnvelope:
    event_type: str
    object_id: str
    schema_version: str
    emitted_at: str
    payload: dict[str, Any]
    parent_ids: dict[str, str] | None = None
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
