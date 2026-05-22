from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mesh_hardened_arena._cli_util import emit, exit_code
from mesh_hardened_arena._version import __version__
from mesh_hardened_arena.hardened_arena import (
    REQUIRED_PROFILE_IDS,
    get_hardened_arena_profile,
    load_hardened_arena_profiles,
    verify_hardened_arena_profiles,
)
from mesh_hardened_arena.hardened_arena_catalog import verify_hardened_arena_catalog
from mesh_hardened_arena.hardened_arena_intent import (
    generate_hardened_arena_intent,
    verify_hardened_arena_intent,
    write_hardened_arena_intent,
)
from mesh_hardened_arena.hardened_arena_packet import (
    generate_hardened_arena_packet,
    verify_hardened_arena_packet,
    write_hardened_arena_packet,
)
from mesh_hardened_arena.verify_e2e import PACKAGE_ROOT, verify_package_e2e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mesh-hardened-arena",
        description="Hardened Arena supply-chain kit — profiles, catalog, review packets, and intent bundles.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-profiles", help="List bundled hardened arena profile ids").add_argument("--json", action="store_true")

    show = sub.add_parser("show-profile", help="Print one profile registry entry")
    show.add_argument("profile_id")
    show.add_argument("--profiles", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.profiles.json")
    show.add_argument("--json", action="store_true")

    vp = sub.add_parser("verify-profiles", help="Verify the profile registry")
    vp.add_argument("--profiles", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.profiles.json")
    vp.add_argument("--json", action="store_true")

    vc = sub.add_parser("verify-catalog", help="Verify the DHI catalog snapshot")
    vc.add_argument("--catalog", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.catalog.json")
    vc.add_argument("--json", action="store_true")

    gp = sub.add_parser("generate-packet", help="Generate a review packet for a profile")
    gp.add_argument("profile_id")
    gp.add_argument("--output", type=Path, required=True)
    gp.add_argument("--profiles", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.profiles.json")
    gp.add_argument("--catalog", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.catalog.json")
    gp.add_argument("--json", action="store_true")

    vpk = sub.add_parser("verify-packet", help="Verify a generated review packet file")
    vpk.add_argument("path", type=Path)
    vpk.add_argument("--json", action="store_true")

    gi = sub.add_parser("generate-intent", help="Generate a review-only intent bundle")
    gi.add_argument("profile_id")
    gi.add_argument("--output-dir", type=Path, required=True)
    gi.add_argument("--profiles", type=Path, default=PACKAGE_ROOT / "config" / "hardened-arena.profiles.json")
    gi.add_argument("--json", action="store_true")

    vi = sub.add_parser("verify-intent", help="Verify a generated intent bundle directory")
    vi.add_argument("path", type=Path)
    vi.add_argument("--json", action="store_true")

    ve = sub.add_parser("verify-e2e", help="Run the full profiles→catalog→packet→intent pipeline")
    ve.add_argument("--output-dir", type=Path, default=None)
    ve.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "list-profiles":
        registry = load_hardened_arena_profiles(PACKAGE_ROOT / "config" / "hardened-arena.profiles.json")
        profile_ids = [str(p["profile_id"]) for p in registry.get("profiles", []) if isinstance(p, dict)]
        payload = {
            "status": "pass",
            "summary": "profile ids",
            "required": sorted(REQUIRED_PROFILE_IDS),
            "profiles": sorted(profile_ids),
        }
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "show-profile":
        profile = get_hardened_arena_profile(args.profile_id, args.profiles)
        payload = {"status": "pass", "summary": args.profile_id, "profile": profile}
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "verify-profiles":
        payload = verify_hardened_arena_profiles(args.profiles)
        payload["summary"] = "verify profiles"
        payload["status"] = payload.get("status", "fail")
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "verify-catalog":
        payload = verify_hardened_arena_catalog(args.catalog)
        payload["summary"] = "verify catalog"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "generate-packet":
        packet = generate_hardened_arena_packet(
            args.profile_id,
            profile_registry_path=args.profiles,
            catalog_path=args.catalog,
        )
        write_hardened_arena_packet(packet, args.output)
        payload = {"status": "pass", "summary": "packet generated", "output": str(args.output), "packet_id": packet.get("packet_id")}
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "verify-packet":
        payload = verify_hardened_arena_packet(args.path)
        payload["summary"] = "verify packet"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "generate-intent":
        intent = generate_hardened_arena_intent(args.profile_id, profile_registry_path=args.profiles)
        bundle_path = write_hardened_arena_intent(intent, args.output_dir)
        payload = {
            "status": "pass",
            "summary": "intent bundle generated",
            "output_dir": str(args.output_dir),
            "bundle_path": str(bundle_path),
            "review_only": intent.get("review_only"),
            "live_deployment_allowed": intent.get("live_deployment_allowed"),
        }
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "verify-intent":
        payload = verify_hardened_arena_intent(args.path)
        payload["summary"] = "verify intent"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "verify-e2e":
        payload = verify_package_e2e(output_dir=args.output_dir)
        payload["summary"] = "verify-e2e"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
