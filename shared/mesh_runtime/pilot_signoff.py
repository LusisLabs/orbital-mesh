from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any

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
    return payload


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
    signoff_go_no_go = packet.get("go_no_go") if isinstance(packet.get("go_no_go"), dict) else {}
    release_provenance = (
        packet.get("release_provenance") if isinstance(packet.get("release_provenance"), dict) else {}
    )
    operator = packet.get("operator") if isinstance(packet.get("operator"), dict) else {}
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
    source_release = go_no_go.get("release_provenance") if isinstance(go_no_go.get("release_provenance"), dict) else {}
    return {
        "hash_matches": signoff_go_no_go.get("packet_sha256") == canonical_payload_sha256(go_no_go),
        "status_matches": (
            signoff_go_no_go.get("packet_version") == go_no_go.get("packet_version")
            and signoff_go_no_go.get("status") == go_no_go.get("status")
            and signoff_go_no_go.get("missing_evidence") == go_no_go.get("missing_evidence")
            and release_provenance.get("status") == source_release.get("status")
            and release_provenance.get("packet_sha256") == source_release.get("packet_sha256")
        ),
    }


def _operator_record(operator: dict[str, Any]) -> dict[str, Any]:
    return {
        "operator_id": str(operator.get("operator_id") or "").strip(),
        "roles": sorted(_roles(operator.get("roles"))),
        "source": str(operator.get("source") or "trusted_proxy").strip(),
    }


def _go_no_go_record(go_no_go: dict[str, Any]) -> dict[str, Any]:
    observed = go_no_go.get("observed") if isinstance(go_no_go.get("observed"), dict) else {}
    return {
        "packet_version": str(go_no_go.get("packet_version") or ""),
        "status": str(go_no_go.get("status") or ""),
        "packet_sha256": canonical_payload_sha256(go_no_go),
        "missing_evidence": [str(item) for item in go_no_go.get("missing_evidence", [])],
        "observed_run_count": int(observed.get("run_count") or 0),
    }


def _release_provenance_record(go_no_go: dict[str, Any]) -> dict[str, Any]:
    release = go_no_go.get("release_provenance") if isinstance(go_no_go.get("release_provenance"), dict) else {}
    return {
        "status": str(release.get("status") or ""),
        "packet_sha256": release.get("packet_sha256") if isinstance(release.get("packet_sha256"), str) else None,
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
    signature = packet.get("signature") if isinstance(packet.get("signature"), dict) else {}
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


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value))


def _field(payload: dict[str, Any] | None, section: str, name: str) -> Any:
    section_value = payload.get(section) if isinstance(payload, dict) else None
    if not isinstance(section_value, dict):
        return None
    return section_value.get(name)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
