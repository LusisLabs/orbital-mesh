#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.pilot_signoff import (
    PILOT_SIGNOFF_VERSION,
    PILOT_SIGNOFF_VERIFICATION_VERSION,
    build_pilot_signoff_packet,
    load_pilot_signoff_packet,
    verify_pilot_signoff_packet,
)


EXPECTED_PILOT_SIGNOFF_VERIFICATION_SCHEMA = "mesh.pilot_signoff_verification.v1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a signed pilot go/no-go operator signoff packet.")
    parser.add_argument("--signoff", help="Path to a mesh.pilot_signoff.v1 JSON packet.")
    parser.add_argument("--go-no-go", help="Path to the captured pilot.go_no_go.v1 packet.")
    parser.add_argument("--build-output", help="Write a mesh.pilot_signoff.v1 packet instead of verifying one.")
    parser.add_argument("--operator-id", help="Operator identity for --build-output.")
    parser.add_argument("--role", action="append", default=[], help="Operator role for --build-output. Repeatable.")
    parser.add_argument("--operator-source", default="trusted_proxy", help="Operator identity source for --build-output.")
    parser.add_argument("--signing-key", help="HMAC signing key. Defaults to MESH_PILOT_SIGNOFF_KEY.")
    parser.add_argument("--signing-key-file", help="File containing the HMAC signing key.")
    parser.add_argument("--expected-release-provenance-sha", help="Expected mesh.release_provenance.v1 packet SHA-256.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    build_mode = bool(args.build_output)
    payload = _build(args) if build_mode else _verify(args)
    if not build_mode and (
        payload.get("schema_version") != PILOT_SIGNOFF_VERIFICATION_VERSION
        or payload.get("schema_version") != EXPECTED_PILOT_SIGNOFF_VERIFICATION_SCHEMA
    ):
        payload = {**payload, "status": "fail", "errors": [*payload.get("errors", []), "unexpected_schema_version"]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif build_mode:
        print(f"built: {payload['schema_version']}")
    else:
        print(f"{payload['status']}: {payload['schema_version']}")
        for name, passed in payload["checks"].items():
            state = "pass" if passed else "fail"
            print(f"{state} {name}")
        for error in payload["errors"]:
            print(error, file=sys.stderr)
    if build_mode:
        return 0 if payload.get("schema_version") == PILOT_SIGNOFF_VERSION else 1
    return 0 if payload["status"] == "pass" else 1


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    if not args.signoff:
        return _failed_payload(["signoff_required"])
    try:
        signoff = load_pilot_signoff_packet(args.signoff)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        signoff = None
        errors.append(f"signoff_load_failed:{exc}")
    try:
        go_no_go = _load_json(args.go_no_go) if args.go_no_go else None
    except (OSError, json.JSONDecodeError) as exc:
        go_no_go = None
        errors.append(f"go_no_go_load_failed:{exc}")
    payload = verify_pilot_signoff_packet(
        packet=signoff,
        signing_key=_read_signing_key(args, errors),
        expected_release_provenance_sha=args.expected_release_provenance_sha,
        go_no_go=go_no_go,
    )
    return {**payload, "errors": [*payload.get("errors", []), *errors]}


def _build(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[str] = []
    if not args.go_no_go:
        return _failed_payload(["go_no_go_required"])
    if not args.operator_id:
        return _failed_payload(["operator_id_required"])
    signing_key = _read_signing_key(args, errors)
    if not signing_key:
        return _failed_payload([*errors, "signing_key_required"])
    try:
        go_no_go = _load_json(args.go_no_go)
        packet = build_pilot_signoff_packet(
            go_no_go=go_no_go,
            operator={
                "operator_id": args.operator_id,
                "roles": args.role,
                "source": args.operator_source,
            },
            signing_key=signing_key,
        )
        Path(args.build_output).write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return packet
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _failed_payload([*errors, f"build_failed:{exc}"])


def _read_signing_key(args: argparse.Namespace, errors: list[str]) -> str | None:
    try:
        if args.signing_key_file:
            return Path(args.signing_key_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors.append(f"signing_key_file_load_failed:{exc}")
        return None
    return args.signing_key or os.environ.get("MESH_PILOT_SIGNOFF_KEY")


def _load_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _failed_payload(errors: list[str]) -> dict[str, Any]:
    return {
        "schema_version": PILOT_SIGNOFF_VERIFICATION_VERSION,
        "generated_at": None,
        "status": "fail",
        "operator_id": None,
        "go_no_go_packet_sha256": None,
        "release_provenance_packet_sha256": None,
        "checks": {},
        "errors": errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
