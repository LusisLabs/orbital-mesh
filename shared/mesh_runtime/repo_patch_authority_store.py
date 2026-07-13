from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, Protocol

from .json_store import LockedJsonFile


AUTHORITY_STORE_VERSION = "mesh.repo_patch_authority_store.v1"
AUTHORITY_RECORD_VERSION = "mesh.repo_patch_authority_record.v1"
AUTHORITY_EVENT_VERSION = "mesh.repo_patch_authority_event_receipt.v1"
GENESIS_EVENT_DIGEST = "sha256:" + ("0" * 64)
TERMINAL_OUTCOMES = frozenset({"succeeded", "failed", "rejected", "unknown"})
_NONCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AuthorityStoreError(ValueError):
    pass


class AuthorityConflictError(AuthorityStoreError):
    pass


class AuthorityNotFoundError(AuthorityStoreError):
    pass


class AuthorityStateError(AuthorityStoreError):
    pass


class RepoPatchAuthorityStore(Protocol):
    def issue_or_get(
        self,
        *,
        authority_id: str,
        idempotency_key: str,
        nonce: str,
        action_binding: dict[str, Any],
    ) -> dict[str, Any]: ...

    def lease_for_dispatch(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        lease_seconds: int = 30,
    ) -> dict[str, Any]: ...

    def mark_dispatched(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
    ) -> dict[str, Any]: ...

    def complete_terminal(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        outcome: str,
        result: dict[str, Any],
    ) -> dict[str, Any]: ...

    def read_for_reconciliation(self, authority_id: str) -> dict[str, Any] | None: ...


def canonical_authority_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class FileRepoPatchAuthorityStore:
    """File-backed authority state with lock-scoped compare-and-set transitions."""

    def __init__(
        self,
        state_directory: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(state_directory).resolve() / "repo_patch_authority_store.json"
        self.clock = clock or _utc_now

    def issue_or_get(
        self,
        *,
        authority_id: str,
        idempotency_key: str,
        nonce: str,
        action_binding: dict[str, Any],
    ) -> dict[str, Any]:
        request = _validated_issue_request(authority_id, idempotency_key, nonce, action_binding)
        with LockedJsonFile(self.path, recover_corrupt_input=False) as payload:
            root = _file_root(payload)
            existing_id = root["idempotency"].get(idempotency_key) or (
                authority_id if authority_id in root["records"] else None
            )
            if existing_id is not None:
                existing = _required_record(root["records"], str(existing_id))
                _require_same_issue(existing, request)
                return deepcopy(existing)
            nonce_owner = root["nonces"].get(nonce)
            if nonce_owner is not None:
                raise AuthorityConflictError(f"authority nonce already belongs to {nonce_owner!r}")
            record, event = _new_issue(request, self.clock())
            root["records"][authority_id] = record
            root["idempotency"][idempotency_key] = authority_id
            root["nonces"][nonce] = authority_id
            root["events"][authority_id] = [event]
            return deepcopy(record)

    def lease_for_dispatch(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        lease_seconds: int = 30,
    ) -> dict[str, Any]:
        now = self.clock()
        with LockedJsonFile(self.path, recover_corrupt_input=False) as payload:
            root = _file_root(payload)
            current = _required_record(root["records"], authority_id)
            updated, event = _lease_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                lease_seconds=lease_seconds,
                now=now,
            )
            _store_file_transition(root, updated, event)
            return deepcopy(updated)

    def mark_dispatched(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
    ) -> dict[str, Any]:
        with LockedJsonFile(self.path, recover_corrupt_input=False) as payload:
            root = _file_root(payload)
            current = _required_record(root["records"], authority_id)
            updated, event = _dispatch_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                now=self.clock(),
            )
            _store_file_transition(root, updated, event)
            return deepcopy(updated)

    def complete_terminal(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        outcome: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with LockedJsonFile(self.path, recover_corrupt_input=False) as payload:
            root = _file_root(payload)
            current = _required_record(root["records"], authority_id)
            updated, event = _terminal_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                outcome=outcome,
                result=result,
                now=self.clock(),
            )
            _store_file_transition(root, updated, event)
            return deepcopy(updated)

    def read_for_reconciliation(self, authority_id: str) -> dict[str, Any] | None:
        with LockedJsonFile(self.path, recover_corrupt_input=False) as payload:
            if not payload:
                return None
            root = _file_root(payload)
            record = root["records"].get(authority_id)
            if record is None:
                return None
            if not isinstance(record, dict):
                raise AuthorityStoreError("authority record is malformed")
            events = root["events"].get(authority_id)
            return _reconciliation_payload(record, events)


