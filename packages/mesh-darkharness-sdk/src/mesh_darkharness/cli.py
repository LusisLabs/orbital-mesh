from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mesh_darkharness._cli_util import emit, exit_code
from mesh_darkharness._version import __version__
from mesh_darkharness.perennial.signing import (
    build_ed25519_signature_proof,
    build_hmac_signature_proof,
    verify_ed25519_signature_proof,
    verify_hmac_signature_proof,
)
from mesh_darkharness.schema_validation import SchemaValidationError, validate_payload
from mesh_darkharness.verify_e2e import (
    evaluate_policy_fixture,
    list_schema_files,
    load_packet_from_path,
    orbital_mesh_root,
    run_mesh_live,
    verify_package_e2e,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mesh-darkharness",
        description="Darkharness Perennial packet SDK — validate, sign, and evaluate governance exports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    verify_e2e = sub.add_parser("verify-e2e", help="Run bundled SDK verification (schema, sign, policy)")
    verify_e2e.add_argument("--json", action="store_true")
    verify_e2e.add_argument(
        "--with-mesh-live",
        action="store_true",
        help="Also run Orbital Mesh control-plane live proof (requires MESH_ORBITAL_ROOT or sibling lusis-mesh checkout)",
    )

    verify_packet = sub.add_parser("verify-packet", help="Validate a pilot packet JSON file against schema")
    verify_packet.add_argument("path", type=Path)
    verify_packet.add_argument("--json", action="store_true")

    sign = sub.add_parser("sign", help="Sign a pilot packet with HMAC or Ed25519")
    sign.add_argument("path", type=Path)
    sign.add_argument("--secret", default="", help="HMAC secret (required unless --ed25519-key-pem is set)")
    sign.add_argument("--key-id", default="darkharness-handover")
    sign.add_argument("--ed25519-key-pem", default="", help="Ed25519 private key PEM path or inline PEM")
    sign.add_argument("--output", type=Path, default=None)
    sign.add_argument("--json", action="store_true")

    verify_sig = sub.add_parser("verify-signature", help="Verify a signature proof against a pilot packet")
    verify_sig.add_argument("packet_path", type=Path)
    verify_sig.add_argument("proof_path", type=Path)
    verify_sig.add_argument("--secret", default="")
    verify_sig.add_argument("--public-key-pem", default="")
    verify_sig.add_argument("--json", action="store_true")

    policy = sub.add_parser("evaluate-policy", help="Evaluate policy checks for a bundled fixture")
    policy.add_argument("fixture", choices=("allowed", "denied"))
    policy.add_argument("--json", action="store_true")

    schemas = sub.add_parser("list-schemas", help="List bundled Perennial JSON schemas")
    schemas.add_argument("--json", action="store_true")

    mesh_live = sub.add_parser("verify-mesh-live", help="Run Orbital Mesh control-plane live packet proof")
    mesh_live.add_argument("--json", action="store_true")
    mesh_live.add_argument("--orbital-root", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "verify-e2e":
        result = verify_package_e2e(with_mesh_live=args.with_mesh_live)
        emit(result, json_mode=args.json)
        return exit_code(result)

    if args.command == "verify-packet":
        try:
            packet = load_packet_from_path(args.path)
            validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)
            payload = {"status": "pass", "summary": "packet schema valid", "packet_id": packet.get("packet_id")}
        except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
            payload = {"status": "fail", "summary": "packet schema invalid", "error": str(exc)}
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "sign":
        try:
            packet = load_packet_from_path(args.path)
            validate_payload("perennial/darkharness-pilot-packet.schema.json", packet)
            if args.ed25519_key_pem:
                pem = Path(args.ed25519_key_pem).read_text(encoding="utf-8") if Path(args.ed25519_key_pem).exists() else args.ed25519_key_pem
                proof = build_ed25519_signature_proof(packet, key_id=args.key_id, private_key_pem=pem)
            else:
                if not args.secret:
                    raise ValueError("--secret is required for HMAC signing")
                proof = build_hmac_signature_proof(packet, key_id=args.key_id, secret=args.secret)
            if args.output:
                args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload = {"status": "pass", "summary": "signature proof created", "proof": proof, "output": str(args.output) if args.output else None}
        except (OSError, ValueError, SchemaValidationError, RuntimeError) as exc:
            payload = {"status": "fail", "summary": "sign failed", "error": str(exc)}
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "verify-signature":
        try:
            packet = load_packet_from_path(args.packet_path)
            proof = json.loads(args.proof_path.read_text(encoding="utf-8"))
            if proof.get("algorithm") == "ed25519":
                ok = verify_ed25519_signature_proof(packet, proof, public_key_pem=args.public_key_pem or None)
            else:
                if not args.secret:
                    raise ValueError("--secret is required for HMAC verification")
                ok = verify_hmac_signature_proof(packet, proof, secret=args.secret)
            payload = {"status": "pass" if ok else "fail", "summary": "signature verified" if ok else "signature invalid"}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            payload = {"status": "fail", "summary": "verify-signature failed", "error": str(exc)}
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "evaluate-policy":
        payload = evaluate_policy_fixture(args.fixture)
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "list-schemas":
        payload = list_schema_files()
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "verify-mesh-live":
        root = args.orbital_root or orbital_mesh_root()
        payload = run_mesh_live(orbital_root=root)
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
