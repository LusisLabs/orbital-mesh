from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a payload does not match a shared contract schema."""


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


@lru_cache(maxsize=None)
def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_name
    with path.open() as handle:
        return json.load(handle)


def validate_payload(schema_name: str, payload: dict[str, Any]) -> None:
    schema = load_schema(schema_name)
    _validate_node(payload, schema, "$")


def _validate_node(value: Any, schema: dict[str, Any], path: str) -> None:
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: {value!r} not in enum {schema['enum']!r}")

    if "type" in schema:
        allowed_types = schema["type"]
        if not isinstance(allowed_types, list):
            allowed_types = [allowed_types]
        if not any(_matches_type(value, item) for item in allowed_types):
            raise SchemaValidationError(f"{path}: expected type {allowed_types!r}, got {type(value).__name__}")

    if value is None:
        return

    if schema.get("type") == "object" or (isinstance(schema.get("type"), list) and "object" in schema["type"] and isinstance(value, dict)):
        _validate_object(value, schema, path)
        return

    if schema.get("type") == "array" or (isinstance(schema.get("type"), list) and "array" in schema["type"] and isinstance(value, list)):
        _validate_array(value, schema, path)
        return


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in value:
            raise SchemaValidationError(f"{path}: missing required field {field_name!r}")

    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra_keys = set(value) - set(properties)
        if extra_keys:
            raise SchemaValidationError(f"{path}: unexpected fields {sorted(extra_keys)!r}")

    for field_name, field_value in value.items():
        child_path = f"{path}.{field_name}"
        property_schema = properties.get(field_name)
        if property_schema is None:
            continue
        _validate_node(field_value, property_schema, child_path)


def _validate_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    min_items = schema.get("minItems")
    if min_items is not None and len(value) < min_items:
        raise SchemaValidationError(f"{path}: expected at least {min_items} items, got {len(value)}")

    item_schema = schema.get("items")
    if item_schema is None:
        return

    for index, item in enumerate(value):
        _validate_node(item, item_schema, f"{path}[{index}]")


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "null":
        return value is None
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    return True
