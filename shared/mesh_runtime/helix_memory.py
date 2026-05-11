from __future__ import annotations

import json
from http import HTTPStatus
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, request

from .config import RuntimeConfig


class HelixMemoryProjectionError(RuntimeError):
    pass


class HelixMemoryProjectionProtocol(Protocol):
    enabled: bool

    def upsert_observation(self, record: dict[str, Any]) -> None: ...

    def upsert_claim(self, record: dict[str, Any]) -> None: ...

    def upsert_relationship(self, record: dict[str, Any]) -> None: ...

    def upsert_supersession(self, record: dict[str, Any]) -> None: ...

    def record_retrieval(self, record: dict[str, Any]) -> None: ...

    def upsert_memory_packet(self, record: dict[str, Any]) -> None: ...


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

    def _query(self, query_name: str, payload: dict[str, Any]) -> None:
        try:
            self.client.query(query_name, payload)
        except Exception as exc:
            raise HelixMemoryProjectionError(f"HelixDB memory projection query {query_name!r} failed: {exc}") from exc


def build_helix_memory_projection(
    config: RuntimeConfig,
    *,
    client: Any | None = None,
) -> HelixMemoryProjectionProtocol:
    if config.memory_graph_backend != "helix":
        return DisabledHelixMemoryProjection()
    return HelixMemoryProjection(config, client=client)


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
        raise HelixMemoryProjectionError(f"HelixDB memory projection record missing {key!r}")
    return str(value)
