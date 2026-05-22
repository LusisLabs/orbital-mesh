from __future__ import annotations

from pathlib import Path
from typing import Any

from mesh_hardened_arena.hardened_arena import verify_hardened_arena_profiles
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

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = PACKAGE_ROOT / "config" / "hardened-arena.profiles.json"
CATALOG_PATH = PACKAGE_ROOT / "config" / "hardened-arena.catalog.json"
GENERATED_AT = "2026-05-22T00:00:00Z"


def verify_package_e2e(*, output_dir: Path | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    out = output_dir or (PACKAGE_ROOT / "dist" / "hardened-arena" / "verify-e2e")
    out.mkdir(parents=True, exist_ok=True)

    profiles = verify_hardened_arena_profiles(str(PROFILES_PATH))
    if profiles.get("status") != "pass":
        blockers.append("profiles_verification_failed")

    catalog = verify_hardened_arena_catalog(str(CATALOG_PATH))
    if catalog.get("status") != "pass":
        blockers.append("catalog_verification_failed")

    packet = generate_hardened_arena_packet("solo_project_default", generated_at=GENERATED_AT)
    packet_file = out / "packet.json"
    write_hardened_arena_packet(packet, packet_file)
    packet_verify = verify_hardened_arena_packet(packet_file)
    if packet_verify.get("status") != "pass":
        blockers.append("packet_verification_failed")

    intent = generate_hardened_arena_intent("solo_project_default", generated_at=GENERATED_AT)
    intent_path = write_hardened_arena_intent(intent, out / "intent")
    intent_verify = verify_hardened_arena_intent(intent_path)
    if intent_verify.get("status") != "pass":
        blockers.append("intent_verification_failed")

    return {
        "status": "pass" if not blockers else "fail",
        "summary": "verify-e2e",
        "profiles": profiles,
        "catalog": catalog,
        "packet": packet_verify,
        "intent": intent_verify,
        "output_dir": str(out),
        "blockers": blockers,
    }
