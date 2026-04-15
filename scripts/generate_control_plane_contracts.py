#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime import control_plane_models as models  # noqa: E402

SCHEMA_PATH = REPO_ROOT / "scaffold" / "contracts" / "schemas" / "control-plane.schema.json"
TYPES_PATH = REPO_ROOT / "web" / "src" / "types.ts"
GENERATED_START = "// <generated-control-plane-contracts>"
GENERATED_END = "// </generated-control-plane-contracts>"

MODEL_CLASSES = (
    models.GoalRecord,
    models.RunEvent,
    models.RunSession,
    models.SteeringCommand,
    models.AgentAttempt,
    models.AgentTask,
    models.IntegrationStatus,
    models.IntegrationReadiness,
    models.MerkleProofStep,
    models.MerkleSnapshot,
    models.MerkleProof,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate control-plane JSON Schema and TypeScript contracts.")
    parser.add_argument("--check", action="store_true", help="Fail if generated files are not up to date.")
    args = parser.parse_args()

    schema_text = json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"
    types_text = render_typescript_block()

    current_types = TYPES_PATH.read_text(encoding="utf-8")
    next_types = replace_generated_block(current_types, types_text)

    if args.check:
        stale = []
        if not SCHEMA_PATH.exists() or SCHEMA_PATH.read_text(encoding="utf-8") != schema_text:
            stale.append(str(SCHEMA_PATH.relative_to(REPO_ROOT)))
        if current_types != next_types:
            stale.append(str(TYPES_PATH.relative_to(REPO_ROOT)))
        if stale:
            print("Generated contracts are stale:", ", ".join(stale), file=sys.stderr)
            print("Run: python3 scripts/generate_control_plane_contracts.py", file=sys.stderr)
            return 1
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text, encoding="utf-8")
    TYPES_PATH.write_text(next_types, encoding="utf-8")
    return 0


def replace_generated_block(current: str, generated: str) -> str:
    if GENERATED_START not in current or GENERATED_END not in current:
        raise SystemExit(f"{TYPES_PATH} must contain {GENERATED_START!r} and {GENERATED_END!r} markers")
    prefix, rest = current.split(GENERATED_START, 1)
    _, suffix = rest.split(GENERATED_END, 1)
    return f"{prefix}{GENERATED_START}\n{generated}{GENERATED_END}{suffix}"


def build_schema() -> dict[str, Any]:
    definitions = {cls.__name__: schema_for_dataclass(cls) for cls in MODEL_CLASSES}
    definitions["RunSessionRecord"] = {"$ref": "#/$defs/RunSession"}
    definitions["RunEventRecord"] = {"$ref": "#/$defs/RunEvent"}
    definitions["RunDetail"] = {
        "allOf": [
            {"$ref": "#/$defs/RunSession"},
            {
                "type": "object",
                "required": ["events", "merkle"],
                "properties": {
                    "events": {"type": "array", "items": {"$ref": "#/$defs/RunEvent"}},
                    "merkle": {"$ref": "#/$defs/MerkleSnapshot"},
                },
            },
        ]
    }
    definitions["SystemSnapshot"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["timestamp", "runs", "readiness", "active_runs"],
        "properties": {
            "timestamp": {"type": "string"},
            "runs": {"type": "array", "items": {"$ref": "#/$defs/RunSession"}},
            "readiness": {"$ref": "#/$defs/IntegrationReadiness"},
            "active_runs": {"type": "array", "items": {"$ref": "#/$defs/RunSession"}},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "control-plane.schema.json",
        "title": "Mesh control-plane contracts",
        "type": "object",
        "$defs": definitions,
    }


def schema_for_dataclass(cls: type[Any]) -> dict[str, Any]:
    hints = get_type_hints(cls)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(cls):
        properties[field.name] = schema_for_type(hints[field.name])
        required.append(field.name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def schema_for_type(tp: Any) -> dict[str, Any]:
    if tp is Any:
        return {}
    if tp is str:
        return {"type": "string"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is bool:
        return {"type": "boolean"}

    origin = get_origin(tp)
    args = get_args(tp)
    if origin in (types.UnionType, Union):
        return union_schema(args)
    if origin is list:
        return {"type": "array", "items": schema_for_type(args[0]) if args else {}}
    if origin is dict:
        value_schema = schema_for_type(args[1]) if len(args) == 2 else {}
        return {"type": "object", "additionalProperties": value_schema}
    if dataclasses.is_dataclass(tp):
        return {"$ref": f"#/$defs/{tp.__name__}"}
    return {}


def union_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    non_null = tuple(arg for arg in args if arg is not type(None))
    schemas = [schema_for_type(arg) for arg in non_null]
    schemas.append({"type": "null"})
    return {"anyOf": schemas}


def render_typescript_block() -> str:
    lines = [
        "/* eslint-disable */",
        "// Generated by scripts/generate_control_plane_contracts.py. Do not edit this block manually.",
        "export type JsonObject = Record<string, unknown>;",
        "",
    ]
    for cls in MODEL_CLASSES:
        lines.extend(render_interface(cls))
        lines.append("")
    lines.extend(
        [
            "export type RunSessionRecord = RunSession;",
            "export type RunEventRecord = RunEvent;",
            "",
            "export interface RunDetail extends RunSession {",
            "  events: RunEvent[];",
            "  merkle: MerkleSnapshot;",
            "}",
            "",
            "export interface SystemSnapshot {",
            "  timestamp: string;",
            "  runs: RunSessionRecord[];",
            "  readiness: IntegrationReadiness;",
            "  active_runs: RunSessionRecord[];",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def render_interface(cls: type[Any]) -> list[str]:
    hints = get_type_hints(cls)
    lines = [f"export interface {cls.__name__} {{"]
    for field in dataclasses.fields(cls):
        optional = "?" if field.default is None else ""
        lines.append(f"  {field.name}{optional}: {typescript_for_type(hints[field.name])};")
    lines.append("}")
    return lines


def typescript_for_type(tp: Any) -> str:
    if tp is Any:
        return "any"
    if tp is str:
        return "string"
    if tp in (int, float):
        return "number"
    if tp is bool:
        return "boolean"

    origin = get_origin(tp)
    args = get_args(tp)
    if origin in (types.UnionType, Union):
        return " | ".join(typescript_for_type(arg) for arg in args)
    if origin is list:
        item = typescript_for_type(args[0]) if args else "unknown"
        return f"{item}[]"
    if origin is dict:
        key_type = args[0] if args else str
        value = typescript_for_type(args[1]) if len(args) == 2 else "unknown"
        if key_type is str:
            return f"Record<string, {value}>"
        return f"Record<string, {value}>"
    if dataclasses.is_dataclass(tp):
        return tp.__name__
    if tp is type(None):
        return "null"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
