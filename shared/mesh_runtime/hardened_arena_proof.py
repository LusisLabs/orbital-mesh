from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .hardened_arena_packet import HARDENED_ARENA_PACKET_SCHEMA, verify_hardened_arena_packet
from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
HARDENED_ARENA_PROOF_SCHEMA = "hardened-arena-proof.schema.json"
HARDENED_ARENA_PROOF_VERSION = "mesh.hardened_arena.proof.v1"
HARDENED_ARENA_PROOF_VERIFICATION_VERSION = "mesh.hardened_arena.proof_verification.v1"
TARGET_PROOF_RESOLVES_PACKET_BLOCKERS = frozenset({"target_validation_missing"})

REQUIRED_PROOF_CHECKS = frozenset(
    {
        "health_endpoint",
        "readiness_endpoint",
        "identity_boundary",
        "persistence",
        "feedback_source",
        "audit_event",
        "rollback_plan",
        "run_export",
        "kill_switch",
        "cleanup",
        "release_packet_binding",
    }
)


def run_hardened_arena_proof(
    evidence_path: str | Path,
    *,
    generated_at: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    evidence = json.loads(_resolve_path(evidence_path).read_text(encoding="utf-8"))
    checked_at = generated_at or _timestamp()
    checks = [_run_check(check_name, evidence, timeout_seconds) for check_name in sorted(REQUIRED_PROOF_CHECKS)]
    blockers = _blockers_for_checks(checks)
    target = evidence.get("target") if isinstance(evidence.get("target"), dict) else {}
    packet_ref = evidence.get("packet_ref")
    target_specific = target.get("target_specific") is True
    request_target_validated = evidence.get("request_target_validated") is True
    if request_target_validated and not target_specific:
        blockers.append("target_validated_requires_target_specific_proof")
    if request_target_validated:
        blockers.extend(_target_validated_packet_ref_blockers(packet_ref, expected_profile_id=str(evidence.get("profile_id") or "")))
    all_observed = not blockers
    if request_target_validated and all_observed and target_specific and packet_ref:
        status = "target_validated"
        target_validated = True
        statement = "Target-specific proof packet completed all required hardened arena checks and references a verified complete arena packet."
    elif all_observed:
        status = "arena_smoke_passed"
        target_validated = False
        statement = "Target-specific arena smoke proof passed; production readiness still requires explicit target validation review."
    else:
        status = "blocked"
        target_validated = False
        statement = "Hardened arena proof is incomplete or unobserved and cannot validate the target."
    proof = {
        "schema_version": HARDENED_ARENA_PROOF_VERSION,
        "proof_id": _proof_id(str(evidence.get("profile_id") or "unknown"), str(target.get("target_id") or "unknown"), checked_at),
        "generated_at": checked_at,
        "profile_id": str(evidence.get("profile_id") or ""),
        "target": {
            "target_id": str(target.get("target_id") or ""),
            "target_specific": target_specific,
            "base_url": target.get("base_url") if target.get("base_url") is not None else None,
            "environment": str(target.get("environment") or "unknown"),
        },
        "packet_ref": str(packet_ref) if packet_ref else None,
        "checks": checks,
        "readiness_posture": {
            "status": "blocked" if blockers else status,
            "target_validated": target_validated and not blockers,
            "target_specific": target_specific,
            "statement": statement,
        },
        "raw_secret_values_present": evidence.get("raw_secret_values_present") is True,
        "blockers": sorted(set(blockers)),
    }
    validate_payload(HARDENED_ARENA_PROOF_SCHEMA, proof)
    return proof


def write_hardened_arena_proof(proof: dict[str, Any], output_path: str | Path) -> None:
    validate_payload(HARDENED_ARENA_PROOF_SCHEMA, proof)
    path = _resolve_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_hardened_arena_proof(path: str | Path) -> dict[str, Any]:
    proof_path = _resolve_path(path)
    blockers: list[str] = []
    proof: dict[str, Any] | None = None
    proof_sha256: str | None = None
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        validate_payload(HARDENED_ARENA_PROOF_SCHEMA, proof)
        proof_sha256 = _sha256(proof_path)
        blockers.extend(_proof_blockers(proof))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"hardened_arena_proof_invalid:{type(exc).__name__}")
        if not proof_path.exists():
            blockers.append("hardened_arena_proof_missing")
    return {
        "schema_version": HARDENED_ARENA_PROOF_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "proof_path": _display_path(proof_path),
        "proof_sha256": proof_sha256,
        "profile_id": proof.get("profile_id") if isinstance(proof, dict) else None,
        "readiness_status": proof.get("readiness_posture", {}).get("status") if isinstance(proof, dict) else None,
        "blockers": sorted(set(blockers)),
    }


def output_path_is_generated(path: str | Path) -> bool:
    resolved = _resolve_path(path)
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "dist"


