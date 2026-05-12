from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from http import HTTPStatus
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib import error, request

from .config import RuntimeConfig
from .json_store import LockedJsonFile


class HelixMemoryProjectionError(RuntimeError):
    pass


class HelixMemoryProjectionRecordError(HelixMemoryProjectionError):
    pass


class HelixMemoryProjectionProtocol(Protocol):
    enabled: bool

    def upsert_observation(self, record: dict[str, Any]) -> None: ...

    def upsert_claim(self, record: dict[str, Any]) -> None: ...

    def upsert_relationship(self, record: dict[str, Any]) -> None: ...

    def upsert_supersession(self, record: dict[str, Any]) -> None: ...

    def record_retrieval(self, record: dict[str, Any]) -> None: ...

    def upsert_memory_packet(self, record: dict[str, Any]) -> None: ...

    def replay_pending(self, limit: int | None = None) -> dict[str, Any]: ...

    def projection_status(self) -> dict[str, Any]: ...


class HelixMemoryProjectionOutboxProtocol(Protocol):
    def enqueue(self, operation: str, record: dict[str, Any]) -> str: ...

    def mark_applied(self, event_id: str) -> None: ...

    def mark_failed(self, event_id: str, error_message: str) -> None: ...

    def pending_events(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def status(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HelixMemoryQueryNames:
    upsert_observation: str
    upsert_claim: str
    upsert_relationship: str
    upsert_supersession: str
    record_retrieval: str
    upsert_memory_packet: str

    @classmethod
    def from_namespace(cls, namespace: str) -> "HelixMemoryQueryNames":
        prefix = namespace.strip() or "mesh"
        return cls(
            upsert_observation=f"{prefix}_upsert_observation",
            upsert_claim=f"{prefix}_upsert_claim",
            upsert_relationship=f"{prefix}_upsert_relationship",
            upsert_supersession=f"{prefix}_upsert_supersession",
            record_retrieval=f"{prefix}_record_retrieval",
            upsert_memory_packet=f"{prefix}_upsert_memory_packet",
        )


class DisabledHelixMemoryProjection:
    enabled = False

    def upsert_observation(self, record: dict[str, Any]) -> None:
        del record

    def upsert_claim(self, record: dict[str, Any]) -> None:
        del record

    def upsert_relationship(self, record: dict[str, Any]) -> None:
        del record

    def upsert_supersession(self, record: dict[str, Any]) -> None:
        del record

    def record_retrieval(self, record: dict[str, Any]) -> None:
        del record

    def upsert_memory_packet(self, record: dict[str, Any]) -> None:
        del record

    def replay_pending(self, limit: int | None = None) -> dict[str, Any]:
        return {"enabled": False, "outbox_enabled": False, "attempted": 0, "applied": 0, "failed": 0, "failures": []}

    def projection_status(self) -> dict[str, Any]:
        return {"enabled": False, "outbox_enabled": False}


class HelixMemoryProjection:
    enabled = True

    def __init__(self, config: RuntimeConfig, *, client: Any | None = None):
        self.config = config
        self.query_names = HelixMemoryQueryNames.from_namespace(config.helix_query_namespace)
        self.client = client if client is not None else _build_helix_client(config)

    def upsert_observation(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.upsert_observation,
            {
                "observation_id": _required(record, "observation_id"),
                "service": _optional(record.get("service")),
                "run_id": _optional(record.get("run_id")),
                "kind": _optional(record.get("kind")),
                "content": _optional(record.get("content")),
                "scope_json": _json_text(record.get("scope", {})),
                "payload_json": _json_text(record),
                "created_at": _optional(record.get("created_at")),
            },
        )

    def upsert_claim(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.upsert_claim,
            {
                "claim_id": _required(record, "claim_id"),
                "state": _optional(record.get("state")),
                "tier": _optional(record.get("tier")),
                "statement": _optional(record.get("statement")),
                "confidence": float(record.get("confidence") or 0.0),
                "freshness": float(record.get("freshness") or 0.0),
                "entity_refs_json": _json_text(record.get("entity_refs", [])),
                "supporting_observation_ids_json": _json_text(record.get("supporting_observation_ids", [])),
                "payload_json": _json_text(record),
                "updated_at": _optional(record.get("updated_at")),
            },
        )

    def upsert_relationship(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.upsert_relationship,
            {
                "relationship_id": _required(record, "relationship_id"),
                "from_id": _required(record, "from_id"),
                "to_id": _required(record, "to_id"),
                "relationship_type": _optional(record.get("relationship_type") or record.get("type")),
                "scope_json": _json_text(record.get("scope", {})),
                "payload_json": _json_text(record),
                "created_at": _optional(record.get("created_at")),
            },
        )

    def upsert_supersession(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.upsert_supersession,
            {
                "supersession_id": _required(record, "supersession_id"),
                "old_claim_id": _required(record, "old_claim_id"),
                "new_claim_id": _required(record, "new_claim_id"),
                "payload_json": _json_text(record),
                "created_at": _optional(record.get("created_at")),
            },
        )

    def record_retrieval(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.record_retrieval,
            {
                "retrieval_id": _required(record, "retrieval_id"),
                "query": _optional(record.get("query")),
                "scope_json": _json_text(record.get("scope", {})),
                "channels_json": _json_text(record.get("channels", [])),
                "payload_json": _json_text(record),
                "created_at": _optional(record.get("created_at")),
            },
        )

    def upsert_memory_packet(self, record: dict[str, Any]) -> None:
        self._query(
            self.query_names.upsert_memory_packet,
            {
                "packet_id": _required(record, "packet_id"),
                "scope_json": _json_text(record.get("scope", {})),
                "claim_ids_json": _json_text([claim.get("claim_id") for claim in record.get("claims", []) if isinstance(claim, dict)]),
                "observation_ids_json": _json_text([
                    observation.get("observation_id")
                    for observation in record.get("observations", [])
                    if isinstance(observation, dict)
                ]),
                "payload_json": _json_text(record),
                "generated_at": _optional(record.get("generated_at")),
            },
        )

    def replay_pending(self, limit: int | None = None) -> dict[str, Any]:
        return {"enabled": True, "outbox_enabled": False, "attempted": 0, "applied": 0, "failed": 0, "failures": []}

    def projection_status(self) -> dict[str, Any]:
        return {"enabled": True, "outbox_enabled": False}

    def _query(self, query_name: str, payload: dict[str, Any]) -> None:
        try:
            self.client.query(query_name, payload)
        except Exception as exc:
            raise HelixMemoryProjectionError(f"HelixDB memory projection query {query_name!r} failed: {exc}") from exc


class DurableHelixMemoryProjection:
    enabled = True

    def __init__(
        self,
        projection: HelixMemoryProjection,
        outbox: HelixMemoryProjectionOutboxProtocol,
        *,
        raise_on_failure: bool = False,
    ):
        self.projection = projection
        self.outbox = outbox
        self.raise_on_failure = raise_on_failure

    def upsert_observation(self, record: dict[str, Any]) -> None:
        self._project("upsert_observation", record)

    def upsert_claim(self, record: dict[str, Any]) -> None:
        self._project("upsert_claim", record)

    def upsert_relationship(self, record: dict[str, Any]) -> None:
        self._project("upsert_relationship", record)

    def upsert_supersession(self, record: dict[str, Any]) -> None:
        self._project("upsert_supersession", record)

    def record_retrieval(self, record: dict[str, Any]) -> None:
        self._project("record_retrieval", record)

    def upsert_memory_packet(self, record: dict[str, Any]) -> None:
        self._project("upsert_memory_packet", record)

    def replay_pending(self, limit: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "enabled": True,
            "outbox_enabled": True,
            "attempted": 0,
            "applied": 0,
            "failed": 0,
            "failures": [],
        }
        failures = cast(list[dict[str, str]], result["failures"])
        for event in self.outbox.pending_events(limit):
            event_id = str(event.get("event_id", ""))
            operation = str(event.get("operation", ""))
            record = event.get("record")
            result["attempted"] = int(result["attempted"]) + 1
            if not event_id or not isinstance(record, dict):
                error_message = "HelixDB projection outbox event is malformed"
                if event_id:
                    self.outbox.mark_failed(event_id, error_message)
                result["failed"] = int(result["failed"]) + 1
                failures.append({"event_id": event_id, "error": error_message})
                continue
            try:
                self._call_operation(operation, cast(dict[str, Any], record))
            except HelixMemoryProjectionError as exc:
                error_message = str(exc)
                self.outbox.mark_failed(event_id, error_message)
                result["failed"] = int(result["failed"]) + 1
                failures.append({"event_id": event_id, "error": error_message})
            else:
                self.outbox.mark_applied(event_id)
                result["applied"] = int(result["applied"]) + 1
        result["outbox"] = self.projection_status()
        return result

    def projection_status(self) -> dict[str, Any]:
        return {"enabled": True, "outbox_enabled": True, **self.outbox.status()}

    def _project(self, operation: str, record: dict[str, Any]) -> None:
        event_id = self.outbox.enqueue(operation, record)
        try:
            self._call_operation(operation, record)
        except HelixMemoryProjectionRecordError as exc:
            self.outbox.mark_failed(event_id, str(exc))
            raise
        except HelixMemoryProjectionError as exc:
            self.outbox.mark_failed(event_id, str(exc))
            if self.raise_on_failure:
                raise
        except Exception as exc:
            wrapped = HelixMemoryProjectionError(f"HelixDB memory projection operation {operation!r} failed: {exc}")
            self.outbox.mark_failed(event_id, str(wrapped))
            if self.raise_on_failure:
                raise wrapped from exc
        else:
            self.outbox.mark_applied(event_id)

    def _call_operation(self, operation: str, record: dict[str, Any]) -> None:
        if operation not in _PROJECTION_OPERATIONS:
            raise HelixMemoryProjectionRecordError(f"unknown HelixDB memory projection operation {operation!r}")
        method = getattr(self.projection, operation)
        method(record)


class HelixMemoryProjectionOutbox:
    def __init__(self, path: Path):
        self.path = path

    def enqueue(self, operation: str, record: dict[str, Any]) -> str:
        event = build_helix_memory_projection_event(operation, record)
        event_id = str(event["event_id"])
        with LockedJsonFile(self.path) as payload:
            events = _outbox_events(payload)
            for existing in events:
                if existing.get("event_id") == event_id:
                    if existing.get("status") != "applied":
                        existing["operation"] = event["operation"]
                        existing["record"] = deepcopy(event["record"])
                        existing["status"] = "pending"
                        existing["updated_at"] = event["updated_at"]
                    return event_id
            events.append(event)
        return event_id

    def mark_applied(self, event_id: str) -> None:
        self._update_event(
            event_id,
            status="applied",
            last_error=None,
            applied_at=_utc_timestamp(),
            increment_attempts=True,
        )

    def mark_failed(self, event_id: str, error_message: str) -> None:
        self._update_event(
            event_id,
            status="failed",
            last_error=error_message,
            applied_at=None,
            increment_attempts=True,
        )

    def pending_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        with LockedJsonFile(self.path) as payload:
            events = [
                deepcopy(event)
                for event in _outbox_events(payload)
                if event.get("status") in {"pending", "failed"}
            ]
        if limit is None:
            return events
        return events[: max(limit, 0)]

    def status(self) -> dict[str, Any]:
        with LockedJsonFile(self.path) as payload:
            events = [deepcopy(event) for event in _outbox_events(payload)]
        return _outbox_status(events, path=str(self.path))

    def _update_event(
        self,
        event_id: str,
        *,
        status: str,
        last_error: str | None,
        applied_at: str | None,
        increment_attempts: bool,
    ) -> None:
        with LockedJsonFile(self.path) as payload:
            for event in _outbox_events(payload):
                if event.get("event_id") != event_id:
                    continue
                event["status"] = status
                event["updated_at"] = _utc_timestamp()
                event["last_error"] = last_error
                event["applied_at"] = applied_at
                if increment_attempts:
                    event["attempts"] = int(event.get("attempts") or 0) + 1
                return


def build_helix_memory_projection(
    config: RuntimeConfig,
    *,
    client: Any | None = None,
    outbox: HelixMemoryProjectionOutboxProtocol | None = None,
    raise_on_failure: bool = False,
) -> HelixMemoryProjectionProtocol:
    if config.memory_graph_backend != "helix":
        return DisabledHelixMemoryProjection()
    projection = HelixMemoryProjection(config, client=client)
    projection_outbox = outbox or HelixMemoryProjectionOutbox(Path(config.state_directory) / "helix_memory_projection_outbox.json")
    return DurableHelixMemoryProjection(projection, projection_outbox, raise_on_failure=raise_on_failure)


def build_helix_memory_projection_event(operation: str, record: dict[str, Any]) -> dict[str, Any]:
    if operation not in _PROJECTION_OPERATIONS:
        raise HelixMemoryProjectionRecordError(f"unknown HelixDB memory projection operation {operation!r}")
    now = _utc_timestamp()
    record_payload = deepcopy(record)
    return {
        "event_id": _projection_event_id(operation, record_payload),
        "operation": operation,
        "record": record_payload,
        "status": "pending",
        "attempts": 0,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
        "applied_at": None,
    }


def _build_helix_client(config: RuntimeConfig) -> Any:
    if config.helix_api_endpoint:
        return _HttpHelixClient(config.helix_api_endpoint)
    try:
        from helix.client import Client
    except ImportError as exc:
        return _HttpHelixClient(f"http://localhost:{config.helix_port}", sdk_import_error=exc)
    return Client(local=True, port=config.helix_port)


class _HttpHelixClient:
    def __init__(self, endpoint: str, *, sdk_import_error: ImportError | None = None):
        self.endpoint = endpoint.rstrip("/")
        self.sdk_import_error = sdk_import_error

    def query(self, name: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self.endpoint}/{name}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=10) as response:
                response_body = response.read().decode("utf-8")
                if response.status < HTTPStatus.OK or response.status >= HTTPStatus.MULTIPLE_CHOICES:
                    raise HelixMemoryProjectionError(f"HelixDB HTTP query {name!r} returned HTTP {response.status}")
                return json.loads(response_body) if response_body else {}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HelixMemoryProjectionError(f"HelixDB HTTP query {name!r} returned HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            hint = ""
            if self.sdk_import_error is not None:
                hint = "; helix-py is not installed, so the adapter used the local HTTP fallback"
            raise HelixMemoryProjectionError(f"HelixDB HTTP endpoint {self.endpoint!r} is unreachable{hint}") from exc


def _json_text(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _optional(value: Any) -> str:
    return "" if value is None else str(value)


def _required(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value is None or value == "":
        raise HelixMemoryProjectionRecordError(f"HelixDB memory projection record missing {key!r}")
    return str(value)


_PROJECTION_OPERATIONS = {
    "upsert_observation",
    "upsert_claim",
    "upsert_relationship",
    "upsert_supersession",
    "record_retrieval",
    "upsert_memory_packet",
}

_PROJECTION_ID_KEYS = {
    "upsert_observation": "observation_id",
    "upsert_claim": "claim_id",
    "upsert_relationship": "relationship_id",
    "upsert_supersession": "supersession_id",
    "record_retrieval": "retrieval_id",
    "upsert_memory_packet": "packet_id",
}


def _projection_event_id(operation: str, record: dict[str, Any]) -> str:
    identity_key = _PROJECTION_ID_KEYS[operation]
    identity = _safe_event_id_part(record.get(identity_key) or "unknown")
    payload_hash = hashlib.sha256(_json_text(record).encode("utf-8")).hexdigest()[:24]
    return f"{operation}:{identity}:{payload_hash}"


def _safe_event_id_part(value: Any) -> str:
    raw = str(value)
    return "".join(character if character.isalnum() or character in {"-", "_", "."} else "_" for character in raw)


def _outbox_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        events: list[dict[str, Any]] = []
        payload["events"] = events
        return events
    if all(isinstance(event, dict) for event in raw_events):
        return cast(list[dict[str, Any]], raw_events)
    events = [event for event in raw_events if isinstance(event, dict)]
    payload["events"] = events
    return events


def _outbox_status(events: list[dict[str, Any]], *, path: str | None = None) -> dict[str, Any]:
    counts = {"pending": 0, "failed": 0, "applied": 0}
    last_error = None
    for event in events:
        status = str(event.get("status") or "pending")
        if status in counts:
            counts[status] += 1
        if event.get("last_error"):
            last_error = str(event["last_error"])
    result: dict[str, Any] = {
        "total": len(events),
        "pending": counts["pending"],
        "failed": counts["failed"],
        "applied": counts["applied"],
        "last_error": last_error,
    }
    if path is not None:
        result["path"] = path
    return result


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