class PostgresRepoPatchAuthorityStore:
    """Postgres authority state using the process-wide Mesh connection pool."""

    def __init__(
        self,
        config: Any | None = None,
        *,
        connection_factory: Callable[[], ContextManager[Any]] | None = None,
        json_adapter: Callable[[Any], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if connection_factory is None:
            if config is None:
                raise ValueError("Postgres authority store requires RuntimeConfig or a connection factory")
            from .postgres_state import _get_or_create_pool

            pool = _get_or_create_pool(config)
            connection_factory = pool.connection
        self._connection_factory = connection_factory
        self._json_adapter = json_adapter or _postgres_jsonb
        self.clock = clock or _utc_now

    def issue_or_get(
        self,
        *,
        authority_id: str,
        idempotency_key: str,
        nonce: str,
        action_binding: dict[str, Any],
    ) -> dict[str, Any]:
        request = _validated_issue_request(authority_id, idempotency_key, nonce, action_binding)
        with self._connection_factory() as conn:
            for lock_key in sorted((f"authority:{authority_id}", f"idempotency:{idempotency_key}", f"nonce:{nonce}")):
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
            row = conn.execute(
                """
                SELECT record FROM repo_patch_authority_records
                WHERE authority_id = %s OR idempotency_key = %s OR nonce = %s
                FOR UPDATE
                """,
                (authority_id, idempotency_key, nonce),
            ).fetchone()
            if row is not None:
                existing = _decoded_json(row[0])
                _require_same_issue(existing, request)
                return deepcopy(existing)
            record, event = _new_issue(request, self.clock())
            conn.execute(
                """
                INSERT INTO repo_patch_authority_records
                  (authority_id, idempotency_key, nonce, action_binding_digest, state, version,
                   event_sequence, latest_event_digest, record, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    authority_id,
                    idempotency_key,
                    nonce,
                    record["action_binding_digest"],
                    record["state"],
                    record["version"],
                    record["event_sequence"],
                    record["latest_event_digest"],
                    self._json_adapter(record),
                    record["issued_at"],
                    record["updated_at"],
                ),
            )
            self._append_event(conn, event)
            return deepcopy(record)

    def lease_for_dispatch(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        lease_seconds: int = 30,
    ) -> dict[str, Any]:
        return self._transition(
            authority_id,
            expected_version,
            lambda current: _lease_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                lease_seconds=lease_seconds,
                now=self.clock(),
            ),
        )

    def mark_dispatched(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            authority_id,
            expected_version,
            lambda current: _dispatch_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                now=self.clock(),
            ),
        )

    def complete_terminal(
        self,
        authority_id: str,
        *,
        expected_version: int,
        lease_id: str,
        outcome: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self._transition(
            authority_id,
            expected_version,
            lambda current: _terminal_transition(
                current,
                expected_version=expected_version,
                lease_id=lease_id,
                outcome=outcome,
                result=result,
                now=self.clock(),
            ),
        )

    def read_for_reconciliation(self, authority_id: str) -> dict[str, Any] | None:
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT record FROM repo_patch_authority_records WHERE authority_id = %s",
                (authority_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = conn.execute(
                "SELECT receipt FROM repo_patch_authority_events WHERE authority_id = %s ORDER BY sequence",
                (authority_id,),
            ).fetchall()
            return _reconciliation_payload(
                _decoded_json(row[0]),
                [_decoded_json(event_row[0]) for event_row in event_rows],
            )

    def _transition(
        self,
        authority_id: str,
        expected_version: int,
        transition: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]],
    ) -> dict[str, Any]:
        _required_text(authority_id, "authority_id")
        _required_version(expected_version)
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT record FROM repo_patch_authority_records WHERE authority_id = %s FOR UPDATE",
                (authority_id,),
            ).fetchone()
            if row is None:
                raise AuthorityNotFoundError(f"authority record {authority_id!r} does not exist")
            current = _decoded_json(row[0])
            updated, event = transition(current)
            changed = conn.execute(
                """
                UPDATE repo_patch_authority_records
                SET state = %s, version = %s, event_sequence = %s, latest_event_digest = %s,
                    record = %s, updated_at = %s
                WHERE authority_id = %s AND version = %s AND state = %s
                RETURNING authority_id
                """,
                (
                    updated["state"],
                    updated["version"],
                    updated["event_sequence"],
                    updated["latest_event_digest"],
                    self._json_adapter(updated),
                    updated["updated_at"],
                    authority_id,
                    expected_version,
                    current["state"],
                ),
            ).fetchone()
            if changed is None:
                raise AuthorityConflictError("authority compare-and-set failed")
            self._append_event(conn, event)
            return deepcopy(updated)

    def _append_event(self, conn: Any, event: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO repo_patch_authority_events
              (authority_id, sequence, event_id, event_type, state_version, previous_event_digest,
               event_digest, recorded_at, receipt)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event["authority_id"],
                event["sequence"],
                event["event_id"],
                event["event_type"],
                event["state_version"],
                event["previous_event_digest"],
                event["event_digest"],
                event["recorded_at"],
                self._json_adapter(event),
            ),
        )


def _validated_issue_request(
    authority_id: str,
    idempotency_key: str,
    nonce: str,
    action_binding: dict[str, Any],
) -> dict[str, Any]:
    _required_text(authority_id, "authority_id")
    _required_text(idempotency_key, "idempotency_key")
    if not _NONCE_PATTERN.fullmatch(nonce):
        raise AuthorityStoreError("nonce must be 64 lowercase hexadecimal characters")
    if not isinstance(action_binding, dict) or not action_binding:
        raise AuthorityStoreError("action_binding must be a nonempty object")
    binding = _json_copy(action_binding)
    return {
        "authority_id": authority_id,
        "idempotency_key": idempotency_key,
        "nonce": nonce,
        "action_binding": binding,
        "action_binding_digest": canonical_authority_digest(binding),
    }


def _new_issue(request: dict[str, Any], now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    timestamp = _format_time(now)
    record = {
        "schema_version": AUTHORITY_RECORD_VERSION,
        **deepcopy(request),
        "state": "issued",
        "version": 1,
        "lease_id": None,
        "lease_expires_at": None,
        "dispatched_at": None,
        "terminal_outcome": None,
        "terminal_result": None,
        "issued_at": timestamp,
        "updated_at": timestamp,
        "event_sequence": 0,
        "latest_event_digest": GENESIS_EVENT_DIGEST,
    }
    return _with_event(record, "issued", {"idempotency_key": request["idempotency_key"], "nonce": request["nonce"]})


def _lease_transition(
    current: dict[str, Any],
    *,
    expected_version: int,
    lease_id: str,
    lease_seconds: int,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_transition(current, expected_version, {"issued", "leased"})
    _required_text(lease_id, "lease_id")
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
        raise AuthorityStoreError("lease_seconds must be a positive integer")
    previous_lease_id = current.get("lease_id")
    if current["state"] == "leased":
        lease_expires_at = current.get("lease_expires_at")
        if not isinstance(lease_expires_at, str) or now <= _parse_time(lease_expires_at):
            raise AuthorityStateError("authority pre-dispatch lease is still active")
        if previous_lease_id == lease_id:
            raise AuthorityConflictError("authority expired lease reclaim requires a fresh lease id")
    updated = deepcopy(current)
    updated["state"] = "leased"
    updated["version"] = expected_version + 1
    updated["lease_id"] = lease_id
    updated["lease_expires_at"] = _format_time(now + timedelta(seconds=lease_seconds))
    updated["updated_at"] = _format_time(now)
    event_type = "expired_pre_dispatch_lease_reclaimed" if current["state"] == "leased" else "leased_for_dispatch"
    return _with_event(
        updated,
        event_type,
        {
            "lease_id": lease_id,
            "lease_expires_at": updated["lease_expires_at"],
            "previous_lease_id": previous_lease_id,
        },
    )


def _dispatch_transition(
    current: dict[str, Any],
    *,
    expected_version: int,
    lease_id: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_transition(current, expected_version, {"leased"})
    _require_lease(current, lease_id)
    lease_expires_at = current.get("lease_expires_at")
    if not isinstance(lease_expires_at, str) or now > _parse_time(lease_expires_at):
        raise AuthorityStateError("authority dispatch lease expired")
    updated = deepcopy(current)
    updated["state"] = "dispatched"
    updated["version"] = expected_version + 1
    updated["dispatched_at"] = _format_time(now)
    updated["updated_at"] = _format_time(now)
    return _with_event(updated, "marked_dispatched", {"lease_id": lease_id})


def _terminal_transition(
    current: dict[str, Any],
    *,
    expected_version: int,
    lease_id: str,
    outcome: str,
    result: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_transition(current, expected_version, {"leased", "dispatched"})
    _require_lease(current, lease_id)
    if outcome not in TERMINAL_OUTCOMES:
        raise AuthorityStoreError(f"unsupported terminal outcome {outcome!r}")
    if current["state"] == "leased" and outcome not in {"failed", "rejected"}:
        raise AuthorityStateError("a pre-dispatch lease may complete only as failed or rejected")
    if not isinstance(result, dict):
        raise AuthorityStoreError("terminal result must be an object")
    terminal_result = _json_copy(result)
    updated = deepcopy(current)
    updated["state"] = "terminal"
    updated["version"] = expected_version + 1
    updated["terminal_outcome"] = outcome
    updated["terminal_result"] = terminal_result
    updated["updated_at"] = _format_time(now)
    return _with_event(
        updated,
        "terminal_completed",
        {
            "lease_id": lease_id,
            "outcome": outcome,
            "result_digest": canonical_authority_digest(terminal_result),
            "dispatch_observed": current["state"] == "dispatched",
        },
    )


def _with_event(
    record: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = deepcopy(record)
    sequence = int(updated.get("event_sequence", 0)) + 1
    event_body = {
        "schema_version": AUTHORITY_EVENT_VERSION,
        "authority_id": updated["authority_id"],
        "sequence": sequence,
        "event_type": event_type,
        "state_version": updated["version"],
        "action_binding_digest": updated["action_binding_digest"],
        "previous_event_digest": updated.get("latest_event_digest") or GENESIS_EVENT_DIGEST,
        "recorded_at": updated["updated_at"],
        "payload": _json_copy(payload),
    }
    event_digest = canonical_authority_digest(event_body)
    event = {
        **event_body,
        "event_id": f"authority_event_{event_digest.removeprefix('sha256:')}",
        "event_digest": event_digest,
    }
    updated["event_sequence"] = sequence
    updated["latest_event_digest"] = event_digest
    return updated, event


def _reconciliation_payload(record: dict[str, Any], events: Any) -> dict[str, Any]:
    _validate_record_binding(record)
    if not isinstance(events, list) or not events:
        raise AuthorityStoreError("authority event receipts are missing")
    previous = GENESIS_EVENT_DIGEST
    for expected_sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            raise AuthorityStoreError("authority event receipt is malformed")
        if event.get("sequence") != expected_sequence:
            raise AuthorityStoreError("authority event sequence is not contiguous")
        if event.get("schema_version") != AUTHORITY_EVENT_VERSION:
            raise AuthorityStoreError("authority event schema version is unsupported")
        if event.get("state_version") != expected_sequence:
            raise AuthorityStoreError("authority event state version is not contiguous")
        if event.get("authority_id") != record.get("authority_id"):
            raise AuthorityStoreError("authority event record binding mismatch")
        if event.get("action_binding_digest") != record.get("action_binding_digest"):
            raise AuthorityStoreError("authority event action binding mismatch")
        if event.get("previous_event_digest") != previous:
            raise AuthorityStoreError("authority event digest chain is broken")
        body = dict(event)
        body.pop("event_id", None)
        claimed_digest = body.pop("event_digest", None)
        if claimed_digest != canonical_authority_digest(body):
            raise AuthorityStoreError("authority event digest is invalid")
        previous = str(claimed_digest)
    if record.get("event_sequence") != len(events):
        raise AuthorityStoreError("authority record event sequence mismatch")
    if record.get("latest_event_digest") != previous:
        raise AuthorityStoreError("authority record latest event digest mismatch")
    if events[-1].get("state_version") != record.get("version"):
        raise AuthorityStoreError("authority record version is not reconciled")
    return {
        "schema_version": AUTHORITY_STORE_VERSION,
        "record": deepcopy(record),
        "events": deepcopy(events),
        "event_chain_valid": True,
    }


def _file_root(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        payload.update(
            {
                "schema_version": AUTHORITY_STORE_VERSION,
                "records": {},
                "idempotency": {},
                "nonces": {},
                "events": {},
            }
        )
    if payload.get("schema_version") != AUTHORITY_STORE_VERSION:
        raise AuthorityStoreError("unsupported repo-patch authority-store version")
    for field in ("records", "idempotency", "nonces", "events"):
        if not isinstance(payload.get(field), dict):
            raise AuthorityStoreError(f"authority store field {field!r} is malformed")
    return payload


def _store_file_transition(root: dict[str, Any], updated: dict[str, Any], event: dict[str, Any]) -> None:
    authority_id = updated["authority_id"]
    events = root["events"].get(authority_id)
    if not isinstance(events, list):
        raise AuthorityStoreError("authority event receipts are missing")
    events.append(event)
    root["records"][authority_id] = updated


def _require_same_issue(existing: dict[str, Any], request: dict[str, Any]) -> None:
    _validate_record_binding(existing)
    for field in ("authority_id", "idempotency_key", "nonce", "action_binding_digest"):
        if existing.get(field) != request.get(field):
            raise AuthorityConflictError(f"issue-or-get conflict on {field}")
    if existing.get("action_binding") != request.get("action_binding"):
        raise AuthorityConflictError("issue-or-get conflict on full action binding")


def _require_transition(record: dict[str, Any], expected_version: int, allowed_states: set[str]) -> None:
    _validate_record_binding(record)
    _required_version(expected_version)
    if record.get("version") != expected_version:
        raise AuthorityConflictError(
            f"authority version conflict: expected {expected_version}, found {record.get('version')!r}"
        )
    if record.get("state") not in allowed_states:
        raise AuthorityStateError(f"authority state {record.get('state')!r} does not allow this transition")


def _require_lease(record: dict[str, Any], lease_id: str) -> None:
    _required_text(lease_id, "lease_id")
    if record.get("lease_id") != lease_id:
        raise AuthorityConflictError("authority lease id mismatch")


def _required_record(records: dict[str, Any], authority_id: str) -> dict[str, Any]:
    _required_text(authority_id, "authority_id")
    record = records.get(authority_id)
    if not isinstance(record, dict):
        raise AuthorityNotFoundError(f"authority record {authority_id!r} does not exist")
    _validate_record_binding(record)
    return record


def _validate_record_binding(record: dict[str, Any]) -> None:
    if record.get("schema_version") != AUTHORITY_RECORD_VERSION:
        raise AuthorityStoreError("unsupported repo-patch authority-record version")
    binding = record.get("action_binding")
    if not isinstance(binding, dict) or not binding:
        raise AuthorityStoreError("authority record action binding is malformed")
    if record.get("action_binding_digest") != canonical_authority_digest(binding):
        raise AuthorityStoreError("authority record action binding digest is invalid")


def _required_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityStoreError(f"{field} must be a nonempty string")


def _required_version(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AuthorityStoreError("expected_version must be a positive integer")


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise AuthorityStoreError("authority payload must be finite JSON data") from exc


def _decoded_json(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise AuthorityStoreError("Postgres authority JSON record is malformed")
    return deepcopy(decoded)


def _postgres_jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Postgres authority store requires psycopg JSON support") from exc
    return Jsonb(value)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise AuthorityStoreError("authority-store clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorityStoreError("authority-store timestamp is malformed") from exc
    if parsed.tzinfo is None:
        raise AuthorityStoreError("authority-store timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)