def _run_check(check_name: str, evidence: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    checks = evidence.get("checks") if isinstance(evidence.get("checks"), dict) else {}
    item = checks.get(check_name) if isinstance(checks.get(check_name), dict) else {}
    url = item.get("url")
    if isinstance(url, str) and url:
        return _http_check(check_name, url, int(item.get("expected_status") or 200), timeout_seconds)
    observed = item.get("observed") is True and bool(item.get("evidence_ref"))
    return {
        "check": check_name,
        "status": "pass" if observed else "blocked",
        "observed": observed,
        "evidence_ref": str(item.get("evidence_ref")) if item.get("evidence_ref") else None,
        "details": str(item.get("details") or ("observed evidence ref supplied" if observed else "observed evidence missing")),
    }


def _http_check(check_name: str, url: str, expected_status: int, timeout_seconds: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            status = int(response.status)
        passed = status == expected_status
        return {
            "check": check_name,
            "status": "pass" if passed else "fail",
            "observed": passed,
            "evidence_ref": url if passed else None,
            "details": f"HTTP {status}; expected {expected_status}",
        }
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return {
            "check": check_name,
            "status": "fail",
            "observed": False,
            "evidence_ref": None,
            "details": f"HTTP check failed: {type(exc).__name__}",
        }


def _blockers_for_checks(checks: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    seen = {str(check.get("check")) for check in checks}
    for check_name in sorted(REQUIRED_PROOF_CHECKS - seen):
        blockers.append(f"proof_check_missing:{check_name}")
    for check in checks:
        if check.get("status") != "pass" or check.get("observed") is not True:
            blockers.append(f"proof_check_not_observed:{check.get('check')}")
    return blockers


def _target_validated_packet_ref_blockers(packet_ref: object, *, expected_profile_id: str) -> list[str]:
    if not packet_ref:
        return ["target_validated_requires_packet_ref"]
    packet_path = _resolve_path(str(packet_ref))
    try:
        packet_result = verify_hardened_arena_packet(packet_path)
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        validate_payload(HARDENED_ARENA_PACKET_SCHEMA, packet)
    except Exception as exc:  # pragma: no cover - verifier is expected to fail closed, but keep proof runner closed too.
        return [
            f"target_validated_packet_ref_invalid:{type(exc).__name__}",
            "target_validated_requires_complete_proof_packet",
        ]
    blockers = []
    if packet_result.get("status") != "pass":
        blockers.append("target_validated_requires_complete_proof_packet")
    blockers.extend(str(blocker) for blocker in packet_result.get("blockers", []))
    packet_profile_id = str(packet.get("selected_profile", {}).get("profile_id") or packet_result.get("profile_id") or "")
    if not packet_profile_id:
        blockers.append("target_validated_packet_ref_profile_missing")
    elif packet_profile_id != expected_profile_id:
        blockers.append("target_validated_packet_ref_profile_mismatch")
    if packet_result.get("readiness_status") == "target_validated":
        blockers.append("target_validated_packet_ref_must_not_preclaim_target_validation")
    required_sections = (
        "selected_profile",
        "component_graph",
        "authority_boundaries",
        "credential_classes",
        "dhi_catalog_refs",
        "proof_checklist",
        "mesh_probe_plan",
        "failure_mode_curriculum",
        "cleanup_plan",
        "data_retention_plan",
        "readiness_posture",
    )
    for section in required_sections:
        if not packet.get(section):
            blockers.append(f"target_validated_packet_ref_section_missing:{section}")
    posture = packet.get("readiness_posture") if isinstance(packet.get("readiness_posture"), dict) else {}
    if posture.get("target_validated") is not False or posture.get("production_ready") is not False:
        blockers.append("target_validated_packet_ref_overclaims_readiness")
    packet_blockers = [str(blocker) for blocker in packet.get("blockers", [])]
    unresolved_packet_blockers = sorted(set(packet_blockers) - TARGET_PROOF_RESOLVES_PACKET_BLOCKERS)
    if unresolved_packet_blockers:
        blockers.append("target_validated_packet_ref_has_unresolved_blockers")
        blockers.extend(f"target_validated_packet_ref_unresolved_blocker:{blocker}" for blocker in unresolved_packet_blockers)
    return blockers


def _proof_blockers(proof: dict[str, Any]) -> list[str]:
    blockers = list(proof.get("blockers", []))
    if proof.get("raw_secret_values_present") is not False:
        blockers.append("proof_contains_raw_secret_values")
    blockers.extend(_blockers_for_checks([check for check in proof.get("checks", []) if isinstance(check, dict)]))
    posture = proof.get("readiness_posture") if isinstance(proof.get("readiness_posture"), dict) else {}
    if posture.get("status") == "arena_smoke_passed":
        if blockers:
            blockers.append("arena_smoke_passed_requires_all_observed_checks")
    if posture.get("status") == "target_validated" or posture.get("target_validated") is True:
        target = proof.get("target") if isinstance(proof.get("target"), dict) else {}
        if target.get("target_specific") is not True or posture.get("target_specific") is not True:
            blockers.append("target_validated_requires_target_specific_proof")
        blockers.extend(
            _target_validated_packet_ref_blockers(
                proof.get("packet_ref"),
                expected_profile_id=str(proof.get("profile_id") or ""),
            )
        )
        if blockers:
            blockers.append("target_validated_requires_complete_proof_packet")
    return blockers


def _proof_id(profile_id: str, target_id: str, generated_at: str) -> str:
    digest = hashlib.sha256(f"{profile_id}:{target_id}:{generated_at}:proof".encode("utf-8")).hexdigest()[:12]
    return f"hardened-arena-proof-{profile_id}-{target_id}-{digest}"


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
