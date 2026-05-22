from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mesh_darkharness.fixtures import load_fixture
from mesh_darkharness.schema_validation import SchemaValidationError

from .boundaries import assert_pilot_scope_boundaries, assert_reservoir_default_deny


@dataclass(frozen=True)
class DarkharnessRegistry:
    tenant_id: str
    pilot_scope: dict[str, Any]
    sensitive_reservoirs: list[dict[str, Any]]
    trust_ladder_ref: str | None
    owner_registry_ref: str | None
    policy_refs: list[str]
    source_path: str | None


def load_darkharness_registry(path: str | Path | None = None) -> DarkharnessRegistry:
    if path is None:
        payload = _fixture_registry()
        source_path = None
    else:
        registry_path = Path(path)
        if not registry_path.exists():
            raise SchemaValidationError(f"{registry_path}: Darkharness registry does not exist")
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"{registry_path}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise SchemaValidationError(f"{registry_path}: registry root must be an object")
        payload = raw
        source_path = str(registry_path)
    return _coerce_registry(payload, source_path=source_path)


def _fixture_registry() -> dict[str, Any]:
    fixture_payload = load_fixture("perennial", "allowed_action.json")
    contracts = cast(dict[str, Any], fixture_payload["contracts"])
    return {
        "registry": "darkharness.registry.v1",
        "tenant_id": "shadow",
        "pilot_scope": contracts["pilot_scope"],
        "sensitive_reservoirs": [contracts["sensitive_reservoir"]],
        "trust_ladder_ref": None,
        "owner_registry_ref": None,
        "policy_refs": ["policy://darkharness/pilot/approval-required"],
    }


def _coerce_registry(payload: dict[str, Any], *, source_path: str | None) -> DarkharnessRegistry:
    pilot_scope = payload.get("pilot_scope")
    if not isinstance(pilot_scope, dict):
        raise SchemaValidationError("$.pilot_scope: required object")
    raw_reservoirs = payload.get("sensitive_reservoirs")
    if not isinstance(raw_reservoirs, list) or not raw_reservoirs:
        raise SchemaValidationError("$.sensitive_reservoirs: required non-empty array")
    reservoirs: list[dict[str, Any]] = []
    for index, reservoir in enumerate(raw_reservoirs):
        if not isinstance(reservoir, dict):
            raise SchemaValidationError(f"$.sensitive_reservoirs[{index}]: required object")
        reservoirs.append(assert_reservoir_default_deny(copy.deepcopy(reservoir)))
    return DarkharnessRegistry(
        tenant_id=str(payload.get("tenant_id") or "shadow"),
        pilot_scope=assert_pilot_scope_boundaries(copy.deepcopy(pilot_scope)),
        sensitive_reservoirs=reservoirs,
        trust_ladder_ref=str(payload["trust_ladder_ref"]) if payload.get("trust_ladder_ref") else None,
        owner_registry_ref=str(payload["owner_registry_ref"]) if payload.get("owner_registry_ref") else None,
        policy_refs=_string_list(payload.get("policy_refs")),
        source_path=source_path,
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None]
    if value is None:
        return []
    return [str(value)]
