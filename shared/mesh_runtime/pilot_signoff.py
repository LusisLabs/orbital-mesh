from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any, cast

from .schema_validation import SchemaValidationError, validate_payload


PILOT_SIGNOFF_SCHEMA = "pilot-signoff.schema.json"
PILOT_SIGNOFF_VERSION = "mesh.pilot_signoff.v1"
PILOT_SIGNOFF_VERIFICATION_VERSION = "mesh.pilot_signoff_verification.v1"
AUTHORIZED_SIGNOFF_ROLES = frozenset({"admin", "approver"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_pilot_signoff_packet(
    *,
    go_no_go: dict[str, Any],
    operator: dict[str, Any],
    signing_key: str,
    signing_key_id: str = "pilot-signoff-hmac",
) -> dict[str, Any]:
    if not signing_key.strip():
        raise ValueError("signing_key is required")
    packet = {
        "schema_version": PILOT_SIGNOFF_VERSION,
        "generated_at": _timestamp(),
        "operator": _operator_record(operator),
        "decision": "go" if go_no_go.get("status") == "go" else "blocked",
        "go_no_go": _go_no_go_record(go_no_go),
        "release_provenance": _release_provenance_record(go_no_go),
    }
    packet["signature"] = _sign_payload(packet, signing_key=signing_key, signing_key_id=signing_key_id)
    validate_payload(PILOT_SIGNOFF_SCHEMA, packet)
    return packet


def load_pilot_signoff_packet(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    signoff_path = Path(path)
    if not signoff_path.exists():
        return None
    payload = json.loads(signoff_path.read_text(encoding="utf-8"))
    validate_payload(PILOT_SIGNOFF_SCHEMA, payload)
    return cast(dict[str, Any], payload)


def verify_pilot_signoff_packet(
    *,
    packet: dict[str, Any] | None,
    signing_key: str | None,
    expected_release_provenance_sha: str | None = None,
    go_no_go: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    schema_valid = False
    if packet is None:
        errors.append("signoff_missing")
    else:
        try:
            validate_payload(PILOT_SIGNOFF_SCHEMA, packet)
            schema_valid = True
        except SchemaValidationError as exc:
            errors.append(f"schema_invalid:{exc}")

    checks = _checks(
        packet=packet or {},
        signing_key=signing_key,
        schema_valid=schema_valid,
        expected_release_provenance_sha=expected_release_provenance_sha,
        go_no_go=go_no_go,
    )
    return {
        "schema_version": PILOT_SIGNOFF_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) and not errors else "fail",
        "operator_id": _field(packet, "operator", "operator_id"),
        "go_no_go_packet_sha256": _field(packet, "go_no_go", "packet_sha256"),
        "release_provenance_packet_sha256": _field(packet, "release_provenance", "packet_sha256"),
        "checks": checks,
        "errors": errors,
    }


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _checks(
    *,
    packet: dict[str, Any],
    signing_key: str | None,
    schema_valid: bool,
    expected_release_provenance_sha: str | None,
    go_no_go: dict[str, Any] | None,
) -> dict[str, bool]:
    raw_signoff_go_no_go = packet.get("go_no_go")
    signoff_go_no_go = cast(dict[str, Any], raw_signoff_go_no_go) if isinstance(raw_signoff_go_no_go, dict) else {}
    raw_release_provenance = packet.get("release_provenance")
    release_provenance = (
        cast(dict[str, Any], raw_release_provenance) if isinstance(raw_release_provenance, dict) else {}
    )
    raw_operator = packet.get("operator")
    operator = cast(dict[str, Any], raw_operator) if isinstance(raw_operator, dict) else {}
    expected_release_sha = (expected_release_provenance_sha or "").strip()
    source_match = _go_no_go_source_matches(signoff_go_no_go, release_provenance, go_no_go)
    return {
        "schema_valid": schema_valid,
        "decision_go": packet.get("decision") == "go",
        "go_no_go_packet_version": signoff_go_no_go.get("packet_version") == "pilot.go_no_go.v1",
        "go_no_go_status_go": signoff_go_no_go.get("status") == "go",
        "go_no_go_no_missing_evidence": signoff_go_no_go.get("missing_evidence") == [],
        "go_no_go_packet_sha256_valid": _valid_sha256(signoff_go_no_go.get("packet_sha256")),
        "go_no_go_packet_hash_matches": source_match["hash_matches"],
        "go_no_go_payload_status_matches": source_match["status_matches"],
        "release_provenance_complete": release_provenance.get("status") == "complete",
        "release_provenance_no_missing": release_provenance.get("missing") == [],
        "release_provenance_checks_passed": _all_true_bool_map(release_provenance.get("checks")),
        "release_provenance_ci_sha_matches_git_commit": (
            _field(release_provenance, "ci_attestation", "sha_matches_git_commit") is True
        ),
        "release_provenance_sha_valid": _valid_sha256(release_provenance.get("packet_sha256")),
        "expected_release_provenance_sha_matches": not expected_release_sha
        or release_provenance.get("packet_sha256") == expected_release_sha,
        "operator_id_present": bool(str(operator.get("operator_id") or "").strip()),
        "operator_role_authorized": bool(AUTHORIZED_SIGNOFF_ROLES.intersection(_roles(operator.get("roles")))),
        "signature_algorithm_hmac_sha256": _field(packet, "signature", "algorithm") == "hmac-sha256",
        "signature_key_id_present": bool(str(_field(packet, "signature", "key_id") or "").strip()),
        "signature_valid": _signature_valid(packet, signing_key=signing_key),
    }


def _go_no_go_source_matches(
    signoff_go_no_go: dict[str, Any],
    release_provenance: dict[str, Any],
    go_no_go: dict[str, Any] | None,
) -> dict[str, bool]:
    if go_no_go is None:
        return {"hash_matches": True, "status_matches": True}
    raw_source_release = go_no_go.get("release_provenance")
    source_release = cast(dict[str, Any], raw_source_release) if isinstance(raw_source_release, dict) else {}
    return {
        "hash_matches": signoff_go_no_go.get("packet_sha256") == canonical_payload_sha256(go_no_go),
        "status_matches": (
            signoff_go_no_go.get("packet_version") == go_no_go.get("packet_version")
            and signoff_go_no_go.get("status") == go_no_go.get("status")
            and signoff_go_no_go.get("missing_evidence") == go_no_go.get("missing_evidence")
            and release_provenance.get("status") == source_release.get("status")
            and release_provenance.get("packet_sha256") == source_release.get("packet_sha256")
            and release_provenance.get("missing") == source_release.get("missing")
            and release_provenance.get("checks") == source_release.get("checks")
            and release_provenance.get("ci_attestation") == source_release.get("ci_attestation")
        ),
    }


def _operator_record(operator: dict[str, Any]) -> dict[str, Any]:
    return {
        "operator_id": str(operator.get("operator_id") or "").strip(),
        "roles": sorted(_roles(operator.get("roles"))),
        "source": str(operator.get("source") or "trusted_proxy").strip(),
    }


def _go_no_go_record(go_no_go: dict[str, Any]) -> dict[str, Any]:
    raw_observed = go_no_go.get("observed")
    observed = cast(dict[str, Any], raw_observed) if isinstance(raw_observed, dict) else {}
    return {
        "packet_version": str(go_no_go.get("packet_version") or ""),
        "status": str(go_no_go.get("status") or ""),
        "packet_sha256": canonical_payload_sha256(go_no_go),
        "missing_evidence": [str(item) for item in go_no_go.get("missing_evidence", [])],
        "observed_run_count": int(observed.get("run_count") or 0),
    }


def _release_provenance_record(go_no_go: dict[str, Any]) -> dict[str, Any]:
    raw_release = go_no_go.get("release_provenance")
    release = cast(dict[str, Any], raw_release) if isinstance(raw_release, dict) else {}
    missing = release.get("missing")
    checks = release.get("checks")
    ci_attestation = release.get("ci_attestation")
    return {
        "status": str(release.get("status") or ""),
        "packet_sha256": release.get("packet_sha256") if isinstance(release.get("packet_sha256"), str) else None,
        "missing": [str(item) for item in missing] if isinstance(missing, list) else [],
        "checks": {
            str(name): value is True
            for name, value in checks.items()
        }
        if isinstance(checks, dict)
        else {},
        "ci_attestation": {
            "provider": _string_or_none(ci_attestation, "provider"),
            "run_id": _string_or_none(ci_attestation, "run_id"),
            "sha": _string_or_none(ci_attestation, "sha"),
            "expected_sha": _string_or_none(ci_attestation, "expected_sha"),
            "sha_matches_git_commit": _field(ci_attestation, "sha_matches_git_commit") is True,
        },
    }


def _roles(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _sign_payload(payload: dict[str, Any], *, signing_key: str, signing_key_id: str) -> dict[str, str]:
    digest = hmac.new(signing_key.encode("utf-8"), _canonical_json(payload), hashlib.sha256).hexdigest()
    return {
        "algorithm": "hmac-sha256",
        "key_id": signing_key_id,
        "signature": digest,
    }


def _signature_valid(packet: dict[str, Any], *, signing_key: str | None) -> bool:
    key = (signing_key or "").strip()
    raw_signature = packet.get("signature")
    signature = cast(dict[str, Any], raw_signature) if isinstance(raw_signature, dict) else {}
    expected = str(signature.get("signature") or "")
    if not key or not expected:
        return False
    signed_payload = {name: value for name, value in packet.items() if name != "signature"}
    actual = _sign_payload(
        signed_payload,
        signing_key=key,
        signing_key_id=str(signature.get("key_id") or ""),
    )["signature"]
    return hmac.compare_digest(expected, actual)


def _all_true_bool_map(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _string_or_none(payload: Any, name: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(name)
    return value if isinstance(value, str) else None


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value))


def _field(payload: Any, section: str, name: str | None = None) -> Any:
    section_value = payload.get(section) if isinstance(payload, dict) else None
    if name is None:
        return section_value
    if not isinstance(section_value, dict):
        return None
    return section_value.get(name)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
