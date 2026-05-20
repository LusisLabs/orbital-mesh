from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.operator_identity import SETTINGS_SCHEMA, OperatorIdentityStore, write_settings_audit


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _identity_path(args: argparse.Namespace) -> Path:
    if args.identity_path:
        return Path(args.identity_path)
    return Path(RuntimeConfig.from_env().operator_identity_path)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _parse_update(raw: list[str]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for item in raw:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"setting must use key=value: {item}")
        updates[key] = value
    return updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect and mutate validated Mesh operator UI settings.")
    parser.add_argument("--identity-path", help="Path to operator identity/settings JSON. Defaults to RuntimeConfig.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Show settings for a scope.")
    show.add_argument("--scope", default="global", help="global, user:<id>, or team:<id>.")

    validate = subparsers.add_parser("validate", help="Validate setting schema and current scope values.")
    validate.add_argument("--scope", default="global", help="global, user:<id>, or team:<id>.")

    set_cmd = subparsers.add_parser("set", help="Set one or more key=value settings.")
    set_cmd.add_argument("--scope", required=True, help="global, user:<id>, or team:<id>.")
    set_cmd.add_argument("--operator-id", required=True)
    set_cmd.add_argument("--reason", required=True)
    set_cmd.add_argument("settings", nargs="+")

    args = parser.parse_args(argv)
    identity_path = _identity_path(args)
    store = OperatorIdentityStore(identity_path)

    try:
        if args.command == "show":
            _json(store.read_scoped_settings(args.scope))
            return 0
        if args.command == "validate":
            payload = store.read_scoped_settings(args.scope)
            invalid = []
            for key, value in payload["settings"].items():
                schema = SETTINGS_SCHEMA.get(key)
                if schema is None or value not in schema["values"]:
                    invalid.append({"field": key, "value": value})
            _json({"scope": args.scope, "valid": not invalid, "invalid": invalid, "settings_schema": SETTINGS_SCHEMA})
            return 0 if not invalid else 2
        if args.command == "set":
            updates = _parse_update(args.settings)
            payload = store.update_scoped_settings(args.scope, updates)
            write_settings_audit(
                identity_path,
                operator_id=args.operator_id,
                reason=args.reason,
                scope=args.scope,
                updates=updates,
                git_commit=_git_commit(),
            )
            _json(payload)
            return 0
    except ValueError as exc:
        _json({"error": str(exc)})
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
